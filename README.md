# RabbitScribe

A PySide6 GUI that walks a video through a 4-step pipeline:

1. **Source** — pick MP4, show metadata, extract MP3 via ffmpeg.
2. **Transcribe** — whisper.cpp (preferred, GPU-friendly) or openai-whisper (Python fallback) → `.raw.srt`.
3. **Cleanup** — toggleable rules (cue duration, char limits, ellipsis, capitalisation, word-substitution dictionary) → `.cleaned.srt`.
4. **Chunks** — split the MP4 into N labelled pieces with ffmpeg `-c copy` (no re-encode).

General-purpose — any video, any language, any chunk list. The first preset shipped is a Dutch business-pitch video, but everything is configurable.

---

## Quick start

```powershell
run.bat
```

That's it. On first launch:

- If `.venv\` doesn't exist, it creates one and installs all dependencies (~2 GB, several minutes — mostly PyTorch).
- If `ffmpeg` is missing from PATH, prints a warning and the `winget install` line, but lets the app launch (the Cleanup tab works without ffmpeg).
- The app's **Setup wizard** auto-pops if no whisper.cpp binary or model is found — one-click download of both.

Subsequent launches: `run.bat` does a fast `importlib.util.find_spec` check (~50 ms) and goes straight to launching the app — sub-second cold boot.

If you'd rather skip the batch file:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m rabbitscribe
```

Requires **Python 3.11+** and **ffmpeg** on PATH (`winget install Gyan.FFmpeg`).

---

## Getting the whisper engine + a model

The Transcribe tab needs two external files. There are two ways to install them:

### Recommended: in-app Setup wizard

- **File → Setup wizard…** (or it auto-opens on first launch).
- Click **Fetch latest release list** → picks variants from the live GitHub releases for `ggerganov/whisper.cpp`. Choose a build (`cublas-*` for NVIDIA, `vulkan-*` for AMD/Intel, plain `bin-x64` for CPU). Click **Download & install** → downloads, extracts to `tools\whisper.cpp\`, and flattens the layout so `main.exe` is where the app expects.
- Below that, pick a model (default `large-v3`, ~3 GB) and click **Download model** → streams it from HuggingFace into `tools\models\`.
- Cancel button on each row actually works (real `QProcess.kill` for whisper jobs, chunked-loop cancel for downloads).

### Manual fallback

If you'd rather download by hand:

| File | Where to put it | Source |
|---|---|---|
| whisper.cpp binary | `tools\whisper.cpp\main.exe` | https://github.com/ggerganov/whisper.cpp/releases |
| Model | `tools\models\ggml-large-v3.bin` | https://huggingface.co/ggerganov/whisper.cpp/tree/main |

The `tools\` folder is gitignored. The Transcribe tab's "Browse for main.exe…" button saves a custom path to the state file — no restart required, `find_whisper_cpp()` reads the override live on every call.

---

## Per-video walkthrough

For a source at `c:\Videos\semovote.mp4`:

| Tab | Action | Output |
|---|---|---|
| Source | Browse for MP4 (or drag onto the window), confirm output dir, click **Extract MP3** | `rabbitscribe_output\semovote.mp3` |
| Transcribe | Pick engine + language (default Dutch) + model, click **Transcribe** | `rabbitscribe_output\semovote.raw.srt` |
| Cleanup | Rules auto-restore from state; optionally **Load…** the Dutch fixes dictionary; click **Preview** then **Clean and save** | `rabbitscribe_output\semovote.cleaned.srt` |
| Chunks | **Load preset…** picks the 14-chunk Semovote preset; **Validate**; **Split All** | `rabbitscribe_output\chunks\NN_label.mp4` × N |

Chunks are stream-copied (`-c copy`) — no re-encode, no quality loss, ~seconds of wall-clock time. Cuts snap to the nearest preceding keyframe (~2 s drift on typical encodings); enable "Frame-accurate (re-encode)" in Chunks options if you need exact cuts.

---

## Project layout

```
rabbitscribe\
  pyproject.toml
  run.bat                              ← one-click launcher + venv bootstrap
  rabbitscribe\
    __main__.py                        ← entry point
    main_window.py                     ← QMainWindow, lazy tabs, file/setup menu
    settings.py                        ← JSON-backed (see "State" below)
    logging_setup.py                   ← file + Qt-signal log handlers
    paths.py                           ← ffmpeg / whisper.cpp / model discovery
    workers\
      _qprocess_worker.py              ← shared QProcess base for ffmpeg/whisper
      ffprobe.py                       ← sync probe → MediaInfo dataclass
      mp3_extract.py                   ← ffmpeg MP3 worker
      transcribe.py                    ← whisper.cpp + openai-whisper CLI workers
      srt_cleaner.py                   ← pure-Python, unit-tested
      chunk_split.py                   ← sequential ffmpeg stream-copy
      setup_downloader.py              ← GitHub/HuggingFace download workers
    widgets\
      source_panel.py, transcribe_panel.py, cleanup_panel.py, chunks_panel.py
      log_view.py, progress_strip.py
      setup_dialog.py                  ← in-app wizard
    models\
      project.py                       ← shared mutable state with QSignals
      chunks.py                        ← QAbstractTableModel + timecode validation
    resources\
      style.qss
      presets\
        semovote_14.json
        dutch_fixes.json
  tests\
    test_srt_cleaner.py                ← 24 tests
