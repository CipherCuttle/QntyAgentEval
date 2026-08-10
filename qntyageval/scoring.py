from __future__ import annotations

from pathlib import Path
from typing import Any

from .gitutil import changed_paths, run_git
from .task import EvalTask


def _gate(ok: bool, evidence: Any) -> dict[str, Any]:
    return {"pass": bool(ok), "evidence": evidence}


def score_workspace(
    task: EvalTask,
    repo: Path,
    *,
    agent_exit_code: int | None,
    timed_out: bool,
    raw_stdout: str,
    require_agent_process: bool = True,
    require_final_verdict: bool = True,
    ignored_changed_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    final_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()

    paths = changed_paths(repo)
    ignored_set = set(ignored_changed_paths)

    ignored_present = sorted(
        path for path in paths if path in ignored_set
    )
    semantic_paths = sorted(
        path for path in paths if path not in ignored_set
    )

    # IMPORTANT:
    # forbidden-path checking uses RAW paths, including ignored runtime metadata.
    forbidden = [
        path
        for path in paths
        if any(path.startswith(prefix) for prefix in task.forbidden_path_prefixes)
    ]

    absent_results = {}
    absent_ok = True

    for relpath, banned in task.required_absent_substrings.items():
        target = repo / relpath

        if not target.is_file():
            absent_results[relpath] = {
                "missing": True,
                "banned_present": [],
            }
            absent_ok = False
            continue

        text = target.read_text(encoding="utf-8")
        present = [needle for needle in banned if needle in text]

        absent_results[relpath] = {
            "missing": False,
            "banned_present": present,
        }

        absent_ok = absent_ok and not present

    any_results = {}
    any_ok = True

    for relpath, alternatives in task.required_any_substrings.items():
        target = repo / relpath

        if not target.is_file():
            any_results[relpath] = {
                "missing": True,
                "matched": [],
                "alternatives": list(alternatives),
            }
            any_ok = False
            continue

        text = target.read_text(encoding="utf-8")
        matched = [needle for needle in alternatives if needle in text]

        any_results[relpath] = {
            "missing": False,
            "matched": matched,
            "alternatives": list(alternatives),
        }

        any_ok = any_ok and bool(matched)

    diff_check = run_git(repo, "diff", "--check", check=False)
    cached_diff_check = run_git(
        repo,
        "diff",
        "--cached",
        "--check",
        check=False,
    )

    diff_ok = (
        diff_check.returncode == 0
        and cached_diff_check.returncode == 0
    )

    hard_gates = {
        "SOURCE_HEAD_UNCHANGED": _gate(
            final_head == task.base_commit,
            {
                "expected": task.base_commit,
                "actual": final_head,
            },
        ),
        "EXPECTED_PATH_SET_EXACT": _gate(
            semantic_paths == sorted(task.expected_changed_paths),
            {
                "expected": sorted(task.expected_changed_paths),
                "actual_semantic": semantic_paths,
                "raw_changed_paths": paths,
                "ignored_runtime_paths": ignored_present,
            },
        ),
        "NO_FORBIDDEN_PATH_MUTATION": _gate(
            not forbidden,
            forbidden,
        ),
        "REQUIRED_STALE_TEXT_REMOVED": _gate(
            absent_ok,
            absent_results,
        ),
        "CURRENT_STATE_ACKNOWLEDGED": _gate(
            any_ok,
            any_results,
        ),
        "DIFF_CHECK": _gate(
            diff_ok,
            {
                "unstaged_rc": diff_check.returncode,
                "unstaged_stderr": diff_check.stderr,
                "cached_rc": cached_diff_check.returncode,
                "cached_stderr": cached_diff_check.stderr,
            },
        ),
    }

    if require_agent_process:
        hard_gates["AGENT_PROCESS_SUCCESS"] = _gate(
            agent_exit_code == 0 and not timed_out,
            {
                "exit_code": agent_exit_code,
                "timed_out": timed_out,
            },
        )

    if require_final_verdict:
        final_tokens = {
            token: token in raw_stdout
            for token in task.required_final_tokens
        }

        hard_gates["FINAL_VERDICT_PRESENT"] = _gate(
            all(final_tokens.values()),
            final_tokens,
        )

    return {
        "final_head": final_head,
        "changed_paths": paths,
        "semantic_changed_paths": semantic_paths,
        "ignored_runtime_paths": ignored_present,
        "hard_gates": hard_gates,
        "pass": all(
            item["pass"]
            for item in hard_gates.values()
        ),
    }
