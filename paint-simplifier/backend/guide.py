"""Guide mode: edge hierarchy analysis, major shapes, focal hint overlays."""

import cv2
import numpy as np


def compute_edge_hierarchy(labels: np.ndarray, num_values: int,
                           img_shape: tuple) -> np.ndarray:
    """Classify every boundary pixel as HARD (2), SOFT (1), or LOST (0).

    For each boundary between value regions, evaluate:
    - value difference between neighboring labels
    - region sizes on each side
    - centrality (distance to image center)

    Returns edge_map (h, w) with values 0=none, 1=lost, 2=soft, 3=hard.
    """
    h, w = labels.shape
    edge_map = np.zeros((h, w), dtype=np.uint8)

    # Compute value step for each label (0..num_values-1 maps to 0..255)
    if num_values <= 1:
        return edge_map
    step_values = np.linspace(0, 255, num_values).astype(np.float32)

    # Precompute region sizes per label
    region_sizes = np.zeros(num_values, dtype=np.int64)
    for v in range(num_values):
        region_sizes[v] = np.sum(labels == v)

    total_pixels = h * w
    # Centrality weight map: 1.0 at center, 0.3 at corners
    cy, cx = h / 2.0, w / 2.0
    max_dist = np.sqrt(cy ** 2 + cx ** 2)
    yy, xx = np.mgrid[0:h, 0:w]
    centrality = 1.0 - 0.7 * (np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / max_dist)

    # Find boundaries: pixels where any 4-neighbor has a different label
    # Shift in 4 directions and compare
    pad = np.pad(labels, 1, mode='edge')
    diff_up = labels != pad[:-2, 1:-1]
    diff_down = labels != pad[2:, 1:-1]
    diff_left = labels != pad[1:-1, :-2]
    diff_right = labels != pad[1:-1, 2:]
    is_boundary = diff_up | diff_down | diff_left | diff_right

    # For each boundary pixel, compute the max value jump to any neighbor
    boundary_ys, boundary_xs = np.where(is_boundary)

    if len(boundary_ys) == 0:
        return edge_map

    # Vectorized: get label at boundary and neighbor labels
    center_labels = labels[boundary_ys, boundary_xs]
    center_vals = step_values[center_labels]

    max_jumps = np.zeros(len(boundary_ys), dtype=np.float32)
    max_neighbor_labels = center_labels.copy()

    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        ny = np.clip(boundary_ys + dy, 0, h - 1)
        nx = np.clip(boundary_xs + dx, 0, w - 1)
        n_labels = labels[ny, nx]
        n_vals = step_values[n_labels]
        jumps = np.abs(center_vals - n_vals)
        update = jumps > max_jumps
        max_jumps[update] = jumps[update]
        max_neighbor_labels[update] = n_labels[update]

    # Region size factor: larger regions on both sides = more important edge
    size_a = region_sizes[center_labels].astype(np.float32)
    size_b = region_sizes[max_neighbor_labels].astype(np.float32)
    min_size = np.minimum(size_a, size_b)
    size_factor = np.clip(min_size / (total_pixels * 0.01), 0, 1)

    # Centrality at boundary pixels
    cent = centrality[boundary_ys, boundary_xs]

    # Combined score
    # Normalize jump to 0..1
    jump_norm = max_jumps / 255.0
    score = jump_norm * 0.5 + size_factor * 0.25 + cent * 0.25

    # Classify
    # HARD: score > 0.45 and jump > 80/255
    # SOFT: score > 0.2 or jump > 40/255
    # LOST: everything else on boundary
    hard_mask = (score > 0.45) & (jump_norm > 0.31)
    soft_mask = ~hard_mask & ((score > 0.2) | (jump_norm > 0.16))
    lost_mask = ~hard_mask & ~soft_mask

    edge_map[boundary_ys[hard_mask], boundary_xs[hard_mask]] = 3
    edge_map[boundary_ys[soft_mask], boundary_xs[soft_mask]] = 2
    edge_map[boundary_ys[lost_mask], boundary_xs[lost_mask]] = 1

    return edge_map


