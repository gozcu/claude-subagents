#!/usr/bin/env python3
"""Tests for scripts/settings_hooks.py.

Runs against temporary folders; nothing outside them is touched.
Usage: python3 scripts/test_settings.py
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "scripts" / "settings_hooks.py"
DIR = "$HOME/.claude/claude-agents"
FAILURES = []


def check(label, condition, detail=""):
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


class Sandbox:
    def __init__(self):
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="settings-test-"))
        self.settings = self.base / "settings.json"
        self.agents = self.base / "agents"
        self.agents.mkdir()
        for path in ROOT.glob("*.md"):
            if path.name != "README.md":
                shutil.copy(path, self.agents / path.name)

    def run(self, command, *extra):
        result = subprocess.run(
            [sys.executable, str(HOOKS), command, "--settings", str(self.settings),
             "--agents-dir", str(self.agents), "--repo", str(ROOT), "--dir-in-hook", DIR, *extra],
            capture_output=True, text=True, timeout=30)
        return result

    def data(self):
        return json.loads(self.settings.read_text())

    def handlers(self, event):
        return [h for g in self.data().get("hooks", {}).get(event, []) for h in g["hooks"]]

    def cleanup(self):
        shutil.rmtree(self.base)


def scenario(fn):
    sandbox = Sandbox()
    try:
        fn(sandbox)
    except Exception as exc:
        FAILURES.append(f"{fn.__name__}: crashed: {exc!r}")
    finally:
        sandbox.cleanup()
    return fn


@scenario
def mcp_router_shape(s):
    r = s.run("install", "--agents", "quick-fixer, implementer")
    check("mcp install exits 0", r.returncode == 0, r.stderr)
    [router] = s.handlers("UserPromptSubmit")
    check("router is an mcp_tool hook", router["type"] == "mcp_tool")
    check("router has only supported fields", set(router) == {"type", "server", "tool", "input", "timeout"},
          str(sorted(router)))
    check("router defaults", (router["server"], router["tool"]) == ("liz", "p2-gozcu-router"))
    check("prompt is substituted by Claude Code", router["input"]["prompt"] == "${prompt}")
    check("only the named agents are sent", list(router["input"]["agents"]) == ["quick-fixer", "implementer"])
    check("descriptions come from the MD files",
          router["input"]["agents"]["quick-fixer"].startswith("Use for small, mechanical"))
    groups = s.data()["hooks"]["UserPromptSubmit"]
    check("no matcher on UserPromptSubmit", all("matcher" not in g for g in groups))


@scenario
def all_agents(s):
    s.run("install")
    agents = s.handlers("UserPromptSubmit")[0]["input"]["agents"]
    expected = sorted(p.stem for p in ROOT.glob("*.md") if p.name != "README.md")
    check("'all' sends every repo agent", sorted(agents) == expected, str(sorted(agents)))


@scenario
def idempotent_and_preserves_other_settings(s):
    s.settings.write_text(json.dumps({"model": "sonnet", "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/guard.sh"}]}]}}))
    s.run("install")
    first = s.settings.read_text()
    r = s.run("install")
    check("re-run changes nothing", s.settings.read_text() == first)
    check("re-run makes no new backup", "backup" not in r.stdout, r.stdout)
    data = s.data()
    check("other settings kept", data["model"] == "sonnet" and data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "~/guard.sh")
    check("one sync hook", len(s.handlers("SessionStart")) == 1)


@scenario
def switching_router_modes(s):
    s.run("install")
    s.run("install", "--router", "off")
    check("off removes the router", s.handlers("UserPromptSubmit") == [])
    check("off keeps the sync hook", len(s.handlers("SessionStart")) == 1)
    s.run("install", "--router", "mcp")
    kinds = [h.get("type") for h in s.handlers("UserPromptSubmit")]
    check("mcp mode adds the router back", kinds == ["mcp_tool"], str(kinds))


@scenario
def sync_hook_can_be_left_out(s):
    s.settings.write_text(json.dumps({"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "~/other-start.sh"}]}]}}))
    r = s.run("install", "--sync", "off")
    check("sync off exits 0", r.returncode == 0, r.stderr)
    check("sync off adds no sync hook", [h["command"] for h in s.handlers("SessionStart")] == ["~/other-start.sh"])
    check("sync off says so", "no sync hook" in r.stdout, r.stdout)
    check("sync off still adds the router", [h.get("type") for h in s.handlers("UserPromptSubmit")] == ["mcp_tool"])
    first = s.settings.read_text()
    r = s.run("install", "--sync", "off")
    check("sync off re-run changes nothing", s.settings.read_text() == first)
    check("sync off re-run makes no backup", "backup" not in r.stdout, r.stdout)


@scenario
def sync_off_removes_an_earlier_hook(s):
    s.run("install")
    check("the sync hook starts out present", len(s.handlers("SessionStart")) == 1)
    r = s.run("install", "--sync", "off")
    check("sync off removes the earlier hook", s.handlers("SessionStart") == [], str(s.data()))
    check("sync off reports the removal", "removed sync hook" in r.stdout, r.stdout)
    check("sync off leaves the router", len(s.handlers("UserPromptSubmit")) == 1)
    s.run("install", "--sync", "on")
    check("sync on adds it back", len(s.handlers("SessionStart")) == 1)


@scenario
def sync_off_keeps_other_session_hooks(s):
    s.settings.write_text(json.dumps({"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "~/other-start.sh"}]}]}}))
    s.run("install")
    s.run("install", "--sync", "off")
    check("only our sync hook is removed", [h["command"] for h in s.handlers("SessionStart")] == ["~/other-start.sh"])


@scenario
def uninstall_after_sync_off(s):
    s.run("install", "--sync", "off")
    r = s.run("uninstall")
    check("uninstall without a sync hook succeeds", r.returncode == 0, r.stderr)
    check("uninstall leaves no hooks", "hooks" not in s.data(), str(s.data()))


@scenario
def sync_rejects_other_values(s):
    r = s.run("install", "--sync", "maybe")
    check("sync takes on or off", r.returncode == 2, r.stderr)


@scenario
def unknown_agent_fails_cleanly(s):
    r = s.run("install", "--agents", "debugger nonexistent")
    check("unknown agent fails", r.returncode == 1 and "nonexistent" in r.stderr, r.stderr)
    check("nothing written on failure", not s.settings.exists())


@scenario
def refresh_follows_md_files(s):
    s.run("install", "--agents", "debugger,reviewer")
    path = s.agents / "debugger.md"
    path.write_text(path.read_text().replace("description: Use for diagnosing", "description: CHANGED Use for diagnosing"))
    r = s.run("refresh", "--agents", "debugger,reviewer")
    agents = s.handlers("UserPromptSubmit")[0]["input"]["agents"]
    check("refresh picks up the new description", agents["debugger"].startswith("CHANGED"))
    check("refresh reports the update", "router agents updated" in r.stderr, r.stderr)
    before = s.settings.read_text()
    r = s.run("refresh", "--agents", "debugger,reviewer")
    check("refresh with no change is silent", r.stderr == "" and s.settings.read_text() == before, r.stderr)
    (s.agents / "reviewer.md").unlink()
    r = s.run("refresh", "--agents", "debugger,reviewer")
    check("refresh skips a missing agent with a warning",
          list(s.handlers("UserPromptSubmit")[0]["input"]["agents"]) == ["debugger"] and "skipped 'reviewer'" in r.stderr)


@scenario
def refresh_without_router_does_nothing(s):
    s.run("install", "--router", "off")
    before = s.settings.read_text()
    s.run("refresh")
    check("refresh leaves a setup without a router alone", s.settings.read_text() == before)


@scenario
def uninstall(s):
    s.settings.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/guard.sh"}]}]}}))
    s.run("install")
    s.run("uninstall")
    data = s.data()
    check("uninstall removes only our hooks", list(data["hooks"]) == ["PreToolUse"], str(data))


def main():
    for failure in FAILURES:
        print(f"FAIL  {failure}")
    print("all settings checks passed" if not FAILURES else f"{len(FAILURES)} settings check(s) failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
