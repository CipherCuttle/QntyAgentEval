from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .gitutil import run_git
from .task import EvalTask


OWNERSHIP_MARKER = ".qntyageval-owned"


def prepare_workspace(task: EvalTask, source_repo: str | Path) -> Path:
    source = Path(source_repo).expanduser().resolve()
    if not (source / ".git").exists():
        raise ValueError(f"source is not a git checkout: {source}")

    exists = subprocess.run(
        ["git", "-C", str(source), "cat-file", "-e", f"{task.base_commit}^{{commit}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if exists.returncode != 0:
        raise ValueError(
            f"base commit {task.base_commit} is not available in source checkout"
        )

    root = Path(tempfile.mkdtemp(prefix=f"qntyageval-{task.task_id.lower()}-",
                                 dir="/tmp"))
    checkout = root / "repo"
    try:
        subprocess.run(
            ["git", "clone", "--shared", "--no-checkout", str(source), str(checkout)],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        run_git(checkout, "checkout", "--detach", task.base_commit)
        head = run_git(checkout, "rev-parse", "HEAD").stdout.strip()
        if head != task.base_commit:
            raise RuntimeError(f"checkout mismatch: {head} != {task.base_commit}")
        (root / OWNERSHIP_MARKER).write_text(task.task_id + "\n", encoding="utf-8")
        return checkout
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def cleanup_workspace(checkout: Path) -> None:
    root = checkout.resolve().parent
    marker = root / OWNERSHIP_MARKER
    if not root.name.startswith("qntyageval-"):
        raise RuntimeError(f"refusing cleanup of non-owned path: {root}")
    if not marker.is_file():
        raise RuntimeError(f"refusing cleanup without ownership marker: {root}")
    shutil.rmtree(root)
