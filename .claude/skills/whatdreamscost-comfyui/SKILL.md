---
name: whatdreamscost-comfyui
description: >-
  Architecture and working knowledge for the WhatDreamsCost-ComfyUI custom-node
  package (LTX Director timeline editor, Prompt Relay temporal masking, LTX
  Sequencer/Keyframer, Multi Image Loader, Speech Length Calculator, Load
  Audio/Video UI). Use this skill whenever working in this repo — adding or
  changing nodes, editing the timeline editor or its right-click/context menus,
  touching the timeline_data / local_prompts / segment_lengths / guide_strength
  serialization, the prompt-relay attention patching, the guide_data channel, the
  audio compositing, or the Load Video UI HTTP routes. Trigger it for any mention
  of LTX Director, the timeline, clips/segments, prompt relay, guide data, or any
  file in this package (ltx_director.py/js, prompt_relay.py, patches.py, etc.) —
  even when the request doesn't name the skill. Reach for it before exploring the
  code from scratch; it points at hand-maintained docs that already map the
  dataflows.
---

# WhatDreamsCost-ComfyUI

A ComfyUI custom-node suite for LTX video generation. This skill is the entry point
for working in the repo: it summarizes the architecture and points at the detailed
docs so you don't re-derive the dataflows each time.

## Read the docs first

Hand-maintained reference docs (with mermaid diagrams) live in [`docs/`](../../../docs/).
Read the relevant one before diving into source — they already trace the code paths:

- [`docs/README.md`](../../../docs/README.md) — node catalogue + conventions.
- [`docs/architecture.md`](../../../docs/architecture.md) — registration, the two
  node API styles, frontend↔backend wiring, file map, HTTP routes.
- [`docs/ltx-director.md`](../../../docs/ltx-director.md) — **the timeline editor in
  depth.** Data model, the widget bus, `commitChanges()` serialization, context
  menus, image upload, the backend `execute()` pipeline. Read this for any LTX
  Director work.
- [`docs/prompt-relay.md`](../../../docs/prompt-relay.md) — tokenization → temporal
  Gaussian mask → cross-attention patching.
- [`docs/nodes.md`](../../../docs/nodes.md) — Sequencer, Keyframer, Multi Image
  Loader, Speech Length Calculator, Load Audio/Video UI.

After substantive changes, **update the matching doc** so it stays the source of
truth.

## Orientation (the 60-second version)

- **Flagship**: LTX Director — a `<canvas>` timeline editor ([`js/ltx_director.js`](../../../js/ltx_director.js),
  the `TimelineEditor` class, ~3.9k lines) driving the backend
  ([`ltx_director.py`](../../../ltx_director.py)) which runs Prompt Relay
  ([`prompt_relay.py`](../../../prompt_relay.py) + [`patches.py`](../../../patches.py)).
- **Two node API styles coexist**: newer nodes subclass `io.ComfyNode`
  (`define_schema`/`execute`); older nodes use legacy `INPUT_TYPES`/`RETURN_TYPES`/
  `FUNCTION`. Match the style of the file you're editing.
- **No frontend build step.** Vanilla JS served from `./js` via `WEB_DIRECTORY`. Each
  node uses `app.registerExtension`.

## The data bus (most important contract)

The JS editor never passes tensors to Python. It serializes editor state into
**hidden string widgets** that `execute()` reads as inputs:

| Widget | Format | Source |
|--------|--------|--------|
| `timeline_data` | JSON `{segments, audioSegments}` | full editor state (minus `imgObj`) |
| `local_prompts` | `" | "`-joined | per contiguous segment |
| `segment_lengths` | `","`-joined | pixel lengths, gaps absorbed, clipped to duration |
| `guide_strength` | `","`-joined | per **non-text** segment |

