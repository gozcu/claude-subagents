#!/usr/bin/env python3
"""Tests for scripts/deploy_agents.py: how agents are installed into
~/.claude/agents/ and when existing files are backed up.

Runs against temporary folders; nothing outside them is touched.
Usage: python3 scripts/test_sync.py
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "scripts" / "deploy_agents.py"
FAILURES = []


def agent(name, body="Do the thing."):
    return f"---\nname: {name}\ndescription: test agent {name}\n---\n\n{body}\n"


class Sandbox:
    def __init__(self):
        self.base = pathlib.Path(tempfile.mkdtemp(prefix="deploy-test-"))
        self.repo = self.base / "repo"
        self.target = self.base / "agents"
        self.backups = self.base / "backups"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "README.md").write_text("# not an agent\n")

    def repo_agent(self, name, body="Do the thing."):
        (self.repo / f"{name}.md").write_text(agent(name, body))

    def run(self, *extra):
        result = subprocess.run(
            [sys.executable, str(DEPLOY), "--repo", str(self.repo), "--target", str(self.target),
             "--backups", str(self.backups), *extra],
            capture_output=True, text=True, timeout=30,
        )
        return result

    def backed_up(self):
        if not self.backups.exists():
            return []
        return sorted(str(p.relative_to(self.backups)).split("/", 1)[1]
                      for p in self.backups.rglob("*.md"))

    def cleanup(self):
        shutil.rmtree(self.base)


def check(label, condition, detail=""):
    if not condition:
        FAILURES.append(f"{label}{': ' + detail if detail else ''}")


def scenario(fn):
    sandbox = Sandbox()
    try:
        fn(sandbox)
    except Exception as exc:  # report and keep going
        FAILURES.append(f"{fn.__name__}: crashed: {exc!r}")
    finally:
        sandbox.cleanup()
    return fn


@scenario
def fresh_install(s):
    s.repo_agent("debugger"); s.repo_agent("reviewer")
    r = s.run()
    check("fresh install exits 0", r.returncode == 0, r.stderr)
    check("fresh install copies agents", (s.target / "debugger.md").read_text() == agent("debugger"))
    check("fresh install skips README", not (s.target / "README.md").exists())
    check("fresh install makes no backups", s.backed_up() == [], str(s.backed_up()))
    manifest = json.loads((s.repo / ".git" / "claude-agents-manifest.json").read_text())
    check("manifest records installed files", sorted(manifest["files"]) == ["debugger.md", "reviewer.md"])


@scenario
def rerun_is_quiet(s):
    s.repo_agent("debugger"); s.run()
    r = s.run()
    check("re-run reports up to date", "already up to date" in r.stdout, r.stdout)
    check("re-run makes no backups", s.backed_up() == [])


@scenario
def team_update_replaces_unedited_copy(s):
    s.repo_agent("debugger", "v1"); s.run()
    s.repo_agent("debugger", "v2")
    r = s.run()
    check("update installs the new version", "v2" in (s.target / "debugger.md").read_text())
    check("update of an unedited copy makes no backup", s.backed_up() == [], str(s.backed_up()))
    check("update is reported", "updated debugger.md" in r.stdout, r.stdout)


@scenario
def locally_edited_copy_is_backed_up(s):
    s.repo_agent("debugger", "v1"); s.run()
    (s.target / "debugger.md").write_text(agent("debugger", "my local edit"))
    s.repo_agent("debugger", "v2"); s.run()
    check("edited copy is backed up", s.backed_up() == ["debugger.md"], str(s.backed_up()))
    check("edited copy is replaced", "v2" in (s.target / "debugger.md").read_text())
    backup = next(s.backups.rglob("debugger.md"))
    check("backup keeps the local edit", "my local edit" in backup.read_text())


@scenario
def local_edit_is_reverted_without_a_team_change(s):
    s.repo_agent("debugger"); s.run()
    (s.target / "debugger.md").write_text(agent("debugger", "my local edit"))
    r = s.run()
    check("edit is backed up even when the team version didn't change", s.backed_up() == ["debugger.md"])
    check("team version is restored", (s.target / "debugger.md").read_text() == agent("debugger"))
    check("reason says edited locally", "debugger.md (edited locally)" in r.stdout, r.stdout)


@scenario
def same_file_name_is_backed_up(s):
    s.target.mkdir(parents=True)
    (s.target / "debugger.md").write_text(agent("my-debugger", "mine"))
    s.repo_agent("debugger"); s.run()
    check("same-file-name file is backed up", s.backed_up() == ["debugger.md"], str(s.backed_up()))
    check("team agent installed in its place", (s.target / "debugger.md").read_text() == agent("debugger"))


@scenario
def same_agent_name_elsewhere_is_backed_up(s):
    (s.target / "personal").mkdir(parents=True)
    (s.target / "personal" / "dbg.md").write_text(agent("debugger", "mine"))
    (s.target / "personal" / "keeper.md").write_text(agent("keeper"))
    (s.target / "notes.md").write_text("# plain notes, no frontmatter\n")
    s.repo_agent("debugger"); r = s.run()
    check("same-agent-name file is backed up", s.backed_up() == ["personal/dbg.md"], str(s.backed_up()))
    check("unrelated agents are untouched", (s.target / "personal" / "keeper.md").exists())
    check("plain notes are untouched", (s.target / "notes.md").exists())
    check("backup reason is reported", "declares the agent name 'debugger'" in r.stdout, r.stdout)


@scenario
def identical_existing_copy_is_adopted(s):
    s.target.mkdir(parents=True)
    (s.target / "debugger.md").write_text(agent("debugger"))
    s.repo_agent("debugger"); s.run()
    check("identical copy is adopted without backup", s.backed_up() == [])


@scenario
def removed_agents(s):
    s.repo_agent("debugger"); s.repo_agent("old"); s.repo_agent("old-edited"); s.run()
    (s.target / "old-edited.md").write_text(agent("old-edited", "edited"))
    (s.repo / "old.md").unlink(); (s.repo / "old-edited.md").unlink()
    s.run()
    check("unedited removed agent is deleted", not (s.target / "old.md").exists())
    check("edited removed agent is backed up", s.backed_up() == ["old-edited.md"], str(s.backed_up()))
    check("remaining agent stays", (s.target / "debugger.md").exists())


@scenario
def uninstall(s):
    s.repo_agent("debugger"); s.repo_agent("reviewer"); s.run()
    (s.target / "reviewer.md").write_text(agent("reviewer", "edited"))
    (s.target / "mine.md").write_text(agent("mine"))
    s.run("--uninstall")
    check("uninstall deletes unedited agents", not (s.target / "debugger.md").exists())
    check("uninstall backs up edited agents", s.backed_up() == ["reviewer.md"], str(s.backed_up()))
    check("uninstall leaves other agents alone", (s.target / "mine.md").exists())


@scenario
def hook_mode_output(s):
    s.repo_agent("debugger"); r = s.run("--hook")
    check("hook mode prints nothing without backups", r.stdout == "", repr(r.stdout))
    (s.target / "debugger.md").write_text(agent("debugger", "edited"))
    s.repo_agent("debugger", "v2"); r = s.run("--hook")
    message = json.loads(r.stdout)["systemMessage"]
    check("hook mode reports backups", "debugger.md" in message and str(s.backups) in message, message)


@scenario
def separate_runs_get_separate_backup_folders(s):
    s.target.mkdir(parents=True)
    s.repo_agent("debugger")
    (s.target / "debugger.md").write_text(agent("x")); s.run()
    (s.target / "debugger.md").write_text(agent("y")); s.run()
    folders = [p for p in s.backups.iterdir()] if s.backups.exists() else []
    check("each run with backups gets its own folder", len(folders) == 2, str(folders))


@scenario
def no_agents_is_an_error(s):
    r = s.run()
    check("empty repo fails in a terminal", r.returncode == 1)
    r = s.run("--hook")
    check("empty repo reports, without failing, as a hook",
          r.returncode == 0 and "failed" in json.loads(r.stdout)["systemMessage"])


def main():
    for failure in FAILURES:
        print(f"FAIL  {failure}")
    print("all sync checks passed" if not FAILURES else f"{len(FAILURES)} sync check(s) failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
