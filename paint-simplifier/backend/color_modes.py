"""Rendering modes: Grayscale and Color (with Painter/Graphic style).

edge_strength: int 0..100 where 0=maximum soft, 100=maximum graphic.
sigma_scale: float — controls edge softness per style mode.
style_mode: 'painter' (alive, warm/cool preserved) or 'graphic' (flat median).

Quantization fix: after edge blur, pixels are snapped back to the
exact palette so N values always produces exactly N tones.
"""

import cv2
import numpy as np


def _apply_edge(img_gray: np.ndarray, edge_strength: int,
                sigma_scale: float = 3.0) -> np.ndarray:
    """0 = full soft, 100 = full graphic."""
    if edge_strength >= 95:
        return img_gray
    sigma = sigma_scale * (1.0 - edge_strength / 100.0)
    if sigma < 0.3:
        return img_gray
    ksize = int(sigma * 4) | 1
    ksize = max(3, ksize)
    return cv2.GaussianBlur(img_gray, (ksize, ksize), sigmaX=sigma)


def _apply_edge_bgr(img_bgr: np.ndarray, edge_strength: int,
                    sigma_scale: float = 3.0) -> np.ndarray:
    if edge_strength >= 95:
        return img_bgr
    sigma = sigma_scale * (1.0 - edge_strength / 100.0)
    if sigma < 0.3:
        return img_bgr
    ksize = int(sigma * 4) | 1
    ksize = max(3, ksize)
    return cv2.GaussianBlur(img_bgr, (ksize, ksize), sigmaX=sigma)


def _snap_gray(out: np.ndarray, steps: np.ndarray) -> np.ndarray:
    """Snap each pixel to the nearest palette value (locks to N tones)."""
    diffs = np.abs(
        out.astype(np.int16)[:, :, np.newaxis]
        - steps.astype(np.int16)[np.newaxis, np.newaxis, :]
    )
    return steps[np.argmin(diffs, axis=2)]


def _snap_bgr(blurred: np.ndarray, flat: np.ndarray) -> np.ndarray:
    """Snap blurred BGR pixels back to nearest palette color using LAB distance.

    Uses LAB color space with luminance-weighted distance to preserve
    value hierarchy — prevents dark regions from snapping to bright colors
    after edge blur.
    """
    h, w = blurred.shape[:2]
    flat_2d = flat.reshape(-1, 3)
    palette_bgr = np.unique(flat_2d, axis=0)

    # Convert palette to LAB for perceptual distance
    # int32 required: LAB diffs up to 255, squared = 65025, overflows int16
    palette_lab = cv2.cvtColor(
        palette_bgr.reshape(1, -1, 3), cv2.COLOR_BGR2LAB
    ).reshape(-1, 3).astype(np.int32)

    # Convert blurred image to LAB
    blurred_lab = cv2.cvtColor(blurred, cv2.COLOR_BGR2LAB)
    out_2d = blurred_lab.reshape(-1, 3).astype(np.int32)

    result = np.empty((h * w, 3), dtype=np.uint8)

    batch = 100000
    for start in range(0, len(out_2d), batch):
        end = min(start + batch, len(out_2d))
        chunk = out_2d[start:end]
        diff = chunk[:, np.newaxis, :] - palette_lab[np.newaxis, :, :]
        # Weight L channel 2x (4x in squared distance) — value-first priority.
        # Prevents blur artifacts from crossing value boundaries.
        dists = 4 * diff[:, :, 0] ** 2 + diff[:, :, 1] ** 2 + diff[:, :, 2] ** 2
        nearest = np.argmin(dists, axis=1)
        result[start:end] = palette_bgr[nearest]

    return result.reshape(h, w, 3)


def render_grayscale(labels: np.ndarray, num_values: int, edge_strength: int,
                     sigma_scale: float = 3.0) -> np.ndarray:
    """Grayscale value steps, locked to exactly num_values tones."""
    if num_values == 1:
        steps = np.array([128], dtype=np.uint8)
    else:
        steps = np.linspace(0, 255, num_values).astype(np.uint8)
    out = steps[labels]
    adjusted = max(0, edge_strength - 10)
    out = _apply_edge(out, adjusted, sigma_scale)
    out = _snap_gray(out, steps)
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

    Sub-clusters on A/B channels only (chrominance) — luminance is locked
    to each value group's median L. This ensures value hierarchy is
    preserved and prevents dark colors from drifting toward white.

    If exaggerate=True, slightly push A/B channels apart for livelier color.
    """
    h, w = labels.shape
    original_lab = cv2.cvtColor(original_bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    out_lab = np.zeros((h, w, 3), dtype=np.float32)

    # Minimum cluster size: 5% of value group area
    min_cluster_frac = 0.05

    for v in range(num_values):
        group_mask = labels == v
        group_pixels = original_lab[group_mask]  # (N, 3)
        n_pixels = len(group_pixels)

        if n_pixels == 0:
            continue

        # Lock luminance to value group's median L — this is the core fix.
        # All structure comes from value grouping; color is decoration only.
        group_L = float(np.median(group_pixels[:, 0]))

        if n_pixels < 50:
            median_ab = np.median(group_pixels[:, 1:3], axis=0)
            out_lab[group_mask] = [group_L, median_ab[0], median_ab[1]]
            continue

        # Sub-cluster on A/B channels only (chrominance).
        # This preserves warm/cool variation without disturbing luminance.
        k = min(3, max(1, n_pixels // 30))
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        ab_samples = group_pixels[:, 1:3].copy().astype(np.float32)
        _, sub_labels, ab_centers = cv2.kmeans(
            ab_samples, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS
        )
        sub_labels = sub_labels.flatten()

        # Build full LAB centers with locked L
        centers = np.zeros((k, 3), dtype=np.float32)
        centers[:, 0] = group_L
        centers[:, 1:3] = ab_centers

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
            surviving_ab = ab_centers[surviving]
            for c in range(k):
                if c not in surviving:
                    dists = np.sum((surviving_ab - ab_centers[c]) ** 2, axis=1)
                    nearest = surviving[np.argmin(dists)]
                    sub_labels[sub_labels == c] = nearest

        # Optionally exaggerate: push A and B channels apart
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
                      style_mode: str = "painter",
                      sigma_scale: float = 3.0,
                      exaggerate: bool = False) -> np.ndarray:
    """Color rendering with style mode selection. Snaps to palette after blur."""
    if style_mode == "graphic":
        flat = _render_color_graphic(labels, num_values, original_bgr)
    else:
        flat = _render_color_painter(labels, num_values, original_bgr, exaggerate)

    out = _apply_edge_bgr(flat, edge_strength, sigma_scale)
    out = _snap_bgr(out, flat)
    return out
