"""Core processing pipeline with Shape Build Level system.

Shape Build Levels replace continuous abstraction.
Each level adds the next layer of visual information,
mirroring how painters actually construct a painting.

Level 1 — NOTAN:       2-3 dominant masses only
Level 2 — PRIMARY:     Large structural shapes
Level 3 — SECONDARY:   Ideal block-in (default)
Level 4 — STRUCTURE:   Medium shapes + form turns
Level 5 — FULL:        All simplified shapes
"""

import cv2
import numpy as np
from .color_modes import render_bw, render_grayscale, render_color_snap
from .guide import (
    compute_edge_hierarchy, compute_major_shapes, compute_focal_hint,
    overlay_edge_map, overlay_major_shapes, overlay_focal_hint,
)
from .utils import resize_preserve_aspect, encode_png


# Minimum region area as fraction of total image area, per build level.
# Below this size, regions get absorbed into neighbors.
LEVEL_MIN_AREA_FRACTION = {
    1: 0.08,    # only massive shapes survive
    2: 0.03,    # large structural masses
    3: 0.012,   # ideal block-in
    4: 0.005,   # medium shapes appear
    5: 0.0015,  # everything simplified but present
}


def kmeans_luminance_labels(l_channel: np.ndarray, num_values: int) -> np.ndarray:
    """Cluster luminance into num_values groups using k-means.

    Returns label map (h, w) in [0..num_values-1], sorted dark->light.
    """
    h, w = l_channel.shape
    samples = l_channel.reshape(-1, 1).astype(np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
    _, flat_labels, centers = cv2.kmeans(
        samples, num_values, None,
        criteria, 5, cv2.KMEANS_PP_CENTERS
    )

    center_order = np.argsort(centers.flatten())
    remap = np.zeros(num_values, dtype=np.int32)
    for new_idx, old_idx in enumerate(center_order):
        remap[old_idx] = new_idx

    return remap[flat_labels.flatten()].reshape(h, w)


def remove_small_regions(labels: np.ndarray, num_values: int,
                         min_area: int) -> np.ndarray:
    """Remove regions smaller than min_area by merging into adjacent neighbor."""
    result = labels.copy()
    for v in range(num_values):
        mask = (result == v).astype(np.uint8)
        num_cc, cc_labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for cc_id in range(1, num_cc):
            area = stats[cc_id, cv2.CC_STAT_AREA]
            if area >= min_area:
                continue
            cc_mask = cc_labels == cc_id
            dilated = cv2.dilate(cc_mask.astype(np.uint8),
                                 np.ones((3, 3), np.uint8), iterations=1)
            border = (dilated > 0) & (~cc_mask)
            neighbor_vals = result[border]
            neighbor_vals = neighbor_vals[neighbor_vals != v]
            if len(neighbor_vals) == 0:
                continue
            counts = np.bincount(neighbor_vals, minlength=num_values)
            result[cc_mask] = np.argmax(counts)
    return result


def smooth_boundaries(labels: np.ndarray, edge_strength: int) -> np.ndarray:
    """Morphological cleanup of label boundaries."""
    num_values = int(labels.max()) + 1
    result = labels.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for v in range(num_values):
        mask = (result == v).astype(np.uint8)
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        if edge_strength > 50:
            closed = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)
        result[closed > 0] = v

    return result


def build_shapes(labels: np.ndarray, num_values: int,
                 build_level: int, total_pixels: int) -> np.ndarray:
    """Shape construction by build level. No blur — shape merging only.

    Two passes of region removal for stability.
    Preserves major silhouettes by never dissolving large masses.
    """
    fraction = LEVEL_MIN_AREA_FRACTION.get(build_level, 0.012)
    min_area = max(10, int(total_pixels * fraction))

    result = remove_small_regions(labels, num_values, min_area)
    # Second pass for stability
    remaining = len(np.unique(result))
    result = remove_small_regions(result, remaining, min_area)

    return result


def process_image(image_bgr: np.ndarray, values: int, build_level: int,
                  mode: str, edge_strength: int, target_max_side: int,
                  color_strategy: str = "painter",
                  exaggerate: bool = False,
                  guide_mode: bool = False,
                  overlay_edges: bool = False,
                  overlay_shapes: bool = False,
                  overlay_focal: bool = False) -> bytes:
    """Full pipeline.

    Args:
        image_bgr: Input BGR image.
        values: Number of value groups (2..10).
        build_level: Shape construction level (1..5).
        mode: 'bw', 'grayscale', or 'color'.
        edge_strength: 0 (soft) to 100 (graphic).
        target_max_side: Max dimension for processing.
        color_strategy: 'painter' or 'graphic' (only for color mode).
        exaggerate: Push color separation (painter mode only).
        guide_mode: Enable guide overlays.
        overlay_edges/shapes/focal: Individual overlay toggles.

    Returns:
        PNG bytes.
    """
    # A) Preprocess
    img = resize_preserve_aspect(image_bgr, target_max_side)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]

    # Mild CLAHE for stable grouping
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_norm = clahe.apply(l_channel)

    # Bilateral pre-filter at lower build levels for cleaner masses
    if build_level <= 3:
        d = 9 if build_level <= 2 else 7
        sigma = 50 if build_level <= 2 else 35
        l_norm = cv2.bilateralFilter(l_norm, d=d, sigmaColor=sigma, sigmaSpace=sigma)

    # B) Smart value grouping
    labels = kmeans_luminance_labels(l_norm, values)

    # C) Shape construction by level
    h, w = labels.shape
    labels = build_shapes(labels, values, build_level, h * w)

    # D) Boundary cleanup
    labels = smooth_boundaries(labels, edge_strength)

    # E) Render
    if mode == "bw":
        rendered = render_bw(labels, values, edge_strength)
    elif mode == "grayscale":
        rendered = render_grayscale(labels, values, edge_strength)
    elif mode == "color":
        rendered = render_color_snap(labels, values, img, edge_strength,
                                     color_strategy, exaggerate)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # F) Guide overlays (focal first, shapes, edges last on top)
    if guide_mode:
        if overlay_focal:
            focal = compute_focal_hint(labels, values, img.shape)
            rendered = overlay_focal_hint(rendered, focal)
        if overlay_shapes:
            shapes = compute_major_shapes(labels, values)
            rendered = overlay_major_shapes(rendered, shapes)
        if overlay_edges:
            edge_map = compute_edge_hierarchy(labels, values, img.shape)
            rendered = overlay_edge_map(rendered, edge_map)

    return encode_png(rendered)
