"""HTTP routes backing the LTX Director timeline *bundle* (portable zip) feature.

A bundle packages a timeline's JSON payload together with the actual media files it
references, so a timeline can be backed up or shared and restored on a fresh install.
It layers on top of the LTX Director 2.0 file save/load: the bundle wraps the exact
same payload produced by the editor's `_getTimelineSavePayload()` and, on import,
returns a manifest of the same shape so the editor can re-hydrate it through its
existing `_applyLoadedTimeline()` path.

Two routes:
  POST /ltx_director/save_bundle  -> zip {timeline.json + media/<rel>} for download
  POST /ltx_director/load_bundle  -> extract media into input/<bundleName>/ and return
                                     the manifest with media paths re-pointed there

Security note: the load route writes files from an *uploaded* zip into ComfyUI's input
directory. It therefore mirrors the hardened-route patterns already used in
load_video_ui.py — every extracted path is basename/relative-sanitised, checked against
an extension allow-list, and asserted to resolve *inside* input/<bundleName>/ (zip-slip
defence). The save route likewise refuses to read any media reference that escapes the
input directory.
"""

import io
import os
import re
import json
import zipfile

import folder_paths
from server import PromptServer
from aiohttp import web

# Media types allowed inside a bundle. Restricting extraction to known media
# extensions prevents a crafted bundle from dropping executable/script files
# (e.g. .py, .bat, .dll) into the ComfyUI input directory.
_BUNDLE_MEDIA_EXTS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif",
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv",
}

# Anything outside this set is collapsed to "_" when deriving a bundle subfolder name.
_BUNDLE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

# Fields on a timeline segment that hold an input-dir-relative media reference.
# In LTX Director 2.0 a main-track *video* segment stores its source in `imageFile`
# (not `videoFile`); `videoFile` is used by the motion track. Collecting every known
# field from every track is robust regardless of segment type.
_SEGMENT_MEDIA_FIELDS = ("imageFile", "videoFile")
_AUDIO_MEDIA_FIELDS = ("audioFile",)


def _safe_bundle_name(raw):
    """Reduce an uploaded filename to a single safe path segment (no separators)."""
    base = os.path.basename(raw or "")
    if base.lower().endswith(".zip"):
        base = base[:-4]
    base = _BUNDLE_NAME_RE.sub("_", base).strip("._")
    return base or "bundle"


def _input_dir():
    return os.path.realpath(folder_paths.get_input_directory())


def _contained(root, path):
    """True iff ``path`` resolves to a location inside ``root`` (symlinks/.. resolved)."""
    try:
        root = os.path.realpath(root)
        target = os.path.realpath(path)
        return os.path.commonpath([root, target]) == root
    except ValueError:
        # Different drives / mixed absolute-relative on Windows -> not contained.
        return False


def _iter_media_holders(timeline):
    """Yield (segment_dict, field_name) for every media-bearing field in a timeline.

    Covers the main track (`segments`), the motion track (`motionSegments`), the audio
    track (`audioSegments`) and the single `retakeVideo` clip. Mutating the yielded
    segment dict in place re-points its reference, which is how load_bundle rewrites
    paths to the staged subfolder.
    """
    for seg in (timeline.get("segments") or []):
        for field in _SEGMENT_MEDIA_FIELDS:
            if seg.get(field):
                yield seg, field
    for seg in (timeline.get("motionSegments") or []):
        for field in _SEGMENT_MEDIA_FIELDS:
            if seg.get(field):
                yield seg, field
    for seg in (timeline.get("audioSegments") or []):
        for field in _AUDIO_MEDIA_FIELDS:
            if seg.get(field):
                yield seg, field
    retake = timeline.get("retakeVideo")
    if isinstance(retake, dict) and retake.get("imageFile"):
        yield retake, "imageFile"


def _collect_media_refs(timeline):
    """Ordered, de-duplicated input-dir-relative media references used by a timeline."""
    seen = set()
    out = []
    for seg, field in _iter_media_holders(timeline):
        ref = seg.get(field)
        if ref and ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


# Marker written by the pre-2.0 bundle/serializer (js _buildSerializationPayload).
_LEGACY_FORMAT = "ltx-director-timeline"


