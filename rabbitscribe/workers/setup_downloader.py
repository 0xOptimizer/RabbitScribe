"""Download workers for the in-app setup wizard.

All workers are QThread subclasses with the same progress/log/finished/error
signal shape as the rest of the app. Cancel is honest: each chunk loop
checks `_cancelled` and aborts cleanly.
"""

from __future__ import annotations

import json
import logging
import shutil
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal


log = logging.getLogger(__name__)


WHISPER_CPP_RELEASES_API = "https://api.github.com/repos/ggerganov/whisper.cpp/releases/latest"
HUGGINGFACE_MODEL_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"


# (display_label, ggml filename, approx_mb) — sizes are nominal full-precision builds
WHISPER_MODELS: list[tuple[str, str, int]] = [
    ("tiny  (~75 MB)",      "ggml-tiny.bin",       75),
    ("base  (~142 MB)",     "ggml-base.bin",      142),
    ("small (~466 MB)",     "ggml-small.bin",     466),
    ("medium (~1.5 GB)",    "ggml-medium.bin",   1500),
    ("large-v2 (~3 GB)",    "ggml-large-v2.bin", 3000),
    ("large-v3 (~3 GB)",    "ggml-large-v3.bin", 3000),
]


def _open_with_ua(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "rabbitscribe/0.1"})
    return urllib.request.urlopen(req, timeout=30)


class ReleaseListFetcher(QThread):
    """Hits GitHub's API for the latest whisper.cpp release and emits the
    list of Windows zip assets so the user can pick a build variant.
    """

    finished_list = Signal(list)  # list of {"name": str, "url": str, "size": int}
    error = Signal(str)

    def run(self) -> None:  # type: ignore[override]
        try:
            with _open_with_ua(WHISPER_CPP_RELEASES_API) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            self.error.emit(f"Could not reach GitHub: {exc}")
            return

        assets = []
        for a in data.get("assets", []):
            name = a.get("name", "")
            if name.lower().endswith(".zip") and "x64" in name.lower():
                assets.append({
                    "name": name,
                    "url": a.get("browser_download_url"),
                    "size": a.get("size", 0),
                })
        if not assets:
            self.error.emit("No matching Windows zip assets found in the latest release.")
            return
        self.finished_list.emit(assets)


class FileDownloader(QThread):
    """Streams a URL to disk with chunk-by-chunk progress."""

    progress = Signal(float)
    log = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, url: str, dest: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._dest = dest
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # type: ignore[override]
        self._dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._dest.with_suffix(self._dest.suffix + ".part")
        try:
            with _open_with_ua(self._url) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                self.log.emit(
                    f"Downloading {self._url}\n"
                    f"  -> {self._dest}"
                    + (f"  ({total / 1024 / 1024:.1f} MB)" if total else "")
                )
                downloaded = 0
                with open(tmp, "wb") as f:
                    while True:
                        if self._cancelled:
                            raise InterruptedError("cancelled")
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            self.progress.emit(downloaded / total)
            if self._dest.exists():
                self._dest.unlink()
            tmp.rename(self._dest)
            self.progress.emit(1.0)
            self.finished.emit(str(self._dest))
        except InterruptedError:
            self._cleanup(tmp)
            self.error.emit("Cancelled")
        except (urllib.error.URLError, OSError) as exc:
            self._cleanup(tmp)
            self.error.emit(f"Download failed: {exc}")

    @staticmethod
    def _cleanup(tmp: Path) -> None:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Extract a zip into dest_dir, returning the list of extracted files.

    Synchronous: zip extraction of a whisper.cpp release is fast (<1s).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)
        for name in zf.namelist():
            target = dest_dir / name
            if target.is_file():
                extracted.append(target)
    return extracted


def flatten_whisper_extract(dest_dir: Path) -> Path | None:
    """Some whisper.cpp zips nest the binaries inside a subfolder. Find the
    whisper binary anywhere under dest_dir and surface its path.
    """
    for candidate_name in ("main.exe", "whisper-cli.exe", "whisper.exe"):
        for found in dest_dir.rglob(candidate_name):
            if found.is_file():
                # If nested, copy to dest_dir/main.exe and flatten neighbours.
                if found.parent != dest_dir:
                    for sibling in found.parent.iterdir():
                        if sibling.is_file():
                            target = dest_dir / sibling.name
                            if target.exists():
                                try:
                                    target.unlink()
                                except OSError:
                                    continue
                            shutil.copy2(sibling, target)
                    return dest_dir / found.name
                return found
    return None
