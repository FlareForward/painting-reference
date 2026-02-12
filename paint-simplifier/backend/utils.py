"""IO, resizing, caching, and helper utilities."""

import uuid
import cv2
import numpy as np
from pathlib import Path
from collections import OrderedDict
import threading

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_DIMENSION = 8000
PREVIEW_MAX_SIDE = 900
EXPORT_MAX_SIDE = 3000


def ensure_dirs():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def generate_image_id() -> str:
    return uuid.uuid4().hex


def save_upload(data: bytes, image_id: str) -> Path:
    """Decode uploaded bytes, validate, convert to PNG, save, return path."""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    h, w = img.shape[:2]
    if h > MAX_DIMENSION or w > MAX_DIMENSION:
        raise ValueError(f"Image too large ({w}x{h}). Max {MAX_DIMENSION}px per side.")
    path = UPLOADS_DIR / f"{image_id}.png"
    cv2.imwrite(str(path), img)
    return path


def load_image(image_id: str) -> np.ndarray:
    """Load an uploaded image by id. Returns BGR numpy array."""
    path = UPLOADS_DIR / f"{image_id}.png"
    if not path.exists():
        raise FileNotFoundError(f"Image {image_id} not found")
    if not path.resolve().parent == UPLOADS_DIR.resolve():
        raise ValueError("Invalid image id")
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not read image file")
    return img


def resize_preserve_aspect(img: np.ndarray, max_side: int) -> np.ndarray:
    """Resize so longest side <= max_side, preserving aspect ratio."""
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img
    scale = max_side / max(h, w)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)


def encode_png(img: np.ndarray) -> bytes:
    """Encode BGR image to PNG bytes."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return buf.tobytes()


class LRUCache:
    """Thread-safe LRU cache for preview results. Capacity 20."""

    def __init__(self, capacity: int = 20):
        self._capacity = capacity
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def make_key(image_id: str, values: int, build_level: int,
                 mode: str, edge_strength: int, max_side: int,
                 preset: str, preserve_subject: bool,
                 guide_mode: bool, overlay_edges: bool,
                 overlay_shapes: bool, overlay_focal: bool) -> str:
        return (f"{image_id}:{values}:{build_level}:{mode}:{edge_strength}:"
                f"{max_side}:{preset}:{preserve_subject}:"
                f"{guide_mode}:{overlay_edges}:{overlay_shapes}:{overlay_focal}")

    def get(self, key: str) -> bytes | None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, key: str, data: bytes):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self._capacity:
                    self._cache.popitem(last=False)
                self._cache[key] = data


preview_cache = LRUCache(20)