def _migrate_legacy_manifest(manifest):
    """Normalise a pre-2.0 bundle manifest in place to the LTX Director 2.0 payload shape.

    Old bundles (``format: "ltx-director-timeline"``) differ from a 2.0 save payload in
    two ways that matter for restore:
      * the global prompt was stored inside ``settings`` rather than at the top level, and
      * an old main-track *video* segment kept its playable file in ``videoFile`` with no
        ``imageFile`` (2.0 reads a video segment's source from ``imageFile``).

    Bridging both here lets the existing 2.0 loader (``_applyLoadedTimeline``) restore an
    old bundle unchanged. Newer manifests are returned untouched.
    """
    if not isinstance(manifest, dict) or manifest.get("format") != _LEGACY_FORMAT:
        return manifest

    settings = manifest.get("settings") or {}
    # Lift the global prompt to the top level so 2.0 restores it via syncGlobalPrompt().
    if manifest.get("global_prompt") is None and "global_prompt" in settings:
        manifest["global_prompt"] = settings.get("global_prompt") or ""

    timeline = manifest.get("timeline") or {}
    for seg in (timeline.get("segments") or []):
        if seg.get("type") == "video" and seg.get("videoFile") and not seg.get("imageFile"):
            # 2.0 plays a main-track video from imageFile; mirror videoFile into it.
            seg["imageFile"] = seg["videoFile"]
            # Old pre-extracted guide frames + stale thumbnail URL are unused by 2.0;
            # drop them so the editor rebuilds the preview from the staged video.
            seg.pop("frames", None)
            seg.pop("imageB64", None)
    return manifest


@PromptServer.instance.routes.post("/ltx_director/save_bundle")
async def save_bundle(request):
    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON body")

    timeline = payload.get("timeline") or {}
    input_dir = _input_dir()

    buf = io.BytesIO()
    missing = []
    written = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("timeline.json", json.dumps(payload, indent=2))
        for rel in _collect_media_refs(timeline):
            # `rel` is an input-dir-relative path; reject anything that escapes it.
            src = os.path.join(input_dir, rel)
            if not _contained(input_dir, src) or not os.path.isfile(src):
                missing.append(rel)
                continue
            arcname = "media/" + rel.replace("\\", "/")
            if arcname in written:
                continue
            written.add(arcname)
            zf.write(src, arcname)

    buf.seek(0)
    name = _safe_bundle_name(payload.get("bundleName") or "ltx_director_bundle")
    headers = {"Content-Disposition": 'attachment; filename="%s.zip"' % name}
    if missing:
        # Surface skipped (missing/out-of-tree) media without failing the download.
        headers["X-Bundle-Missing"] = str(len(missing))
    return web.Response(body=buf.read(), content_type="application/zip", headers=headers)


@PromptServer.instance.routes.post("/ltx_director/load_bundle")
async def load_bundle(request):
    post = await request.post()
    field = post.get("bundle")
    if field is None:
        return web.Response(status=400, text="Missing bundle file")

    bundle_name = _safe_bundle_name(getattr(field, "filename", "") or "bundle.zip")

    real_dest_root = os.path.realpath(os.path.join(_input_dir(), bundle_name))
    # Defence in depth: the sanitised name must keep us inside the input directory.
    if not _contained(_input_dir(), real_dest_root):
        return web.Response(status=400, text="Invalid bundle name")

    try:
        data = field.file.read()
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return web.Response(status=400, text="Invalid zip file")

    try:
        manifest = json.loads(zf.read("timeline.json").decode("utf-8"))
    except Exception:
        return web.Response(status=400, text="Bundle missing timeline.json")

    # Bring a pre-2.0 bundle up to the 2.0 payload shape before media is re-pointed,
    # so legacy video segments (videoFile -> imageFile) get staged/re-pointed correctly.
    manifest = _migrate_legacy_manifest(manifest)

    os.makedirs(real_dest_root, exist_ok=True)

    staged = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if not name.startswith("media/"):
            continue
        rel = name[len("media/"):]
        if not rel:
            continue
        # Zip-slip defence: resolve under dest root and confirm containment.
        out_path = os.path.join(real_dest_root, *[p for p in rel.split("/") if p])
        if not _contained(real_dest_root, out_path):
            continue
        if os.path.splitext(out_path)[1].lower() not in _BUNDLE_MEDIA_EXTS:
            continue
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        # Always write (create-or-overwrite) per the staging contract.
        with open(out_path, "wb") as fh:
            fh.write(zf.read(info))
        staged.append(rel)

    # Re-point every media reference to input/<bundleName>/<rel> so the editor resolves
    # the staged copies. The editor splits each ref into filename + subfolder for its
    # /view URL, so a nested ref like "whatdreamscost/foo.mp4" simply gains the bundle
    # prefix and keeps working.
    timeline = manifest.get("timeline") or {}
    for seg, fieldname in _iter_media_holders(timeline):
        ref = seg.get(fieldname)
        seg[fieldname] = "%s/%s" % (bundle_name, ref.replace("\\", "/"))

    manifest["bundleName"] = bundle_name
    return web.json_response({"payload": manifest, "staged": staged, "bundleName": bundle_name})
