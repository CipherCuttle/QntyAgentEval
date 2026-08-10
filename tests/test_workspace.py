import subprocess
from dataclasses import replace
from pathlib import Path

from qntyageval.task import load_task
from qntyageval.workspace import cleanup_workspace, prepare_workspace


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


def source_repo(tmp_path: Path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "Fixture")
    (repo / "CLAUDE.md").write_text("tracked\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "base")
    sha = git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, sha


def test_workspace_is_independent_clone_and_source_dirt_does_not_enter(tmp_path):
    source, sha = source_repo(tmp_path)
    (source / "CLAUDE.md").write_text("dirty source edit\n", encoding="utf-8")
    (source / "untracked.txt").write_text("dirty untracked\n", encoding="utf-8")
    task = replace(TASK, base_commit=sha)

    checkout = prepare_workspace(task, source)
    try:
        assert (checkout / "CLAUDE.md").read_text(encoding="utf-8") == "tracked\n"
        assert not (checkout / "untracked.txt").exists()
        assert git(checkout, "rev-parse", "HEAD").stdout.strip() == sha
        assert checkout.parent.name.startswith("qntyageval-")
        assert (checkout.parent / ".qntyageval-owned").is_file()
    finally:
        owned_root = checkout.parent
        cleanup_workspace(checkout)
        assert not owned_root.exists()


def test_cleanup_refuses_unowned_path(tmp_path):
    fake = tmp_path / "repo"
    fake.mkdir()
    try:
        cleanup_workspace(fake)
    except RuntimeError as exc:
        assert "refusing cleanup" in str(exc)
    else:
        raise AssertionError("cleanup should refuse an unowned path")
