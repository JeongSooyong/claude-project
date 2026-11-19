# Plan: 기술 문서 → 유튜브 쇼츠 생성기 (v1)

- Source spec: `.omc/specs/deep-interview-docs-to-shorts.md`
- Mode: consensus (RALPLAN-DR short), direct
- Status: **pending approval**
- Revision: v2 (final; Critic: APPROVE, Architect: SOUND_WITH_CHANGES → must-fix items applied)
- Date: 2026-11-19

## 0. Environment facts (verified 2026-11-19)
`C:\workspace` is empty and is not a git repo. On this Windows 11 machine:
- **Python: not installed** (`python` is the Microsoft Store alias stub, exit 49)
- **Node: not installed**
- **FFmpeg: not installed**
- Git: installed

## 1. Requirements Summary
Single-user local app. Input is one tech-doc URL or one `.md` file. Claude writes a Korean scene script plus YouTube metadata, and the user edits and approves it in a localhost web UI. OpenAI generates background images and Korean TTS. The app renders a 1080×1920 mp4 of 30–59 s with a verbatim code overlay and synced Korean subtitles, saves the video and metadata, and uploads it to YouTube as **private**. Providers sit behind interfaces; the target cost is a few hundred KRW per video. See spec AC-1…AC-11.

## 2. RALPLAN-DR Summary

### Principles
1. **Code is never regenerated.** The LLM only *references* code by `blockId` + 1-based inclusive line range, and the renderer draws the original text. `onScreenText` may not contain code-like text.
2. **Approval is bound to exact content.** Approval stores a hash of the script plus every asset. Render and upload refuse if the current hash differs.
3. **Providers behind narrow interfaces**, with deterministic fakes, so the whole pipeline runs offline (AC-9).
4. **Measure, don't estimate.** Timing comes from PCM sample counts of the TTS audio, rounded to whole frames. Approval gates on the *predicted rendered* duration.
5. **One text engine, one seam.** Pillow draws all text (code, on-screen text, subtitles) as PNGs, and ffmpeg only composites and encodes. A pure `timeline.json` connects planning and rendering.

### Decision Drivers
1. Verbatim code + Korean text rendering correctness on Windows
2. Install/maintenance burden on a machine with no runtimes yet
3. Testability of the full pipeline without paid API calls

### Viable Options
| | A. Python + FastAPI + Pillow/Pygments + FFmpeg (**favored**) | B. Node/TS + Remotion |
|---|---|---|
| Install | Python + uv + FFmpeg (3 winget installs) | Node only (Remotion v4 bundles ffmpeg); Chromium downloaded on first render |
| Rendering | Pillow PNG layers (bg, code card, highlight variants, subtitle cards) composited by ffmpeg `overlay=enable='between(t,a,b)'` | React components rendered by headless Chromium; Shiki highlighting; CSS `word-break: keep-all` for Korean |
| Review fidelity | Per-scene preview **mp4** rendered through the same compose path (with subtitles and timing) | Remotion Player in the UI = exact WYSIWYG |
| Testability | Byte-level assertions on token streams, PNGs and timelines; deterministic | Frame snapshots; Chromium nondeterminism; harder to unit-test text layout |
| Cons | Motion limited to zoom/fade + highlighted-line switching | Heavier runtime, slower renders; text correctness depends on browser layout, which is harder to assert |

**Steelman for B (from Architect), and why we still choose A:** B wins on motion and preview fidelity, and needs one fewer install. A closes most of that gap with two choices. Per-scene preview mp4s come from the real compose path. Pre-rendered line-highlight variants are switched on cue times, which gives the core "highlight the line being explained" effect. A keeps byte-level verifiability of code (driver 1) and deterministic offline tests (driver 3), and B cannot match either cheaply. `timeline.json` is the port seam if B is wanted later.

**Option C rejected** (Python + MoviePy). It does slower per-frame Python compositing and adds nothing over ffmpeg overlays.

### Tradeoff tensions acknowledged
- **Verifiability vs. engagement.** Static frames are testable, and motion drives retention. Resolution: highlight variants + zoom now; real typing animation is a follow-up.
- **Measured timing vs. natural speech.** Per-sentence TTS gives exact cue times but may lose prosody across sentences. Mitigation: the same voice + fixed `instructions` (tone) on every call, and a 120 ms inter-sentence gap. If quality is poor in the live E2E, switch to per-scene TTS with proportional cue allocation inside the scene; the timeline stays the same shape.

