# QntyAgentEval V0 self-hostile candidate review

Status: implementation self-review only. This is **not** claimed as an
independent hostile review.

## Findings repaired

### H-01 — required-file deletion crashed scorer

Original behavior: if an agent deleted a required scored file, the scorer raised
`FileNotFoundError` instead of producing a deterministic FAIL.

Repair: missing required files now fail both relevant content gates.

Regression: `test_deleted_required_file_fails_closed`.

### H-02 — ignored side effects were invisible to scope gate

Original behavior: ordinary `git status --porcelain` did not surface files
created under ignored paths, allowing an agent to leave unrelated ignored
artifacts while still satisfying the exact changed-path set.

Repair: scope collection now includes `--ignored=matching` and all untracked
files in the pristine disposable clone.

Regression: `test_ignored_artifact_is_still_scope_violation`.

### H-03 — agent could commit and hide working-tree diff

Disposition: already fail-closed through the immutable source-HEAD gate.
Regression added: `test_committing_the_change_fails_source_head_gate`.

## Workspace isolation review

The harness uses an independent disposable local clone, not a Qnty/QntyLab Git
worktree. A regression test verifies dirty/untracked bytes in the user's source
checkout do not enter the fixture checkout, and cleanup refuses non-owned paths.

## Known limitations accepted for Fixture 001

1. Native Claude mode does not mechanically block every possible child-process
   network call. Fixture 001 requires repository-local evidence only and
   disallows web search in the prompt/tool surface; stronger transport/tool
   isolation is required before tasks where network provenance could affect
   scientific conclusions.
2. Exact model identity is only preregistered when `--model` is supplied.
3. The real Claude/Codex binaries and authentication are unavailable in this
   build environment, so end-to-end agent execution must occur on the user's
   machine. `doctor` verifies required CLI flags before a run.
4. This self-review does not consume or substitute for an independent hostile
   review if the user applies the Qnty bounded-review policy to this new repo.

## Candidate verdict

`READY_FOR_NATIVE_FIXTURE_EXECUTION`

Not yet `V0_PASS`.
