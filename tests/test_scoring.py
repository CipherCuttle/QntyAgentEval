import subprocess
from pathlib import Path

from qntyageval.scoring import score_workspace
from qntyageval.task import load_task


ROOT = Path(__file__).parents[1]
TASK = load_task(ROOT / "tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json")


def git(repo: Path, *args: str):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "docs/control").mkdir(parents=True)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- Python >=3.10; no CI; no linter configured.\n",
        encoding="utf-8",
    )
    (repo / "docs/control/active_task.json").write_text("{}", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    return repo


def with_fixture_commit(task, repo):
    from dataclasses import replace
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    return replace(task, base_commit=sha)


def test_known_good_edit_passes(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- Python >=3.10; GitHub Actions CI is configured; no linter configured.\n",
        encoding="utf-8",
    )
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="VERDICT READY_FOR_REVIEW",
    )
    assert result["pass"] is True


def test_extra_file_fails(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- Python >=3.10; GitHub Actions CI is configured; no linter configured.\n",
        encoding="utf-8",
    )
    (repo / "oops.txt").write_text("scope creep", encoding="utf-8")
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="READY_FOR_REVIEW",
    )
    assert result["pass"] is False
    assert result["hard_gates"]["EXPECTED_PATH_SET_EXACT"]["pass"] is False


def test_stale_claim_fails(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- no CI, but GitHub Actions exists.\n",
        encoding="utf-8",
    )
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="READY_FOR_REVIEW",
    )
    assert result["pass"] is False
    assert result["hard_gates"]["REQUIRED_STALE_TEXT_REMOVED"]["pass"] is False


def test_missing_final_verdict_fails(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="done",
    )
    assert result["pass"] is False
    assert result["hard_gates"]["FINAL_VERDICT_PRESENT"]["pass"] is False


def test_deleted_required_file_fails_closed(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").unlink()
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="READY_FOR_REVIEW",
    )
    assert result["pass"] is False
    assert result["hard_gates"]["REQUIRED_STALE_TEXT_REMOVED"]["pass"] is False
    assert result["hard_gates"]["CURRENT_STATE_ACKNOWLEDGED"]["pass"] is False


def test_ignored_artifact_is_still_scope_violation(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / ".gitignore").write_text("generated/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore generated")
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )
    (repo / "generated").mkdir()
    (repo / "generated/side-effect.txt").write_text("unexpected", encoding="utf-8")
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="READY_FOR_REVIEW",
    )
    assert result["pass"] is False
    assert "generated/" in result["changed_paths"] or any(
        p.startswith("generated/") for p in result["changed_paths"]
    )


def test_committing_the_change_fails_source_head_gate(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)
    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-m", "agent should not commit")
    result = score_workspace(
        task,
        repo,
        agent_exit_code=0,
        timed_out=False,
        raw_stdout="READY_FOR_REVIEW",
    )
    assert result["pass"] is False
    assert result["hard_gates"]["SOURCE_HEAD_UNCHANGED"]["pass"] is False