## 3. Architecture

```
shortsgen/
  pyproject.toml   # deps: fastapi, uvicorn, httpx, beautifulsoup4, markdownify, markdown-it-py,
                   #   pydantic, anthropic, openai, pillow, pygments, numpy, soundfile,
                   #   google-api-python-client, google-auth-oauthlib, python-dotenv, pytest
  .env.example     # ANTHROPIC_API_KEY, OPENAI_API_KEY, SCRIPT_MODEL, IMAGE_MODEL, IMAGE_QUALITY=low,
                   #   TTS_MODEL, TTS_VOICE, COST_CEILING_KRW=1000, USD_KRW
  .gitignore       # projects/, .env, client_secret*.json, token*.json
  assets/fonts/    # NotoSansKR (Google Fonts, OFL), D2Coding (github.com/naver/d2codingfont, OFL)
  src/shortsgen/
    config.py
    models.py      # TechDoc, CodeBlock, CodeRef(blockId, startLine, endLine: 1-based inclusive),
                   #   Scene, Script(title, description, hashtags[], scenes[]), Timeline, Project, CostLog
    storage.py     # projects/<id>/{project.json, cost.json, timeline.json, assets/, out/}
    hashing.py     # content hashes for scenes/assets; approved_hash
    ingest/
      normalize.py # the ONLY normalization: CRLF/CR -> LF
      markdown.py  # markdown-it-py fenced code -> CodeBlock; prose keeps [[CODE:id]] placeholders
      url.py       # httpx (timeout 15s) -> BeautifulSoup -> main/article/[role=main];
                   #   drop .linenos, .copybutton, button (UI chrome only); KEEP prompt spans
                   #   (.gp, ">>>", "$") verbatim — code stays exactly as the page displays it;
                   #   <br> -> "\n" inside <pre>; strip one leading "\n"; lang from language-*/highlight-*;
                   #   replace each <pre> with [[CODE:id]] then markdownify prose
    providers/
      base.py              # ScriptProvider, ImageProvider, TTSProvider (+ cost reporting)
      anthropic_script.py  # tool-use JSON schema; no field accepts code text
      openai_image.py      # portrait 1024x1536, quality from config; cover-crop to 1080x1920
      openai_tts.py        # response_format=pcm (raw 24 kHz s16le mono; samples = bytes/2);
                           #   wav headers written by our code; same voice + instructions every call
      fake.py              # fake script; solid-colour images; silent wav of chosen length
      retry.py             # timeouts + 2 retries with backoff for all providers
    script/
      generate.py
      validate.py          # see "Validation rules"
    timeline/
      plan.py              # pure fn: script + audio sample counts -> timeline.json
    render/
      text_layout.py       # Korean-aware wrapping by pixel width (break at spaces, fallback per char)
      code_card.py         # Pygments(stripnl=False, ensurenl=False); tabs expanded (width 4);
                           #   returns PNG + list of drawn token strings; overflow = error
      highlight.py         # per-cue highlighted-line PNG variants
      subtitle_card.py     # cue text -> transparent PNG (NotoSansKR, outline)
      scene_frame.py       # bg (2x upscaled for zoompan) + 55% dim + code card + onScreenText
      compose.py           # ffmpeg args list, cwd=project dir, relative paths; per scene:
                           #   VIDEO-ONLY clip: still fed as single frame (no -loop) to zoompan d=<frames>
                           #   + overlays enabled by cue time; libx264 yuv420p 30fps;
                           #   concat clips; then mux ONE master audio track (master.wav) once,
                           #   AAC 48kHz, -shortest, +faststart
      audio.py             # build master.wav in Python: per-scene PCM (sentences + 120 ms gaps)
                           #   padded with silence to that scene's frame-rounded duration
      ffmpeg.py            # locate binaries, run, capture stderr, ffprobe json
    publish/
      youtube.py           # scope youtube.upload only; InstalledAppFlow.run_local_server;
                           #   client secret + token in %APPDATA%/shortsgen/; on invalid_grant re-auth;
                           #   resumable upload; privacyStatus=private; selfDeclaredMadeForKids=false;
                           #   persist videoId + upload URI (idempotent)
    web/
      app.py               # uvicorn bound to 127.0.0.1 only; background tasks for render/upload
      static/index.html, app.js, style.css   # vanilla JS, polling for job status
  tests/
    fixtures/  # hand-written expected outputs (NOT produced by the parser under test)
```

