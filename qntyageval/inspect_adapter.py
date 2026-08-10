"""Trusted orchestration for the single bounded Inspect Docker operation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .gitutil import run_git
from .remote import RequestError, SHA_RE, TARGET_REPO, V1_OPERATION, V1_CONTROL_COMMIT


def _safe_target_tree(source: Path, target_sha: str) -> None:
    tree = run_git(source, "ls-tree", "-r", "-z", target_sha).stdout
    for entry in tree.split("\0"):
        if not entry:
            continue
        mode, _ = entry.split(" ", 1)
        if mode in {"120000", "160000"}:
            raise RequestError("TARGET_INCOMPATIBLE", "target tree contains a symlink or submodule")


def validate_control_commit(source: Path, target_sha: str) -> None:
    if not SHA_RE.fullmatch(target_sha):
        raise RequestError("INVALID_REQUEST", "target SHA is not full length")
    for commit in (target_sha, V1_CONTROL_COMMIT):
        if subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise RequestError("TARGET_NOT_FOUND", "target or control commit is unavailable")
    if subprocess.run(["git", "-C", str(source), "merge-base", "--is-ancestor", V1_CONTROL_COMMIT, target_sha], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise RequestError("TARGET_INCOMPATIBLE", "target is not descended from the frozen V1 control commit")
    protected = subprocess.run(
        ["git", "-C", str(source), "diff", "--quiet", V1_CONTROL_COMMIT, target_sha, "--", "quantbot/__init__.py", "quantbot/continuity", "quantbot/assurance", "quantbot/artifacts"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if protected.returncode != 0:
        raise RequestError("TARGET_INCOMPATIBLE", "target changed the frozen continuity operation")
    _safe_target_tree(source, target_sha)


def interpret_observation(evidence: dict[str, Any]) -> tuple[str, bool | None]:
    """Interpret only evaluator-owned process facts, never target prose/files."""
    if evidence.get("evaluator_status") != "COMPLETED":
        return ("SANDBOX_UNAVAILABLE", None)
    passed = (
        evidence.get("exit_code") == 0
        and evidence.get("host_canary_unchanged") is True
        and str(evidence.get("observed", "")).startswith("CONTINUITY_VERIFY_OK")
    )
    return ("COMPLETED", passed)


def run_inspect_smoke(source: Path, target_sha: str, host_canary: Path) -> dict[str, Any]:
    """Build a fixed Inspect Docker task and return only trusted structured evidence."""
    validate_control_commit(source, target_sha)
    root = Path(tempfile.mkdtemp(prefix="qntyageval-inspect-", dir="/tmp"))
    try:
        context = root / "context"
        target = context / "qnty"
        target.mkdir(parents=True)
        archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", target_sha], check=True, stdout=subprocess.PIPE)
        import tarfile
        import io
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
            tar.extractall(target, filter="data")
        (context / "Dockerfile").write_text(
            "FROM python:3.12-slim\nCOPY qnty /qnty\nENV PYTHONPATH=/qnty\nWORKDIR /qnty\n",
            encoding="utf-8",
        )
        (context / "compose.yaml").write_text(
            'services:\n  default:\n    build: .\n    init: true\n    command: ["sleep", "infinity"]\n    network_mode: none\n    read_only: true\n    tmpfs:\n      - /tmp\n',
            encoding="utf-8",
        )
        output = root / "observation.json"
        task = root / "task.py"
        task.write_text(_task_source(output), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(task)], cwd=root, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": ""},
        )
        if proc.returncode != 0:
            return {"operation_id": V1_OPERATION, "exit_code": None, "expected_observation": "CONTINUITY_VERIFY_OK", "evaluator_status": "SANDBOX_UNAVAILABLE", "detail": "Inspect process failed"}
        observation = json.loads(output.read_text(encoding="utf-8"))
        observation["operation_id"] = V1_OPERATION
        observation["expected_observation"] = "CONTINUITY_VERIFY_OK"
        observation["host_canary_unchanged"] = host_canary.read_text(encoding="utf-8") == "HOST_ONLY_CANARY\n"
        observation["target_sha"] = target_sha
        return observation
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
        return {"operation_id": V1_OPERATION, "exit_code": None, "expected_observation": "CONTINUITY_VERIFY_OK", "evaluator_status": "SANDBOX_UNAVAILABLE", "detail": type(exc).__name__}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _task_source(output: Path) -> str:
    return f'''import json
from inspect_ai import Task, eval, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, scorer
from inspect_ai.solver import solver
from inspect_ai.util import sandbox

@solver
def fixed_probe():
    async def solve(state, generate):
        return state
    return solve

@scorer(metrics=[])
def record_probe():
    async def score(state, target):
        result = await sandbox().exec(["python", "-S", "-m", "quantbot.continuity", "verify", "--root", "/qnty"], timeout=30)
        probe = {{"exit_code": result.returncode, "stdout": result.stdout[-512:], "stderr": result.stderr[-512:]}}
        return Score(value=probe["exit_code"] == 0, metadata={{"probe": probe}})
    return score

@task
def smoke():
    return Task(dataset=[Sample(input="fixed infrastructure probe")], solver=fixed_probe(), scorer=record_probe(), sandbox=("docker", "{(output.parent / "context" / "compose.yaml").as_posix()}"))

logs = eval(smoke(), display="none", sandbox_cleanup=True, log_dir="{output.parent.as_posix()}")
log = logs[0]
sample = log.samples[0] if log.samples else None
score = sample.score if sample else None
probe = score.metadata["probe"] if score and score.metadata and "probe" in score.metadata else {{}}
json.dump({{"exit_code": probe.get("exit_code"), "observed": probe.get("stdout", ""), "stderr": probe.get("stderr", ""), "evaluator_status": "COMPLETED" if str(log.status).lower() == "success" else "EVALUATOR_ERROR", "log_error": str(log.error) if log.error else ""}}, open("{output.as_posix()}", "w"))
'''
