# How it works

| Piece | File | What it does |
|---|---|---|
| Agents | `*.md` at the repo root | Each one sets a model, an effort level, tools and instructions |
| Sync hook | `scripts/sync-agents.sh` | Opt-in ([`CLAUDE_SESSION_SYNC=true`](installer.md#the-session-start-sync)). Runs at session start, updates the checkout, copies the agents into `~/.claude/agents/`, and refreshes the router's agent list |
| Risk check | `p2-gozcu-is_risky` on the status402 MCP server | The default. Runs before every shell command and file write or edit, and asks you to confirm high-risk ones |
| Router hook | `p2-gozcu-router` on the status402 MCP server | Opt-in (`CLAUDE_TOOLS=router`). Runs on every prompt and returns a short note naming the agent that matches |
| Routing rules | `setup/routing-rules.md` | Imported into `~/.claude/CLAUDE.md`; tells Claude to delegate when the router adds a note |

With the router installed, a prompt goes like this:

```
You:      "The auth test is failing with a stack trace in login.ts"
Router:   adds "Task routing: this request matches the debugger subagent"
Claude:   follows the routing rules and delegates to debugger
debugger: runs on Sonnet at high effort, fixes the bug, reports back
```

A hook can't switch models by itself, which is why the rules are needed. Only the delegated work runs on the agent's model; your main session keeps its own model and summarises the result.

## The agents

| Agent | Model | Effort | Use for |
|---|---|---|---|
| `quick-fixer` | haiku | low | Renames, typos, formatting, config values, format conversion, lookups |
| `implementer` | sonnet | medium | Well-specified features with a known approach |
| `debugger` | sonnet | high | Failing tests, errors, regressions, flaky behaviour |
| `architect` | opus | high | Multi-module refactors, design decisions, performance, API and schema evolution |
| `reviewer` | opus | high | Read-only review of diffs, branches and pull requests |
| `deep-systems` | fable | xhigh | Distributed systems, concurrency, operators, cross-service root-cause work |
| `data-pipeline` | opus | high | Spark, Flink, Kafka, Airflow, dbt, lakehouse tables |
| `database-ops` | sonnet | high | Query tuning, indexes, schema design, migrations |

Every agent returns one of two signals instead of guessing:

- `ESCALATE: <reason>` plus a suggested agent, when the task is outside its scope.
- `DECISION NEEDED: <decision>`, before anything destructive or irreversible.

## Customise

- **No access to Fable, or it bills usage credits on your plan?** Change `deep-systems` to `model: opus` and keep `effort: xhigh`.
- **Lower cost:** drop effort one level, or move `architect` and `reviewer` to `sonnet`.
- **Personal tweaks:** don't edit the installed copies. The next sync moves your edited copy to the backup folder and puts the team version back. Instead, copy the agent to a new file name with a new `name` in its frontmatter, or override it for one project in that project's `.claude/agents/`, which takes precedence and which the sync never touches. To let the router pick your own agent, add its name to `CLAUDE_ROUTER_AGENTS`; its description is read from its MD file.
- **One project only:** copy the agent files into that project's `.claude/agents/` and commit them, instead of installing.
- **Turn routing off:** re-run the installer without `CLAUDE_TOOLS` (or with `CLAUDE_TOOLS=risk`), or with `CLAUDE_TOOLS=none` for no hooks on the MCP server at all. The agents still work when you name them.
- **Pin model versions:** the aliases (`haiku`, `sonnet`, `opus`, `fable`) resolve to the right version for your provider. Use a full model ID such as `claude-opus-5-5` to pin one.
