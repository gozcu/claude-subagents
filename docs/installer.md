# Installer reference

## Requirements

- Claude Code, with the `claude` command on your PATH, plus `git` and `python3` (3.8 or later)
- macOS, Linux, or WSL on Windows. The scripts work with the bash 3.2 that macOS ships.
- A [platform.status402.io](https://platform.status402.io) account for the risk check and the router. The installer signs you in through your browser; there's no token to copy.
- Read access to this repo. If it's private, git needs credentials that work without a prompt (an SSH key or a credential helper), and you'll need the clone method below rather than `curl`.

## Install from a clone

Clone first if you'd like to read the script before running it:

```bash
git clone https://github.com/gozcu/claude-agents-.git ~/.claude/claude-agents
~/.claude/claude-agents/scripts/install.sh
```

## Install options

You can re-run the installer at any time; it only changes what's needed, and options you don't pass keep their previous values. `CLAUDE_TOOLS` is the exception: leaving it out always means `risk`, so a router installed earlier is removed.

| Option | Default | Effect |
|---|---|---|
| `CLAUDE_TOOLS` | `risk` | The status402 tool to hook up: `risk` for [the risk check](risk-check.md) or `router` for the prompt router, not both. The one you leave out is removed if an earlier run added it. `none` installs the agents only |
| `CLAUDE_ROUTER_AGENTS` | `all` | Router only: the agents it may choose, by name, such as `"quick-fixer implementer debugger"` |
| `CLAUDE_ROUTER_SERVER` | `liz` | MCP server name, for the router and the risk check. A claude.ai connector name, such as `"claude.ai liz"`, uses that connector instead |
| `CLAUDE_ROUTER_TOOL` | `p1-gozcu-router` | Router tool name |
| `CLAUDE_SESSION_SYNC` | `false` | `true` adds the session-start sync hook, which updates the agents at every session start; see [the session-start sync](#the-session-start-sync) |
| `CLAUDE_RISK_NO_DENY` | `true` | Risk check: `true` asks you to confirm high-risk calls, `false` blocks them |
| `STATUS402_MCP_URL` | the veryliz endpoint | MCP endpoint, `https://platform.status402.io/mcp/paid/veryliz/scope/dev/gozcu` |
| `CLAUDE_AGENTS_REPO` | this repo on GitHub | Install from a fork, or from a local path |
| `CLAUDE_AGENTS_BRANCH` | `main` | Branch or tag to track. Pin a reviewed tag for stricter control |
| `CLAUDE_AGENTS_DIR` | `~/.claude/claude-agents` | Where to keep the checkout. Must be outside `~/.claude/agents/`, or every agent would load twice |

To let the router choose between three agents only:

```bash
CLAUDE_TOOLS=router CLAUDE_ROUTER_AGENTS="quick-fixer implementer debugger" ~/.claude/claude-agents/scripts/install.sh
```

To try your own changes before pushing them, install from your local checkout:

```bash
cd ~/Projects/claude-agents
CLAUDE_AGENTS_REPO="$PWD" CLAUDE_AGENTS_BRANCH=my-branch ./scripts/install.sh
```

The sync then pulls from your checkout, and only sees committed changes. If you've already installed, switch the source with `git -C ~/.claude/claude-agents remote set-url origin <url-or-path>`.

## What the installer changes

1. **`~/.claude/claude-agents/`**: a read-only checkout of this repo. It holds the scripts and routing rules. Each sync discards local edits there.
2. **`~/.claude/agents/`**: the agent files, copied in directly, where Claude Code loads them. See [how the sync treats existing files](#how-the-sync-treats-existing-files).
3. **`~/.claude.json`**: registers the status402 MCP server as `liz` for all projects (user scope), through `claude mcp add-json`, then signs in with `claude mcp login liz`:

   ```json
   {
     "type": "http",
     "url": "https://platform.status402.io/mcp/paid/veryliz/scope/dev/gozcu"
   }
   ```

   A user-scope server called `liz` with this URL is kept as it is. One with another URL is replaced.

4. **`~/.claude/settings.json`**: adds [the risk-check hook](risk-check.md) or the router hook, plus the sync hook below if you set `CLAUDE_SESSION_SYNC=true`, and saves the previous file as `settings.json.bak-<timestamp>`. The router hook is only written with `CLAUDE_TOOLS=router`; its `agents` list is generated from the agents' MD files, and is shortened here:

   ```json
   {
     "hooks": {
       "SessionStart": [
         {
           "matcher": "startup|resume",
           "hooks": [
             {
               "type": "command",
               "command": "\"$HOME/.claude/claude-agents/scripts/sync-agents.sh\" --hook \"$HOME/.claude/claude-agents\"",
               "timeout": 60
             }
           ]
         }
       ],
       "UserPromptSubmit": [
         {
           "hooks": [
             {
               "type": "mcp_tool",
               "server": "liz",
               "tool": "p1-gozcu-router",
               "input": {
                 "prompt": "${prompt}",
                 "agents": {
                   "quick-fixer": "Use for small, mechanical, low-risk changes with one obvious correct result - ...",
                   "implementer": "Use for well-specified feature work with a clear, known approach - ..."
                 }
               },
               "timeout": 15
             }
           ]
         }
       ]
     }
   }
   ```

5. **`~/.claude/CLAUDE.md`**: appends an import of the routing rules (only used by the router, but always added):

   ```markdown
   ## Team agents
   @~/.claude/claude-agents/setup/routing-rules.md
   ```

To set up by hand instead: clone the repo to `~/.claude/claude-agents`, run `git -C ~/.claude/claude-agents config claude-agents.branch main` (the sync only updates checkouts marked this way), and run `~/.claude/claude-agents/scripts/sync-agents.sh` once to copy the agents. Then make changes 3 to 5 yourself; `scripts/mcp_server.py ensure` can register the server and sign in, and `scripts/settings_hooks.py install` can write the hooks (see their `--help`).

## Signing in

Hook entries can't carry headers, so the credentials go on the MCP server instead. status402 supports OAuth dynamic client registration: the installer runs `claude mcp login liz`, Claude Code registers itself as an OAuth client, your browser opens for you to sign in, and Claude Code keeps and refreshes the credentials. Nothing secret is written to `settings.json` or `~/.claude.json`, and it works however Claude Code is started.

The sign-in needs a terminal and the `claude` CLI. Without them, for example in a script, the installer registers what it can, prints a warning and carries on; run `claude mcp login liz` afterwards (add `--no-browser` over SSH), or sign in from `/mcp` in Claude Code. Until then the router adds no notes, and the risk check isn't added.

## How the sync treats existing files

The sync runs when you run the installer or `sync-agents.sh`, and at the start of every session if you [turned that on](#the-session-start-sync).

| What's in `~/.claude/agents/` | What the sync does |
|---|---|
| Nothing with that file name | Copies the team agent in |
| A team agent the sync installed, unedited | Replaces it with the latest version. No backup: that version is in git history |
| A file with the same file name that you created or edited | Moves it to `~/.claude/agent-backups/<timestamp>/`, then copies the team agent in |
| Any other `.md`, in any subfolder, that declares the same agent `name` | Moves it to the backup folder. Two agents with one name make Claude Code pick one arbitrarily |
| A team agent that has been removed from the repo | Deletes it if unedited, moves it to the backup folder if edited |
| Your own agents with other names, and anything else | Leaves them alone |

Each run that backs something up gets its own timestamped folder, and Claude Code shows a message naming the files and the folder. The backup folder sits outside `~/.claude/agents/` so backed-up agents don't load, and nothing in it is ever deleted automatically.

The sync records what it installed, with checksums, in `~/.claude/claude-agents/.git/claude-agents-manifest.json`. That's how it tells an unedited team agent from one you changed. After installing the agents, it rebuilds the router's `agents` list from their MD files, so description changes reach the router at the next sync.

## The session-start sync

The installer copies the agents once and, by default, adds no `SessionStart` hook: the agents change only when you re-run the installer or run `~/.claude/claude-agents/scripts/sync-agents.sh`. Install with `CLAUDE_SESSION_SYNC=true` to add a hook that runs `sync-agents.sh` every time a session starts or resumes, so the agents and the router's agent list stay up to date on their own. The choice is remembered on later runs; set `CLAUDE_SESSION_SYNC=false` to remove the hook again.

It's off by default, and you might want to keep it off, because:

- **It contacts the git remote at every session start.** The sync runs `git fetch` before copying the agents. Offline or behind a proxy, that fetch fails (it gives up after a few seconds on SSH, and never prompts for credentials), prints `agent sync: fetch failed` and installs the cached agents; the session still starts, but with that delay and message each time.
- **It installs whatever is on the tracked branch without you reviewing it.** The sync resets the checkout to the latest commit of `CLAUDE_AGENTS_BRANCH` and copies the agents in, so a change to an agent's instructions, model or tools takes effect at your next session. It also runs the scripts from that checkout. See [Security](contributing.md#security).
- **You stay on a known version.** Without the hook, the installed agents only change when you run the installer or `sync-agents.sh`, so you choose when. (If you turn the hook on, pinning a reviewed tag with `CLAUDE_AGENTS_BRANCH` is the other way; the hook then only re-fetches that tag.)
- **It replaces agents you edited.** If you edited an installed team agent, the next sync moves your copy to `~/.claude/agent-backups/` and puts the team version back (see [how the sync treats existing files](#how-the-sync-treats-existing-files)). Without the hook that only happens when you run the installer or `sync-agents.sh` yourself, so it won't catch you out at session start. It doesn't protect your edits for good, since those two still do it; for that, see Personal tweaks under [Customise](how-it-works.md#customise).

What you give up without it: the agents don't update on their own, and neither does the router's agent list. Both refresh only when you re-run the installer (which also applies any option changes) or run `sync-agents.sh`. Turn the hook on if you'd rather always have the team's latest agents without thinking about it.

## Check it works

1. Run `/mcp` in Claude Code. The `liz` server should be connected. If it needs authentication, sign in from there.
2. Run `/hooks`. The hook you chose (the risk check, or the router) should be listed under user settings, plus the sync hook if you installed with `CLAUDE_SESSION_SYNC=true`.
3. Type `@` in the prompt box. The agents appear with "(agent)" after their names.
4. With the router, send `The auth test is failing with a stack trace in login.ts`. The transcript shows a `debugger(…)` row, and `/tasks` shows the model and effort it's running on.

## Update

The agents don't update on their own unless you turned on [the session-start sync](#the-session-start-sync). To update now, run:

```bash
~/.claude/claude-agents/scripts/sync-agents.sh
```

Re-running the installer also updates, and works whether or not the hook is installed.
