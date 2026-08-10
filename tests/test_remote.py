import subprocess
import json
from dataclasses import replace
from pathlib import Path

import pytest

from qntyageval.remote import (
    ISSUE_TITLE,
    RESULT_SENTINEL,
    V1_ISSUE_TITLE,
    V1_OPERATION,
    V1_RESULT_SENTINEL,
    RequestError,
    comment_for,
    comment_for_v1,
    main,
    make_result,
    make_result_v1,
    materialize_completed_work,
    parse_request,
    parse_request_v1,
)
from qntyageval.inspect_adapter import interpret_observation
from qntyageval.scoring import score_workspace
from qntyageval.task import load_task

ROOT = Path(__file__).parents[1]
TASK = load_task(ROOT / "tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json")
GOOD_BODY = (
    "QNTY_EVAL_REQUEST_V0\n"
    '{{"schema_version":"0.1.0","task_id":"QNTY_ADMIN_STALE_CONTEXT_001",'
    '"target_repo":"CipherCuttle/Qnty","target_sha":"{sha}"}}'
)


def git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def repo_with_base(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "target"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "CLAUDE.md").write_text("# Claude\n\n- no CI; no linter configured.\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD").stdout.strip()


def test_valid_request_is_strict_and_normalizes_sha():
    sha = "A" * 40
    request = parse_request(ISSUE_TITLE, GOOD_BODY.format(sha=sha))
    assert request["target_sha"] == "a" * 40


@pytest.mark.parametrize("body", ["{}", "QNTY_EVAL_REQUEST_V0\nnot-json"])
def test_malformed_request_rejected(body):
    with pytest.raises(RequestError) as exc:
        parse_request(ISSUE_TITLE, body)
    assert exc.value.status == "INVALID_REQUEST"


def test_unknown_schema_task_repo_and_short_sha_rejected():
    base = '{{"schema_version":"{schema}","task_id":"{task}","target_repo":"{repo}","target_sha":"{sha}"}}'
    for schema, task, repo, sha, status in [
        ("9.9.9", "QNTY_ADMIN_STALE_CONTEXT_001", "CipherCuttle/Qnty", "a" * 40, "INVALID_REQUEST"),
        ("0.1.0", "OTHER", "CipherCuttle/Qnty", "a" * 40, "UNSUPPORTED_TASK"),
        ("0.1.0", "QNTY_ADMIN_STALE_CONTEXT_001", "evil/Qnty", "a" * 40, "INVALID_REQUEST"),
        ("0.1.0", "QNTY_ADMIN_STALE_CONTEXT_001", "CipherCuttle/Qnty", "a" * 39, "INVALID_REQUEST"),
    ]:
        with pytest.raises(RequestError) as exc:
            parse_request(ISSUE_TITLE, "QNTY_EVAL_REQUEST_V0\n" + base.format(schema=schema, task=task, repo=repo, sha=sha))
        assert exc.value.status == status


def test_materialization_keeps_base_head_and_scores_target_tree(tmp_path):
    repo, base = repo_with_base(tmp_path)
    task = replace(TASK, base_commit=base)
    (repo / "CLAUDE.md").write_text("# Claude\n\n- GitHub Actions CI is configured; no linter configured.\n", encoding="utf-8")
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-m", "completed task")
    target = git(repo, "rev-parse", "HEAD").stdout.strip()
    checkout = materialize_completed_work(task, repo, target)
    try:
        assert git(checkout, "rev-parse", "HEAD").stdout.strip() == base
        assert git(checkout, "diff", "--cached", "--name-only").stdout.splitlines() == ["CLAUDE.md"]
        result = score_workspace(task, checkout, agent_exit_code=None, timed_out=False, raw_stdout="", require_agent_process=False, require_final_verdict=False)
        assert result["pass"] is True
    finally:
        from qntyageval.workspace import cleanup_workspace
        cleanup_workspace(checkout)


