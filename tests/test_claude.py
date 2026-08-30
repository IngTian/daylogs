import asyncio
import json

import pytest

from daybook import claude as C


class FakeProc:
    """A stand-in for asyncio's Process, faithful about `returncode`.

    It used to report `rc` from the start, including while hanging. That is a lie a
    real process cannot tell — `returncode` is None until the child exits — and it
    hid the fact that cleanup code guarding on `returncode is None` would skip a
    still-running child. Kept honest so a double cannot make a bug look fixed.
    """

    def __init__(self, stdout=b"", stderr=b"", rc=0, hang=False):
        self._out, self._err, self._rc, self._hang = stdout, stderr, rc, hang
        self.killed = False
        self._exited = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10)
        self._exited = True
        return self._out, self._err

    def kill(self):
        self.killed = True
        self._exited = True

    async def wait(self):
        self._exited = True
        return self._rc

    @property
    def returncode(self):
        return self._rc if self._exited else None


@pytest.fixture()
def spy(monkeypatch):
    captured: dict = {}

    def make(proc):
        async def fake_exec(*args, **kwargs):
            captured["argv"] = list(args)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        return captured

    return make


async def test_text_returns_stripped_stdout(spy):
    cap = spy(FakeProc(stdout=b"  hello world \n"))
    out = await C.run_oneshot_text("sys", "user", timeout_sec=5)
    assert out == "hello world"
    argv = cap["argv"]
    assert argv[0] == "claude" and "-p" in argv
    assert "--system-prompt" in argv and "sys" in argv
    assert "--output-format" in argv and "text" in argv
    assert "--no-session-persistence" in argv
    assert argv[-1] == "user"


async def test_model_flag_only_when_given(spy):
    cap = spy(FakeProc(stdout=b"x"))
    await C.run_oneshot_text("s", "u", timeout_sec=5)
    assert "--model" not in cap["argv"]
    cap = spy(FakeProc(stdout=b"x"))
    await C.run_oneshot_text("s", "u", timeout_sec=5, model="sonnet")
    assert cap["argv"][cap["argv"].index("--model") + 1] == "sonnet"


async def test_missing_binary_raises_claude_error(monkeypatch):
    async def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    with pytest.raises(C.ClaudeError, match="not on PATH"):
        await C.run_oneshot_text("s", "u", timeout_sec=5)


async def test_nonzero_exit_includes_truncated_stderr(spy):
    spy(FakeProc(stdout=b"", stderr=b"E" * 900, rc=2))
    with pytest.raises(C.ClaudeError) as e:
        await C.run_oneshot_text("s", "u", timeout_sec=5)
    assert "exited 2" in str(e.value)
    assert len(str(e.value)) < 700


async def test_timeout_kills_the_process(spy):
    proc = FakeProc(hang=True)
    spy(proc)
    with pytest.raises(C.ClaudeError, match="timed out"):
        await C.run_oneshot_text("s", "u", timeout_sec=0.01)
    assert proc.killed is True


async def test_json_returns_structured_output(spy):
    envelope = {"type": "result", "structured_output": {"description": "salad", "kcal": 610}}
    cap = spy(FakeProc(stdout=json.dumps(envelope).encode()))
    got = await C.run_oneshot_json(
        system_prompt="s", user_prompt="u", json_schema={"type": "object"}, timeout_sec=5
    )
    assert got == {"description": "salad", "kcal": 610}
    argv = cap["argv"]
    assert "--json-schema" in argv
    assert argv[argv.index("--output-format") + 1] == "json"


async def test_json_schema_is_serialised_into_argv(spy):
    envelope = {"structured_output": {"ok": True}}
    schema = {"type": "object", "required": ["ok"]}
    cap = spy(FakeProc(stdout=json.dumps(envelope).encode()))
    await C.run_oneshot_json(
        system_prompt="s", user_prompt="u", json_schema=schema, timeout_sec=5
    )
    argv = cap["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1]) == schema


async def test_json_rejects_non_json_stdout(spy):
    spy(FakeProc(stdout=b"not json at all"))
    with pytest.raises(C.ClaudeError, match="non-JSON"):
        await C.run_oneshot_json(system_prompt="s", user_prompt="u", json_schema={}, timeout_sec=5)


async def test_json_rejects_envelope_without_structured_output(spy):
    spy(FakeProc(stdout=json.dumps({"type": "result"}).encode()))
    with pytest.raises(C.ClaudeError, match="structured_output"):
        await C.run_oneshot_json(system_prompt="s", user_prompt="u", json_schema={}, timeout_sec=5)


async def test_image_call_grants_read_on_the_image_directory(spy, tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff")
    envelope = {"structured_output": {"description": "steak", "kcal": 900}}
    cap = spy(FakeProc(stdout=json.dumps(envelope).encode()))
    got = await C.run_with_image_json(
        image_path=str(img), prompt="read it", json_schema={}, timeout_sec=5
    )
    assert got["kcal"] == 900
    argv = cap["argv"]
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)
    assert argv[argv.index("--tools") + 1] == "Read"
    assert "--no-session-persistence" in argv


# ── a cancelled call must not leave the child running (#10) ───────────────


async def test_cancelling_a_call_kills_the_child(spy):
    """`FakeProc` level: the fast check that the kill happens at all.

    `CancelledError` is a BaseException, so the `except TimeoutError` branch never
    sees it — a superseded estimate used to leave its child alive for up to
    `timeout_sec`.
    """
    proc = FakeProc(hang=True)
    spy(proc)
    task = asyncio.create_task(C.run_oneshot_text("s", "u", timeout_sec=60))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert proc.killed is True, "a cancelled call left its child running"


async def test_cancelling_a_call_reaps_a_real_child(monkeypatch):
    """And with a real process, because that is the thing being claimed.

    A FakeProc only proves `kill()` was called. This proves the OS process is
    actually gone — which needs the `await proc.wait()`, since without it the child
    lingers as a zombie that `os.kill(pid, 0)` still reports as alive.
    """
    import os

    pids: list[int] = []
    real_exec = asyncio.create_subprocess_exec

    async def spy_exec(*args, **kwargs):
        proc = await real_exec(*args, **kwargs)
        pids.append(proc.pid)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)

    def alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    task = asyncio.create_task(C._run(["sleep", "30"], timeout_sec=60, label="probe"))
    for _ in range(200):
        if pids:
            break
        await asyncio.sleep(0.01)
    assert pids, "the child never started, so this test would prove nothing"
    pid = pids[0]
    assert alive(pid), "the child was not running before cancellation"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Immediately, with no polling. That is the point of the `await proc.wait()`:
    # asyncio's child watcher does reap the corpse on its own, but not until roughly
    # 50 ms later (measured), so without the wait the process is still there the
    # instant the call it belonged to has finished unwinding. Polling for it would
    # pass either way and prove nothing.
    assert not alive(pid), (
        f"pid {pid} was still alive the moment the cancelled call returned — "
        "the child was killed but not reaped"
    )


async def test_a_timeout_still_kills_the_child(spy):
    """The path that already worked must keep working — the fix shares its cleanup."""
    proc = FakeProc(hang=True)
    spy(proc)
    with pytest.raises(C.ClaudeError, match="timed out"):
        await C.run_oneshot_text("s", "u", timeout_sec=0.01)
    assert proc.killed is True
