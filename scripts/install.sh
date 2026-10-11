#!/usr/bin/env bash
# Sets up the shared Claude Code agents, and the status402 risk check or prompt router.
#
#   curl -fsSL https://raw.githubusercontent.com/gozcu/claude-agents-/main/scripts/install.sh | bash
#
#   1. Clones this repo into ~/.claude/claude-agents and installs its agents
#      directly into ~/.claude/agents/. Any file there that would be replaced,
#      or that uses the same agent name, is first moved to
#      ~/.claude/agent-backups/<timestamp>/.
#   2. Registers the status402 MCP server for all projects and opens your
#      browser to sign in. There is no token to copy.
#   3. Adds hooks to ~/.claude/settings.json, backing up the old file:
#      by CLAUDE_TOOLS (default: risk):
#        PreToolUse       -> the risk check (asks is_risky before shell commands and file writes or edits)
#        UserPromptSubmit -> the router (names the agent for each prompt)
#      and, only with CLAUDE_SESSION_SYNC=true:
#        SessionStart     -> scripts/sync-agents.sh (keeps the agents up to date)
#      The router and the risk check can't be installed together: the risk check
#      stops the subagents the router delegates to, and you would have to approve
#      each of their tool calls by hand. Pick one.
#   4. Imports setup/routing-rules.md into ~/.claude/CLAUDE.md.
#
# Safe to re-run: each step only adds or updates what is needed.
#
#   install.sh --uninstall   undoes all of it (agents you edited are backed up)
#
# Options (environment variables). On a re-run, unset options other than
# CLAUDE_TOOLS keep the values from the previous install.
#   CLAUDE_AGENTS_REPO     git URL or local path to install from
#   CLAUDE_AGENTS_BRANCH   branch or tag to track (default: main)
#   CLAUDE_AGENTS_DIR      where to keep the checkout (default: ~/.claude/claude-agents)
#   CLAUDE_TOOLS           the status402 tool to hook up: risk or router, not both.
#                          Default: risk. The tool you leave out is removed again if an
#                          earlier run added it; "none" installs the agents only.
#   CLAUDE_ROUTER_AGENTS   agent names the router may choose, e.g. "quick-fixer implementer";
#                          default: all. Descriptions are read from the agents' MD files.
#   CLAUDE_ROUTER_SERVER   MCP server name (default: liz). A claude.ai connector name such
#                          as "claude.ai liz" uses that connector instead.
#   CLAUDE_ROUTER_TOOL     router tool (default: p1-gozcu-router)
#   CLAUDE_SESSION_SYNC    false (default): no SessionStart hook (removed if an earlier run added
#                          it); the agents are copied once by the installer, and update only when
#                          you re-run it or run scripts/sync-agents.sh by hand. true: the hook
#                          updates the checkout and the agents (and the router's agent list) at
#                          every session start
#   CLAUDE_RISK_NO_DENY    for the risk check. true (default): high-risk calls ask you to
#                          confirm; false: they are blocked
#   STATUS402_MCP_URL      MCP endpoint (default: the veryliz endpoint on platform.status402.io)
#
# Everything runs inside main() so bash reads the whole file first; that makes
# `curl | bash` and running this file from the checkout it updates both safe.
# Written for bash 3.2, which macOS ships.
set -euo pipefail

DEFAULT_MCP_URL="https://platform.status402.io/mcp/paid/veryliz/scope/dev/gozcu"

