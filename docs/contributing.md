# Contributing

- One agent per file, at the repo root, with the file name matching the agent's `name` (`debugger.md` has `name: debugger`). The sync only installs root-level files, and the validator enforces both rules.
- Write the `description` as the explicit responsibilities and tasks the agent owns. Draw boundaries by making each scope precise (e.g. "within a single service", "inside a database engine") instead of listing what the agent is not for. It's what the router chooses by, and all descriptions share one context budget, so keep it short.
- Keep agents generic: no hard-coded languages, paths, hosts or company-specific commands.
- Don't add `hooks` or `mcpServers` to agent frontmatter. Installed user-level agents run them without a trust prompt on every machine.
- Run the checks before opening a pull request. CI runs the same checks plus an install and uninstall smoke test.

  ```bash
  pip install pyyaml
  python3 scripts/validate_agents.py
  python3 scripts/test_sync.py
  python3 scripts/test_settings.py
  python3 scripts/test_mcp_server.py
  python3 scripts/test_risk_hook.py
  ```

## Security

Every machine that installs this repo runs its scripts and follows its instructions: at install, on every prompt or tool call for the hook you chose, and at each session start with [the session-start sync](installer.md#the-session-start-sync). Anyone who can push to the tracked branch can change what runs on all of those machines, including the hooks that call status402 with each developer's sign-in. Protect `main`, require review for every change, and consider pinning installs to a reviewed tag with `CLAUDE_AGENTS_BRANCH`.

Never put a token in a hook entry or a committed settings file. Hook entries ignore `headers`, so a token there does nothing except leak.
