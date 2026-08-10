"""Trusted, non-executing GitHub-Issues remote evaluator for Fixture 001."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .gitutil import run_git
from .scoring import score_workspace
from .task import load_task
from .workspace import cleanup_workspace, prepare_workspace

REQUEST_SENTINEL = "QNTY_EVAL_REQUEST_V0"
RESULT_SENTINEL = "QNTY_EVAL_RESULT_V0"
REQUEST_SCHEMA = "0.1.0"
RESULT_SCHEMA = "0.1.0"
TASK_ID = "QNTY_ADMIN_STALE_CONTEXT_001"
TARGET_REPO = "CipherCuttle/Qnty"
ISSUE_TITLE = "QntyAgentEval evaluation request"
V1_ISSUE_TITLE = "QntyAgentEval sandbox evaluation request"
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
ALLOWED_REQUEST_FIELDS = {"schema_version", "task_id", "target_repo", "target_sha"}
V1_REQUEST_SENTINEL = "QNTY_EVAL_REQUEST_V1"
V1_RESULT_SENTINEL = "QNTY_EVAL_RESULT_V1"
V1_REQUEST_SCHEMA = "0.2.0"
V1_RESULT_SCHEMA = "0.2.0"
V1_OPERATION = "QNTY_SANDBOX_EXECUTION_SMOKE_V1"
V1_CONTROL_COMMIT = "3a54f4e7f0fb8c510033ce780267b539949d30b7"
V1_ALLOWED_REQUEST_FIELDS = {"schema_version", "operation", "target_repo", "target_sha"}


class RequestError(ValueError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _strict_object(text: str) -> dict[str, Any]:
    seen: set[str] = set()

    def pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError(f"duplicate field: {key}")
            seen.add(key)
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise ValueError("request JSON must be an object")
    return value


def parse_request(title: str, body: str) -> dict[str, str]:
    if title != ISSUE_TITLE:
        raise RequestError("INVALID_REQUEST", "issue title is not the exact V0 title")
    lines = body.splitlines()
    if len(lines) != 2 or lines[0] != REQUEST_SENTINEL:
        raise RequestError("INVALID_REQUEST", "invalid request envelope")
    try:
        request = _strict_object(lines[1])
    except (json.JSONDecodeError, ValueError) as exc:
        raise RequestError("INVALID_REQUEST", str(exc)) from exc
    if set(request) != ALLOWED_REQUEST_FIELDS:
        raise RequestError("INVALID_REQUEST", "request fields are not exact")
    if request.get("schema_version") != REQUEST_SCHEMA:
        raise RequestError("INVALID_REQUEST", "unsupported request schema")
    if request.get("task_id") != TASK_ID:
        raise RequestError("UNSUPPORTED_TASK", "task is not enabled for remote V0")
    if request.get("target_repo") != TARGET_REPO:
        raise RequestError("INVALID_REQUEST", "target repository is not allowlisted")
    target_sha = request.get("target_sha")
    if not isinstance(target_sha, str) or not SHA_RE.fullmatch(target_sha):
        raise RequestError("INVALID_REQUEST", "target_sha must be a full 40-character SHA")
    return {
        "schema_version": REQUEST_SCHEMA,
        "task_id": TASK_ID,
        "target_repo": TARGET_REPO,
        "target_sha": target_sha.lower(),
    }


def parse_request_v1(title: str, body: str) -> dict[str, str]:
    if title != V1_ISSUE_TITLE:
        raise RequestError("INVALID_REQUEST", "issue title is not the exact V1 title")
    lines = body.splitlines()
    if len(lines) != 2 or lines[0] != V1_REQUEST_SENTINEL:
        raise RequestError("INVALID_REQUEST", "invalid request envelope")
    try:
        request = _strict_object(lines[1])
    except (json.JSONDecodeError, ValueError) as exc:
        raise RequestError("INVALID_REQUEST", str(exc)) from exc
    if set(request) != V1_ALLOWED_REQUEST_FIELDS:
        raise RequestError("INVALID_REQUEST", "request fields are not exact")
    if request.get("schema_version") != V1_REQUEST_SCHEMA:
        raise RequestError("INVALID_REQUEST", "unsupported request schema")
    if request.get("operation") != V1_OPERATION:
        raise RequestError("UNSUPPORTED_OPERATION", "operation is not enabled for remote V1")
    if request.get("target_repo") != TARGET_REPO:
        raise RequestError("INVALID_REQUEST", "target repository is not allowlisted")
    target_sha = request.get("target_sha")
    if not isinstance(target_sha, str) or not SHA_RE.fullmatch(target_sha):
        raise RequestError("INVALID_REQUEST", "target_sha must be a full 40-character SHA")
    return {"schema_version": V1_REQUEST_SCHEMA, "operation": V1_OPERATION, "target_repo": TARGET_REPO, "target_sha": target_sha.lower()}


def make_result_v1(*, request_issue: int, request: dict[str, str], evaluation_status: str,
                   task_pass: bool | None, sandbox_evidence: dict[str, Any], evaluator_commit: str) -> dict[str, Any]:
    return {
        "schema_version": V1_RESULT_SCHEMA, "request_issue": request_issue,
        "operation": request.get("operation"), "target_repo": request.get("target_repo"),
        "target_sha": request.get("target_sha"), "evaluation_status": evaluation_status,
        "task_pass": task_pass, "evaluator_commit": evaluator_commit,
        "sandbox_backend": "inspect/docker", "sandbox_evidence": sandbox_evidence,
    }


def comment_for_v1(result: dict[str, Any]) -> str:
    status = result["evaluation_status"]
    summary = (f"{'PASS' if result['task_pass'] else 'FAIL'} — sandbox operation completed"
               if status == "COMPLETED" else f"EVALUATION COULD NOT BE PERFORMED — {status}")
    return f"{summary}\n\n{V1_RESULT_SENTINEL}\n```json\n{json.dumps(result, sort_keys=True, indent=2)}\n```\n"


def evaluate_v1_request(request: dict[str, str], evaluator_repo: str | Path, issue_number: int) -> dict[str, Any]:
    clone_root = Path(tempfile.mkdtemp(prefix="qntyageval-target-", dir="/tmp"))
    source = clone_root / "repo"
    try:
        subprocess.run(["git", "clone", "--no-checkout", "--no-tags", f"https://github.com/{TARGET_REPO}.git", str(source)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        from .inspect_adapter import interpret_observation, run_inspect_smoke, validate_control_commit
        validate_control_commit(source, request["target_sha"])
        canary_dir = Path(tempfile.mkdtemp(prefix="qntyageval-canary-", dir="/tmp"))
        canary = canary_dir / "HOST_ONLY_CANARY"
        canary.write_text("HOST_ONLY_CANARY\n", encoding="utf-8")
        try:
            evidence = run_inspect_smoke(source, request["target_sha"], canary)
        finally:
            shutil.rmtree(canary_dir, ignore_errors=True)
        status, passed = interpret_observation(evidence)
        return make_result_v1(request_issue=issue_number, request=request, evaluation_status=status, task_pass=passed if status == "COMPLETED" else None, sandbox_evidence={k: evidence[k] for k in ("operation_id", "exit_code", "expected_observation", "host_canary_unchanged", "target_sha") if k in evidence}, evaluator_commit=run_git(Path(evaluator_repo), "rev-parse", "HEAD").stdout.strip())
    finally:
        shutil.rmtree(clone_root, ignore_errors=True)


def materialize_completed_work(task: Any, source_repo: str | Path, target_sha: str) -> Path:
    """Present target_sha as uncommitted changes on task.base_commit."""
    if not SHA_RE.fullmatch(target_sha):
        raise RequestError("INVALID_REQUEST", "target SHA is not full length")
    source = Path(source_repo).resolve()
    target_exists = subprocess.run(
        ["git", "-C", str(source), "cat-file", "-e", f"{target_sha}^{{commit}}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if target_exists.returncode != 0:
        raise RequestError("TARGET_NOT_FOUND", "target commit is unavailable")
    base_exists = subprocess.run(
        ["git", "-C", str(source), "cat-file", "-e", f"{task.base_commit}^{{commit}}"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if base_exists.returncode != 0:
        raise RequestError("BASE_NOT_ANCESTOR_OR_INCOMPATIBLE", "task base is unavailable")
    ancestry = subprocess.run(
        ["git", "-C", str(source), "merge-base", "--is-ancestor", task.base_commit, target_sha],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if ancestry.returncode != 0:
        raise RequestError("BASE_NOT_ANCESTOR_OR_INCOMPATIBLE", "target is not derived from task base")
    tree = run_git(source, "ls-tree", "-r", "-z", target_sha).stdout
    for entry in tree.split("\0"):
        if not entry:
            continue
        mode, remainder = entry.split(" ", 1)
        if mode in {"120000", "160000"}:
            raise RequestError("EVALUATOR_ERROR", "target tree contains a symlink or submodule")

    checkout = prepare_workspace(task, source)
    try:
        run_git(checkout, "read-tree", "--reset", "-u", target_sha)
        if run_git(checkout, "rev-parse", "HEAD").stdout.strip() != task.base_commit:
            raise RuntimeError("materialized checkout HEAD changed")
        return checkout
    except Exception:
        cleanup_workspace(checkout)
        raise


def evaluate_request(request: dict[str, str], evaluator_repo: str | Path, issue_number: int) -> dict[str, Any]:
    task_path = Path(evaluator_repo) / "tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json"
    task = load_task(task_path)
    clone_root = Path(tempfile.mkdtemp(prefix="qntyageval-target-", dir="/tmp"))
    owned_source = clone_root / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--no-checkout", "--no-tags", f"https://github.com/{TARGET_REPO}.git", str(owned_source)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except Exception:
        shutil.rmtree(clone_root, ignore_errors=True)
        raise
    source = owned_source
    checkout: Path | None = None
    try:
        checkout = materialize_completed_work(task, source, request["target_sha"])
        scoring = score_workspace(
            task, checkout, agent_exit_code=None, timed_out=False, raw_stdout="",
            require_agent_process=False, require_final_verdict=False,
        )
        return make_result(
            request_issue=issue_number, request=request, base_commit=task.base_commit,
            evaluation_status="COMPLETED", task_pass=scoring["pass"],
            hard_gates=scoring["hard_gates"], changed_paths=scoring["changed_paths"],
            evaluator_commit=run_git(Path(evaluator_repo), "rev-parse", "HEAD").stdout.strip(),
        )
    finally:
        if checkout is not None:
            cleanup_workspace(checkout)
        shutil.rmtree(owned_source.parent, ignore_errors=True)


def make_result(*, request_issue: int, request: dict[str, str], base_commit: str | None,
                evaluation_status: str, task_pass: bool | None, hard_gates: dict[str, Any],
                changed_paths: list[str], evaluator_commit: str) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA, "request_issue": request_issue,
        "task_id": request.get("task_id"), "target_repo": request.get("target_repo"),
        "target_sha": request.get("target_sha"), "base_commit": base_commit,
        "evaluation_status": evaluation_status, "task_pass": task_pass,
        "hard_gates": hard_gates, "changed_paths": changed_paths,
        "evaluator_commit": evaluator_commit,
    }


def comment_for(result: dict[str, Any]) -> str:
    status = result["evaluation_status"]
    if status == "COMPLETED":
        passed = [g for g in result["hard_gates"].values() if g.get("pass")]
        total = len(result["hard_gates"])
        summary = f"{'PASS' if result['task_pass'] else 'FAIL'} — {len(passed)}/{total} hard gates"
    else:
        summary = f"EVALUATION COULD NOT BE PERFORMED — {status}"
    return f"{summary}\n\n{RESULT_SENTINEL}\n```json\n{json.dumps(result, sort_keys=True, indent=2)}\n```\n"


def _event_result(event_path: Path, evaluator_repo: Path) -> dict[str, Any]:
    title = ""
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
        issue = event.get("issue") if isinstance(event, dict) else None
        issue_number = issue.get("number") if isinstance(issue, dict) else None
        title = issue.get("title") if isinstance(issue, dict) else ""
        body = issue.get("body") if isinstance(issue, dict) else ""
        if not isinstance(issue_number, int) or issue_number < 1:
            raise RequestError("INVALID_REQUEST", "issue number is invalid")
        if title == V1_ISSUE_TITLE:
            request = parse_request_v1(title, body or "")
            return evaluate_v1_request(request, evaluator_repo, issue_number)
        request = parse_request(title, body or "")
        return evaluate_request(request, evaluator_repo, issue_number)
    except RequestError as exc:
        if title == V1_ISSUE_TITLE:
            return make_result_v1(
                request_issue=int(issue_number) if isinstance(issue_number, int) else 0,
                request={"operation": None, "target_repo": None, "target_sha": None},
                evaluation_status=exc.status, task_pass=None, sandbox_evidence={"REQUEST_VALID": False, "evidence": str(exc)},
                evaluator_commit=run_git(evaluator_repo, "rev-parse", "HEAD").stdout.strip(),
            )
        return make_result(
            request_issue=int(issue_number) if isinstance(issue_number, int) else 0,
            request={"task_id": None, "target_repo": None, "target_sha": None},
            base_commit=None, evaluation_status=exc.status, task_pass=None,
            hard_gates={"REQUEST_VALID": {"pass": False, "evidence": str(exc)}},
            changed_paths=[], evaluator_commit=run_git(evaluator_repo, "rev-parse", "HEAD").stdout.strip(),
        )
    except Exception as exc:
        if title == V1_ISSUE_TITLE:
            return make_result_v1(
                request_issue=int(issue_number) if isinstance(issue_number, int) else 0,
                request={"operation": None, "target_repo": None, "target_sha": None},
                evaluation_status="EVALUATOR_ERROR", task_pass=None,
                sandbox_evidence={"evaluator_error": str(exc)},
                evaluator_commit=run_git(evaluator_repo, "rev-parse", "HEAD").stdout.strip(),
            )
        return make_result(
            request_issue=int(issue_number) if isinstance(issue_number, int) else 0,
            request={"task_id": None, "target_repo": None, "target_sha": None},
            base_commit=None, evaluation_status="EVALUATOR_ERROR", task_pass=None,
            hard_gates={"EVALUATOR_ERROR": {"pass": False, "evidence": str(exc)}},
            changed_paths=[], evaluator_commit=run_git(evaluator_repo, "rev-parse", "HEAD").stdout.strip(),
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = _event_result(args.event, Path.cwd())
    args.output.write_text(comment_for(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
