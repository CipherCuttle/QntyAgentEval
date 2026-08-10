from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NativeRun:
    command: tuple[str, ...]
    pid: int
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    stdout: str
    stderr: str
    version: str


def _version(binary: str) -> str:
    try:
        proc = subprocess.run(
            [binary, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        return proc.stdout.strip()
    except Exception as exc:
        return f"UNAVAILABLE: {type(exc).__name__}: {exc}"


def _codex_command(prompt: str, model: str | None) -> list[str]:
    cmd = [
        "codex",
        "--ask-for-approval",
        "never",
        "exec",
        "--json",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
    ]
    if model:
        cmd += ["-m", model]
    cmd += [prompt]
    return cmd


def _claude_command(prompt: str, model: str | None, max_turns: int) -> list[str]:
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--max-turns",
        str(max_turns),
        "--disallowedTools",
        "WebSearch",
    ]
    if model:
        cmd += ["--model", model]
    cmd += [prompt]
    return cmd


def build_command(
    agent: str, prompt: str, *, model: str | None = None, max_turns: int = 40
) -> list[str]:
    if agent == "codex":
        return _codex_command(prompt, model)
    if agent == "claude":
        return _claude_command(prompt, model, max_turns)
    raise ValueError(f"unsupported agent: {agent}")


def run_native(
    *,
    agent: str,
    repo: Path,
    prompt: str,
    model: str | None,
    timeout_seconds: int,
    max_turns: int = 40,
) -> NativeRun:
    cmd = build_command(agent, prompt, model=model, max_turns=max_turns)
    binary = cmd[0]
    version = _version(binary)

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=repo,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        env=os.environ.copy(),
    )

    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()

    duration = time.monotonic() - started
    return NativeRun(
        command=tuple(cmd),
        pid=proc.pid,
        exit_code=proc.returncode,
        timed_out=timed_out,
        duration_seconds=duration,
        stdout=stdout,
        stderr=stderr,
        version=version,
    )
