from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def changed_paths(repo: Path) -> list[str]:
    proc = run_git(
        repo,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignored=matching",
    )
    fields = [field for field in proc.stdout.split("\0") if field]
    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        if len(entry) < 4:
            raise ValueError(f"unparseable git status entry: {entry!r}")
        status = entry[:2]
        path = entry[3:]
        if "R" in status or "C" in status:
            # In -z form rename/copy entries are followed by the second path.
            paths.append(path)
            i += 1
            if i >= len(fields):
                raise ValueError("rename/copy status missing destination path")
            paths.append(fields[i])
        else:
            paths.append(path)
        i += 1
    return sorted(set(paths))