`commitChanges()` (in `ltx_director.js`, ~line 2761) is the single serialization
choke point. **Any mutation of `this.timeline` must end with `commitChanges()`** or
the backend sees stale data. Segments are image-or-text by `type` + presence of
`imageFile`/`imageB64`; audio lives in a separate `audioSegments` array. Full schema
in [`docs/ltx-director.md`](../../../docs/ltx-director.md#the-timeline-data-model).

## Common task → where to look

- **Right-click / context menu items** → `showContextMenu()` (per-segment) and
  `showGapContextMenu()` (empty track) in `ltx_director.js` (~line 2943+). Reuse the
  `pr-gap-menu` / `pr-gap-menu-btn` CSS classes. Mutate `this.timeline`, then
  `commitChanges()`.
- **Convert a clip image↔text** → flip `seg.type` and add/remove
  `imageFile`/`imageB64`/`imgObj`; `commitChanges()`. (`guide_strength` is non-text
  only, so the alignment shifts automatically.)
- **Replace an image on a clip** → run `handleImageUpload`-style `/upload/image`,
  then assign the result onto the existing segment instead of pushing a new one.
- **Export/import a timeline** → the source of truth is the `timeline_data` JSON.
  Media is referenced by `imageFile`/`audioFile` into the ComfyUI input dir, so a
  raw export is **not self-contained** — copy/embed media for portability. The
  `global_prompt` is a separate node widget, not part of `timeline_data`.
- **Prompt-relay / attention behavior** → `_encode_relay()` in `ltx_director.py` and
  [`docs/prompt-relay.md`](../../../docs/prompt-relay.md).
- **Guide images into latent** → `LTXDirectorGuide` reads the `guide_data` custom
  socket (`GuideData = io.Custom("GUIDE_DATA")`).
- **Audio compositing** → `_build_combined_audio()` in `ltx_director.py`.

## Security note for server routes

`load_video_ui.py` is the reference for safe aiohttp routes in this package:
normalize with `os.path.realpath`, allow-list extensions, strip path components with
`os.path.basename`, and confirm containment with `os.path.commonpath`. Any new route
that serves or writes files must do the same — these guard against arbitrary
file read/write. See [`docs/architecture.md`](../../../docs/architecture.md#http-routes-server-side).

## Conventions

- Keep frontend changes in vanilla JS matching the surrounding style; no new build
  tooling.
- Pixel-space frames everywhere on the timeline; latent frames are derived
  (`((pixel_length-1)//8)+1` for LTX). `display_mode` only affects on-screen labels.
- When a widget visibility change doesn't take visually, copy the existing
  "double-toggle `display_mode`" force-refresh trick.
- This is a maintained fork that submits PRs upstream — see the Git workflow below.
  Keep unrelated changes (like this skill and `docs/`) out of feature PRs.

## Git workflow (fork maintenance)

This is a **fork that tracks a moving upstream and submits clean PRs back to it**, so
branch hygiene matters. The whole point is to keep each change independently
rebaseable onto upstream.

**Remotes are named the reverse of the usual convention — do not assume:**

| Remote | Repo | Role |
|--------|------|------|
| `origin` | `WhatDreamsCost/WhatDreamsCost-ComfyUI` | **parent / upstream** — pull from it, open PRs against it |
| `fork` | `baslack/WhatDreamsCost-ComfyUI` | **personal fork** — push topic branches here |

**Branch model:**

- `main` — clean mirror of `origin/main`. Never commit here; only fast-forward it from
  upstream.
- **One topic branch per logically-separable change, branched directly off `main`**
  (not off the integration branch, not stacked unless the changes genuinely depend on
  each other). Examples already in the repo: `fix/file-route-path-validation`,
  `fix/director-guide-zero-size-resize` — each a single clean commit off `main`,
  pushed to `fork`, PR-ready against `origin`.
- **PR-bound vs fork-only are different lifecycles.** Code fixes/features → PR to
  `origin`. Fork-only material that will never go upstream (this skill, `docs/`) lives
  on its own topic (e.g. `chore/dev-skill-and-docs`) and is merged into the
  integration branch but never PR'd.
- `local/all-fixes` — the **integration branch / daily driver**: a *merge* of all the
  topic branches. It is never PR'd ("not for PR").

**Treat the integration branch as rebuilt, not rebased.** You cannot cleanly rebase a
merge commit across a moved upstream, so when `origin/main` advances:

1. Rebase each topic onto the new main (trivial — they're single commits):
   `git rebase origin/main <topic>`.
2. Regenerate the integration branch:
   `git switch local/all-fixes && git reset --hard origin/main && git merge <topic> <topic> ...`.
3. When a topic's PR merges upstream, **delete the topic and drop it from the merge** —
   it returns via the `main` pull, so no duplicate commits.

Enable `git rerere` once (`git config rerere.enabled true`) so recurring merge
conflicts resolve themselves on every rebuild.

> When asked to make a change here, put it on the right kind of branch off `main`
> (PR-bound topic vs fork-only topic) rather than committing onto `local/all-fixes`
> directly, then fold it into `local/all-fixes`.
