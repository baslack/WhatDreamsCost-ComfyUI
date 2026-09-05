"""HTTP routes for server-side LTX Director timeline save/load.

Some browsers (notably Brave) ship the File System Access API disabled, so the editor
can't do a silent local "Save". These routes persist the timeline JSON on the ComfyUI
host instead, so Save can overwrite a remembered name without a file dialog and Load can
offer a list of saved timelines. Names are basename/charset-sanitised and every path is
asserted to resolve inside the per-user timelines directory.

Routes:
  POST /ltx_director/save_timeline   -> {name, payload} write <name>.json, return {name}
  GET  /ltx_director/list_timelines  -> {names: [...]}
  GET  /ltx_director/load_timeline   -> ?name=<name> returns the JSON text
"""

import os
import re
import json

import folder_paths
from server import PromptServer
from aiohttp import web

# Spaces are allowed for readable names; everything else outside this set collapses to "_".
_TIMELINE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]")


def _contained(root, path):
    """True iff ``path`` resolves to a location inside ``root`` (symlinks/.. resolved)."""
    try:
        root = os.path.realpath(root)
        target = os.path.realpath(path)
        return os.path.commonpath([root, target]) == root
    except ValueError:
        # Different drives / mixed absolute-relative on Windows -> not contained.
        return False


def _timeline_dir(request):
    # Resolve user/<userid>/ltx_director_timelines via ComfyUI's UserManager so it honours
    # the active user — "default" in single-user mode (where ComfyUI puts workflows), or the
    # real id under multi-user — instead of hardcoding "default". Fall back to user/default/
    # for older ComfyUI without per-user routing.
    d = None
    try:
        d = PromptServer.instance.user_manager.get_request_user_filepath(
            request, "ltx_director_timelines", create_dir=True)
    except Exception:
        d = None
    if not d:
        d = os.path.join(folder_paths.get_user_directory(), "default", "ltx_director_timelines")
    os.makedirs(d, exist_ok=True)
    return os.path.realpath(d)


def _safe_timeline_name(raw):
    """Reduce a requested timeline name to a single safe filename stem (no extension)."""
    base = os.path.basename(str(raw or ""))
    if base.lower().endswith(".json"):
        base = base[:-5]
    base = _TIMELINE_NAME_RE.sub("_", base).strip(" ._")
    return base or "timeline"


@PromptServer.instance.routes.post("/ltx_director/save_timeline")
async def save_timeline(request):
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON body")

    name = _safe_timeline_name(data.get("name"))
    payload = data.get("payload")
    if payload is None:
        return web.Response(status=400, text="Missing payload")

    out_dir = _timeline_dir(request)
    out_path = os.path.join(out_dir, name + ".json")
    if not _contained(out_dir, out_path):
        return web.Response(status=400, text="Invalid name")

    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception as e:
        return web.Response(status=500, text="Failed to write timeline: %s" % e)
    return web.json_response({"name": name})


@PromptServer.instance.routes.get("/ltx_director/list_timelines")
async def list_timelines(request):
    out_dir = _timeline_dir(request)
    try:
        names = sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(out_dir)
            if f.lower().endswith(".json") and os.path.isfile(os.path.join(out_dir, f))
        )
    except Exception:
        names = []
    return web.json_response({"names": names})


@PromptServer.instance.routes.get("/ltx_director/load_timeline")
async def load_timeline(request):
    name = _safe_timeline_name(request.query.get("name"))
    out_dir = _timeline_dir(request)
    path = os.path.join(out_dir, name + ".json")
    if not _contained(out_dir, path) or not os.path.isfile(path):
        return web.Response(status=404, text="Timeline not found")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except Exception as e:
        return web.Response(status=500, text="Failed to read timeline: %s" % e)
    return web.Response(text=text, content_type="application/json")
