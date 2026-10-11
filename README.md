# Claude Code agents

A shared set of [Claude Code subagents](https://code.claude.com/docs/en/sub-agents), each pinned to the right model and effort level, plus an installer that adds a risk check on your tool calls or, if you prefer, a prompt router that sends each task to the agent that fits. The agents are language- and framework-agnostic: they read each project's own conventions, build files and test commands instead of assuming them.

## What gets sent where

The agents are local files. The two optional tools call the status402 MCP server, which you sign in to through your browser:

| Tool | Sends to status402 | When |
|---|---|---|
| Risk check (the default) | The tool's name, the command or file path, and the text being written | Before every shell command and file write or edit |
| Router (`CLAUDE_TOOLS=router`) | Your prompt, and the agents' names and descriptions | On every prompt |

With `CLAUDE_TOOLS=none` nothing is sent. The installer and the optional session-start sync also fetch this repo from GitHub. Machines that install this repo run its scripts, so read [Security](docs/contributing.md#security) before sharing it with a team.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/gozcu/claude-subagents/main/scripts/install.sh | bash
```

This installs the agents and the risk check. Your browser opens to sign in to status402; then restart Claude Code. It needs Claude Code, `git`, `python3` and a status402 account. To choose the tool, set `CLAUDE_TOOLS` on `bash`:

```bash
curl -fsSL https://raw.githubusercontent.com/gozcu/claude-subagents/main/scripts/install.sh | CLAUDE_TOOLS=router bash
```

`risk` is the default, `router` installs the prompt router instead, and `none` installs the agents only. The router and the risk check can't be combined: the risk check stops the subagents the router delegates to. Re-run the installer to update the agents or switch tools.

## Uninstall

```bash
~/.claude/claude-agents/scripts/install.sh --uninstall
```

This removes the agents (any you edited are moved to `~/.claude/agent-backups/` first), the hooks, the MCP server the installer registered, the routing rules import and the checkout. Restart Claude Code afterwards. Without a checkout, run the install command with `bash -s -- --uninstall`.

## More

- [How it works](docs/how-it-works.md): the pieces, the agents and their models, and how to customise them
- [Installer reference](docs/installer.md): requirements, options, what the installer changes, signing in, the sync, updating
- [The risk-check hook](docs/risk-check.md) and [the MCP router](docs/router.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Contributing and security](docs/contributing.md)
