#!/usr/bin/env python3
"""
capture_demo_story.py — CLI tool to capture a generated story as a demo story.

Usage:
    cd backend
    python scripts/capture_demo_story.py <story_id> <raw_story_file>

Where:
    story_id        Slug for the demo story folder (e.g. luna_the_curious_cat)
    raw_story_file  Path to a JSON file containing:
                      {
                        "story":  <StoryResponse object>,
                        "events": <list of SSE event dicts>
                      }

    You can produce raw_story_file by opening the browser DevTools Network tab while
    generating a story, copying the final "complete" SSE payload, wrapping it like:
        {"story": <paste the data field here>, "events": <paste the progress/detail list>}
    and saving it to a .json file.

The script will:
  1. Create backend/demo_stories/<story_id>/
  2. Download all images (cover, pages, the_end) to images/
  3. Rewrite image_url fields in story.json to /api/demo-stories/<story_id>/images/<file>
  4. Write story.json, events.json, and meta.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent.parent
_DEMO_ROOT   = _BACKEND_DIR / "demo_stories"


def slugify(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s_-]+", "_", name)
    return name


def download_image(url: str, dest: Path) -> bool:
    """Download url to dest. Returns True on success."""
    if not url or url.startswith("/api/"):
        return False  # already local or empty
    print(f"  Downloading {url} → {dest.name}")
    try:
        urllib.request.urlretrieve(url, str(dest))  # noqa: S310 (url from trusted story output)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  WARNING: failed to download {url}: {exc}", file=sys.stderr)
        return False


def capture(story_id: str, raw_path: Path) -> None:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    story  = raw.get("story") or raw  # accept bare StoryResponse too
    events = raw.get("events", [])

    story_dir = _DEMO_ROOT / story_id
    images_dir = story_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing to {story_dir}/")

    # ── Download images and rewrite URLs ──────────────────────────────────────
    def rewrite(field: str, filename: str) -> None:
        original_url = story.get(field)
        if not original_url:
            return
        dest = images_dir / filename
        downloaded = download_image(original_url, dest)
        if downloaded:
            story[field] = f"/api/demo-stories/{story_id}/images/{filename}"

    rewrite("cover_image_url", "cover.png")
    rewrite("the_end_image_url", "the_end.png")

    pages = story.get("pages") or []
    for i, page in enumerate(pages, start=1):
        filename = f"page_{i}.png"
        original_url = page.get("image_url")
        if not original_url:
            continue
        dest = images_dir / filename
        downloaded = download_image(original_url, dest)
        if downloaded:
            page["image_url"] = f"/api/demo-stories/{story_id}/images/{filename}"

    # ── Write story.json ──────────────────────────────────────────────────────
    (story_dir / "story.json").write_text(
        json.dumps(story, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("  Wrote story.json")

    # ── Write events.json ─────────────────────────────────────────────────────
    (story_dir / "events.json").write_text(
        json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("  Wrote events.json")

    # ── Write meta.json ───────────────────────────────────────────────────────
    title = story.get("title") or story_id.replace("_", " ").title()
    moral = story.get("moral_summary") or ""
    description = ""
    # Build a short description from the first page text if available
    if pages and pages[0].get("text"):
        first_text = pages[0]["text"]
        description = first_text[:120].rstrip() + ("…" if len(first_text) > 120 else "")

    cover_url = story.get("cover_image_url") or ""

    meta = {
        "id":              story_id,
        "title":           title,
        "description":     description,
        "moral":           moral,
        "cover_image_url": cover_url,
    }
    (story_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("  Wrote meta.json")
    print(f"\nDone! Demo story '{story_id}' is ready at {story_dir}")
    print("You can now restart the backend and it will appear in GET /api/demo-stories")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("story_id",       help="Slug for the demo story (e.g. luna_the_curious_cat)")
    parser.add_argument("raw_story_file", help="Path to the raw JSON file containing story + events")
    args = parser.parse_args()

    story_id = slugify(args.story_id) if args.story_id else ""
    if not story_id:
        print("ERROR: story_id must be a non-empty string.", file=sys.stderr)
        sys.exit(1)

    raw_path = Path(args.raw_story_file)
    if not raw_path.is_file():
        print(f"ERROR: File not found: {raw_path}", file=sys.stderr)
        sys.exit(1)

    capture(story_id, raw_path)


if __name__ == "__main__":
    main()