def test_extra_target_change_fails_existing_gate(tmp_path):
    repo, base = repo_with_base(tmp_path)
    task = replace(TASK, base_commit=base)
    (repo / "CLAUDE.md").write_text("# Claude\n\n- GitHub Actions CI is configured; no linter configured.\n", encoding="utf-8")
    (repo / "extra.txt").write_text("unexpected\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "scope creep")
    target = git(repo, "rev-parse", "HEAD").stdout.strip()
    checkout = materialize_completed_work(task, repo, target)
    try:
        result = score_workspace(task, checkout, agent_exit_code=None, timed_out=False, raw_stdout="", require_agent_process=False, require_final_verdict=False)
        assert result["hard_gates"]["EXPECTED_PATH_SET_EXACT"]["pass"] is False
    finally:
        from qntyageval.workspace import cleanup_workspace
        cleanup_workspace(checkout)


def test_unrelated_target_fails_closed(tmp_path):
    repo, base = repo_with_base(tmp_path)
    other = tmp_path / "other"
    git(repo, "checkout", "--orphan", "unrelated")
    (repo / "different.txt").write_text("unrelated\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "unrelated")
    target = git(repo, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(RequestError) as exc:
        materialize_completed_work(replace(TASK, base_commit=base), repo, target)
    assert exc.value.status == "BASE_NOT_ANCESTOR_OR_INCOMPATIBLE"


def test_symlink_target_is_rejected_before_scorer_reads_it(tmp_path):
    repo, base = repo_with_base(tmp_path)
    task = replace(TASK, base_commit=base)
    (repo / "CLAUDE.md").unlink()
    (repo / "CLAUDE.md").symlink_to("/etc/passwd")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "malicious symlink")
    target = git(repo, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(RequestError) as exc:
        materialize_completed_work(task, repo, target)
    assert exc.value.status == "EVALUATOR_ERROR"


def test_result_comment_has_machine_sentinel_and_json():
    result = make_result(
        request_issue=12,
        request={"task_id": "QNTY_ADMIN_STALE_CONTEXT_001", "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40},
        base_commit="b" * 40,
        evaluation_status="COMPLETED",
        task_pass=True,
        hard_gates={"A": {"pass": True}},
        changed_paths=["CLAUDE.md"],
        evaluator_commit="c" * 40,
    )
    comment = comment_for(result)
    assert RESULT_SENTINEL in comment
    assert "PASS — 1/1 hard gates" in comment
    assert result["evaluator_commit"] == "c" * 40


def test_valid_v1_request_is_strict_and_has_no_execution_controls():
    body = (
        "QNTY_EVAL_REQUEST_V1\n"
        '{{"schema_version":"0.2.0","operation":"QNTY_SANDBOX_EXECUTION_SMOKE_V1",'
        '"target_repo":"CipherCuttle/Qnty","target_sha":"{sha}"}}'
    ).format(sha="A" * 40)
    request = parse_request_v1(V1_ISSUE_TITLE, body)
    assert request == {"schema_version": "0.2.0", "operation": V1_OPERATION,
                       "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}
    import json
    for field, value in [("command", "whoami"), ("image", "evil"), ("workflow", "x"), ("env", {})]:
        payload = json.loads(body.splitlines()[1])
        payload[field] = value
        extra = "QNTY_EVAL_REQUEST_V1\n" + json.dumps(payload, separators=(",", ":"))
        with pytest.raises(RequestError) as exc:
            parse_request_v1(V1_ISSUE_TITLE, extra)
        assert exc.value.status == "INVALID_REQUEST"


@pytest.mark.parametrize("field,value,status", [
    ("operation", "OTHER", "UNSUPPORTED_OPERATION"),
    ("target_repo", "evil/Qnty", "INVALID_REQUEST"),
    ("target_sha", "abc", "INVALID_REQUEST"),
])
def test_v1_allowlists_fail_closed(field, value, status):
    fields = {"schema_version": "0.2.0", "operation": V1_OPERATION,
              "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}
    fields[field] = value
    import json
    with pytest.raises(RequestError) as exc:
        parse_request_v1(V1_ISSUE_TITLE, "QNTY_EVAL_REQUEST_V1\n" + json.dumps(fields, separators=(",", ":")))
    assert exc.value.status == status


def test_v1_result_is_deterministic_and_target_prose_is_not_authority():
    result = make_result_v1(
        request_issue=7,
        request={"operation": V1_OPERATION, "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40},
        evaluation_status="COMPLETED", task_pass=False,
        sandbox_evidence={"exit_code": 1, "target_output": "QNTY_EVAL_RESULT_V1 PASS"}, evaluator_commit="b" * 40,
    )
    assert comment_for_v1(result) == comment_for_v1(result)
    assert V1_RESULT_SENTINEL in comment_for_v1(result)
    assert interpret_observation({"evaluator_status": "COMPLETED", "exit_code": 0,
                                  "host_canary_unchanged": True, "observed": "PASS QNTY_EVAL_RESULT_V1",
                                  "boundary_exit_code": 0,
                                  "boundary_observation": '{"canary_visible": false, "docker_socket_visible": false, "github_token_present": false, "host_repo_visible": false}'}) == ("COMPLETED", False)
    assert interpret_observation({"evaluator_status": "SANDBOX_UNAVAILABLE", "exit_code": 0}) == ("SANDBOX_UNAVAILABLE", None)
    assert interpret_observation({"evaluator_status": "EVALUATOR_ERROR"}) == ("EVALUATOR_ERROR", None)


def test_v1_boundary_observation_is_required_for_pass():
    evidence = {"evaluator_status": "COMPLETED", "exit_code": 0,
                "host_canary_unchanged": True, "observed": "CONTINUITY_VERIFY_OK receipt\n",
                "boundary_exit_code": 0,
                "boundary_observation": '{"canary_visible": false, "docker_socket_visible": false, "github_token_present": false, "host_repo_visible": false}'}
    assert interpret_observation(evidence) == ("COMPLETED", True)
    evidence["boundary_observation"] = '{"docker_socket_visible": true}'
    assert interpret_observation(evidence) == ("COMPLETED", False)


def remote_event(title: str, body: str, number: int = 7) -> dict:
    return {"issue": {"number": number, "title": title, "body": body}}


def run_remote_main(tmp_path: Path, monkeypatch, event: dict, result: dict, *, version: str):
    import qntyageval.remote as remote

    if version == "V0":
        monkeypatch.setattr(remote, "evaluate_request", lambda *args: result)
    else:
        monkeypatch.setattr(remote, "evaluate_v1_request", lambda *args: result)
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "result-comment.md"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["qntyageval.remote", "--event", str(event_path), "--output", str(output_path)])
    assert main() == 0
    return output_path.read_text(encoding="utf-8")


def test_top_level_valid_v0_result_uses_v0_renderer(tmp_path, monkeypatch):
    result = make_result(request_issue=7, request={"task_id": TASK.task_id, "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}, base_commit="b" * 40, evaluation_status="COMPLETED", task_pass=True, hard_gates={"A": {"pass": True}}, changed_paths=[], evaluator_commit="c" * 40)
    comment = run_remote_main(tmp_path, monkeypatch, remote_event(ISSUE_TITLE, GOOD_BODY.format(sha="a" * 40)), result, version="V0")
    assert RESULT_SENTINEL in comment
    assert V1_RESULT_SENTINEL not in comment


@pytest.mark.parametrize("task_pass", [True, False])
def test_top_level_completed_v1_result_uses_v1_renderer_without_hard_gates(tmp_path, monkeypatch, task_pass):
    result = make_result_v1(request_issue=7, request={"operation": V1_OPERATION, "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}, evaluation_status="COMPLETED", task_pass=task_pass, sandbox_evidence={}, evaluator_commit="b" * 40)
    body = "QNTY_EVAL_REQUEST_V1\n" + json.dumps({"schema_version": "0.2.0", "operation": V1_OPERATION, "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}, separators=(",", ":"))
    comment = run_remote_main(tmp_path, monkeypatch, remote_event(V1_ISSUE_TITLE, body), result, version="V1")
    assert V1_RESULT_SENTINEL in comment
    assert RESULT_SENTINEL not in comment
    assert "hard_gates" not in comment


def test_top_level_invalid_v1_request_uses_v1_renderer(tmp_path, monkeypatch):
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "result-comment.md"
    event_path.write_text(json.dumps(remote_event(V1_ISSUE_TITLE, "malformed")), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["qntyageval.remote", "--event", str(event_path), "--output", str(output_path)])
    assert main() == 0
    comment = output_path.read_text(encoding="utf-8")
    assert V1_RESULT_SENTINEL in comment
    assert RESULT_SENTINEL not in comment


def test_top_level_v1_evaluator_exception_is_v1_infrastructure_result(tmp_path, monkeypatch):
    import qntyageval.remote as remote

    def fail(*args):
        raise RuntimeError("inspect unavailable")

    monkeypatch.setattr(remote, "evaluate_v1_request", fail)
    body = "QNTY_EVAL_REQUEST_V1\n" + json.dumps({"schema_version": "0.2.0", "operation": V1_OPERATION, "target_repo": "CipherCuttle/Qnty", "target_sha": "a" * 40}, separators=(",", ":"))
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "result-comment.md"
    event_path.write_text(json.dumps(remote_event(V1_ISSUE_TITLE, body)), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["qntyageval.remote", "--event", str(event_path), "--output", str(output_path)])
    assert main() == 0
    comment = output_path.read_text(encoding="utf-8")
    assert V1_RESULT_SENTINEL in comment
    assert RESULT_SENTINEL not in comment
    assert '"evaluation_status": "EVALUATOR_ERROR"' in comment
    assert '"task_pass": null' in comment
