# Troubleshooting

| Symptom | Fix |
|---|---|
| Agents don't appear after installing | If `~/.claude/agents/` didn't exist when the session started, restart Claude Code once. To find broken definitions, run `python3 ~/.claude/claude-agents/scripts/validate_agents.py ~/.claude/agents` (needs `pip install pyyaml`). |
| `liz` isn't connected in `/mcp` | Run `claude mcp login liz`, or pick the server in `/mcp` and authenticate there. If the server isn't listed at all, re-run the installer. |
| `install: the router and the risk check can't be used together` | Pick one: `CLAUDE_TOOLS=router` or `CLAUDE_TOOLS=risk`. |
| A hook error naming `p2-gozcu-router` | The tool doesn't exist on the server, or your account can't call it. Check the server's tools in `/mcp`. |
| Notes never appear | The router is off by default; install it with `CLAUDE_TOOLS=router`. Run `/hooks` and check the router hook is listed. Check that `disableAllHooks` isn't set, and ask your admin whether managed settings set `allowManagedHooksOnly`. Start with `claude --debug` to see hook output. |
| Notes appear but Claude doesn't delegate | Check that `~/.claude/CLAUDE.md` contains the import line. In Cowork sessions in the desktop app, imports from outside the session's folder are skipped, so the routing rules don't load there. |
| One of my own agents disappeared | It had the same file name or agent `name` as a team agent, so the sync moved it to `~/.claude/agent-backups/`. Give it a different file name and `name`, then move it back. |
| My edit to a team agent keeps being undone | The installed copies follow the repo. See **Personal tweaks** under Customise. |
| Agents run on the wrong model or effort | `CLAUDE_CODE_EFFORT_LEVEL` overrides every agent's effort, and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` makes Claude Code ignore their `model`. Leave both unset. Your organisation's model restrictions can also substitute a model. `/tasks` shows what each agent is running on. |
| Each prompt gets two notes | Another router hook is still registered. Remove the duplicate from `~/.claude/settings.json`. |
| `install: ... no agent MD file with a description for: <name>` | A name in `CLAUDE_ROUTER_AGENTS` doesn't match any agent in `~/.claude/agents/`. |
| `agent sync: ... not a checkout created by install.sh` | Run the installer once to adopt the folder. |
| `agent sync: another sync is running` | Two sessions started at once and the other one is syncing. A lock left by a crashed sync clears itself after two minutes. |
| `agent sync: fetch failed` | You're offline or lack access to the repo. The sync still installs the cached agents. To stop it trying at every session start, re-run the installer with `CLAUDE_SESSION_SYNC=false`; see [the session-start sync](installer.md#the-session-start-sync). |
