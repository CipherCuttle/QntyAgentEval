# Remote evaluation trigger V0

ChatGPT can request the single enabled Fixture 001 evaluation by opening an
issue in `QntyAgentEval` with this exact title:

`QntyAgentEval evaluation request`

The body is exactly two lines: the sentinel and one strict JSON object.

```text
QNTY_EVAL_REQUEST_V0
{"schema_version":"0.1.0","task_id":"QNTY_ADMIN_STALE_CONTEXT_001","target_repo":"CipherCuttle/Qnty","target_sha":"<40 lowercase hex characters>"}
```

The workflow validates the envelope and fixed allowlists, clones the fixed
`CipherCuttle/Qnty` repository, and verifies that the requested commit is
derived from the task's frozen base commit. It then materializes the target
tree as index/working-tree changes while keeping evaluation `HEAD` at the
frozen base, and calls the existing trusted text/diff scorer. No target
repository scripts, tests, imports, or application code are executed.

The workflow updates one authoritative issue comment containing
`QNTY_EVAL_RESULT_V0` followed by strict JSON. `COMPLETED` with `task_pass`
false means the task was evaluated and failed; the other statuses indicate
that evaluation could not be performed.

`REMOTE_EVAL_INSPECT_V1` is intentionally not implemented. It is the future
boundary for tasks that need untrusted target-code execution, using an Inspect
sandbox and a host-side scorer. Fixture 002 remains outside this remote V0.
