#!/usr/bin/env python3
"""Manage the hooks this repo adds to ~/.claude/settings.json.

  settings_hooks.py install   --dir-in-hook DIR [--router mcp|off] [--sync on|off] [router options]
  settings_hooks.py uninstall --dir-in-hook DIR [--tool NAME]
  settings_hooks.py refresh   [router options]

install    adds the SessionStart sync hook (none, and removed if present, with
           --sync off) and the UserPromptSubmit router hook (none with
           --router off). Backs up the file.
uninstall  removes them.
refresh    rebuilds the MCP router's agent list from the agent MD files. The sync
           runs this, so with the sync hook description edits reach the router
           at the next session start, without re-installing.

Router options:
  --server NAME      MCP server the router tool lives on (default: liz)
  --tool NAME        router tool (default: p2-gozcu-router)
  --agents LIST      "all" (every agent in --repo) or agent names, comma- or space-separated
  --repo DIR         the checkout; "all" means every agent at its root
  --agents-dir DIR   where to read agent MD files (default: ~/.claude/agents)

The MCP router hook sends the tool {"prompt": <the prompt>, "agents": {name: description}}.
Only names are configured; descriptions always come from the MD files.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from deploy_agents import frontmatter  # noqa: E402

HOME = pathlib.Path.home()


class SettingsError(Exception):
    pass


# --- agent catalogue -------------------------------------------------------

def agent_files(agents_dir):
    """Map agent name -> MD file for every agent under agents_dir."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(agents_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for filename in sorted(filenames):
            if filename.endswith(".md"):
                path = pathlib.Path(dirpath) / filename
                name = frontmatter(path).get("name")
                if name:
                    # Prefer <name>.md at the top level if a name appears twice.
                    if name not in found or path == agents_dir / f"{name}.md":
                        found[name] = path
    return found


def resolve_names(spec, repo):
    if spec.strip().lower() == "all":
        if repo is None:
            raise SettingsError("--agents all needs --repo")
        names = [frontmatter(p).get("name") for p in sorted(pathlib.Path(repo).glob("*.md"))]
        return [n for n in names if n]
    names = [n for n in re.split(r"[\s,]+", spec) if n]
    if not names:
        raise SettingsError("no agent names given")
    return list(dict.fromkeys(names))


def agents_map(names, agents_dir, strict=True):
    """{name: description}, read from each agent's MD file."""
    files, result, missing = agent_files(agents_dir), {}, []
    for name in names:
        description = frontmatter(files[name]).get("description") if name in files else None
        if description:
            result[name] = " ".join(description.split())
        else:
            missing.append(name)
    if missing and strict:
        raise SettingsError(f"no agent MD file with a description for: {', '.join(missing)} "
                            f"(looked in {agents_dir})")
    return result, missing


# --- settings file ---------------------------------------------------------

def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{path} is not valid JSON ({exc}). Fix it and re-run; nothing was changed.")
    if not isinstance(settings, dict):
        raise SettingsError(f"unexpected structure in {path}; nothing was changed")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict) or not all(
            isinstance(g, list) and all(isinstance(x, dict) for x in g) for g in hooks.values()):
        raise SettingsError(f"unexpected structure under hooks in {path}; edit it by hand (see docs/installer.md)")
    return settings


