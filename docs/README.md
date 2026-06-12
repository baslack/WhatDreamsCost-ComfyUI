# WhatDreamsCost-ComfyUI — Developer Documentation

Internal reference docs for working on this ComfyUI custom-node package. These are
maintained by hand alongside the code; the matching agent skill lives at
[`.claude/skills/whatdreamscost-comfyui/`](../.claude/skills/whatdreamscost-comfyui/SKILL.md).

## What this package is

A suite of ComfyUI custom nodes aimed at LTX (Lightricks) video generation and
general creative workflows. The flagship is **LTX Director**, a full timeline
editor rendered inside the node that drives LTX video + audio generation through an
integrated **Prompt Relay** (temporal cross-attention masking) implementation.

## Node catalogue

| Node | Backend | Frontend | Purpose |
|------|---------|----------|---------|
| **LTX Director** | [`ltx_director.py`](../ltx_director.py) | [`js/ltx_director.js`](../js/ltx_director.js) | Timeline editor → prompt-relay encode, latent/audio generation, guide data |
| **LTX Director Guide** | [`ltx_director_guide.py`](../ltx_director_guide.py) | [`js/ltx_director_guide.js`](../js/ltx_director_guide.js) | Applies the Director's guide images into the latent at their frame positions |
| **LTX Sequencer** | [`ltx_sequencer.py`](../ltx_sequencer.py) | [`js/ltx_sequencer.js`](../js/ltx_sequencer.js) | Multi-keyframe guide insertion (FFLF / shot sequences) by frame or second |
| **LTX Keyframer** | [`ltx_keyframer.py`](../ltx_keyframer.py) | [`js/ltx_keyframer.js`](../js/ltx_keyframer.js) | Replaces latent frames with encoded images (legacy; Sequencer preferred) |
| **Multi Image Loader** | [`multi_image_loader.py`](../multi_image_loader.py) | [`js/multi_image_loader.js`](../js/multi_image_loader.js) | Gallery loader, resize + compression, batched + 50 individual outputs |
| **Speech Length Calculator** | [`speech_length_calculator.py`](../speech_length_calculator.py) | [`js/speech_length_calculator.js`](../js/speech_length_calculator.js) | Realtime frame-count estimate from quoted dialogue |
| **Load Audio UI** | [`load_audio_ui.py`](../load_audio_ui.py) | [`js/load_audio_ui.js`](../js/load_audio_ui.js) | Trim/preview audio with a custom interface |
| **Load Video UI** | [`load_video_ui.py`](../load_video_ui.py) | [`js/load_video_ui.js`](../js/load_video_ui.js) | Trim/resize/crop/preview video; chunked upload + preview HTTP routes |

Shared backend infrastructure (not standalone nodes):

| Module | Role |
|--------|------|
| [`prompt_relay.py`](../prompt_relay.py) | Tokenization → temporal Gaussian penalty → attention mask closure |
| [`patches.py`](../patches.py) | Detects model arch (Wan / LTX) and patches cross-attention `forward` |
| [`__init__.py`](../__init__.py) | Node registration (both new `ComfyExtension` and legacy mappings) |

## Documentation map

- **[architecture.md](architecture.md)** — package registration, the two node API
  styles, frontend↔backend wiring, file map.
- **[ltx-director.md](ltx-director.md)** — the timeline editor in depth: data model,
  serialization contract, context menus, the full execute() pipeline. **Start here
  for any LTX Director work.**
- **[prompt-relay.md](prompt-relay.md)** — how prompt segments become a temporal
  attention mask and get patched onto the diffusion model.
- **[nodes.md](nodes.md)** — reference for the remaining nodes (Sequencer, Keyframer,
  Multi Image Loader, Speech Length Calculator, Load Audio/Video UI).

## Conventions at a glance

- **Two node API styles coexist.** Newer nodes subclass `io.ComfyNode` with
  `define_schema()` / `execute()` (LTX Director, Director Guide, Sequencer,
  Keyframer). Older nodes use the legacy `INPUT_TYPES` / `RETURN_TYPES` / `FUNCTION`
  dict style (Multi Image Loader, Speech Length Calculator, Load Audio/Video UI).
- **Frontend is vanilla JS**, served from `./js` (declared by `WEB_DIRECTORY` in
  `__init__.py`). No build step. Each node registers via `app.registerExtension`.
- **Hidden string widgets are the data bus.** The JS editor writes JSON/CSV into
  hidden widgets (`timeline_data`, `local_prompts`, `segment_lengths`,
  `guide_strength`) that the Python `execute()` reads. See
  [ltx-director.md](ltx-director.md#the-widget-data-bus).
- **Images live in the ComfyUI input dir.** Uploads go through `/upload/image`;
  segments reference them by `imageFile` (input-relative path). `imageB64` usually
  holds a `/view?...` URL, not real base64 — the backend ignores `/view?` values.
