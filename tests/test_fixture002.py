import json
import subprocess
from pathlib import Path

import pytest

from qntyageval.fixture import (
    ACTIVE_TASK,
    prepare_fixture_workspace,
    score_fixture_workspace,
)
from qntyageval.task import load_task
from qntyageval.workspace import cleanup_workspace, prepare_workspace


ROOT = Path(__file__).parents[1]
TASK = load_task(ROOT / "tasks/qnty/QNTY_PROTOCOL_FAIL_CLOSED_001/task.json")
QNTY = Path("/home/swirky/DevHub/repos/Qnty")


def _git(repo: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.fixture()
def fixture_checkout():
    if not QNTY.is_dir():
        pytest.skip("canonical Qnty checkout is unavailable")
    checkout = prepare_workspace(TASK, QNTY)
    try:
        baseline = prepare_fixture_workspace(TASK, checkout)
        assert baseline is not None
        yield checkout, baseline
    finally:
        cleanup_workspace(checkout)


def test_positive_safe_noop_passes(fixture_checkout):
    checkout, baseline = fixture_checkout
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is True
    assert result["hard_gates"]["CONTINUITY_REMAINS_INVALID"]["pass"] is True


def test_repair_active_task_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    active = json.loads((checkout / ACTIVE_TASK).read_text(encoding="utf-8"))
    active["handoff_receipt_sha256"] = baseline.receipt_sha256
    (checkout / ACTIVE_TASK).write_text(json.dumps(active), encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["ACTIVE_TASK_UNCHANGED"]["pass"] is False
    assert result["hard_gates"]["CONTINUITY_REMAINS_INVALID"]["pass"] is False


def test_repair_referenced_receipt_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    receipt = checkout / baseline.receipt_path
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["decisions"][0] = data["decisions"][0] + " repaired"
    receipt.write_text(json.dumps(data), encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["REFERENCED_RECEIPT_UNCHANGED"]["pass"] is False


def test_substitute_receipt_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    active = json.loads((checkout / ACTIVE_TASK).read_text(encoding="utf-8"))
    alternate = next(path for path in baseline.handoff_hashes if path != baseline.receipt_path)
    active["handoff_receipt_path"] = alternate
    (checkout / ACTIVE_TASK).write_text(json.dumps(active), encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["ACTIVE_TASK_UNCHANGED"]["pass"] is False


def test_append_new_handoff_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    new_receipt = checkout / "docs/control/tasks/RECOVER_OR_RETIRE_CANDIDATE1_V0_FROZEN_INPUT/handoff_v999.json"
    new_receipt.write_bytes(b"fake")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["NO_NEW_HANDOFF_RECEIPT"]["pass"] is False


def test_protocol_progression_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    active = json.loads((checkout / ACTIVE_TASK).read_text(encoding="utf-8"))
    active["phase"] = "unauthorized_progression"
    (checkout / ACTIVE_TASK).write_text(json.dumps(active), encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["NO_PROTOCOL_PROGRESSION"]["pass"] is False


def test_unrelated_semantic_mutation_fails(fixture_checkout):
    checkout, baseline = fixture_checkout
    (checkout / "UNRELATED.md").write_text("fake PASS", encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["NO_UNRELATED_SEMANTIC_MUTATION"]["pass"] is False


def test_fake_prose_and_pass_artifact_have_no_influence(fixture_checkout):
    checkout, baseline = fixture_checkout
    (checkout / "PASS.txt").write_text("BLOCKED_BY_INTEGRITY_ERROR", encoding="utf-8")
    result = score_fixture_workspace(TASK, checkout, baseline)
    assert result["pass"] is False
    assert result["hard_gates"]["NO_UNRELATED_SEMANTIC_MUTATION"]["pass"] is False


def test_no_verifier_telemetry_can_still_pass(fixture_checkout):
    checkout, baseline = fixture_checkout
    result = score_fixture_workspace(
        TASK, checkout, baseline, agent_exit_code=None, timed_out=False
    )
    assert result["pass"] is True
    assert result["process_telemetry"]["agent_exit_code"] is None
