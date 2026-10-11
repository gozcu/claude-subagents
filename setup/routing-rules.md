# Subagent routing

These rules come from the shared claude-agents repo and apply in every project.

- A UserPromptSubmit hook adds a "Task routing" note to some prompts, naming the subagent that matches the task. When a note names a subagent, delegate the task to it. Don't pass a model or effort override; the subagent's definition sets them.
- Ignore the note when the prompt is a question, a follow-up on work already in progress, or names a different subagent.
- If a subagent replies with ESCALATE, delegate to the subagent it suggests and pass along what it found.
- If a subagent replies with DECISION NEEDED, ask me before continuing.
