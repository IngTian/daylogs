import asyncio
import json

import pytest

from daybook import claude as C


class FakeProc:
    def __init__(self, stdout=b"", stderr=b"", rc=0, hang=False):
        self._out, self._err, self._rc, self._hang = stdout, stderr, rc, hang
        self.killed = False

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(10)
        return self._out, self._err

    def kill(self):
        self.killed = True

    async def wait(self):
        return self._rc

    @property
    def returncode(self):
        return self._rc


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