def save(path, settings, backup):
    path = pathlib.Path(path)
    if backup and path.exists():
        copy = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(path, copy)
        print(f"    backup: {copy}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def handlers(hooks, event):
    for group in hooks.get(event, []):
        for handler in group.get("hooks", []):
            if isinstance(handler, dict):
                yield handler


def remove(hooks, event, predicate, label):
    removed = 0
    for group in hooks.get(event, []):
        kept = [h for h in group.get("hooks", []) if not (isinstance(h, dict) and predicate(h))]
        removed += len(group.get("hooks", [])) - len(kept)
        group["hooks"] = kept
    if event in hooks:
        hooks[event] = [g for g in hooks[event] if g.get("hooks")]
        if not hooks[event]:
            del hooks[event]
    if removed:
        print(f"    {event}: removed {label}")
    return removed


def add(hooks, event, group):
    hooks.setdefault(event, []).append(group)
    print(f"    {event}: added {describe(group['hooks'][0])}")


def describe(handler):
    if handler.get("type") == "mcp_tool":
        return f"MCP router ({handler.get('server')} / {handler.get('tool')})"
    return handler.get("command", "hook")


def sync_command(dir_in_hook):
    return f'"{dir_in_hook}/scripts/sync-agents.sh" --hook "{dir_in_hook}"'


def is_mcp_router(handler, tool):
    return handler.get("type") == "mcp_tool" and handler.get("tool") == tool


def mcp_router(server, tool, agents):
    return {"type": "mcp_tool", "server": server, "tool": tool,
            "input": {"prompt": "${prompt}", "agents": agents}, "timeout": 15}


# --- commands --------------------------------------------------------------

def cmd_install(args):
    settings = load(args.settings)
    hooks = settings.setdefault("hooks", {})
    sync_cmd = sync_command(args.dir_in_hook)
    changed = 0

    if args.sync == "off":
        changed += remove(hooks, "SessionStart", lambda h: h.get("command") == sync_cmd, "sync hook")
        print("    SessionStart: no sync hook (CLAUDE_SESSION_SYNC=true adds it)")
    elif sync_cmd in (h.get("command") for h in handlers(hooks, "SessionStart")):
        print("    SessionStart: sync hook already present")
    else:
        add(hooks, "SessionStart", {"matcher": "startup|resume", "hooks": [
            {"type": "command", "command": sync_cmd, "timeout": 60}]})
        changed += 1

    if args.router == "mcp":
        names = resolve_names(args.agents, args.repo)
        agents, _ = agents_map(names, args.agents_dir)
        wanted = mcp_router(args.server, args.tool, agents)
        existing = [h for h in handlers(hooks, "UserPromptSubmit") if is_mcp_router(h, args.tool)]
        if existing == [wanted]:
            print("    UserPromptSubmit: MCP router already present")
        else:
            changed += remove(hooks, "UserPromptSubmit", lambda h: is_mcp_router(h, args.tool), "previous MCP router")
            add(hooks, "UserPromptSubmit", {"hooks": [wanted]})
            changed += 1
        print(f"    router agents: {', '.join(agents)}")
    else:
        changed += remove(hooks, "UserPromptSubmit", lambda h: is_mcp_router(h, args.tool), "MCP router")
        print("    UserPromptSubmit: no router (CLAUDE_TOOLS=router adds it)")

    for h in handlers(hooks, "SessionStart"):
        if "sync-agents.sh" in h.get("command", "") and h.get("command") != sync_cmd:
            also = "also " if args.sync == "on" else ""
            print(f"    warning: another SessionStart hook {also}runs sync-agents.sh: {h['command']}")
    if settings.get("disableAllHooks"):
        print("    warning: disableAllHooks is true in this file, so no hooks will run")

    if changed:
        save(args.settings, settings, backup=True)


def cmd_uninstall(args):
    settings = load(args.settings)
    hooks = settings.get("hooks", {})
    sync_cmd = sync_command(args.dir_in_hook)
    changed = remove(hooks, "SessionStart", lambda h: h.get("command") == sync_cmd, "sync hook")
    changed += remove(hooks, "UserPromptSubmit", lambda h: is_mcp_router(h, args.tool), "MCP router")
    if not hooks:
        settings.pop("hooks", None)
    if changed:
        save(args.settings, settings, backup=True)
    else:
        print("    no hooks to remove")


def cmd_refresh(args):
    """Rebuild the MCP router's agent list; quiet unless something changed."""
    settings = load(args.settings)
    hooks = settings.get("hooks", {})
    routers = [h for h in handlers(hooks, "UserPromptSubmit") if is_mcp_router(h, args.tool)]
    if not routers:
        return
    names = resolve_names(args.agents, args.repo)
    agents, missing = agents_map(names, args.agents_dir, strict=False)
    for name in missing:
        print(f"router agents: skipped '{name}', no MD file with a description", file=sys.stderr)
    changed = False
    for handler in routers:
        handler_input = handler.setdefault("input", {})
        if handler_input.get("agents") != agents:
            handler_input["agents"] = agents
            changed = True
    if changed:
        save(args.settings, settings, backup=False)
        print(f"router agents updated: {', '.join(agents)}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["install", "uninstall", "refresh"])
    parser.add_argument("--settings", type=pathlib.Path, default=HOME / ".claude" / "settings.json")
    parser.add_argument("--dir-in-hook", help="checkout path as written in hook commands")
    parser.add_argument("--router", choices=["mcp", "off"], default="mcp")
    parser.add_argument("--sync", choices=["on", "off"], default="on")
    parser.add_argument("--server", default="liz")
    parser.add_argument("--tool", default="p2-gozcu-router")
    parser.add_argument("--agents", default="all")
    parser.add_argument("--repo", type=pathlib.Path)
    parser.add_argument("--agents-dir", type=pathlib.Path, default=HOME / ".claude" / "agents")
    args = parser.parse_args()
    if args.command in ("install", "uninstall") and not args.dir_in_hook:
        parser.error("--dir-in-hook is required")
    try:
        {"install": cmd_install, "uninstall": cmd_uninstall, "refresh": cmd_refresh}[args.command](args)
    except SettingsError as exc:
        print(f"settings: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
