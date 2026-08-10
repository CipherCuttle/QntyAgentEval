from qntyageval.runners.native import build_command


def test_codex_native_command_is_headless_and_bounded_to_workspace_write():
    cmd = build_command("codex", "do task", model="example-model")
    assert cmd[:3] == ["codex", "--ask-for-approval", "never"]
    assert "exec" in cmd
    assert cmd.index("--ask-for-approval") < cmd.index("exec")
    assert "--json" in cmd
    assert "--ephemeral" in cmd
    assert "workspace-write" in cmd
    assert ["-m", "example-model"] == cmd[cmd.index("-m"):cmd.index("-m") + 2]


def test_claude_native_command_is_headless_and_websearch_disallowed():
    cmd = build_command("claude", "do task", model="sonnet", max_turns=17)
    assert cmd[:2] == ["claude", "-p"]
    assert "stream-json" in cmd
    assert "bypassPermissions" in cmd
    assert "WebSearch" in cmd
    assert "17" in cmd