main() {
  local mode="install"
  case "${1:-}" in
    "") ;;
    --uninstall) mode="uninstall" ;;
    *) echo "usage: install.sh [--uninstall]" >&2; exit 2 ;;
  esac

  local repo_url="${CLAUDE_AGENTS_REPO:-https://github.com/gozcu/claude-agents-.git}"
  local branch="${CLAUDE_AGENTS_BRANCH:-main}"
  local dir="${CLAUDE_AGENTS_DIR:-$HOME/.claude/claude-agents}"
  local agents_dir="$HOME/.claude/agents"
  local backups="$HOME/.claude/agent-backups"
  local router="off" router_agents router_server router_tool mcp_url
  local risk="off" previous_risk risk_no_deny server_ready session_sync
  local tools="${CLAUDE_TOOLS-risk}" item
  local dir_in_hook dir_in_md tool

  for item in ${tools//,/ }; do
    case "$item" in
      router) router="mcp" ;;
      risk) risk="on" ;;
      none) ;;
      *) echo "install: CLAUDE_TOOLS takes router, risk or none, comma-separated (got '$item')" >&2; exit 1 ;;
    esac
  done
  if [ "$mode" = "install" ] && [ "$router" = "mcp" ] && [ "$risk" = "on" ]; then
    echo "install: the router and the risk check can't be used together. The risk check stops the" >&2
    echo "subagents the router delegates to, so you would have to approve each of their tool calls by hand." >&2
    echo "Pick one: CLAUDE_TOOLS=router or CLAUDE_TOOLS=risk" >&2
    exit 1
  fi

  for tool in git python3; do
    command -v "$tool" >/dev/null || { echo "install: $tool is required" >&2; exit 1; }
  done
  export GIT_TERMINAL_PROMPT=0

  case "$dir" in
    "$agents_dir" | "$agents_dir"/*)
      echo "install: CLAUDE_AGENTS_DIR must be outside $agents_dir, or Claude Code would load every agent twice" >&2
      exit 1 ;;
  esac

  # Paths under $HOME are written as "$HOME/..." in hooks and "~/..." in
  # CLAUDE.md, so both stay readable. The literal tilde is intentional.
  # shellcheck disable=SC2088
  case "$dir" in
    "$HOME"/*) dir_in_hook="\$HOME/${dir#"$HOME"/}"; dir_in_md="~/${dir#"$HOME"/}" ;;
    *)         dir_in_hook="$dir";                   dir_in_md="$dir" ;;
  esac

  if [ "$mode" = "uninstall" ]; then
    do_uninstall
  else
    do_install
  fi
}

# A router option: the environment wins, then the previous install's value, then the default.
option() {
  local env_value="$1" key="$2" default="$3" saved=""
  if [ -n "$env_value" ]; then echo "$env_value"; return; fi
  if [ -d "$dir/.git" ]; then saved="$(git -C "$dir" config --get "claude-agents.$key" || true)"; fi
  echo "${saved:-$default}"
}

do_install() {
  echo "1/4 Agents"
  if [ -d "$dir/.git" ]; then
    if ! git -C "$dir" config --get claude-agents.branch >/dev/null; then
      if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
        echo "install: $dir has uncommitted changes. Commit or remove them, or set CLAUDE_AGENTS_DIR." >&2
        exit 1
      fi
      git -C "$dir" config claude-agents.branch "$(git -C "$dir" rev-parse --abbrev-ref HEAD)"
      echo "    adopted $dir as the checkout (syncs will discard local edits)"
    fi
    if [ -n "${CLAUDE_AGENTS_BRANCH:-}" ]; then
      git -C "$dir" config claude-agents.branch "$CLAUDE_AGENTS_BRANCH"
    fi
  elif [ -e "$dir" ]; then
    echo "install: $dir exists and is not a git checkout. Move it or set CLAUDE_AGENTS_DIR." >&2
    exit 1
  else
    mkdir -p "$(dirname "$dir")"
    if ! git clone --quiet --depth 1 --branch "$branch" "$repo_url" "$dir" 2>/dev/null; then
      echo "install: could not clone $repo_url ($branch). Check the URL, branch and your access." >&2
      exit 1
    fi
    git -C "$dir" config claude-agents.branch "$branch"
  fi
  if [ ! -f "$dir/scripts/settings_hooks.py" ]; then
    echo "install: $dir doesn't contain scripts/settings_hooks.py; is it the right repo?" >&2
    exit 1
  fi
  echo "    checkout: $dir ($(git -C "$dir" config --get remote.origin.url), $(git -C "$dir" config --get claude-agents.branch))"

  router_agents="$(option "${CLAUDE_ROUTER_AGENTS:-}" router-agents all)"
  router_server="$(option "${CLAUDE_ROUTER_SERVER:-}" router-server liz)"
  router_tool="$(option "${CLAUDE_ROUTER_TOOL:-}" router-tool p1-gozcu-router)"
  mcp_url="$(option "${STATUS402_MCP_URL:-}" mcp-url "$DEFAULT_MCP_URL")"
  git -C "$dir" config claude-agents.router "$router"
  git -C "$dir" config claude-agents.router-agents "$router_agents"
  git -C "$dir" config claude-agents.router-server "$router_server"
  git -C "$dir" config claude-agents.router-tool "$router_tool"
  git -C "$dir" config claude-agents.mcp-url "$mcp_url"

  previous_risk="$(option "" risk-hook off)"
  risk_no_deny="$(option "${CLAUDE_RISK_NO_DENY:-}" risk-no-deny true)"
  case "$risk_no_deny" in
    true | false) ;;
    *) echo "install: CLAUDE_RISK_NO_DENY must be true or false (got '$risk_no_deny')" >&2; exit 1 ;;
  esac
  session_sync="$(option "${CLAUDE_SESSION_SYNC:-}" session-sync false)"
  case "$session_sync" in
    true | false) ;;
    *) echo "install: CLAUDE_SESSION_SYNC must be true or false (got '$session_sync')" >&2; exit 1 ;;
  esac
  git -C "$dir" config claude-agents.session-sync "$session_sync"
  git -C "$dir" config claude-agents.risk-hook "$risk"
  git -C "$dir" config claude-agents.risk-no-deny "$risk_no_deny"

  bash "$dir/scripts/sync-agents.sh" "$dir"

  echo "2/4 MCP server (tools: ${tools:-none})"
  server_ready=1
  if [ "$router" = "mcp" ] || [ "$risk" = "on" ]; then
    case "$router_server" in
      "claude.ai "*) echo "    using the $router_server connector from claude.ai" ;;
      *) register_server ;;
    esac
  fi

  echo "3/4 Hooks -> $HOME/.claude/settings.json"
  python3 "$dir/scripts/settings_hooks.py" install --dir-in-hook "$dir_in_hook" --router "$router" \
    --server "$router_server" --tool "$router_tool" --agents "$router_agents" --repo "$dir" \
    --sync "$([ "$session_sync" = true ] && echo on || echo off)"
  if [ "$session_sync" = false ]; then
    echo "    the sync hook was left out (CLAUDE_SESSION_SYNC=true adds it): the agents won't update on their own."
    echo "    To update, re-run the installer or run: $dir/scripts/sync-agents.sh"
    if [ "$router" = "mcp" ]; then
      echo "    The router's agent list is refreshed by the same two commands, and only by them."
    fi
  fi
  if [ "$risk" = "on" ]; then
    install_risk_hook
  elif [ "$previous_risk" = "on" ]; then
    python3 "$dir/scripts/risk_hook.py" uninstall
  fi

  echo "4/4 Routing rules -> $HOME/.claude/CLAUDE.md"
  edit_claude_md install

  echo
  echo "Done. Restart Claude Code, then run /hooks to check the hooks are listed."
}

do_uninstall() {
  local have_checkout=""
  if [ -d "$dir/.git" ] && git -C "$dir" config --get claude-agents.branch >/dev/null; then
    have_checkout=1
  fi
  router_server="$(option "" router-server liz)"
  router_tool="$(option "" router-tool p1-gozcu-router)"
  risk="$(option "" risk-hook off)"

  echo "1/4 Agents"
  if [ -n "$have_checkout" ]; then
    python3 "$dir/scripts/deploy_agents.py" --repo "$dir" --uninstall
  else
    echo "    no checkout at $dir; agent files left in place"
  fi

  # Hooks go first, so that the server step sees which hooks still call the server.
  echo "2/4 Hooks -> $HOME/.claude/settings.json"
  if [ -n "$have_checkout" ]; then
    python3 "$dir/scripts/settings_hooks.py" uninstall --dir-in-hook "$dir_in_hook" --tool "$router_tool"
    if [ "$risk" = "on" ]; then python3 "$dir/scripts/risk_hook.py" uninstall; fi
  else
    echo "    no checkout at $dir; remove the hooks by hand (see docs/installer.md)"
  fi

  echo "3/4 MCP server"
  unregister_server

  echo "4/4 Routing rules -> $HOME/.claude/CLAUDE.md"
  edit_claude_md uninstall

  if [ -n "$have_checkout" ]; then
    rm -rf "$dir"
    echo "Removed the checkout at $dir."
  fi
  echo "Done. Restart Claude Code."
}

# Registers the status402 MCP server for all projects (user scope) and signs in
# through your browser. status402 supports OAuth dynamic client registration, so
# there is no token: Claude Code registers itself as a client and keeps the
# credentials. A failure here doesn't stop the install; the router stays silent
# until the sign-in is done.
register_server() {
  if ! python3 "$dir/scripts/mcp_server.py" ensure --server "$router_server" --url "$mcp_url" \
       --repo "$dir" <"$(sign_in_input)"; then
    server_ready=""
    if [ "$router" = "mcp" ]; then
      echo "    warning: the router won't add notes until the MCP server is registered and signed in"
    fi
  fi
}

# The sign-in needs a terminal, and under `curl | bash` stdin is the script.
sign_in_input() {
  if { : </dev/tty; } 2>/dev/null; then echo /dev/tty; else echo /dev/null; fi
}

# Adds the risk-check hook on the router's MCP server. risk_hook.py only writes
# the hook once the server is signed in; a failure here doesn't stop the install.
install_risk_hook() {
  if [ -n "$server_ready" ] &&
     python3 "$dir/scripts/risk_hook.py" install --server "$router_server" --url "$mcp_url" \
       --no-deny "$risk_no_deny" <"$(sign_in_input)"; then
    return
  fi
  echo "    warning: the risk check wasn't added; re-run the installer once the MCP server is signed in"
}

unregister_server() {
  local registered=""
  case "$router_server" in "claude.ai "*) echo "    $router_server is a claude.ai connector; left alone"; return ;; esac
  if [ -n "$have_checkout" ]; then
    registered="$(git -C "$dir" config --get claude-agents.registered-server || true)"
  fi
  case "$(server_state "$registered")" in
    ours) ;;
    in-use) echo "    MCP server '$router_server': another hook still uses it; left registered"; return ;;
    kept)
      echo "    MCP server '$router_server': it was registered before this install, so it's left registered"
      echo "    to remove it, run: claude mcp remove $router_server --scope user"
      return ;;
    *) echo "    MCP server '$router_server': not registered for all projects; nothing to remove"; return ;;
  esac
  if command -v claude >/dev/null; then
    (cd "$HOME" && claude mcp remove "$router_server" --scope user >/dev/null)
    echo "    removed the user-scope MCP server '$router_server'"
  else
    echo "    the claude CLI isn't on your PATH; run: claude mcp remove $router_server --scope user"
  fi
}

# Whether to remove the user-scope server entry in ~/.claude.json (read only). Prints nothing
# if there is no entry, in-use if a hook other than the router calls the server, ours if this
# installer registered it (REGISTERED names it), and kept if it was already there when the
# installer ran.
server_state() {
  python3 - "$HOME/.claude.json" "$HOME/.claude/settings.json" "$router_server" "$router_tool" "$1" <<'PY'
import json, sys
config, settings, name, tool, registered = sys.argv[1:6]

def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

current = (read(config).get("mcpServers") or {}).get(name)
if not isinstance(current, dict):
    sys.exit()
ours = name == registered
try:
    others = [h for groups in read(settings).get("hooks", {}).values() for g in groups
              for h in g.get("hooks", [])
              if h.get("type") == "mcp_tool" and h.get("server") == name and h.get("tool") != tool]
except (AttributeError, TypeError):
    others = []
print("in-use" if others else "ours" if ours else "kept")
PY
}

edit_claude_md() {
  python3 - "$1" "$HOME/.claude/CLAUDE.md" "@${dir_in_md// /\\ }/setup/routing-rules.md" <<'PY'
import os, sys

mode, path, line = sys.argv[1], sys.argv[2], sys.argv[3]
header = "## Team agents"

try:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
except FileNotFoundError:
    lines = []

def ours(text):
    return text.strip() == line

if mode == "install":
    if any(ours(l) for l in lines):
        print("    already imported")
        sys.exit()
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ([""] if lines else []) + [header, line]
    print(f"    added: {line}")
else:
    kept = []
    for l in lines:
        if ours(l):
            if kept and kept[-1].strip() == header:
                kept.pop()
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        kept.append(l)
    if kept == lines:
        print("    no import to remove")
        sys.exit()
    lines = kept
    print("    removed the routing rules import")

os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + ("\n" if lines else ""))
PY
}

main "$@"
