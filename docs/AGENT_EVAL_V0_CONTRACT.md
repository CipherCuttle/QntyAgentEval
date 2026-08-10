# Qnty Agent Harness Fixture V0 Contract

## Objective

Determine whether the same frozen repository task can be executed by Claude
Code and Codex and graded by deterministic, non-LLM hard gates.

## Non-authority invariant

QntyAgentEval is an observer/test harness only.

It MUST NOT:

- write to the user's canonical Qnty or QntyLab checkout;
- mutate Qnty continuity/control state;
- mutate QntyLab research memory;
- authorize research, execution, paper, shadow, or live behavior;
- manufacture protocol next actions;
- treat its own results as Qnty/QntyLab evidence.

## Workspace isolation

The native runner MUST NOT use `git worktree add` against Qnty/QntyLab.

It creates an independent disposable local clone under `/tmp` from the supplied
source checkout and then checks out the task's immutable `base_commit`. Dirty
or untracked files in the user's source checkout therefore cannot enter the
fixture.

The disposable clone is marked with `.qntyageval-owned`. Cleanup may remove only
a path created by this harness that has that marker and whose basename starts
with `qntyageval-`.

## Source identity

Every task freezes:

- repository identity;
- immutable base commit;
- task prompt bytes;
- expected changed paths;
- hard-fail conditions.

Changing any of those creates a new task version.

## Scoring policy

Hard gates dominate all telemetry.

A run FAILS if any hard gate fails even if the patch otherwise looks useful.

V0 hard gates are machine-checkable only. No LLM-as-judge scorer is permitted.

Secondary telemetry may be incomplete in V0 and never converts a failed hard
gate into a pass.

## Native runners

The native runners intentionally invoke the user's installed coding agents:

- Claude Code: non-interactive `claude -p`
- Codex: non-interactive `codex exec`

Runner process ownership is explicit: PID/process group, command, working
directory, exit code, stdout/stderr, and timeout outcome are recorded.

## Bounded completion

V0 follows:

IMPLEMENT → TEST → ONE hostile review → fix Critical/High only →
ONE targeted rereview if required → COMMIT → MOVE FORWARD.

Medium/Low findings do not restart V0 unless they invalidate deterministic
scoring, authority isolation, or the stated objective.

## V0 kill criterion

Kill or radically simplify V0 if four historical tasks cannot eventually be
scored with stable objective gates without creating a bespoke platform or
adding an LLM judge to determine success.
