"""FastAPI server: serve frontend + API routes for paint simplifier."""

import os
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from pathlib import Path

from .utils import (
    ensure_dirs, generate_image_id, save_upload, load_image,
    preview_cache, LRUCache,
    MAX_UPLOAD_BYTES, PREVIEW_MAX_SIDE, EXPORT_MAX_SIDE,
)
from .processor import process_image

app = FastAPI(title="Paint Simplifier")
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
    build_level: int = Field(ge=1, le=5)
    mode: str = Field(pattern=r"^(bw|grayscale|color)$")
    edge_strength: int = Field(ge=0, le=100)
    color_strategy: str = Field(default="painter", pattern=r"^(painter|graphic)$")
    exaggerate: bool = False
    guide_mode: bool = False
    overlays: OverlaySettings = OverlaySettings()


# --- API routes ---

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

    img = load_image(image_id)
    h, w = img.shape[:2]
    return {"image_id": image_id, "width": w, "height": h}


@app.post("/api/preview")
async def preview(req: ProcessRequest):
    cache_key = LRUCache.make_key(
        req.image_id, req.values, req.build_level,
        req.mode, req.edge_strength, PREVIEW_MAX_SIDE,
        req.color_strategy, req.exaggerate,
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
        color_strategy=req.color_strategy,
        exaggerate=req.exaggerate,
        guide_mode=req.guide_mode,
        overlay_edges=req.overlays.edges,
        overlay_shapes=req.overlays.shapes,
        overlay_focal=req.overlays.focal,
    )

    preview_cache.put(cache_key, png_bytes)
    return Response(content=png_bytes, media_type="image/png")


@app.post("/api/export")
async def export_image(req: ProcessRequest):
    try:
        img = load_image(req.image_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))

    png_bytes = process_image(
        img, req.values, req.build_level,
        req.mode, req.edge_strength, EXPORT_MAX_SIDE,
        color_strategy=req.color_strategy,
        exaggerate=req.exaggerate,
        guide_mode=req.guide_mode,
        overlay_edges=req.overlays.edges,
        overlay_shapes=req.overlays.shapes,
        overlay_focal=req.overlays.focal,
    )

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": "attachment; filename=paint_simplifier_export.png"}
    )


# --- Serve frontend ---

@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
