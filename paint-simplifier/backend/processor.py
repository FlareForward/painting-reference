"""Core processing pipeline with Master Painter Presets.

Each preset controls the entire render engine:
  - Pre-filtering (median, bilateral)
  - Value grouping (k-means on LAB luminance)
  - Shape construction (build levels + merge tolerance)
  - Boundary cleanup (edge softness)
  - Color rendering (strategy + exaggeration)

Shape Build Levels (4 levels):
  Level 1 — BLOCK:      Bold masses only
  Level 2 — SECONDARY:  Large structural shapes (default)
  Level 3 — STRUCTURE:  Medium shapes + form turns
  Level 4 — FULL:       All simplified shapes
"""

import cv2
import numpy as np
from .presets import get_preset_config
from .color_modes import render_grayscale, render_color_snap
from .guide import (
    compute_edge_hierarchy, compute_major_shapes, compute_focal_hint,
    overlay_edge_map, overlay_major_shapes, overlay_focal_hint,
)
from .utils import resize_preserve_aspect, encode_png


# Minimum region area as fraction of total image area, per build level.
# Below this size, regions get absorbed into neighbors.
LEVEL_MIN_AREA_FRACTION = {
    1: 0.06,    # bold masses only
    2: 0.02,    # large structural shapes
    3: 0.007,   # medium shapes + form turns
    4: 0.002,   # all simplified shapes
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


def detect_dominant_subject(labels: np.ndarray, num_values: int) -> int:
    """Detect the dominant subject label to protect from merging.

    Finds the background (most common label on image border), then
    returns the non-background label with the largest central presence.
    Returns -1 if no clear subject found.
    """
    h, w = labels.shape

    border = np.concatenate([
        labels[0, :], labels[-1, :],
        labels[:, 0], labels[:, -1],
    ])
    bg_label = int(np.argmax(np.bincount(border, minlength=num_values)))

    non_bg = (labels != bg_label).astype(np.uint8)
    num_cc, cc_labels, stats, centroids = cv2.connectedComponentsWithStats(
        non_bg, connectivity=8
    )

    if num_cc <= 1:
        return -1

    center_y, center_x = h / 2.0, w / 2.0
    max_dist = np.sqrt(center_x ** 2 + center_y ** 2)
    best_score = 0.0
    best_label = -1

    for cc_id in range(1, num_cc):
        area = stats[cc_id, cv2.CC_STAT_AREA]
        cy, cx = centroids[cc_id]
        dist = np.sqrt((cx - center_x) ** 2 + (cy - center_y) ** 2)
        proximity = 1.0 - dist / max_dist
        score = area * proximity

        if score > best_score:
            best_score = score
            cc_mask = cc_labels == cc_id
            component_labels = labels[cc_mask]
            best_label = int(np.argmax(
                np.bincount(component_labels, minlength=num_values)
            ))

    return best_label


def remove_small_regions(labels: np.ndarray, num_values: int,
                         min_area: int,
                         protected_label: int = -1) -> np.ndarray:
    """Remove regions smaller than min_area by merging into adjacent neighbor."""
    result = labels.copy()
    for v in range(num_values):
        if v == protected_label:
            continue
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


def smooth_boundaries(labels: np.ndarray, edge_strength: int,
                      kernel_size: int = 5) -> np.ndarray:
    """Unbiased boundary cleanup using median filter on label image.

    Median filter picks the majority label in each neighborhood —
    no label is favored (fixes the old bug where the brightest label
    spread into all boundaries because it was processed last).
    """
    result = labels.astype(np.uint8)
    # Ensure odd kernel size
    ks = kernel_size | 1
    result = cv2.medianBlur(result, ks)
    # Softer edges: second pass with smaller kernel
    if edge_strength < 50:
        ks2 = max(3, ks - 2) | 1
        result = cv2.medianBlur(result, ks2)
    return result.astype(labels.dtype)


def build_shapes(labels: np.ndarray, num_values: int,
                 build_level: int, total_pixels: int,
                 area_multiplier: float = 1.0,
                 protected_label: int = -1,
                 allow_micro_values: bool = False) -> np.ndarray:
    """Shape construction by build level, scaled by preset config.

    Two passes of region removal for stability (unless allow_micro_values
    is True, in which case only one pass — preserving small color fragments
    for impressionist-style broken color).
    """
    fraction = LEVEL_MIN_AREA_FRACTION.get(build_level, 0.012)
    min_area = max(10, int(total_pixels * fraction * area_multiplier))

    result = remove_small_regions(labels, num_values, min_area, protected_label)

    if not allow_micro_values:
        remaining = len(np.unique(result))
        result = remove_small_regions(result, remaining, min_area, protected_label)

    return result


def apply_contrast_boost(rendered: np.ndarray, boost: float) -> np.ndarray:
    """Apply contrast boost around the mean. >1.0 increases contrast."""
    if abs(boost - 1.0) < 0.01:
        return rendered
    img_f = rendered.astype(np.float32)
    mean = img_f.mean()
    img_f = mean + (img_f - mean) * boost
    return np.clip(img_f, 0, 255).astype(np.uint8)


def process_image(image_bgr: np.ndarray, values: int, build_level: int,
                  mode: str, edge_strength: int, target_max_side: int,
                  preset: str = "sargent",
                  preserve_subject: bool = False,
                  guide_mode: bool = False,
                  overlay_edges: bool = False,
                  overlay_shapes: bool = False,
                  overlay_focal: bool = False) -> bytes:
    """Full pipeline driven by preset engine config.

    Args:
        image_bgr: Input BGR image.
        values: Number of value groups (2..10) — slider override.
        build_level: Shape construction level (1..4) — slider override.
        mode: 'grayscale' or 'color' — slider override.
        edge_strength: 0 (soft) to 100 (graphic) — slider override.
        target_max_side: Max dimension for processing.
        preset: Preset name — controls engine internals.
        preserve_subject: Protect dominant subject from being merged.
        guide_mode: Enable guide overlays.
        overlay_edges/shapes/focal: Individual overlay toggles.

    Returns:
        PNG bytes.
    """
    cfg = get_preset_config(preset)

    # A) Preprocess — value-first pipeline
    # NO CLAHE: it distorts global value relationships, causing dark
    # saturated colors to cluster with bright values (the white-patch bug).
    img = resize_preserve_aspect(image_bgr, target_max_side)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]
    l_norm = l_channel.copy()

    # Aggressive median pre-filter (Graphic Poster: poster-like flattening)
    pre_median = cfg.get("pre_median_ksize", 0)
    if pre_median > 0:
        l_norm = cv2.medianBlur(l_norm, pre_median)

    # Bilateral pre-filter with split sigma:
    #   sigmaColor: controls value separation preservation
    #   sigmaSpace: controls spatial softness of shapes
    apply_bilateral = cfg["bilateral_always"] or build_level <= 3
    if apply_bilateral:
        if build_level <= 3:
            d = cfg["bilateral_d"]
            sc = cfg["bilateral_sigma_color"]
            ss = cfg["bilateral_sigma_space"]
        else:
            d = cfg["bilateral_d_high"]
            sc = cfg["bilateral_sigma_color_high"]
            ss = cfg["bilateral_sigma_space_high"]
        if d > 0 and sc > 0:
            l_norm = cv2.bilateralFilter(l_norm, d=d, sigmaColor=sc,
                                         sigmaSpace=ss)

    # B) Smart value grouping
    labels = kmeans_luminance_labels(l_norm, values)

    # Detect dominant subject if requested
    protected_label = -1
    if preserve_subject:
        protected_label = detect_dominant_subject(labels, values)

    # C) Shape construction by level
    h, w = labels.shape
    labels = build_shapes(labels, values, build_level, h * w,
                          area_multiplier=cfg["min_area_multiplier"],
                          protected_label=protected_label,
                          allow_micro_values=cfg.get("allow_micro_values", False))

    # D) Boundary cleanup (unbiased median filter)
    labels = smooth_boundaries(labels, edge_strength,
                               kernel_size=cfg["morph_kernel_size"])

    # D2) Micro-fragment cleanup: median filter can create new tiny regions.
    #     Merge anything under 0.05% of canvas into its neighbor.
    micro_threshold = max(5, int(h * w * 0.0005))
    remaining = len(np.unique(labels))
    labels = remove_small_regions(labels, remaining, micro_threshold)

    # E) Render
    sigma_scale = cfg["edge_sigma_scale"]
    color_strategy = cfg.get("color_strategy", "painter")

    if mode == "grayscale":
        rendered = render_grayscale(labels, values, edge_strength,
                                    sigma_scale=sigma_scale)
    elif mode == "color":
        rendered = render_color_snap(labels, values, img, edge_strength,
                                     style_mode=color_strategy,
                                     sigma_scale=sigma_scale,
                                     exaggerate=cfg["color_exaggerate"])
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # Contrast boost (Graphic Poster pushes darks/lights apart)
    rendered = apply_contrast_boost(rendered, cfg.get("contrast_boost", 1.0))

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
