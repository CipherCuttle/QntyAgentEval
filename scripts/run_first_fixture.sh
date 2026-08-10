#!/usr/bin/env bash
set -euo pipefail

SOURCE_REPO="${QNTY_SOURCE_REPO:-/home/swirky/DevHub/repos/Qnty}"
TASK="tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json"

python -m qntyageval.cli doctor --task "$TASK" --source-repo "$SOURCE_REPO"

python -m qntyageval.cli run \
  --task "$TASK" \
  --agent codex \
  --source-repo "$SOURCE_REPO"

python -m qntyageval.cli run \
  --task "$TASK" \
  --agent claude \
  --source-repo "$SOURCE_REPO"
