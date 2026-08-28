import sqlite3

import pytest

from daybook.__main__ import main


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYBOOK_HOME", str(tmp_path))
    return tmp_path


def _seed_weight(kg=70.0):
    from daybook.body import add_weight
    from daybook.config import load_config
    from daybook.db import connect, ensure_schema

    cfg = load_config()
    conn = connect(cfg.db_path)
    ensure_schema(conn)
    add_weight(conn, kg=kg, date="2026-08-27", at=1)
    conn.close()


def test_version(capsys):
    assert main(["--version"]) == 0
    assert "daybook" in capsys.readouterr().out.lower()


def test_unknown_command_is_an_error():
    assert main(["nonsense"]) != 0


def test_summary_prints_generated_content(capsys, monkeypatch):
    async def fake_runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        return "## Body\n\nAll steady."

    monkeypatch.setattr("daybook.__main__.claude.run_oneshot_text", fake_runner)
    assert main(["summary"]) == 0
    assert "All steady." in capsys.readouterr().out


def test_summary_honours_explicit_date(capsys, monkeypatch):
    async def fake_runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        assert '"target_date": "2026-08-20"' in user_prompt
        return "dated"

    monkeypatch.setattr("daybook.__main__.claude.run_oneshot_text", fake_runner)
    assert main(["summary", "--date", "2026-08-20"]) == 0
    assert "dated" in capsys.readouterr().out


def test_summary_persists_so_a_second_run_can_read_it(monkeypatch):
    async def fake_runner(system_prompt, user_prompt, *, timeout_sec, model=None):
        return "persisted"

    monkeypatch.setattr("daybook.__main__.claude.run_oneshot_text", fake_runner)
    assert main(["summary", "--date", "2026-08-20"]) == 0

    from daybook.config import load_config
    from daybook.db import connect
    from daybook.summary import get_report

    conn = connect(load_config().db_path)
    assert get_report(conn, "2026-08-20")["content"] == "persisted"
    conn.close()


def test_summary_reports_failure_with_nonzero_exit(capsys, monkeypatch):
    from daybook.claude import ClaudeError

    async def boom(*a, **k):
        raise ClaudeError("no claude on PATH")

    monkeypatch.setattr("daybook.__main__.claude.run_oneshot_text", boom)
    assert main(["summary"]) != 0
    assert "no claude" in capsys.readouterr().err


def test_summary_rejects_a_bad_date(capsys):
    assert main(["summary", "--date", "20-08-2026"]) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_backup_writes_a_readable_copy(tmp_path, capsys):
    _seed_weight()
    dest = tmp_path / "backups"
    assert main(["backup", str(dest)]) == 0
    out = capsys.readouterr().out.strip()
    copies = list(dest.glob("daybook-*.db"))
    assert len(copies) == 1
    assert str(copies[0]) in out
    c = sqlite3.connect(copies[0])
    assert c.execute("SELECT count(*) FROM weight").fetchone()[0] == 1
    c.close()


def test_backup_creates_the_destination_directory(tmp_path):
    assert main(["backup", str(tmp_path / "deep" / "nested")]) == 0
    assert (tmp_path / "deep" / "nested").is_dir()


def test_backup_is_repeatable_same_day(tmp_path):
    dest = tmp_path / "b"
    assert main(["backup", str(dest)]) == 0
    assert main(["backup", str(dest)]) == 0
    assert len(list(dest.glob("daybook-*.db"))) == 1


def test_running_a_command_creates_the_schema(tmp_path):
    assert main(["backup", str(tmp_path / "b")]) == 0
    from daybook.config import load_config
    from daybook.db import TABLES

    conn = sqlite3.connect(load_config().db_path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert set(TABLES) <= names
