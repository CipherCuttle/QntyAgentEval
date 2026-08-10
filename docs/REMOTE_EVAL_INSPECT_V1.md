# Remote evaluation Inspect V1

V1 adds one infrastructure-only operation while preserving
`QNTY_EVAL_REQUEST_V0` and `QNTY_EVAL_RESULT_V0` unchanged.

The exact issue title is:

`QntyAgentEval sandbox evaluation request`

The body is exactly two lines:

```text
QNTY_EVAL_REQUEST_V1
{"schema_version":"0.2.0","operation":"QNTY_SANDBOX_EXECUTION_SMOKE_V1","target_repo":"CipherCuttle/Qnty","target_sha":"<40 hexadecimal characters>"}
```

No command, image, workflow, environment, or other execution control is
accepted from the requester. The only enabled operation is the evaluator-owned
`python -S -m quantbot.continuity verify --root /qnty` probe.

## Frozen control and compatibility

The control commit is
`3a54f4e7f0fb8c510033ce780267b539949d30b7`. It was inspected and its real
continuity verifier returned exit code 0 with a deterministic
`CONTINUITY_VERIFY_OK` observation. A requested commit must be a descendant of
that commit and must leave `quantbot/continuity`, `quantbot/assurance`, and
`quantbot/artifacts` unchanged. Symlinks and submodules are rejected.

This bounds the operation code while still materializing the requested
immutable target tree in the sandbox.

## Boundary

Trusted QntyAgentEval code creates a temporary Docker build context from
`git archive`; it does not import, test, or execute target code on the Actions
host. Inspect's built-in `docker` provider builds the target tree into a
container with no host mounts, no Docker socket, no GitHub token, no SSH keys,
no provider secrets, `network_mode: none`, a read-only root, and disposable
`/tmp` storage. Inspect owns container cleanup.

The host interprets only the Inspect process result, exit code, expected
observation, and a host-only canary check. Target-created files, prose, fake
sentinels, and fake PASS artifacts are never read as authority. The trusted
host constructs the sole `QNTY_EVAL_RESULT_V1` comment.

The result distinguishes completed workload failure from sandbox/evaluator
failure. Infrastructure failure never becomes task PASS.

This proves only that the selected target tree can execute the frozen,
deterministic Qnty control operation inside this configured Inspect Docker
boundary and return bounded evidence through the issue loop. It does not prove
general container security, scientific validity, protocol authority, model
quality, or Fixture 002 completion semantics.