def compute_major_shapes(labels: np.ndarray, num_values: int,
                         top_n: int = 7) -> list[dict]:
    """Find the top N largest connected value regions.

    Returns list of dicts: {label, area, contour} sorted by area descending.
    """
    h, w = labels.shape
    shapes = []

    for v in range(num_values):
        mask = (labels == v).astype(np.uint8)
        num_cc, cc_labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for cc_id in range(1, num_cc):
            area = stats[cc_id, cv2.CC_STAT_AREA]
            cc_mask = (cc_labels == cc_id).astype(np.uint8)
            contours, _ = cv2.findContours(cc_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                shapes.append({
                    "label": v,
                    "area": area,
                    "contour": contours[0],
                })

    shapes.sort(key=lambda s: s["area"], reverse=True)
    return shapes[:top_n]


def compute_focal_hint(labels: np.ndarray, num_values: int,
                       img_shape: tuple) -> np.ndarray:
    """Subtle focal emphasis based on high-contrast clusters near center.

    Returns alpha mask (h, w) float32 in [0..1] for overlay compositing.
    Brightest near center where contrast is highest.
    """
    h, w = labels.shape

    if num_values <= 1:
        return np.zeros((h, w), dtype=np.float32)

    step_values = np.linspace(0, 255, num_values).astype(np.float32)

    # Local contrast: for each pixel, max value difference to 4-neighbors
    pixel_vals = step_values[labels]
    pad = np.pad(pixel_vals, 1, mode='edge')
    diffs = np.stack([
        np.abs(pixel_vals - pad[:-2, 1:-1]),
        np.abs(pixel_vals - pad[2:, 1:-1]),
        np.abs(pixel_vals - pad[1:-1, :-2]),
        np.abs(pixel_vals - pad[1:-1, 2:]),
    ], axis=0)
    local_contrast = np.max(diffs, axis=0) / 255.0

    # Blur to get regional contrast
    local_contrast = cv2.GaussianBlur(local_contrast, (0, 0), sigmaX=h * 0.08)

    # Radial weight: strongest at center, fading out
    cy, cx = h / 2.0, w / 2.0
    max_r = np.sqrt(cy ** 2 + cx ** 2)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    radial = np.clip(1.0 - (dist / (max_r * 0.7)), 0, 1) ** 2

    # Combine: contrast * radial
    focal = local_contrast * radial
    # Normalize to 0..1
    fmax = focal.max()
    if fmax > 0:
        focal /= fmax

    return focal.astype(np.float32)


def overlay_edge_map(rendered: np.ndarray, edge_map: np.ndarray) -> np.ndarray:
    """Draw edge hierarchy on rendered image.

    Hard edges -> thin red, Soft -> thin blue, Lost -> faint yellow.
    Low opacity to not overpower.
    """
    out = rendered.copy()

    # HARD (3): red, alpha ~0.5
    hard = edge_map == 3
    out[hard] = (out[hard].astype(np.float32) * 0.5 +
                 np.array([0, 0, 220], dtype=np.float32) * 0.5).astype(np.uint8)

    # SOFT (2): blue, alpha ~0.35
    soft = edge_map == 2
    out[soft] = (out[soft].astype(np.float32) * 0.65 +
                 np.array([220, 120, 0], dtype=np.float32) * 0.35).astype(np.uint8)

    # LOST (1): yellow, alpha ~0.15
    lost = edge_map == 1
    out[lost] = (out[lost].astype(np.float32) * 0.85 +
                 np.array([0, 200, 220], dtype=np.float32) * 0.15).astype(np.uint8)

    return out


def overlay_major_shapes(rendered: np.ndarray, shapes: list[dict]) -> np.ndarray:
    """Gently outline top major shapes for composition reading."""
    out = rendered.copy()
    # Subtle white outlines at low opacity
    overlay = out.copy()
    for s in shapes:
        cv2.drawContours(overlay, [s["contour"]], -1, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.4, out, 0.6, 0, out)
    return out


def overlay_focal_hint(rendered: np.ndarray, focal: np.ndarray) -> np.ndarray:
    """Apply subtle radial emphasis — soft vignette-like brighten at focal area."""
    out = rendered.astype(np.float32)
    # Very subtle: brighten by up to 15% where focal is strongest
    boost = 1.0 + focal[:, :, np.newaxis] * 0.15
    out = np.clip(out * boost, 0, 255).astype(np.uint8)
    return out
