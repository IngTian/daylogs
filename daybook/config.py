"""Typed config loaded from ~/Documents/daybook/config.toml.

Every key has a default, so an absent file is a supported state — a fresh
install runs with no configuration at all. The data root is overridable with
DAYBOOK_HOME, which is how the tests isolate.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_TZ = "America/Toronto"


@dataclass(frozen=True)
class Config:
    root: Path
    db_path: Path
    inbox_dir: Path
    memory_path: Path
    timezone: str = _DEFAULT_TZ
    height_cm: float | None = None
    sex: str | None = None
    birthday: str | None = None
    claude_model: str | None = None
    summary_after_hour: int = 6
    summary_timeout_sec: int = 120
    estimate_timeout_sec: int = 60
    extra_categories: tuple[tuple[str, str, str], ...] = ()


def default_root() -> Path:
    env = os.environ.get("DAYBOOK_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Documents" / "daybook"


def load_config(root: Path | None = None) -> Config:
    root = Path(root).expanduser() if root is not None else default_root()
    raw = _read_toml(root / "config.toml")

    def path_of(key: str, default_name: str) -> Path:
        value = raw.get(key)
        if not value:
            return root / default_name
        p = Path(str(value)).expanduser()
        return p if p.is_absolute() else root / p

    cats = tuple(
        (str(c["slug"]), str(c.get("display", c["slug"])), str(c.get("color", "")))
        for c in raw.get("category", [])
        if isinstance(c, dict) and c.get("slug")
    )

    return Config(
        root=root,
        db_path=path_of("db_path", "daybook.db"),
        inbox_dir=path_of("inbox_dir", "inbox"),
        memory_path=path_of("memory_path", "memory.md"),
        timezone=str(raw.get("timezone") or _DEFAULT_TZ),
        height_cm=_opt_float(raw.get("height_cm")),
        sex=_opt_str(raw.get("sex")),
        birthday=_opt_str(raw.get("birthday")),
        claude_model=_opt_str(raw.get("claude_model")),
        summary_after_hour=int(raw.get("summary_after_hour", 6)),
        summary_timeout_sec=int(raw.get("summary_timeout_sec", 120)),
        estimate_timeout_sec=int(raw.get("estimate_timeout_sec", 60)),
        extra_categories=cats,
    )


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"{path} is not valid TOML: {e}") from e


def _opt_str(value: object) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def _opt_float(value: object) -> float | None:
    return float(value) if value is not None else None


# ── writing ──────────────────────────────────────────────────────────────
_TABLE_HEADER = re.compile(r"^\s*\[")


def _toml_scalar(value: float | int | str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_config(path: Path | str, values: dict[str, float | int | str]) -> None:
    """Set top-level scalar keys in config.toml, leaving the rest of the file alone.

    Edited as text rather than re-serialised. The stdlib reads TOML and cannot
    write it, and the file may carry the user's comments and `[[category]]` blocks
    that a naive round-trip would drop.

    New keys are inserted **before the first table header**, not appended. A scalar
    written after `[[category]]` is a field *of that table* as far as TOML is
    concerned, so appending would quietly move the setting somewhere it is never
    read from — and the file would still parse, so nothing would complain.
    """
    path = Path(path).expanduser()
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines()

    # Where the top-level scalar region ends.
    limit = next((i for i, line in enumerate(lines) if _TABLE_HEADER.match(line)), len(lines))

    pending: list[str] = []
    for key, value in values.items():
        rendered = f"{key} = {_toml_scalar(value)}"
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for i in range(limit):
            if pattern.match(lines[i]):
                lines[i] = rendered
                break
        else:
            pending.append(rendered)

    if pending:
        # Keep a blank line between the scalars and a following table, so the file
        # still reads like something a person wrote.
        if limit < len(lines) and lines[limit].strip():
            pending.append("")
        lines[limit:limit] = pending

    path.parent.mkdir(parents=True, exist_ok=True)
    out = "\n".join(lines).rstrip("\n") + "\n"
    # Write via a sibling temp file: a half-written config.toml would make the app
    # unopenable, and this runs on a keystroke.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(out)
    tmp.replace(path)
