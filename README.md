# QntyAgentEval

A small, external evaluation harness for the coding agents that work on **Qnty**
and **QntyLab**.

## Authority boundary

`QntyAgentEval` has **zero scientific, economic, protocol, paper, shadow, or live
authority**.

It may:

- materialize an immutable historical checkout into a disposable clone;
- run Claude Code or Codex CLI against a frozen task;
- capture the agent trajectory and repository diff;
- score objective invariants;
- emit an evaluation receipt.

It must never become a source of truth for Qnty or QntyLab. Those repositories
retain their own canonical state, ledgers, verifiers, receipts, and authority
boundaries.

## V0 objective

Prove one thing first:

> The same frozen Qnty task can be handed to Claude Code and Codex, and the
> harness can mechanically determine whether the task was completed correctly
> without an LLM judge.

V0 deliberately does **not** include skills, multi-agent orchestration, DSPy,
persistent memory, dashboards, or automatic scientific progression.

## First fixture

`QNTY_ADMIN_STALE_CONTEXT_001`

Pinned Qnty base:

`3a54f4e7f0fb8c510033ce780267b539949d30b7`

The agent must reconcile one stale development-infrastructure statement in
`CLAUDE.md` with the repository's actual CI state while preserving every
protocol/control surface.

## Setup

Python >= 3.10 is sufficient for the harness itself.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest -q
```

The native agent runner assumes the CLIs you already use are authenticated:

```bash
claude --version
codex --version
```

## Doctor

```bash
python -m qntyageval.cli doctor \
  --source-repo /home/swirky/DevHub/repos/Qnty
```

## Run first fixture with Codex

```bash
python -m qntyageval.cli run \
  --task tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json \
  --agent codex \
  --source-repo /home/swirky/DevHub/repos/Qnty
```

## Run first fixture with Claude Code

```bash
python -m qntyageval.cli run \
  --task tasks/qnty/QNTY_ADMIN_STALE_CONTEXT_001/task.json \
  --agent claude \
  --source-repo /home/swirky/DevHub/repos/Qnty
```

Each run creates a receipt under `runs/` and preserves stdout/stderr plus the
final patch. `runs/` is ignored by Git.

## Why native CLIs first?

V0 measures the actual Claude Code and Codex CLI installations/authentication
used in the development workflow. The runner interface is intentionally small
so an Inspect SWE adapter can be added later without changing task or scoring
contracts.

## V0 completion gate

V0 does **not** advance until:

1. this first fixture is objective and deterministic;
2. both native runner adapters execute it successfully on the target machine;
3. a known-good synthetic edit scores PASS;
4. protected-path or extra-file mutations score FAIL;
5. no LLM-as-judge is required.

Then add the second fixture. Not before.
