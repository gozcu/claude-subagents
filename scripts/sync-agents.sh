#!/usr/bin/env bash
# Keeps the team agents up to date: updates the local checkout of this repo,
# then installs its agents directly into ~/.claude/agents/.
#
# install.sh registers it as a Claude Code SessionStart hook:
#
#   "$HOME/.claude/claude-agents/scripts/sync-agents.sh" --hook "$HOME/.claude/claude-agents"
#
# Usage: sync-agents.sh [--hook] [CHECKOUT_DIR]
#   --hook                report to Claude Code (JSON on stdout) instead of the terminal
#   CHECKOUT_DIR          defaults to $CLAUDE_AGENTS_DIR, then ~/.claude/claude-agents
#   CLAUDE_AGENTS_REPO    git URL or path to clone from if the checkout is missing
#   CLAUDE_AGENTS_BRANCH  branch or tag to track (default: the one recorded at install)
#
# Files in ~/.claude/agents/ that would be overwritten or clash with a team
# agent are moved to ~/.claude/agent-backups/<timestamp>/ first; see
# deploy_agents.py for the rules.
#
# Only checkouts created or adopted by install.sh are updated (they carry the
# git config key claude-agents.branch), so a development checkout is never reset.
#
# Everything runs inside main() so bash reads the whole file before running
# it: this script runs from the same checkout it updates.
set -u

# Global, not local to main(): the EXIT trap runs after main() has returned.
SYNC_LOCK=""
trap 'if [ -n "$SYNC_LOCK" ]; then rmdir "$SYNC_LOCK" 2>/dev/null; fi' EXIT

main() {
  # A plain string, not an array: macOS ships bash 3.2, where an empty array
  # under `set -u` is an error.
  local hook=""
  if [ "${1:-}" = "--hook" ]; then hook="--hook"; shift; fi
  local repo="${1:-${CLAUDE_AGENTS_DIR:-$HOME/.claude/claude-agents}}"
  local repo_url="${CLAUDE_AGENTS_REPO:-https://github.com/gozcu/claude-subagents.git}"
  local branch lock

  # Never hang a session waiting for credentials or a slow network.
  export GIT_TERMINAL_PROMPT=0
  export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=5}"

  if [ -d "$repo/.git" ]; then
    branch="$(git -C "$repo" config --get claude-agents.branch)" || {
      echo "agent sync: $repo is not a checkout created by install.sh; not updating it" >&2
      return
    }
    branch="${CLAUDE_AGENTS_BRANCH:-$branch}"

    # One sync at a time when several sessions start together.
    lock="$repo/.git/claude-agents-sync.lock"
    if ! mkdir "$lock" 2>/dev/null; then
      if [ -n "$(find "$lock" -maxdepth 0 -mmin +2 2>/dev/null)" ]; then
        rmdir "$lock" 2>/dev/null; mkdir "$lock" 2>/dev/null || return
      else
        echo "agent sync: another sync is running" >&2
        return
      fi
    fi
    SYNC_LOCK="$lock"

    if git -C "$repo" fetch --quiet --depth 1 origin "$branch" 2>/dev/null; then
      # The checkout is read-only: local edits are discarded.
      git -C "$repo" reset --quiet --hard FETCH_HEAD
    else
      echo "agent sync: fetch failed, installing the cached agents" >&2
    fi
  elif [ -e "$repo" ]; then
    echo "agent sync: $repo exists but is not a git checkout; skipping" >&2
    return
  else
    branch="${CLAUDE_AGENTS_BRANCH:-main}"
    mkdir -p "$(dirname "$repo")"
    if ! git clone --quiet --depth 1 --branch "$branch" "$repo_url" "$repo" 2>/dev/null; then
      echo "agent sync: clone failed for $repo_url ($branch)" >&2
      return
    fi
    git -C "$repo" config claude-agents.branch "$branch"
  fi

  python3 "$repo/scripts/deploy_agents.py" --repo "$repo" ${hook:+"$hook"} || return

  # Keep the MCP router's agent list in step with the MD files it was built from.
  if [ "$(git -C "$repo" config --get claude-agents.router || true)" = "mcp" ]; then
    python3 "$repo/scripts/settings_hooks.py" refresh --repo "$repo" \
      --server "$(git -C "$repo" config --get claude-agents.router-server || echo liz)" \
      --tool "$(git -C "$repo" config --get claude-agents.router-tool || echo p2-gozcu-router)" \
      --agents "$(git -C "$repo" config --get claude-agents.router-agents || echo all)" 2>&1 >/dev/null | sed 's/^/agent sync: /' >&2
  fi
}

if main "$@"; then
  exit 0
else
  status=$?
  # As a hook, never block a session over a sync failure. In a terminal,
  # report it so install.sh can stop.
  case " $* " in *" --hook "*) exit 0 ;; esac
  exit "$status"
fi
