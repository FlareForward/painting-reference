"""FastAPI server: serve frontend + API routes for Block-In Studio.

Fully local, deterministic rendering — no external API calls.
"""

import os
import logging

from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from pathlib import Path

from .utils import (
    ensure_dirs, generate_image_id, save_upload, load_image,
    preview_cache, LRUCache, cleanup_uploads,
    MAX_UPLOAD_BYTES, PREVIEW_MAX_SIDE, EXPORT_MAX_SIDE,
)
from .processor import process_image
from .presets import get_presets_info, VALID_PRESETS

logger = logging.getLogger(__name__)

app = FastAPI(title="Block-In Studio")
PORT = int(os.environ.get("PORT", 589))

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

ensure_dirs()


# --- API models ---

class OverlaySettings(BaseModel):
    edges: bool = False
    shapes: bool = False
    focal: bool = False


class ProcessRequest(BaseModel):
    image_id: str
    values: int = Field(ge=2, le=10)
    build_level: int = Field(ge=1, le=4)
    mode: str = Field(pattern=r"^(grayscale|color)$")
    edge_strength: int = Field(ge=0, le=100)
    preset: str = Field(default="sargent")
    preserve_subject: bool = False
    guide_mode: bool = False
    overlays: OverlaySettings = OverlaySettings()


# --- API routes ---

@app.get("/api/presets")
async def list_presets():
    """Return available presets with display info and default slider values."""
    return get_presets_info()


@app.post("/api/upload")
async def upload_image(file: UploadFile):
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File too large (max {MAX_UPLOAD_BYTES // (1024*1024)}MB)")

    image_id = generate_image_id()
    try:
        save_upload(data, image_id)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Free memory: clear cached previews and delete previous upload files
    preview_cache.clear()
    cleanup_uploads(keep_id=image_id)

    img = load_image(image_id)
    h, w = img.shape[:2]
    return {"image_id": image_id, "width": w, "height": h}


@app.post("/api/preview")
async def preview(req: ProcessRequest):
    if req.preset not in VALID_PRESETS:
        raise HTTPException(400, f"Unknown preset: {req.preset}")

    cache_key = LRUCache.make_key(
        req.image_id, req.values, req.build_level,
        req.mode, req.edge_strength, PREVIEW_MAX_SIDE,
        req.preset, req.preserve_subject,
        req.guide_mode, req.overlays.edges,
        req.overlays.shapes, req.overlays.focal,
    )
    cached = preview_cache.get(cache_key)
    if cached is not None:
        return Response(content=cached, media_type="image/png")

    try:
        img = load_image(req.image_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))

    png_bytes = process_image(
        img, req.values, req.build_level,
        req.mode, req.edge_strength, PREVIEW_MAX_SIDE,
        preset=req.preset,
        preserve_subject=req.preserve_subject,
        guide_mode=req.guide_mode,
        overlay_edges=req.overlays.edges,
        overlay_shapes=req.overlays.shapes,
        overlay_focal=req.overlays.focal,
    )

    preview_cache.put(cache_key, png_bytes)
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/export")
async def export_image(req: ProcessRequest):
    if req.preset not in VALID_PRESETS:
        raise HTTPException(400, f"Unknown preset: {req.preset}")

    try:
        img = load_image(req.image_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))

    png_bytes = process_image(
        img, req.values, req.build_level,
        req.mode, req.edge_strength, EXPORT_MAX_SIDE,
        preset=req.preset,
        preserve_subject=req.preserve_subject,
        guide_mode=req.guide_mode,
        overlay_edges=req.overlays.edges,
        overlay_shapes=req.overlays.shapes,
        overlay_focal=req.overlays.focal,
    )

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": "attachment; filename=block_in_studio_export.png"}
    )


# --- Serve frontend ---

@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