### Validation rules (`script/validate.py`)
- 3–8 scenes. Every `CodeRef` points to an existing block, with 1 ≤ start ≤ end ≤ block line count.
- Code card: at most 18 lines. No line overflows at a font size ≥ 28 px after shrinking (otherwise error, never clip).
- `onScreenText`: ≤ 3 lines after wrapping at 44 px, and no code-like text (regex: backtick, `{`, `}`, `;`, `=>`, `::`, `identifier(`). Ordinary parentheses in Korean text, such as `(선택)`, are allowed.
- Narration: each sentence is non-empty and ≤ 80 characters. Identifiers stay in their original form. An optional `highlightLine` on each sentence must satisfy `startLine ≤ highlightLine ≤ endLine` of that scene's CodeRef.
- Glyph coverage: every character in narration, `onScreenText` and the referenced code must exist in the cmap of the font that draws it (checked with fontTools).
- Metadata: title is 1–100 characters, description ≤ 5000 characters, 1–10 hashtags.

### Timeline (`timeline.json`)
- Per scene: the scene's audio is the PCM of its sentences concatenated in Python with 120 ms gaps. Sentence offsets come from sample counts.
- Scene duration = audio + 300 ms tail, rounded up to whole frames at 30 fps. Scenes are joined by hard cuts (no fade overlap), so the total = Σ scene durations exactly. `master.wav` is padded so that every scene's audio occupies exactly that scene's frame-rounded span; the track's sample count equals total × 48000 after resampling.
- Cues: each sentence is split into display cues of at most 2 lines, each line ≤ 16 characters **and** ≤ 960 px wide at the subtitle font size. Time within a sentence is allocated in proportion to cue length. A cue inherits its sentence's `highlightLine`.
- **Predicted duration** = timeline total, which must be in [30.0, 59.0] s to approve.

### State machine
`ingested → scripted → reviewing → approved → rendering → rendered → uploading → uploaded`, plus `render_failed` / `upload_failed`, with an `error` field.
- Editing a scene marks that scene's TTS, image and frame stale (by hash) and resets the state to `reviewing`. Editing metadata also resets to `reviewing`.
- `approve` requires: validation passes, every asset is fresh, and the predicted duration is in range. It stores `approved_hash`.
- `render` requires state `approved` (or `render_failed`) **and** the recomputed hash equal to `approved_hash`. Otherwise it returns 409.
- `render` stores `rendered_hash` (the content hash + a sha256 of `out/video.mp4`).
- `upload` requires state `rendered` (or `upload_failed`) **and** both the content hash and the mp4 sha256 to match `rendered_hash`. If a `videoId` already exists it returns 409; a failed upload resumes from the stored URI.

### Web API
- `POST /projects` takes a URL or an uploaded .md, then ingests it and generates the script.
- `GET /projects/{id}` returns the project, including state, error and cost.
- `PUT /projects/{id}/scenes/{sid}` edits one scene.
- `PUT /projects/{id}/metadata` edits the title, description and hashtags.
- `POST /projects/{id}/scenes/{sid}/image` regenerates that scene's image.
- `POST /projects/{id}/tts` generates TTS for stale scenes only, rebuilds the timeline and returns the predicted duration.
- `POST /projects/{id}/scenes/{sid}/preview` starts a background job that renders that scene through the real compose path, with subtitles. The result is cached by scene hash. Returns 409 if the scene's assets are stale or a full render is running.
- `GET /projects/{id}/scenes/{sid}/preview.mp4` only serves the cached file (404 if there is none).
- `POST /projects/{id}/approve`, `POST /projects/{id}/render` and `POST /projects/{id}/upload` are the gated actions; render and upload run as background jobs.
- `GET /projects/{id}/job` reports job status and ffmpeg stderr on failure.

