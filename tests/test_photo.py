import os

import pytest

from daybook import photo


def test_next_inbox_returns_oldest_image(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    older, newer = inbox / "a.jpg", inbox / "b.png"
    older.write_bytes(b"x")
    newer.write_bytes(b"y")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))
    assert photo.next_inbox_image(inbox) == older


def test_next_inbox_ignores_non_images_and_processed(tmp_path):
    inbox = tmp_path / "inbox"
    (inbox / "processed").mkdir(parents=True)
    (inbox / "notes.txt").write_bytes(b"x")
    (inbox / "processed" / "old.jpg").write_bytes(b"x")
    assert photo.next_inbox_image(inbox) is None
    assert photo.pending_count(inbox) == 0


def test_next_inbox_missing_dir_is_not_an_error(tmp_path):
    assert photo.next_inbox_image(tmp_path / "nope") is None
    assert photo.pending_count(tmp_path / "nope") == 0


def test_pending_count(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for n in ("a.jpg", "b.jpeg", "c.png", "d.heic"):
        (inbox / n).write_bytes(b"x")
    assert photo.pending_count(inbox) == 4


def test_suffix_matching_is_case_insensitive(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "SHOT.JPG").write_bytes(b"x")
    assert photo.pending_count(inbox) == 1


def test_mark_processed_moves_and_deduplicates(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    first = inbox / "a.jpg"
    first.write_bytes(b"x")
    moved = photo.mark_processed(first, inbox)
    assert moved.parent.name == "processed"
    assert not first.exists()

    again = inbox / "a.jpg"
    again.write_bytes(b"y")
    moved2 = photo.mark_processed(again, inbox)
    assert moved2 != moved
    assert moved.exists() and moved2.exists()


def test_resolve_path_accepts_quoted_and_escaped_input(tmp_path):
    f = tmp_path / "my photo.jpg"
    f.write_bytes(b"x")
    assert photo.resolve_path(f'"{f}"') == f
    assert photo.resolve_path(str(f).replace(" ", "\\ ")) == f


def test_resolve_path_rejects_missing_and_non_image(tmp_path):
    with pytest.raises(photo.PhotoError, match="no file"):
        photo.resolve_path(str(tmp_path / "nope.jpg"))
    txt = tmp_path / "a.txt"
    txt.write_bytes(b"x")
    with pytest.raises(photo.PhotoError, match="image"):
        photo.resolve_path(str(txt))


def test_clipboard_returns_none_when_osascript_finds_no_image(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        class R:
            returncode = 1
            stdout = b""
            stderr = b"can't get the clipboard as PNG"

        return R()

    monkeypatch.setattr(photo.subprocess, "run", fake_run)
    assert photo.clipboard_image(tmp_path) is None


def test_clipboard_returns_none_when_osascript_is_missing(tmp_path, monkeypatch):
    def boom(argv, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(photo.subprocess, "run", boom)
    assert photo.clipboard_image(tmp_path) is None


def test_clipboard_returns_none_on_an_empty_write(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        photo._clip_target(tmp_path).write_bytes(b"")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(photo.subprocess, "run", fake_run)
    assert photo.clipboard_image(tmp_path) is None


def test_clipboard_returns_written_file_on_success(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        photo._clip_target(tmp_path).write_bytes(b"\x89PNG\r\n\x1a\n")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(photo.subprocess, "run", fake_run)
    got = photo.clipboard_image(tmp_path)
    assert got is not None and got.read_bytes().startswith(b"\x89PNG")


def test_clip_script_requests_png_flavour(tmp_path):
    script = photo._clip_script(tmp_path / "x.png")
    assert "«class PNGf»" in script
    assert "close access fd" in script
