"""URL download workers for the Source tab.

`GoogleDriveDownloader` wraps the `gdown` CLI in a subprocess — gives real
cancel (QProcess.kill) and parses tqdm progress lines from stderr.
Direct HTTP URLs (a plain .mp4 link) reuse the existing `FileDownloader`
QThread from setup_downloader.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject

from rabbitscribe.workers._qprocess_worker import QProcessWorker


log = logging.getLogger(__name__)


_TQDM_PCT_RE = re.compile(r"(\d{1,3})%\|")


def is_google_drive_url(url: str) -> bool:
    return "drive.google.com" in url.lower() or "drive.usercontent.google.com" in url.lower()


def is_http_url(url: str) -> bool:
    return urlparse(url).scheme in ("http", "https")


def _find_gdown_cli() -> Path | None:
    candidates = [
        Path(sys.prefix) / "Scripts" / "gdown.exe",
        Path(sys.prefix) / "Scripts" / "gdown",
        Path(sys.prefix) / "bin" / "gdown",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def default_download_dir() -> Path:
    """Where downloaded source videos land: <project>/downloads/."""
    return Path(__file__).resolve().parent.parent.parent / "downloads"


def filename_from_url(url: str, fallback_stem: str = "video") -> str:
    """Best-effort filename guess for direct HTTP URLs.

    Drive URLs don't carry a meaningful filename here — gdown will fetch
    the real one and write it itself.
    """
    parsed = urlparse(url)
    name = Path(parsed.path).name
    if name and "." in name:
        return name
    return f"{fallback_stem}.mp4"


class GoogleDriveDownloader(QProcessWorker):
    """Wraps `gdown <URL> -O <dest> --fuzzy` in a QProcess.

    On finish, `output_path` (passed to start) is the file that ended up
    on disk; gdown respects -O when given a full file path.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def start(self, url: str, dest: Path) -> None:
        cli = _find_gdown_cli()
        if cli is None:
            self.error.emit(
                "gdown CLI not found. Install with: pip install gdown"
            )
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        # gdown 5+ parses Drive URL variants by default; older `--fuzzy`
        # flag was removed.
        args = [url, "-O", str(dest)]
        self._start(str(cli), args, output_path=dest)

    def _parse_progress(self, line: str) -> float | None:
        m = _TQDM_PCT_RE.search(line)
        if not m:
            return None
        try:
            return int(m.group(1)) / 100.0
        except ValueError:
            return None
