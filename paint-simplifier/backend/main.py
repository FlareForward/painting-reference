"""FastAPI server: serve frontend + API routes for paint simplifier."""

import os
import time
import base64
import json
import logging

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field
from pathlib import Path

# Load .env - check paint-simplifier/ first, then project root as fallback
_project_dir = Path(__file__).resolve().parent.parent
load_dotenv(_project_dir / ".env")
load_dotenv(_project_dir.parent / ".env", override=True)

from .utils import (
    ensure_dirs, generate_image_id, save_upload, load_image,
    preview_cache, LRUCache,
    MAX_UPLOAD_BYTES, PREVIEW_MAX_SIDE, EXPORT_MAX_SIDE,
)
from .processor import process_image

logger = logging.getLogger(__name__)

app = FastAPI(title="Paint Simplifier")
PORT = int(os.environ.get("PORT", 589))

# --- AI config (local-only) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODE = os.environ.get("AI_MODE", "")
AI_MAX_PER_HOUR = 20
_ai_call_timestamps: list[float] = []

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
    style_mode: str = Field(default="painter", pattern=r"^(painter|graphic)$")
    preserve_subject: bool = False
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
        req.style_mode, req.preserve_subject,
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
        style_mode=req.style_mode,
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
    try:
        img = load_image(req.image_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))

    png_bytes = process_image(
        img, req.values, req.build_level,
        req.mode, req.edge_strength, EXPORT_MAX_SIDE,
        style_mode=req.style_mode,
        preserve_subject=req.preserve_subject,
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


# --- AI analysis route (local-only) ---

class AIRequest(BaseModel):
    image_id: str
    values: int = 4
    build_level: int = 3
    mode: str = "grayscale"
    edge_strength: int = 70
    style_mode: str = "painter"


AI_SYSTEM_PROMPT = (
    "You are a master painting instructor helping a painter simplify a reference "
    "image into a strong painting block-in.\n\n"
    "Give concise structured advice:\n"
    "- focal point guidance\n"
    "- value grouping suggestions\n"
    "- edge hierarchy\n"
    "- simplification advice\n"
    "- color grouping notes\n\n"
    "Be brief, practical, and painter-focused.\n\n"
    "Return ONLY valid JSON with these keys: focal, values, edges, simplification, color"
)


def _check_ai_rate_limit() -> bool:
    """Return True if under the rate limit, pruning old timestamps."""
    now = time.time()
    cutoff = now - 3600
    _ai_call_timestamps[:] = [t for t in _ai_call_timestamps if t > cutoff]
    return len(_ai_call_timestamps) < AI_MAX_PER_HOUR


@app.post("/api/ai-analyze")
async def ai_analyze(req: AIRequest, request: Request):
    # Localhost guard
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "AI assist disabled in public mode")

    # AI mode guard
    if AI_MODE != "local_only":
        raise HTTPException(403, "AI assist disabled in public mode")

    # API key guard
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your_key_here":
        raise HTTPException(503, "AI disabled: no API key configured")

    # Rate limit
    if not _check_ai_rate_limit():
        raise HTTPException(429, "Local AI limit reached. Wait a bit.")

    # Load and encode the image
    try:
        img = load_image(req.image_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))

    # Generate a small preview for the AI (keep tokens low)
    png_bytes = process_image(
        img, req.values, req.build_level,
        req.mode, req.edge_strength, 512,
        style_mode=req.style_mode,
    )
    img_b64 = base64.b64encode(png_bytes).decode("utf-8")

    settings_context = (
        f"Current settings: {req.values} value groups, "
        f"build level {req.build_level}, {req.mode} mode, "
        f"edge strength {req.edge_strength}, {req.style_mode} style."
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Analyze this simplified painting reference. {settings_context}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_b64}",
                            },
                        },
                    ],
                },
            ],
            max_tokens=500,
        )

        _ai_call_timestamps.append(time.time())
        result = json.loads(response.choices[0].message.content)
        return result

    except json.JSONDecodeError:
        return {"error": "AI returned invalid response"}
    except Exception as e:
        logger.error("AI analysis failed: %s", e)
        raise HTTPException(500, "AI analysis unavailable")


# --- Serve frontend ---

@app.get("/")
async def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
