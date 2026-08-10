from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fixture import FixtureBaseline, prepare_fixture_workspace, score_fixture_workspace
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


def _run_id(task_id: str, suffix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_{task_id}_{suffix}"


def _write_repo_artifacts(repo: Path, run_dir: Path) -> None:
    diff = run_git(repo, "diff", "--binary", "HEAD", check=False)
    cached = run_git(repo, "diff", "--cached", "--binary", "HEAD", check=False)

    (run_dir / "patch.diff").write_text(
        diff.stdout + cached.stdout,
        encoding="utf-8",
    )

    status = run_git(
        repo,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--ignored=matching",
        check=False,
    ).stdout
    (run_dir / "status.txt").write_text(status, encoding="utf-8")



def _capture_runtime_artifacts(
    repo: Path,
    run_dir: Path,
    relative_paths: tuple[str, ...],
) -> dict:
    captured = {}

    for relpath in relative_paths:
        source = repo / relpath

        if not source.is_file():
            continue

        destination = run_dir / "runtime_artifacts" / relpath
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

        captured[relpath] = {
            "artifact": str(destination.relative_to(run_dir)),
            "sha256": sha256_bytes(source.read_bytes()),
        }

    return captured


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
            [
                "git",
                "-C",
                str(source),
                "cat-file",
                "-e",
                f"{task.base_commit}^{{commit}}",
            ],
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
    try:
        fixture_baseline = prepare_fixture_workspace(task, checkout)
    except Exception:
        cleanup_workspace(checkout)
        raise

    run_id = _run_id(task.task_id, args.agent)
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

        (run_dir / "stdout.jsonl").write_text(
            native.stdout,
            encoding="utf-8",
        )
        (run_dir / "stderr.txt").write_text(
            native.stderr,
            encoding="utf-8",
        )

        _write_repo_artifacts(checkout, run_dir)

        if fixture_baseline is not None:
            scoring = score_fixture_workspace(
                task, checkout, fixture_baseline,
                agent_exit_code=native.exit_code,
                timed_out=native.timed_out,
            )
        else:
            scoring = score_workspace(
                task,
                checkout,
                agent_exit_code=native.exit_code,
                timed_out=native.timed_out,
                raw_stdout=native.stdout,
                require_agent_process=True,
                require_final_verdict=True,
                ignored_changed_paths=(),
            )

        if native.timed_out:
            evaluation_status = "RUNNER_TIMEOUT"
            task_pass = None
        elif native.exit_code != 0:
            evaluation_status = "RUNNER_FAILURE"
            task_pass = None
        else:
            evaluation_status = "COMPLETED"
            task_pass = scoring["pass"]

        receipt = {
            "schema_version": "0.1.2",
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
            "evaluation_status": evaluation_status,
            "task_pass": task_pass,
            "final_head": scoring["final_head"],
            "changed_paths": scoring["changed_paths"],
            "semantic_changed_paths": scoring["semantic_changed_paths"],
            "ignored_runtime_paths": scoring.get("ignored_runtime_paths", []),
            "hard_gates": scoring["hard_gates"],
            "pass": bool(task_pass) if task_pass is not None else False,
            "artifacts": {
                "stdout": "stdout.jsonl",
                "stderr": "stderr.txt",
                "patch": "patch.diff",
                "status": "status.txt",
            },
            "runner": "native_cli_v0r2",
            "runner_limitations": [
                "No LLM judge is used.",
                "Native Claude mode does not mechanically block every possible child-process network call.",
                "Model identity is fully frozen only when --model is supplied.",
            ],
        }

        write_receipt(run_dir / "result.json", receipt)
        print(json.dumps(receipt, indent=2))

        if evaluation_status != "COMPLETED":
            return 2

        return 0 if task_pass else 1

    finally:
        if args.keep_workspace:
            print(f"WORKSPACE_PRESERVED={checkout}", file=sys.stderr)
        else:
            cleanup_workspace(checkout)


def prepare(args: argparse.Namespace) -> int:
    task_file = Path(args.task).resolve()
    task = load_task(task_file)

    checkout = prepare_workspace(task, args.source_repo)

    run_id = _run_id(task.task_id, f"{args.agent}_interactive")
    runs_dir = Path(args.runs_dir).resolve()
    run_dir = runs_dir / run_id

    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        fixture_baseline = prepare_fixture_workspace(task, checkout)

        prompt_bytes = task.prompt_path.read_bytes()
        prompt_file = run_dir / "prompt.md"
        prompt_file.write_bytes(prompt_bytes)

        prepared = {
            "schema_version": "0.1.2",
            "run_id": run_id,
            "mode": "interactive",
            "agent": args.agent,
            "repository": task.repository,
            "task_id": task.task_id,
            "task_file": str(task_file),
            "base_commit": task.base_commit,
            "prompt_sha256": sha256_bytes(prompt_bytes),
            "prompt_file": str(prompt_file),
            "workspace": str(checkout),
            "fixture_baseline": (
                fixture_baseline.as_dict() if fixture_baseline is not None else None
            ),
        }

        write_receipt(run_dir / "prepared.json", prepared)

        print(json.dumps(prepared, indent=2))
        return 0

    except Exception:
        cleanup_workspace(checkout)
        raise


def score(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir).resolve()
    run_dir = runs_dir / args.run_id

    prepared_file = run_dir / "prepared.json"
    if not prepared_file.is_file():
        raise SystemExit(f"prepared run not found: {prepared_file}")

    prepared = json.loads(prepared_file.read_text(encoding="utf-8"))

    if prepared.get("mode") != "interactive":
        raise SystemExit("score only accepts an interactive prepared run")

    checkout = Path(prepared["workspace"]).resolve()
    task = load_task(prepared["task_file"])

    if task.task_id != prepared["task_id"]:
        raise SystemExit("prepared task identity mismatch")

    if task.base_commit != prepared["base_commit"]:
        raise SystemExit("prepared base commit mismatch")

    if not checkout.is_dir():
        raise SystemExit(f"prepared workspace no longer exists: {checkout}")

    try:
        _write_repo_artifacts(checkout, run_dir)

        ignored_runtime_paths = (
            (".claude/settings.local.json",)
            if prepared["agent"] == "claude"
            else ()
        )

        runtime_artifacts = _capture_runtime_artifacts(
            checkout,
            run_dir,
            ignored_runtime_paths,
        )

        if prepared.get("fixture_baseline") is not None:
            scoring = score_fixture_workspace(
                task,
                checkout,
                FixtureBaseline.from_dict(prepared["fixture_baseline"]),
                ignored_changed_paths=ignored_runtime_paths,
            )
        else:
            scoring = score_workspace(
                task,
                checkout,
                agent_exit_code=None,
                timed_out=False,
                raw_stdout="",
                require_agent_process=False,
                require_final_verdict=False,
                ignored_changed_paths=ignored_runtime_paths,
            )

        receipt = {
            "schema_version": "0.1.2",
            "task_id": task.task_id,
            "agent": prepared["agent"],
            "repository": task.repository,
            "base_commit": task.base_commit,
            "prompt_sha256": prepared["prompt_sha256"],
            "agent_version": _command_version(prepared["agent"]),
            "model_request": None,
            "command": None,
            "pid": None,
            "agent_exit_code": None,
            "timed_out": False,
            "duration_seconds": 0.0,
            "evaluation_status": "COMPLETED",
            "task_pass": scoring["pass"],
            "final_head": scoring["final_head"],
            "changed_paths": scoring["changed_paths"],
            "semantic_changed_paths": scoring["semantic_changed_paths"],
            "ignored_runtime_paths": scoring.get("ignored_runtime_paths", []),
            "hard_gates": scoring["hard_gates"],
            "pass": scoring["pass"],
            "artifacts": {
                "prompt": "prompt.md",
                "patch": "patch.diff",
                "status": "status.txt",
                "prepared": "prepared.json",
            },
            "runtime_artifacts": runtime_artifacts,
            "runner": "interactive_manual_v0r2",
            "runner_limitations": [
                "No LLM judge is used.",
                "Interactive session duration/tool telemetry is not captured in V0R1.",
                "Interactive Claude can invoke tools outside the harness process boundary; task instructions remain part of the frozen fixture.",
                "Final prose verdict is telemetry, not a hard gate in interactive mode.",
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

    prep = sub.add_parser("prepare")
    prep.add_argument("--task", default=default_task)
    prep.add_argument("--agent", default="claude", choices=["claude", "codex"])
    prep.add_argument("--source-repo", required=True)
    prep.add_argument("--runs-dir", default="runs")
    prep.set_defaults(func=prepare)

    s = sub.add_parser("score")
    s.add_argument("--run-id", required=True)
    s.add_argument("--runs-dir", default="runs")
    s.add_argument("--keep-workspace", action="store_true")
    s.set_defaults(func=score)

    return p


def main() -> int:
    args = parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
