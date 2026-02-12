"""Master Painter Presets — rendering engine configurations.

Each preset controls the ENTIRE render pipeline, not just UI labels.
Presets define: pre-filtering, value grouping, shape merge behavior,
edge softness, color handling, and detail tolerance.

To add a new preset:
  1. Add an entry to PRESETS dict below.
  2. It will auto-appear in the API and UI.
"""

PRESETS = {
    "sargent": {
        # --- Display ---
        "name": "Sargent",
        "description": "Confident oil-paint block-in \u2014 bold value masses, minimal noise",

        # --- Pre-filtering ---
        # No aggressive median; moderate bilateral for soft mass grouping.
        # sigmaColor moderate to preserve dark/light value separation.
        "pre_median_ksize": 0,
        "bilateral_d": 13,
        "bilateral_sigma_color": 45,
        "bilateral_sigma_space": 80,
        "bilateral_d_high": 11,
        "bilateral_sigma_color_high": 35,
        "bilateral_sigma_space_high": 60,
        "bilateral_always": True,

        # --- Shape construction ---
        # Aggressive merge: large confident shapes, remove small fragments.
        "min_area_multiplier": 1.3,
        "allow_micro_values": False,

        # --- Boundary cleanup ---
        "morph_kernel_size": 7,

        # --- Edge rendering ---
        # High softness: soft internal edges, strong hierarchy.
        "edge_sigma_scale": 5.0,

        # --- Color ---
        # Simplified but accurate: warm/cool preserved, slight exaggeration.
        "color_strategy": "painter",
        "color_exaggerate": True,
        "contrast_boost": 1.0,

        # --- Default slider positions ---
        "default_values": 4,
        "default_build_level": 2,
        "default_edge_strength": 40,
        "default_color_mode": "grayscale",
    },

    "impressionist": {
        # --- Display ---
        "name": "Impressionist",
        "description": "Paintable color grouping \u2014 broken color, atmosphere, temperature shifts",

        # --- Pre-filtering ---
        # Lighter smoothing: allows more color variation to survive.
        "pre_median_ksize": 0,
        "bilateral_d": 9,
        "bilateral_sigma_color": 35,
        "bilateral_sigma_space": 65,
        "bilateral_d_high": 7,
        "bilateral_sigma_color_high": 25,
        "bilateral_sigma_space_high": 45,
        "bilateral_always": True,

        # --- Shape construction ---
        # Less aggressive merge: keeps small color variations inside shapes.
        "min_area_multiplier": 0.7,
        "allow_micro_values": True,

        # --- Boundary cleanup ---
        "morph_kernel_size": 5,

        # --- Edge rendering ---
        # Moderate softness: visible structure but still painterly.
        "edge_sigma_scale": 3.5,

        # --- Color ---
        # Strong color preservation: keep temperature shifts, exaggerate warm/cool.
        "color_strategy": "painter",
        "color_exaggerate": True,
        "contrast_boost": 1.0,

        # --- Default slider positions ---
        "default_values": 7,
        "default_build_level": 3,
        "default_edge_strength": 50,
        "default_color_mode": "color",
    },

    "graphic_poster": {
        # --- Display ---
        "name": "Graphic Poster",
        "description": "Bold simplified design \u2014 flat blocks, hard edges, strong silhouette",

        # --- Pre-filtering ---
        # Aggressive median for poster-like flattening, tight bilateral.
        "pre_median_ksize": 15,
        "bilateral_d": 5,
        "bilateral_sigma_color": 15,
        "bilateral_sigma_space": 15,
        "bilateral_d_high": 0,
        "bilateral_sigma_color_high": 0,
        "bilateral_sigma_space_high": 0,
        "bilateral_always": False,

        # --- Shape construction ---
        # Extreme merge: bold shapes, no subtle transitions.
        "min_area_multiplier": 2.8,
        "allow_micro_values": False,

        # --- Boundary cleanup ---
        "morph_kernel_size": 11,

        # --- Edge rendering ---
        # Hard edges: no gradients, sharp silhouettes.
        "edge_sigma_scale": 1.0,

        # --- Color ---
        # Flat palette: one median color per value group, contrast boosted.
        "color_strategy": "graphic",
        "color_exaggerate": False,
        "contrast_boost": 1.15,

        # --- Default slider positions ---
        "default_values": 3,
        "default_build_level": 1,
        "default_edge_strength": 90,
        "default_color_mode": "grayscale",
    },
}

# Ordered list of preset keys (controls UI order).
PRESET_ORDER = ["sargent", "impressionist", "graphic_poster"]

# Valid preset names for request validation.
VALID_PRESETS = set(PRESETS.keys())


def get_preset_config(preset_name: str) -> dict:
    """Return engine config for a preset. Raises KeyError if unknown."""
    if preset_name not in PRESETS:
        raise KeyError(f"Unknown preset: {preset_name}")
    return PRESETS[preset_name]


def get_presets_info() -> list[dict]:
    """Return display info + defaults for all presets (for the frontend API)."""
    result = []
    for key in PRESET_ORDER:
        p = PRESETS[key]
        result.append({
            "key": key,
            "name": p["name"],
            "description": p["description"],
            "defaults": {
                "values": p["default_values"],
                "build_level": p["default_build_level"],
                "edge_strength": p["default_edge_strength"],
                "color_mode": p["default_color_mode"],
            },
        })
    return result
