from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .gitutil import run_git
from .receipt import sha256_bytes, write_receipt
from .runners.native import run_native
from .scoring import score_workspace
from .task import load_task
from .workspace import cleanup_workspace, prepare_workspace


def _command_version(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        return "NOT_FOUND"
    proc = subprocess.run(
        [binary, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    return proc.stdout.strip()


def _help_contains(command: list[str], required: list[str]) -> dict[str, bool]:
    if not shutil.which(command[0]):
        return {flag: False for flag in required}
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    output = proc.stdout
    return {flag: flag in output for flag in required}


def doctor(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    source = Path(args.source_repo).expanduser().resolve()
    claude_flags = _help_contains(
        ["claude", "--help"],
        ["--output-format", "--permission-mode", "--disallowedTools"],
    )
    codex_global_flags = _help_contains(
        ["codex", "--help"],
        ["--ask-for-approval"],
    )
    codex_exec_flags = _help_contains(
        ["codex", "exec", "--help"],
        ["--json", "--ephemeral", "--sandbox"],
    )
    checks = {
        "git": _command_version("git"),
        "claude": _command_version("claude"),
        "codex": _command_version("codex"),
        "claude_required_flags": claude_flags,
        "claude_max_turns": "DOCUMENTED_BUT_NOT_HELP_PROBED",
        "codex_global_required_flags": codex_global_flags,
        "codex_exec_required_flags": codex_exec_flags,
        "source_repo": str(source),
        "source_repo_exists": source.is_dir(),
        "base_commit": task.base_commit,
        "base_commit_available": False,
    }
    if source.is_dir():
        proc = subprocess.run(
            ["git", "-C", str(source), "cat-file", "-e", f"{task.base_commit}^{{commit}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        checks["base_commit_available"] = proc.returncode == 0
    print(json.dumps(checks, indent=2))
    compatible = (
        all(claude_flags.values())
        and all(codex_global_flags.values())
        and all(codex_exec_flags.values())
    )
    return 0 if checks["base_commit_available"] and compatible else 2


def run(args: argparse.Namespace) -> int:
    task = load_task(args.task)
    prompt_bytes = task.prompt_path.read_bytes()
    prompt = prompt_bytes.decode("utf-8")

    checkout = prepare_workspace(task, args.source_repo)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + f"_{task.task_id}_{args.agent}"
    )
    runs_dir = Path(args.runs_dir).resolve()
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    try:
        native = run_native(
            agent=args.agent,
            repo=checkout,
            prompt=prompt,
            model=args.model,
            timeout_seconds=args.timeout,
            max_turns=args.max_turns,
        )

        (run_dir / "stdout.jsonl").write_text(native.stdout, encoding="utf-8")
        (run_dir / "stderr.txt").write_text(native.stderr, encoding="utf-8")

        diff = run_git(checkout, "diff", "--binary", "HEAD", check=False)
        cached = run_git(checkout, "diff", "--cached", "--binary", "HEAD", check=False)
        patch = diff.stdout + cached.stdout
        (run_dir / "patch.diff").write_text(patch, encoding="utf-8")

        status = run_git(checkout, "status", "--porcelain=v1").stdout
        (run_dir / "status.txt").write_text(status, encoding="utf-8")

        scoring = score_workspace(
            task,
            checkout,
            agent_exit_code=native.exit_code,
            timed_out=native.timed_out,
            raw_stdout=native.stdout,
        )

        receipt = {
            "schema_version": "0.1.0",
            "task_id": task.task_id,
            "agent": args.agent,
            "repository": task.repository,
            "base_commit": task.base_commit,
            "prompt_sha256": sha256_bytes(prompt_bytes),
            "agent_version": native.version,
            "model_request": args.model,
            "command": list(native.command),
            "pid": native.pid,
            "agent_exit_code": native.exit_code,
            "timed_out": native.timed_out,
            "duration_seconds": round(native.duration_seconds, 6),
            "final_head": scoring["final_head"],
            "changed_paths": scoring["changed_paths"],
            "hard_gates": scoring["hard_gates"],
            "pass": scoring["pass"],
            "artifacts": {
                "stdout": "stdout.jsonl",
                "stderr": "stderr.txt",
                "patch": "patch.diff",
                "status": "status.txt",
            },
            "runner": "native_cli_v0",
            "runner_limitations": [
                "No LLM judge is used.",
                "Claude native mode does not mechanically block all child-process network access.",
                "Model identity is fully frozen only when --model is supplied.",
            ],
        }
        write_receipt(run_dir / "result.json", receipt)
        print(json.dumps(receipt, indent=2))
        return 0 if receipt["pass"] else 1
    finally:
        if args.keep_workspace:
            print(f"WORKSPACE_PRESERVED={checkout}", file=sys.stderr)
        else:
            cleanup_workspace(checkout)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qntyageval")
    sub = p.add_subparsers(dest="command", required=True)

    default_task = "tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json"

    d = sub.add_parser("doctor")
    d.add_argument("--task", default=default_task)
    d.add_argument("--source-repo", required=True)
    d.set_defaults(func=doctor)

    r = sub.add_parser("run")
    r.add_argument("--task", default=default_task)
    r.add_argument("--agent", required=True, choices=["claude", "codex"])
    r.add_argument("--source-repo", required=True)
    r.add_argument("--model")
    r.add_argument("--timeout", type=int, default=1800)
    r.add_argument("--max-turns", type=int, default=40)
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--keep-workspace", action="store_true")
    r.set_defaults(func=run)

    return p


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
