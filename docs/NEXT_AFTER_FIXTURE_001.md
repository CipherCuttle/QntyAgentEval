# Stop point after Fixture 001

Do not add another agent feature merely because Fixture 001 runs.

After one Codex and one Claude execution, inspect:

- Did both runs start from the exact pinned Qnty commit?
- Did the harness preserve the user's canonical Qnty checkout?
- Did a correct one-file patch PASS?
- Did any extra mutation FAIL?
- Did the result depend on an LLM judge?
- Did native runner configuration, authentication, or CLI drift make the
  comparison invalid?

If the harness itself is sound, the next fixture is
`QNTY_PROTOCOL_FAIL_CLOSED_001`.

If not, repair only Critical/High defects in the harness, run one targeted
re-review, then either close V0 or move forward under the bounded-completion
policy.
