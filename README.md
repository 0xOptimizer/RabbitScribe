# RabbitScribe

A reusable PySide6 GUI that drives video files through a 4-step pipeline:

1. **Source** — pick MP4, show ffprobe metadata, extract MP3 via ffmpeg.
2. **Transcribe** — run whisper.cpp (preferred) or openai-whisper (fallback) -> `.raw.srt`.
3. **Cleanup** — apply toggleable rules (cue duration, char limits, ellipsis, capitalisation, word-substitution dictionary) -> `.cleaned.srt`.
4. **Chunks** — split the source MP4 into N labelled pieces with ffmpeg `-c copy` (no re-encode).

The app is general-purpose. Any video, any language, any chunk list — the first dataset shipped here is a Dutch business-pitch video, but everything is configurable.

---

## Install

Requires **Python 3.11+** and **ffmpeg** on `PATH`.

```powershell
# 1. Clone or open the project folder
cd c:\Developments\automation\rabbitscribe

# 2. Create a venv and install
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The `dev` extra adds `pytest` for the SRT-cleaner test suite.

If you don't have ffmpeg yet:

```powershell
winget install Gyan.FFmpeg
```

---

## Run

```powershell
.venv\Scripts\python.exe -m rabbitscribe
```

or, after activating the venv:

```powershell
.venv\Scripts\activate
rabbitscribe
```

---

## External binaries (whisper.cpp)

RabbitScribe is a Qt GUI on top of [whisper.cpp](https://github.com/ggerganov/whisper.cpp). You need two pieces:

1. **`main.exe`** — drop the Windows release binary into:

   ```
   tools\whisper.cpp\main.exe
   ```

   Download from https://github.com/ggerganov/whisper.cpp/releases. Pick the AVX2 / Vulkan / cuBLAS build that matches your hardware.

2. **A `ggml-*.bin` model** — drop into:

   ```
   tools\models\ggml-large-v3.bin
   ```

   Download from https://huggingface.co/ggerganov/whisper.cpp/tree/main. Models in this folder are auto-detected by the Transcribe tab.

If `main.exe` is missing, the Transcribe tab will show a dialog with a download link and a "Browse for main.exe" button. As a fallback, you can switch the engine to **openai-whisper** in the same tab — that path uses the Python package (already installed by `pip install -e .`).

---

## Project layout

```
rabbitscribe\
  pyproject.toml
  rabbitscribe\
    __main__.py            # entry point
    main_window.py         # QMainWindow with 4 tabs
    settings.py            # QSettings wrapper
    logging_setup.py       # file + Qt-signal log handlers
    paths.py               # ffmpeg / whisper.cpp / model discovery
    workers\               # ffprobe, mp3_extract, transcribe, chunk_split, srt_cleaner
    widgets\               # source_panel, transcribe_panel, cleanup_panel, chunks_panel + log/progress
    models\                # Project state + chunks table model
    resources\
      style.qss
      presets\
        semovote_14.json   # 14-chunk preset for the first-run Dutch video
        dutch_fixes.json   # proper-name substitutions for the cleanup tab
  tests\
    test_srt_cleaner.py    # 24 unit tests
```

---

## Testing

```powershell
.venv\Scripts\python.exe -m pytest
```

Only the pure-Python pieces are unit-tested (the SRT cleaner). The GUI is verified manually by walking through all four tabs end-to-end.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg not found` in Source tab | `winget install Gyan.FFmpeg`, then restart the app |
| Transcribe tab shows "whisper.cpp binary not found" | Place `main.exe` at `tools\whisper.cpp\main.exe`, or use the "Browse" dialog and restart |
| Transcribe tab shows "(no models in tools/models/)" | Download a `ggml-*.bin` and drop it in `tools\models\` |
| openai-whisper transcription is extremely slow | That path runs on CPU/GPU per your `torch` install. Use whisper.cpp instead for GPU-accelerated transcription |
| Chunks "Split All" gives an error and no output | Click "Validate" first — start/end must be `HH:MM:SS`, end > start, end <= video duration |
| Window doesn't remember size on next launch | Make sure the app exited cleanly via File -> Quit or the window's close button; force-killed processes don't write QSettings |

Logs are written to `~\.rabbitscribe\logs\app.log` (rotating, 5 MB x 3 files).

---

## Out of scope

PyInstaller packaging, subtitle burn-in, speaker diarization, cloud transcription APIs, and UI localisation are explicitly deferred. The app runs from source via `python -m rabbitscribe`.
