# The MCP router

The router is opt-in: install it with `CLAUDE_TOOLS=router`. It can't be used together with the risk check, which stops the subagents it delegates to.

On every prompt, Claude Code calls the router tool with:

```json
{
  "prompt": "The auth test is failing with a stack trace in login.ts",
  "agents": { "quick-fixer": "<description from quick-fixer.md>", "debugger": "<description from debugger.md>" }
}
```

The tool must reply with text that Claude Code reads like a command hook's output:

- To name an agent, return this JSON. Write the note as a fact, because instructions belong in `setup/routing-rules.md`:

  ```json
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Task routing: this request matches the debugger subagent."}}
  ```

- To route nowhere, return nothing or `{}`. Claude handles the prompt itself.
- Don't return `model`, `effort` or `updatedInput`. `UserPromptSubmit` doesn't support them.
- Plain text is added to Claude's context as-is, so prefer the JSON form.

Things to know:

- **It's a paid call on every prompt.** That includes follow-ups, slash commands, scheduled tasks and messages from background subagents, because hook entries can't filter prompts. The tool should return quickly with nothing for prompts it doesn't need to route.
- **Failures never block you.** If the server is unreachable, you aren't signed in or the call takes longer than 15 seconds, the prompt goes through without a note.

You can also choose an agent yourself by @-mentioning it or naming it: "use the debugger subagent to…".