```

---

## State and persistence

Two files outside the project directory:

| File | Contents |
|---|---|
| `~\.rabbitscribe\state.json` | App settings: window geometry, last MP4, last engine/language/model, cleanup rules, substitution dict, first-run flag, custom whisper.cpp path |
| `~\.rabbitscribe\logs\app.log` | Rotating log (5 MB × 3 files); also mirrored into the Log dock at runtime |

The state file is plain JSON (sorted keys, pretty-printed). Window-geometry blobs are base64-encoded inside a `{"__bytes_b64__": "..."}` wrapper. Atomic writes: a crash mid-save can't corrupt the file. Delete the file to fully reset the app.

---

## Testing

```powershell
.venv\Scripts\python.exe -m pytest
```

24 tests covering every rule in the SRT cleaner plus integration cases. The GUI is verified by launching it and walking through the four tabs.

---

## Performance notes

Cold boot to interactive: **~750 ms** (sub-second). Achieved via:

- Lazy panel construction — only the visible tab is built at boot; the rest construct in ~40-50 ms on first click.
- Hardcoded openai-whisper model list — avoids `import whisper` (which would trigger `import torch`, costing several seconds) just to populate a combo.
- Deferred ffprobe call when restoring the last-used MP4 — runs after the first paint.
- `run.bat`'s dependency check uses `importlib.util.find_spec` instead of `import`, so it doesn't drag PyTorch in on every launch.

Transcription speed depends entirely on the whisper.cpp build you install:

| Build | Hardware | ~56-min audio on large-v3 |
|---|---|---|
| cublas (NVIDIA) | GPU | a few minutes |
| vulkan (AMD/Intel) | GPU | minutes-tens of minutes |
| plain bin-x64 (CPU) | CPU | tens of minutes to ~1 hour |

The openai-whisper fallback runs whatever `torch` was installed. `pip install openai-whisper` on Windows pulls the **CPU-only** PyTorch wheel by default, so that path is slow. Use whisper.cpp with a GPU build for production work.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg not found` | `winget install Gyan.FFmpeg`, restart `run.bat` |
| Transcribe tab: "whisper.cpp binary missing" | Click **Open Setup wizard…** → Fetch list → pick a variant → Download. Or use **Browse for main.exe…** for an existing one |
| Transcribe tab: "(no models in tools/models/)" | Open Setup wizard → Model section → Download |
| Python-whisper engine is extremely slow | Either install a GPU torch (`pip install torch --index-url https://download.pytorch.org/whl/cu121`) or just use whisper.cpp with a CUDA build |
| Chunks **Split All** errors immediately | Click **Validate** first — start/end must be `HH:MM:SS`, end > start, end ≤ video duration |
| Window geometry / last MP4 forgotten | Make sure the app exited via the close button or File → Quit; force-killed runs may skip the `closeEvent` save |
| Want to fully reset state | Delete `~\.rabbitscribe\state.json` |
| Setup wizard "Could not reach GitHub" | Network/proxy issue. Use the manual fallback (drop `main.exe` into `tools\whisper.cpp\`) |

---

## Out of scope

PyInstaller packaging, subtitle burn-in, speaker diarization, cloud transcription APIs, per-chunk SRTs, and UI localisation are deferred. The app runs from source via `run.bat` or `python -m rabbitscribe`.