### Cost control
- `cost.json` logs every provider call: kind, units (tokens, image count, TTS characters or seconds) and an estimated USD amount from a price table in config. **Confirm current prices at implementation time.**
- The UI shows the running KRW total.
- Image or TTS generation is refused if it would exceed `COST_CEILING_KRW` (default 1000). This is a **hard cap**, not the target; the user can raise it.
- **Target:** ≤ 700 KRW per video (the spec's "a few hundred won"), asserted in the live E2E.
- Defaults: `IMAGE_QUALITY=low`; `TTS_MODEL=gpt-4o-mini-tts`; `IMAGE_MODEL=gpt-image-1` (or its current low-cost successor). Confirm the current model ids and prices at implementation time.

## 4. Implementation Steps (each ends in a check)
1. **Environment.**
   - Install Python 3.12+ with `winget install Python.Python.3.12`, then uv and FFmpeg (`Gyan.FFmpeg`).
   - Open a new shell so PATH refreshes.
   - Run `git init` and scaffold the project.
   - Download fonts from the sources listed in §3.
   - *Check:* `ffmpeg -version` succeeds, and `uv run pytest` passes `tests/test_smoke.py` (imports the package; fonts load in Pillow).
2. **Models, storage, hashing.** *Check:* round-trip and hash-stability tests.
3. **Ingest.**
   - Fixtures: a Sphinx page with `linenos` and a copy button, an MDN page, a page with `<br>` inside `<pre>`, and an .md file with tabs, trailing spaces, blank edge lines, a Korean comment and CRLF line endings.
   - *Check:* code blocks equal the **hand-written** expected strings, and the placeholders sit in the prose at the right positions.
4. **Providers, fakes, retry, cost log.** *Check:* unit tests with fakes, a test that the cost ceiling refuses a call, and an opt-in live smoke test (`-m live`).
5. **Script generation + validation.** Claude returns scenes plus title, description and hashtags. *Check:* one validator test per rule in §3, including code-like `onScreenText` being rejected.
6. **Timeline + master audio.** *Check:*
   - With fake TTS producing silent PCM of known lengths, cue offsets equal the expected sample-derived values.
   - The total is a whole number of frames.
   - The `master.wav` sample count equals the timeline total × 48000.
   - Each scene's audio starts exactly at its frame-rounded boundary.
   - A cue's highlight line equals its sentence's `highlightLine`.
   - Out-of-range totals block approval.
7. **Render.** *Check:*
   - **AC-7:** `"".join(drawn tokens) == CodeBlock.content` lines start..end (inclusive) with tabs expanded, compared with fixture expectations.
   - An overflow case raises an error.
   - **AC-6:** ffprobe reports 1080×1920, h264/yuv420p, 30 fps, AAC, and a duration equal to the timeline total ±1 frame.
   - **AC-8:** every scene has image, audio and frame PNG files; the number of subtitle overlays equals the number of cues.
   - **Glyph coverage:** a fontTools cmap check covers every character in narration, `onScreenText` and code. A missing glyph is a validation error, not a tofu box.
   - **Audio sync:** the ffprobe audio duration equals the video duration ±1 frame. In a fixture where scene 2 starts with a 440 Hz tone, the tone onset in the output falls at scene 2's timeline start ±1 frame.
   - A test runs on a project path containing Korean characters.
8. **Web UI + state machine.**
   - The page has: an input form; scene cards (narration, `onScreenText`, `imagePrompt`, code range picker over the original code, image regenerate, preview mp4); a metadata editor; a duration meter; a cost meter; and Approve / Render / Upload buttons enabled by state.
   - *Check (TestClient):* every 409 rule in §3 (including preview on stale assets, and upload after the mp4 has been modified); edit after approve resets the state; TTS edits mark scenes stale; the preview is served from the cache on the second request; the server binds to 127.0.0.1.
9. **Publish.** *Check (mocked googleapiclient):*
   - The request body has `privacyStatus == "private"`, `selfDeclaredMadeForKids == false`, and title and description from the script.
   - The response JSON contains `https://youtu.be/{id}`.
   - A second upload returns 409.
   - `invalid_grant` triggers the re-auth path.
   - Check the `containsSyntheticMedia` field against current API docs; set it to true if it exists.
10. **E2E.**
    - Offline, with fakes: md fixture → script → TTS → approve → render. Must pass the AC-6, 7, 8 and 10 checks (`out/video.mp4`, plus `out/metadata.json` with non-empty fields).
    - Live, manual, once: a real doc URL through to a private upload. Record wall time and confirm `cost.json` total ≤ 700 KRW.
    - Fill in the manual checklist: code readable on a phone; subtitles in sync; the image has no garbled text.
11. **README.** Cover:
    - Setup and API keys.
    - Creating the Google Cloud OAuth client.
    - "Testing" status: refresh tokens expire after 7 days, so re-authentication is expected.
    - Uploads from an unverified API project are locked to private and can only be made public after an API audit.
    - Cost table.
    - Known limits: JS-rendered docs are not supported.

## 5. Acceptance Criteria → Verification
| AC | Verification |
|---|---|
| AC-1 URL ingest | Step 3 fixture tests against hand-written expected code and placeholders |
| AC-2 MD ingest | Step 3 md fixture test (tabs, CRLF, Korean comment) |
| AC-3 Scene script | Step 5 schema and validator tests. Live smoke test: 3–8 scenes. Predicted duration within 30–59 s after TTS (step 6) |
| AC-4 Editable | Step 8: PUT scene and metadata and POST image regenerate change `project.json`; preview mp4 returns 200 |
| AC-5 Approval gate | Step 8: render returns 409 before approve or on hash mismatch; upload returns 409 before render or after `videoId` exists |
| AC-6 Format | Step 7/10 ffprobe: 1080×1920, 30 fps, h264/yuv420p, AAC, 30–59 s, ±1 frame of the timeline |
| AC-7 Verbatim code | Step 7: drawn-token join equals the source range; overflow raises an error; `onScreenText` code-like text is rejected |
| AC-8 Composition | Step 7: per-scene asset files exist, overlay count equals cue count, Hangul glyph render test |
| AC-9 Swappable | Step 10: offline E2E runs entirely on `fake.py` |
| AC-10 Local save | Step 10: `out/video.mp4` exists and `out/metadata.json` fields are non-empty |
| AC-11 Private upload | Step 9 mocked request and response assertions, plus one live upload |
| Cost target (spec constraint) | Step 4 ceiling test, plus Step 10 live `cost.json` ≤ `COST_CEILING_KRW` |

## 6. Risks & Mitigations
| Risk | Mitigation |
|---|---|
| Docs pages render their code with JS | Static HTML only in v1. If a page has no `<pre>`, show an explicit error suggesting the .md or raw source. Headless fetch is a follow-up |
| Doc-site chrome leaks into code (line numbers, prompts, copy buttons) | Strip rules in `url.py` + Sphinx fixture. The user sees the original code in the range picker before approving |
| Long code lines | Choose a line range + shrink the font (min 28 px). Overflow is a validation error, never a silent clip |
| Duration out of 30–59 s | Approval gates on the predicted timeline duration, so the user trims or extends the narration. A TTS speed setting (0.9–1.15) helps |
| Missing Korean glyphs | All text is drawn by Pillow with the bundled NotoSansKR / D2Coding (no libass/fontconfig). Glyph test in step 7 |
| Stale assets approved | Content hashes + `approved_hash` re-checked at render and upload |
| AI image contains text or clashes with the overlay | Prompt suffix "no text, no letters, abstract, dark", 55% dim layer, per-scene regenerate |
| Cost creep | `IMAGE_QUALITY=low` by default, `cost.json`, ceiling refusal |
| OAuth: 7-day refresh token in Testing mode; unverified project locked to private | Re-auth on `invalid_grant`; documented in the README; private-only fits the spec |
| Upload quota | Check the current `videos.insert` cost in the docs at implementation time; show API errors verbatim |
| Provider outages / hangs | Timeouts + 2 retries; partial failure sets the `error` field and leaves other assets intact |
| Exposure / secrets | Bind to 127.0.0.1 only; `.env`, client secret and token kept out of the repo (`%APPDATA%/shortsgen/`) |
| Windows ffmpeg path quoting | Args passed as a list; `cwd` = project dir with relative paths; Korean-path test |

## 7. ADR
- **Decision:**
  - Stack: Python 3.12 + FastAPI (127.0.0.1) + a vanilla-JS UI.
  - Rendering: Pillow draws every text layer; Pygments highlights code; ffmpeg composites the overlays and encodes; a pure `timeline.json` connects the two.
  - Providers: Claude writes the script and metadata; OpenAI generates images (low quality) and TTS (wav, per sentence).
  - Publish: YouTube Data API v3 private upload with the `youtube.upload` scope.
  - Approval: bound to a content hash.
  - Storage: file-based.
- **Drivers:** verbatim code fidelity and Korean text correctness on Windows; minimal install; offline testability.
- **Alternatives considered:**
  - Node + Remotion: stronger motion and true WYSIWYG preview, but harder to verify byte-exact code and text, plus a Chromium render cost. Kept as a future port through `timeline.json`.
  - Python + MoviePy: slower, and adds nothing.
  - ASS subtitles burned via libass: rejected because of Windows font and path fragility.
  - A hosted service: out of scope.
- **Why chosen:** it is the smallest stack that meets every AC with exact-code and approval guarantees enforced structurally. Per-scene preview mp4s and highlight variants recover most of what B offers for review and engagement.
- **Consequences:**
  - Motion is limited to zoom + highlighted-line switching, with no typing animation.
  - Per-sentence TTS may sound slightly choppy (mitigation and fallback in §2).
  - Video is private-only until the user's Google project passes an audit.
- **Follow-ups:** typing animation (Pillow frame sequences or a Remotion port); JS-rendered docs (headless fetch); splitting one doc into a series; public or scheduled publishing; other platforms.

## Changelog
- v0: Planner draft.
- v1, from Critic:
  - Metadata fields added to the script schema and validated.
  - Cost config, `cost.json`, ceiling and live check added.
  - AC-7 test is now non-tautological (drawn-token join, `stripnl=False`, explicit tab width, 1-based inclusive range).
  - Asset hashes added to prevent stale approval.
  - Duration is gated on the predicted timeline; fake TTS writes silent wav.
  - Korean text wrapping added.
  - Smoke test, PATH refresh and font sources added to step 1.
  - 127.0.0.1 binding and secret locations set.
  - Timeouts, retries, error state and idempotent upload added.
  - Manual checks replaced with concrete tests and a checklist.
  - 409 rules made explicit.
  - `<br>` handling and hand-written fixtures added.
- v1, from Architect:
  - Steelman for B recorded, with the response.
  - `timeline.json` seam added.
  - Pillow subtitle cards composited as ffmpeg overlays replace libass.
  - Per-scene preview mp4 and highlight variants added.
  - wav/PCM timing from sample counts and frame rounding added; cues split to 2×16 characters.
  - Sphinx `linenos`, copy-button and leading-newline handling added; `[[CODE:id]]` placeholders keep context; CRLF normalization is the only normalization.
  - `onScreenText` code-like validator added.
  - ffmpeg list args, cwd/relative paths, uniform encoding, faststart and 2× upscale for zoompan added.
  - `rendering`, `uploading` and failed states added, with background jobs.
  - OAuth details: upload-only scope, `invalid_grant` re-auth, 7-day Testing expiry, locked-private warning, `selfDeclaredMadeForKids`.
  - The `#Shorts` title requirement was dropped in favour of 9:16 and duration checks.
  - Quota and `containsSyntheticMedia` are to be verified against current docs.
- v2 (final; Critic APPROVE, Architect SOUND_WITH_CHANGES → must-fix items applied):
  - **Audio:** scene clips are now video-only, and one padded `master.wav` is muxed once (stops AAC priming drift at scene joins). TTS now uses `response_format=pcm` with headers written in code. A tone-onset sync test was added.
  - **Prompt spans:** `.gp` / `>>>` / `$` prompts are kept verbatim (consistent with AC-7).
  - **Preview:** now a POST background job, cached by scene hash, and returns 409 on stale assets or during a render.
  - **Highlight line:** `highlightLine` added to the schema, with validation and a test.
  - **Upload binding:** `rendered_hash` ties upload to the exact mp4.
  - **Glyphs:** the glyph test is now a fontTools cmap coverage check (in the validator and in tests).
  - **`onScreenText`:** the regex now allows ordinary Korean parentheses.
  - **Exact limits:** cue lines ≤ 16 chars and ≤ 960 px; the TTS and image model ids are named; cost target ≤ 700 KRW with 1000 KRW as a hard cap.
  - **zoompan:** the still is fed as a single frame.
