"""Getting a food photo into a terminal app.

Three sources, tried in order by the Body tab: the clipboard, the iCloud
inbox folder, and an explicitly pasted path. The clipboard path uses
osascript rather than pngpaste, so there is no brew dependency to install on
a fresh machine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".heic", ".webp"})
PROCESSED_DIR = "processed"
_CLIP_NAME = "clipboard.png"
_OSASCRIPT_TIMEOUT = 10


class PhotoError(RuntimeError):
    pass


def _clip_target(dest_dir: Path) -> Path:
    return Path(dest_dir) / _CLIP_NAME


def _clip_script(target: Path) -> str:
    # AppleScript can write binary data straight to a file handle, which keeps
    # this dependency-free. The access is closed on both paths so a failure
    # does not leave the file locked for the next attempt.
    return (
        f'set p to POSIX file "{target}"\n'
        "set fd to open for access p with write permission\n"
        "try\n"
        "  set eof fd to 0\n"
        "  write (the clipboard as «class PNGf») to fd\n"
        "  close access fd\n"
        "on error errMsg\n"
        "  try\n"
        "    close access fd\n"
        "  end try\n"
        "  error errMsg\n"
        "end try\n"
    )


def clipboard_image(dest_dir: Path) -> Path | None:
    """Write the clipboard's PNG representation to dest_dir and return it, or
    None when the clipboard holds no image."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = _clip_target(dest_dir)
    target.unlink(missing_ok=True)
    try:
        result = subprocess.run(
            ["osascript", "-e", _clip_script(target)],
            capture_output=True,
            timeout=_OSASCRIPT_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return None
    return target


def _images_in(inbox: Path) -> list[Path]:
    inbox = Path(inbox)
    if not inbox.is_dir():
        return []
    return [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]


def next_inbox_image(inbox: Path) -> Path | None:
    files = _images_in(inbox)
    return min(files, key=lambda p: p.stat().st_mtime) if files else None


def pending_count(inbox: Path) -> int:
    return len(_images_in(inbox))


def mark_processed(path: Path, inbox: Path) -> Path:
    dest_dir = Path(inbox) / PROCESSED_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    dest = dest_dir / path.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{path.stem}-{n}{path.suffix}"
        n += 1
    return path.replace(dest)


def resolve_path(raw: str) -> Path:
    """Terminals paste dragged files quoted or backslash-escaped. Accept both
    rather than making the user clean it up by hand."""
    s = raw.strip().strip('"').strip("'").replace("\\ ", " ")
    p = Path(s).expanduser()
    if not p.is_file():
        raise PhotoError(f"no file at {p}")
    if p.suffix.lower() not in IMAGE_SUFFIXES:
        raise PhotoError(f"{p.suffix or 'that'} is not an image ({sorted(IMAGE_SUFFIXES)})")
    return p
