"""
main.py — FastAPI application entry point.

Endpoints:
  GET  /api/health              — health check
  POST /api/generate-story      — runs the story workflow; streams SSE progress events
  GET  /api/sample-stories      — list saved story snapshots
  GET  /api/sample-stories/{id} — load a full story snapshot
  POST /api/sample-stories      — save a story snapshot
"""

import json
import logging
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

load_dotenv()  # Agent Framework reads env vars directly — ensure .env is loaded early

from .config import settings  # noqa: E402
from .models import StoryRequest  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Children's Story Multi-Agent API",
    description=(
        "Multi-agent orchestration for generating illustrated children's stories "
        "using Microsoft Agent Framework."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin, "http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Telemetry (must be configured BEFORE importing StoryGenerator) ───────────

from .telemetry import configure_telemetry  # noqa: E402

configure_telemetry(app)

# ─── Service instances ────────────────────────────────────────────────────────

from .story_generator import StoryGenerator  # noqa: E402
from .tts import TTSService, TTSRequest  # noqa: E402
from .suggestion import StorySuggestionService  # noqa: E402

_story_generator = StoryGenerator()

# ─── Health check ─────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "children-story-multi-agent"}


# ─── Story generation (SSE) ───────────────────────────────────────────────────


@app.post("/api/generate-story")
async def generate_story(request: StoryRequest) -> EventSourceResponse:
    """Accepts story parameters and streams back SSE events as the multi-agent
    workflow progresses.  The final event (type: 'complete') contains the
    full illustrated StoryResponse.
    """
    return _story_generator.event_source_response(request)


# ─── Text-to-Speech (TTS) ─────────────────────────────────────────────────────

_tts = TTSService()

@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    """Synthesize speech and stream audio/mpeg chunks to the client."""
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is required.")
    _tts.validate_config()
    return _tts.streaming_response(req.text.strip())


# ─── Story suggestion ("Surprise Me" auto-fill) ───────────────────────────────

_suggestion_service = StorySuggestionService()


@app.post("/api/suggest-story")
async def suggest_story() -> dict:
    """Return a creative, internally-consistent set of seed values to auto-fill
    the create-story form. Each call produces a fresh suggestion driven by a
    randomized inspiration block — variety is part of the contract.
    """
    try:
        suggestion = await _suggestion_service.suggest()
    except Exception as exc:
        logger.exception("Failed to generate story suggestion")
        raise HTTPException(status_code=502, detail=f"Suggestion service error: {exc}")
    return suggestion.model_dump()


# ─── Demo Stories ─────────────────────────────────────────────────────────────

from .demo_stories import (  # noqa: E402
    list_demo_stories,
    get_demo_story,
    get_demo_image_bytes,
    save_demo_story,
    get_draft_image_bytes,
    cleanup_old_drafts,
    seed_demo_stories_if_empty,
)
from fastapi.responses import Response  # noqa: E402


@app.on_event("startup")
async def _storage_startup() -> None:
    """On boot: (1) seed bundled sample stories into the configured
    backend if it's empty, then (2) sweep stale per-session draft
    folders/blobs.

    Seeding is idempotent — once stories are present it's a no-op, so it
    safely runs on every container start.  The drafts sweep keeps an
    aborted generation from leaving image files behind forever (24h is a
    forgiving default well clear of the longest plausible session).
    """
    try:
        seed_demo_stories_if_empty()
    except Exception:
        logger.exception("Failed to seed demo stories on startup")
    try:
        cleanup_old_drafts()
    except Exception:
        logger.exception("Failed to clean up draft folders on startup")


@app.get("/api/demo-stories")
async def demo_stories_list() -> list:
    """Return metadata for all available demo stories."""
    return list_demo_stories()


@app.get("/api/demo-stories/{story_id}")
async def demo_story_detail(story_id: str) -> dict:
    """Return the full story + events for a single demo story."""
    data = get_demo_story(story_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Demo story '{story_id}' not found.")
    return data


@app.get("/api/demo-stories/{story_id}/images/{filename}")
async def demo_story_image(story_id: str, filename: str):
    """Serve an image file for a demo story (from local disk or blob)."""
    data = get_demo_image_bytes(story_id, filename)
    if data is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return Response(content=data, media_type=_guess_image_media_type(filename))


@app.get("/api/drafts/{session_id}/images/{filename}")
async def draft_image(session_id: str, filename: str):
    """Serve an in-progress (not-yet-saved) image for the given session.

    These bytes are written by ArtDirector during generation and live under
    the per-session ``_drafts/<session_id>/images/`` prefix until either the
    user saves the story (which promotes them to a demo-story folder/prefix)
    or the 24h cleanup sweep removes them.
    """
    data = get_draft_image_bytes(session_id, filename)
    if data is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return Response(content=data, media_type=_guess_image_media_type(filename))


def _guess_image_media_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/png"


@app.post("/api/demo-stories")
async def save_demo_story_endpoint(request: dict):
    """Save a story snapshot as a new demo story.

    Expects JSON with: meta {id?, title, description, moral}, story, events.
    Images are extracted from base64 data URIs and saved as separate files.
    """
    try:
        story_id = save_demo_story(request)
        return {"status": "ok", "id": story_id}
    except Exception as e:
        logger.exception("Failed to save demo story")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Static frontend (production) ─────────────────────────────────────────────
#
# In local development the React dev server (Vite) runs on :5173 and proxies
# /api → :8000.  In production the frontend is built (`npm run build`) and the
# resulting `dist/` directory is mounted into the container at FRONTEND_DIST_DIR.
# When that directory exists, we serve it directly so the whole app runs from
# a single origin (no CORS, SSE works natively).

import os  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse as _FileResponse  # noqa: E402
from starlette.requests import Request  # noqa: E402

_FRONTEND_DIST = Path(
    os.environ.get(
        "FRONTEND_DIST_DIR",
        str(Path(__file__).parent.parent.parent / "frontend" / "dist"),
    )
)

if _FRONTEND_DIST.is_dir():
    logger.info("Serving built frontend from %s", _FRONTEND_DIST)

    # Serve hashed assets under /assets/* directly.
    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str, request: Request):
        # API and asset routes are handled by their own handlers (registered
        # above); anything else falls back to index.html so the SPA router
        # can take over.  We still 404 on unknown /api/* to avoid masking bugs.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return _FileResponse(str(candidate))
        return _FileResponse(str(_FRONTEND_DIST / "index.html"))
else:
    logger.info(
        "Frontend dist directory not found at %s — running in API-only mode "
        "(use the Vite dev server for the UI).",
        _FRONTEND_DIST,
    )