#!/usr/bin/env python3
"""Register the risk-check hook in ~/.claude/settings.json.

  risk_hook.py install   [--no-deny true|false] [--server NAME] [options]
  risk_hook.py uninstall [--tool NAME]

install    adds a PreToolUse hook that sends every Bash, Edit, Write and NotebookEdit call to
           the is_risky tool on the status402 MCP server. Backs up the file.
           Re-running updates the hook in place.
uninstall  removes it. The MCP server stays registered.

Don't use it together with the prompt router (UserPromptSubmit hook): the risk
check stops the subagents the router delegates to, and you would have to approve
each of their tool calls by hand. install warns if it finds the router.

install asks for no_deny, unless --no-deny is given:
  true (the default): high-risk calls ask you to confirm.
  false: high-risk calls are blocked.

If the MCP server isn't registered in Claude Code yet, install registers it for
all projects and runs `claude mcp login`, which opens your browser to sign in.
status402 supports OAuth dynamic client registration, so there is no token to
copy; Claude Code keeps the credentials. A registered server that still needs
authentication gets the same sign-in.

Options:
  --server NAME   MCP server the tool lives on. Default: the first of
                  "claude.ai liz" and "liz" that is registered, else "liz"
  --tool NAME     risk tool (default: p2-gozcu-is_risky)
  --matcher RE    tools to check (default: Bash|Edit|Write|MultiEdit|NotebookEdit)
  --url URL       MCP endpoint, used when registering the server
"""
import argparse
import os
import pathlib
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mcp_server import DEFAULT_MCP_URL, interactive, login, register_server, registered_servers, server_state  # noqa: E402
from settings_hooks import SettingsError, handlers, load, remove, save  # noqa: E402

HOME = pathlib.Path.home()
EVENT = "PreToolUse"
SERVERS = ("claude.ai liz", "liz")
ROUTER_TOOL = "p2-gozcu-router"  # the router's default tool name; see settings_hooks.py
MATCHER = "Bash|Edit|Write|MultiEdit|NotebookEdit"  # MultiEdit only exists in older Claude Code versions
# What is_risky gets to judge: the tool, then its command or the file it changes, then the
# text it writes. Each tool sets only some of these fields; Claude Code renders the others
# as empty strings (checked on 2.1.296), so the same template serves every matched tool.
COMMAND = ("${tool_name} ${tool_input.command}${tool_input.file_path}${tool_input.notebook_path} "
           "${tool_input.content}${tool_input.new_string}${tool_input.new_source}${tool_input.edits}")
BOOLS = {"true": True, "yes": True, "y": True, "1": True,
         "false": False, "no": False, "n": False, "0": False}


def parse_bool(text):
    try:
        return BOOLS[text.strip().lower()]
    except KeyError:
        raise argparse.ArgumentTypeError(f"expected true or false, got '{text}'")


def ask_no_deny(preset):
    if preset is not None:
        return preset
    while interactive():
        answer = input("    no_deny - ask instead of blocking high-risk calls? [Y/n]: ").strip().lower()
        if not answer:
            break
        if answer in BOOLS:
            return BOOLS[answer]
    return True


# --- MCP server ------------------------------------------------------------

def ensure_server(args):
    """The server name to put in the hook, registered and signed in."""
    registered = registered_servers()
    for server in ([args.server] if args.server else SERVERS):
        state = server_state(server, registered)
        if state:
            print(f"    MCP server '{server}': already registered")
            if state == "needs-auth":
                login(server)
            return server
    server = args.server or "liz"
    if server.startswith("claude.ai "):
        raise SettingsError(f"'{server}' is a claude.ai connector and isn't connected. Add it at "
                            f"claude.ai, or drop --server to register the server here.")
    register_server(server, args.url)
    login(server)
    return server


# --- commands --------------------------------------------------------------

def is_risk_hook(handler, tool):
    return handler.get("type") == "mcp_tool" and handler.get("tool") == tool


def cmd_install(args):
    settings = load(args.settings)  # before anything else, so a broken file changes nothing
    hooks = settings.setdefault("hooks", {})
    no_deny = ask_no_deny(args.no_deny)
    server = ensure_server(args)

    group = {"matcher": args.matcher, "hooks": [
        {"type": "mcp_tool", "server": server, "tool": args.tool,
         "input": {"command": COMMAND, "no_deny": no_deny}}]}
    label = f"risk check ({server} / {args.tool}, no_deny={str(no_deny).lower()})"
    existing = [h for h in handlers(hooks, EVENT) if is_risk_hook(h, args.tool)]
    if len(existing) == 1 and group in hooks[EVENT]:
        print(f"    {EVENT}: {label} already present")
    else:
        remove(hooks, EVENT, lambda h: is_risk_hook(h, args.tool), "previous risk check")
        hooks.setdefault(EVENT, []).append(group)
        print(f"    {EVENT}: added {label} on {args.matcher}")
        save(args.settings, settings, backup=True)
    if any(is_risk_hook(h, ROUTER_TOOL) for h in handlers(hooks, "UserPromptSubmit")):
        print("    warning: the prompt router is also installed. The risk check stops the subagents it "
              "delegates to, so you would have to approve each of their tool calls by hand. Use one of "
              "them: CLAUDE_TOOLS=risk or CLAUDE_TOOLS=router with scripts/install.sh")
    if settings.get("disableAllHooks"):
        print("    warning: disableAllHooks is true in this file, so no hooks will run")


def cmd_uninstall(args):
    settings = load(args.settings)
    hooks = settings.get("hooks", {})
    if remove(hooks, EVENT, lambda h: is_risk_hook(h, args.tool), "risk check"):
        if not hooks:
            settings.pop("hooks", None)
        save(args.settings, settings, backup=True)
    else:
        print("    no risk check hook to remove")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["install", "uninstall"])
    parser.add_argument("--settings", type=pathlib.Path, default=HOME / ".claude" / "settings.json")
    parser.add_argument("--no-deny", type=parse_bool, metavar="true|false")
    parser.add_argument("--server")
    parser.add_argument("--tool", default="p2-gozcu-is_risky")
    parser.add_argument("--matcher", default=MATCHER)
    parser.add_argument("--url", default=os.environ.get("STATUS402_MCP_URL") or DEFAULT_MCP_URL)
    args = parser.parse_args()
    try:
        {"install": cmd_install, "uninstall": cmd_uninstall}[args.command](args)
    except SettingsError as exc:
        print(f"risk hook: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nrisk hook: cancelled; nothing was changed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
