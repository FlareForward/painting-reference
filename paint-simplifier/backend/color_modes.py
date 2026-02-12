"""Rendering modes: B/W, Grayscale, Color (with Painter/Graphic strategy).

edge_strength: int 0..100 where 0=maximum soft, 100=maximum graphic.
color_strategy: 'painter' (alive, warm/cool preserved) or 'graphic' (flat median).
exaggeration: bool - slightly push color separation for painter mode.
"""

import cv2
import numpy as np


def _apply_edge(img_gray: np.ndarray, edge_strength: int) -> np.ndarray:
    """0 = full soft, 100 = full graphic."""
    if edge_strength >= 95:
        return img_gray
    sigma = 3.0 * (1.0 - edge_strength / 100.0)
    if sigma < 0.3:
        return img_gray
    ksize = int(sigma * 4) | 1
    ksize = max(3, ksize)
    return cv2.GaussianBlur(img_gray, (ksize, ksize), sigmaX=sigma)


def _apply_edge_bgr(img_bgr: np.ndarray, edge_strength: int) -> np.ndarray:
    if edge_strength >= 95:
        return img_bgr
    sigma = 3.0 * (1.0 - edge_strength / 100.0)
    if sigma < 0.3:
        return img_bgr
    ksize = int(sigma * 4) | 1
    ksize = max(3, ksize)
    return cv2.GaussianBlur(img_bgr, (ksize, ksize), sigmaX=sigma)


def render_bw(labels: np.ndarray, num_values: int, edge_strength: int) -> np.ndarray:
    """Flat B/W value steps."""
    if num_values == 1:
        steps = np.array([128], dtype=np.uint8)
    else:
        steps = np.linspace(0, 255, num_values).astype(np.uint8)
    out = steps[labels]
    out = _apply_edge(out, edge_strength)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def render_grayscale(labels: np.ndarray, num_values: int, edge_strength: int) -> np.ndarray:
    """Slightly smoother mapping at boundaries."""
    if num_values == 1:
        steps = np.array([128], dtype=np.uint8)
    else:
        steps = np.linspace(0, 255, num_values).astype(np.uint8)
    out = steps[labels]
    adjusted = max(0, edge_strength - 10)
    out = _apply_edge(out, adjusted)
    return cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)


def _render_color_graphic(labels: np.ndarray, num_values: int,
                          original_bgr: np.ndarray) -> np.ndarray:
    """Graphic strategy: ONE flat median color per value group."""
    h, w = labels.shape
    original_lab = cv2.cvtColor(original_bgr, cv2.COLOR_BGR2LAB)

    palette_lab = np.zeros((num_values, 3), dtype=np.float32)
    for i in range(num_values):
        mask = labels == i
        if np.any(mask):
            palette_lab[i] = np.median(original_lab[mask], axis=0)
        else:
            lum = int(255 * i / max(num_values - 1, 1))
            palette_lab[i] = [lum, 128, 128]

    palette_u8 = np.clip(palette_lab, 0, 255).astype(np.uint8)

    out_lab = np.zeros((h, w, 3), dtype=np.uint8)
    for i in range(num_values):
        out_lab[labels == i] = palette_u8[i]

    return cv2.cvtColor(out_lab, cv2.COLOR_LAB2BGR)


def _render_color_painter(labels: np.ndarray, num_values: int,
                          original_bgr: np.ndarray,
                          exaggerate: bool = False) -> np.ndarray:
    """Painter strategy: 2-3 colors per value group, preserving warm/cool.

    Inside each value group:
    - k-means (k=3) on LAB color
    - remove micro clusters
    - preserve warm/cool temperature variation
    - max 3 colors per value group

    If exaggerate=True, slightly push A/B channels apart for livelier color.
    """
    h, w = labels.shape
    original_lab = cv2.cvtColor(original_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    out_lab = np.zeros((h, w, 3), dtype=np.float32)

    total_pixels = h * w
    # Minimum cluster size: 0.5% of value group area
    min_cluster_frac = 0.05

    for v in range(num_values):
        group_mask = labels == v
        group_pixels = original_lab[group_mask]  # (N, 3)
        n_pixels = len(group_pixels)

        if n_pixels == 0:
            continue

        if n_pixels < 50:
            # Too few pixels, just use median
            out_lab[group_mask] = np.median(group_pixels, axis=0)
            continue

        # Cluster this value group into up to 3 sub-colors
        k = min(3, max(1, n_pixels // 30))
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        samples = group_pixels.astype(np.float32)
        _, sub_labels, centers = cv2.kmeans(
            samples, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
        sub_labels = sub_labels.flatten()

        # Remove micro clusters: reassign to nearest surviving cluster
        min_size = max(10, int(n_pixels * min_cluster_frac))
        surviving = []
        for c in range(k):
            if np.sum(sub_labels == c) >= min_size:
                surviving.append(c)

        if not surviving:
            surviving = [0]  # keep at least one

        # Reassign dead clusters to nearest surviving
        if len(surviving) < k:
            surviving_centers = centers[surviving]
            for c in range(k):
                if c not in surviving:
                    dists = np.sum((surviving_centers - centers[c]) ** 2, axis=1)
                    nearest = surviving[np.argmin(dists)]
                    sub_labels[sub_labels == c] = nearest

        # Optionally exaggerate: push A and B channels away from group mean
        if exaggerate and len(surviving) > 1:
            group_mean_ab = np.mean(group_pixels[:, 1:3], axis=0)
            for c in surviving:
                delta = centers[c, 1:3] - group_mean_ab
                centers[c, 1:3] = group_mean_ab + delta * 1.35

        # Assign colors
        group_indices = np.where(group_mask)
        for c in range(k):
            c_mask = sub_labels == c
            if not np.any(c_mask):
                continue
            ys = group_indices[0][c_mask]
            xs = group_indices[1][c_mask]
            out_lab[ys, xs] = centers[c if c in surviving else surviving[0]]

    out_lab = np.clip(out_lab, 0, 255).astype(np.uint8)
    return cv2.cvtColor(out_lab, cv2.COLOR_LAB2BGR)


def render_color_snap(labels: np.ndarray, num_values: int,
                      original_bgr: np.ndarray, edge_strength: int,
                      color_strategy: str = "painter",
                      exaggerate: bool = False) -> np.ndarray:
    """Color rendering with strategy selection."""
    if color_strategy == "graphic":
        out = _render_color_graphic(labels, num_values, original_bgr)
    else:
        out = _render_color_painter(labels, num_values, original_bgr, exaggerate)

    return _apply_edge_bgr(out, edge_strength)
