from pathlib import Path

from qntyageval.task import load_task


ROOT = Path(__file__).parents[1]


def test_first_task_contract_loads():
    task = load_task(
        ROOT / "tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json"
    )
    assert task.task_id == "QNTY_ADMIN_STALE_CONTEXT_001"
    assert task.base_commit == "3a54f4e7f0fb8c510033ce780267b539949d30b7"
    assert task.expected_changed_paths == ("CLAUDE.md",)
