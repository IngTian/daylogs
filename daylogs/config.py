"""Typed config loaded from ~/Documents/daylogs/config.toml.

Every key has a default, so an absent file is a supported state — a fresh
install runs with no configuration at all. The data root is overridable with
DAYLOGS_HOME, which is how the tests isolate.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def is_zone(name: str) -> bool:
    """Whether `name` is a zone the tz database actually has."""
    try:
        ZoneInfo(name)
    except (KeyError, ValueError, OSError):
        return False
    return True


def system_timezone() -> str:
    """The machine's IANA zone name — what `timezone` defaults to.

    Detected rather than hardcoded. The default used to be the literal
    "America/Toronto", which is right for exactly one machine: everywhere else every
    time the grammar parsed was resolved in Toronto while `fmt` rendered in the
    machine's own zone, so an edit's prefill round-trip moved the row by the offset.
    Making the default *be* the machine's zone is what makes the two agree by
    construction rather than by luck.

    Best effort, in the order that is actually reliable: `TZ` when it is set — which is
    also how the test suite pins a zone, and the config has to agree with the process or
    the tests disagree with themselves — then the `/etc/localtime` symlink that macOS
    and Linux both keep pointing into the tzdata tree.

    `UTC` is the last resort. It is wrong by an offset, but it is honest about being a
    fallback and `h` fixes it in one line; guessing a populated zone would put a
    plausible wrong answer everywhere instead.
    """
    env = os.environ.get("TZ", "").strip()
    if env and is_zone(env):
        return env
    try:
        parts = Path("/etc/localtime").resolve().parts
        if "zoneinfo" in parts:
            name = "/".join(parts[parts.index("zoneinfo") + 1 :])
            if is_zone(name):
                return name
    except OSError:
        pass
    return "UTC"


# A Textual theme name. Duplicated as a literal rather than imported from
# tui.themes on purpose: this module is pure — no textual, no database — and
# importing the UI framework to load a config file would invert that. The two are
# tied together by a test, not by an import.
_DEFAULT_THEME = "gruvbox"


@dataclass(frozen=True)
class Config:
    root: Path
    db_path: Path
    inbox_dir: Path
    memory_path: Path
    # Always a real IANA name, so every reader can do `ZoneInfo(cfg.timezone)`
    # without a None branch. `default_factory` rather than a literal: a module-level
    # default would freeze the machine's zone at import time, which is wrong for a
    # long-running process and untestable.
    timezone: str = field(default_factory=system_timezone)
    height_cm: float | None = None
    sex: str | None = None
    birthday: str | None = None
    claude_model: str | None = None
    theme: str = _DEFAULT_THEME
    # A key of body.ACTIVITY_LEVELS: what an ordinary day looks like, so a day that
    # matches it needs no entry. Deliberately not defaulted -- see the design note.
    activity: str | None = None
    summary_after_hour: int = 6
    summary_timeout_sec: int = 120
    estimate_timeout_sec: int = 60
    extra_categories: tuple[tuple[str, str, str], ...] = ()


def _zone_or_system(raw) -> str:
    """A configured zone, or the machine's when it is absent or not a real zone.

    A typo in a hand-edited config.toml must not stop the app — the same stance the
    theme and the activity level take — and it must not leave an unusable string behind
    either, because every reader does `ZoneInfo(cfg.timezone)` on the next keystroke.
    """
    name = str(raw or "").strip()
    return name if name and is_zone(name) else system_timezone()


def default_root() -> Path:
    env = os.environ.get("DAYLOGS_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / "Documents" / "daylogs"


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
        db_path=path_of("db_path", "daylogs.db"),
        inbox_dir=path_of("inbox_dir", "inbox"),
        memory_path=path_of("memory_path", "memory.md"),
        timezone=_zone_or_system(raw.get("timezone")),
        height_cm=_opt_float(raw.get("height_cm")),
        sex=_opt_str(raw.get("sex")),
        birthday=_opt_str(raw.get("birthday")),
        claude_model=_opt_str(raw.get("claude_model")),
        theme=str(raw.get("theme") or _DEFAULT_THEME),
        activity=_opt_str(raw.get("activity")),
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


def add_category(path: Path | str, *, slug: str, display: str | None) -> None:
    """Append a `[[category]]` block to config.toml.

    Appends where `update_config` *prepends*, and the asymmetry is deliberate rather than
    an inconsistency to tidy up. Both rules exist because TOML's scoping is positional and
    both failures are silent — the file still parses either way:

    - a **scalar** written after a table header becomes a field of that table, so the
      setting is simply never read again;
    - a **table block** written among the scalars swallows every scalar below it.

    So one has to go first and the other last. Edited as text, like `update_config`, so a
    hand-written comment or a `[[category]]` block you added yourself survives.

    `display` is omitted when absent: `categories.all_categories` already falls back to
    the slug. No colour either — `auto_color` derives a stable one from the slug.
    """
    path = Path(path).expanduser()
    text = path.read_text() if path.exists() else ""
    block = ["[[category]]", f"slug = {_toml_scalar(slug)}"]
    if display:
        block.append(f"display = {_toml_scalar(display)}")
    prefix = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    path.write_text(text + prefix + "\n".join(block) + "\n")


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
