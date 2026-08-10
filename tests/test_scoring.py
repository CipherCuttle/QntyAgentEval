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


def test_interactive_scoring_uses_semantic_gates_only(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)

    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )

    result = score_workspace(
        task,
        repo,
        agent_exit_code=None,
        timed_out=False,
        raw_stdout="",
        require_agent_process=False,
        require_final_verdict=False,
    )

    assert result["pass"] is True
    assert "AGENT_PROCESS_SUCCESS" not in result["hard_gates"]
    assert "FINAL_VERDICT_PRESENT" not in result["hard_gates"]


def test_exact_claude_runtime_metadata_can_be_excluded_from_semantic_paths(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)

    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )

    runtime = repo / ".claude/settings.local.json"
    runtime.parent.mkdir()
    runtime.write_text('{"permissions": {}}\n', encoding="utf-8")

    result = score_workspace(
        task,
        repo,
        agent_exit_code=None,
        timed_out=False,
        raw_stdout="",
        require_agent_process=False,
        require_final_verdict=False,
        ignored_changed_paths=(".claude/settings.local.json",),
    )

    assert result["pass"] is True
    assert ".claude/settings.local.json" in result["changed_paths"]
    assert result["semantic_changed_paths"] == ["CLAUDE.md"]
    assert result["ignored_runtime_paths"] == [
        ".claude/settings.local.json"
    ]


def test_other_claude_files_are_not_covered_by_runtime_exception(tmp_path):
    repo = make_repo(tmp_path)
    task = with_fixture_commit(TASK, repo)

    (repo / "CLAUDE.md").write_text(
        "# Claude\n\n- GitHub Actions CI is configured.\n",
        encoding="utf-8",
    )

    runtime = repo / ".claude/other.json"
    runtime.parent.mkdir()
    runtime.write_text("{}\n", encoding="utf-8")

    result = score_workspace(
        task,
        repo,
        agent_exit_code=None,
        timed_out=False,
        raw_stdout="",
        require_agent_process=False,
        require_final_verdict=False,
        ignored_changed_paths=(".claude/settings.local.json",),
    )

    assert result["pass"] is False
    assert ".claude/other.json" in result["semantic_changed_paths"]
