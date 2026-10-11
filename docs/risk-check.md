# The risk-check hook

`scripts/risk_hook.py` adds a `PreToolUse` hook that sends every Bash, Edit, Write and NotebookEdit call to the `p1-gozcu-is_risky` tool before it runs: the tool's name, then the command or the path of the file it changes, then the text it writes. The installer adds it unless `CLAUDE_TOOLS` leaves `risk` out. Set `CLAUDE_RISK_NO_DENY=false` to block high-risk calls instead of asking; that value is remembered for later runs. It can't be combined with [the router](router.md): the risk check stops the subagents the router delegates to. The installer puts the hook on the MCP server named by `CLAUDE_ROUTER_SERVER`, and removes it again when you re-run with `CLAUDE_TOOLS=router` or `--uninstall`. If the sign-in doesn't finish, the hook isn't written; re-run the installer once you've signed in.

You can also run the script yourself, for example to change the server, tool or matcher. If the router hook (`p1-gozcu-router`) is already in `settings.json`, it prints a warning but still installs; remove one of the two yourself. A router under a custom `CLAUDE_ROUTER_TOOL` name isn't detected.

```bash
~/.claude/claude-agents/scripts/risk_hook.py install
```

To use the hook without installing the agents or cloning the repo, download the script and the three modules it imports, then run it from there:

```bash
d=$(mktemp -d) && for f in risk_hook mcp_server settings_hooks deploy_agents; do
  curl -fsSL "https://raw.githubusercontent.com/gozcu/claude-subagents/main/scripts/$f.py" -o "$d/$f.py" || break
done && python3 "$d/risk_hook.py" install
```

This needs `python3` and the `claude` CLI on your PATH. Run it as a file rather than piping it into `python3`: the `no_deny` question and the sign-in need a terminal. The hook doesn't refer to the script, so the downloaded files can be deleted afterwards; run the same command with `uninstall` to remove the hook.

Run this way, it asks for **`no_deny`** (default `true`): high-risk calls ask you to confirm. With `false` they're blocked. Pass `--no-deny true|false` to skip the question.

It uses the `claude.ai liz` connector or a `liz` server if either is registered in Claude Code. Otherwise it registers `liz` for all projects and runs `claude mcp login liz`, which opens your browser to sign in. status402 supports OAuth dynamic client registration, so there's no token to copy, and Claude Code keeps the credentials. The hook is only written once the sign-in succeeds.

It then writes this to `~/.claude/settings.json`, after backing the file up:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "mcp_tool",
            "server": "claude.ai liz",
            "tool": "p1-gozcu-is_risky",
            "input": {
              "command": "${tool_name} ${tool_input.command}${tool_input.file_path}${tool_input.notebook_path} ${tool_input.content}${tool_input.new_string}${tool_input.new_source}${tool_input.edits}",
              "no_deny": true
            }
          }
        ]
      }
    ]
  }
}
```

Re-run it to change `no_deny`; the hook is updated in place. `risk_hook.py uninstall` removes the hook and leaves the MCP server registered. `--server`, `--tool`, `--matcher` and `--url` override the defaults (see `--help`).
