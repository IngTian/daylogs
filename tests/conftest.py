import pytest

from daylogs.config import Config
from daylogs.db import connect, ensure_schema


@pytest.fixture()
def db(tmp_path):
    conn = connect(tmp_path / "test.db")
    ensure_schema(conn)
    yield conn
    conn.close()


@pytest.fixture()
def make_cfg(tmp_path):
    """A Config rooted at tmp_path. summary_after_hour defaults to 99 so the
    summary autorun never fires unless a test asks for it."""

    def _make(**kw):
        base = dict(
            root=tmp_path,
            db_path=tmp_path / "test.db",
            inbox_dir=tmp_path / "inbox",
            memory_path=tmp_path / "memory.md",
            summary_after_hour=99,
        )
        return Config(**{**base, **kw})

    return _make


@pytest.fixture()
def make_app(db, make_cfg):
    """Build a DaylogsApp against the test database with injected runners."""
    from daylogs.tui.app import DaylogsApp

    def _make(*, cfg=None, **kw):
        runners = {k: kw.pop(k) for k in list(kw) if k.startswith("runner_")}
        now = kw.pop("now", None)
        return DaylogsApp(cfg or make_cfg(**kw), db, now=now, **runners)

    return _make


@pytest.fixture()
def type_into():
    """Type a string into whatever has focus, one key at a time."""

    async def _type(pilot, text):
        for ch in text:
            await pilot.press("space" if ch == " " else ch)

    return _type
