"""Subprocess wrappers for `claude -p`.

Three call shapes: plain text (the daily summary), structured JSON from text
(a calorie estimate from a description), and structured JSON from an image (a
calorie estimate from a photo). One error type for all of them, because a
caller forced to distinguish "binary missing" from "timed out" from "bad
JSON" is a caller that will forget one of them.

Every invocation passes --no-session-persistence, so daybook never pollutes
~/.claude/projects/. Runs under a Max OAuth subscription — no per-token API
charge.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os.path

log = logging.getLogger(__name__)

CLAUDE_BIN = "claude"
_STDERR_TAIL = 500


class ClaudeError(RuntimeError):
    """Missing binary, timeout, non-zero exit, or unparseable output."""


async def _run(argv: list[str], *, timeout_sec: float, label: str) -> bytes:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as e:
        raise ClaudeError(f"{CLAUDE_BIN} not on PATH") from e

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise ClaudeError(f"{label} timed out after {timeout_sec}s") from e

    if proc.returncode != 0:
        tail = stderr.decode(errors="replace")[-_STDERR_TAIL:]
        raise ClaudeError(f"{label} exited {proc.returncode}: {tail}")
    return stdout


def _structured(stdout: bytes, label: str) -> dict:
    try:
        envelope = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        tail = stdout.decode(errors="replace")[-_STDERR_TAIL:]
        raise ClaudeError(f"{label} returned non-JSON stdout: {tail}") from e
    inner = envelope.get("structured_output")
    if inner is None:
        raise ClaudeError(f"{label} envelope missing structured_output key")
    return inner


def _model_args(model: str | None) -> list[str]:
    return ["--model", model] if model else []


async def run_oneshot_text(
    system_prompt: str,
    user_prompt: str,
    *,
    timeout_sec: float,
    model: str | None = None,
) -> str:
    argv = [
        CLAUDE_BIN,
        "-p",
        "--system-prompt",
        system_prompt,
        *_model_args(model),
        "--output-format",
        "text",
        "--no-session-persistence",
        user_prompt,
    ]
    stdout = await _run(argv, timeout_sec=timeout_sec, label="claude -p")
    return stdout.decode().strip()


async def run_oneshot_json(
    *,
    system_prompt: str,
    user_prompt: str,
    json_schema: dict,
    timeout_sec: float,
    model: str | None = None,
) -> dict:
    argv = [
        CLAUDE_BIN,
        "-p",
        "--system-prompt",
        system_prompt,
        *_model_args(model),
        "--json-schema",
        json.dumps(json_schema),
        "--output-format",
        "json",
        "--no-session-persistence",
        user_prompt,
    ]
    stdout = await _run(argv, timeout_sec=timeout_sec, label="claude -p (json)")
    return _structured(stdout, "claude -p (json)")


async def run_with_image_json(
    *,
    image_path: str,
    prompt: str,
    json_schema: dict,
    timeout_sec: float,
    model: str | None = None,
) -> dict:
    """The prompt must reference the image by absolute path; claude reads it
    with the Read tool, which --add-dir plus --tools Read grant and nothing
    else does."""
    argv = [
        CLAUDE_BIN,
        "-p",
        "--add-dir",
        os.path.dirname(image_path),
        "--tools",
        "Read",
        *_model_args(model),
        "--json-schema",
        json.dumps(json_schema),
        "--output-format",
        "json",
        "--no-session-persistence",
        prompt,
    ]
    stdout = await _run(argv, timeout_sec=timeout_sec, label="claude -p (image)")
    return _structured(stdout, "claude -p (image)")
