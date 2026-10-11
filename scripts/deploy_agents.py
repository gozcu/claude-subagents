#!/usr/bin/env python3
"""Install this repo's agents directly into ~/.claude/agents/.

sync-agents.sh runs this after updating the checkout. It needs only the
Python standard library.

Rules:
- Every .md file at the repo root with a `name:` in its frontmatter is an
  agent, copied to ~/.claude/agents/<same file name>.
- Before anything is overwritten or would clash, it is moved to
  ~/.claude/agent-backups/<timestamp>/. That covers a file with the same
  file name, and any .md under ~/.claude/agents/ declaring the same agent name
  (two agents with one name make Claude Code pick one arbitrarily).
- A file this script installed earlier and nobody has edited is replaced
  without a backup; that version is still in the repo's git history.
- An agent removed from the repo is deleted if unedited, backed up if edited.
- Installed files and their checksums are recorded in the checkout's
  .git/claude-agents-manifest.json.

Usage:
  deploy_agents.py --repo DIR [--hook] [--uninstall]
    --hook       report backups to Claude Code as a systemMessage (JSON on
                 stdout) and send everything else to stderr
    --uninstall  remove the installed agents (edited ones are backed up)
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import time

HOME = pathlib.Path.home()
FIELD_RE = re.compile(r"^([A-Za-z][\w-]*):\s*(.*)$")


def frontmatter(path):
    """Top-level scalar fields of a Markdown file's YAML frontmatter.

    Standard library only, so the hooks need no extra packages. Handles plain
    and quoted values and folded (>) or literal (|) blocks, which covers
    agent definitions; lists and maps are skipped.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 3)
    lines = text[4:end if end != -1 else len(text)].splitlines()
    fields, i = {}, 0
    while i < len(lines):
        match = FIELD_RE.match(lines[i])
        i += 1
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if value[:1] in (">", "|"):
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in " \t"):
                block.append(lines[i].strip())
                i += 1
            value = (" " if value[0] == ">" else "\n").join(b for b in block if b)
        elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


def agent_name(path):
    """Return the frontmatter name of an agent file, or None."""
    return frontmatter(path).get("name") or None


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_atomic(path, data):
    tmp = path.with_name(f".{path.name}.tmp")  # not *.md, so Claude Code ignores it
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Deployer:
    def __init__(self, repo, target, backups):
        self.repo, self.target, self.backups = repo, target, backups
        self.manifest_path = repo / ".git" / "claude-agents-manifest.json"
        self.backup_dir = None
        self.log, self.backed_up = [], []

    def load_manifest(self):
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8")).get("files", {})
        except (OSError, ValueError):
            return {}

    def save_manifest(self, files):
        data = json.dumps({"files": dict(sorted(files.items()))}, indent=2).encode() + b"\n"
        write_atomic(self.manifest_path, data)

    def backup(self, path, reason):
        if self.backup_dir is None:
            stamp = time.strftime("%Y-%m-%d_%H%M%S")
            candidate, n = self.backups / stamp, 1
            while candidate.exists():
                candidate, n = self.backups / f"{stamp}-{n}", n + 1
            self.backup_dir = candidate
        dest = self.backup_dir / path.relative_to(self.target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        self.backed_up.append(str(path.relative_to(self.target)))
        self.log.append(f"backed up {path.relative_to(self.target)} ({reason})")

    def repo_agents(self):
        agents = {}
        for path in sorted(self.repo.glob("*.md")):
            name = agent_name(path)
            if name:
                agents[path.name] = (name, path)
        return agents

    def other_agent_files(self, skip):
        """Every .md under the target except the given root-level file names."""
        for dirpath, dirnames, filenames in os.walk(self.target):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for filename in filenames:
                path = pathlib.Path(dirpath) / filename
                if path.suffix == ".md" and not (path.parent == self.target and filename in skip):
                    yield path

    def remove_managed(self, filename, recorded_sha, why):
        path = self.target / filename
        if not path.exists():
            return
        if sha256(path) == recorded_sha:
            path.unlink()
            self.log.append(f"removed {filename} ({why})")
        else:
            self.backup(path, f"{why}, but edited locally")

    def deploy(self):
        agents = self.repo_agents()
        if not agents:
            raise SystemExit(f"no agent files found at the root of {self.repo}")
        manifest = self.load_manifest()
        self.target.mkdir(parents=True, exist_ok=True)

        # 1. Other files that declare one of our agent names.
        names = {name for name, _ in agents.values()}
        for path in list(self.other_agent_files(skip=set(agents))):
            name = agent_name(path)
            if name in names:
                self.backup(path, f"declares the agent name '{name}'")

        # 2. Install or update each agent.
        for filename, (_, src) in agents.items():
            dest, new = self.target / filename, sha256(src)
            if dest.exists():
                current = sha256(dest)
                if current == new:
                    manifest[filename] = new
                    continue
                recorded = manifest.get(filename)
                if recorded is None:
                    self.backup(dest, "a different file with the same name")
                    self.log.append(f"installed {filename}")
                elif recorded != current:
                    self.backup(dest, "edited locally")
                    self.log.append(f"restored the team version of {filename}")
                else:
                    self.log.append(f"updated {filename}")
            else:
                self.log.append(f"installed {filename}")
            write_atomic(dest, src.read_bytes())
            manifest[filename] = new

        # 3. Agents removed from the repo.
        for filename in [f for f in manifest if f not in agents]:
            self.remove_managed(filename, manifest.pop(filename), "removed from the repo")

        self.save_manifest(manifest)

    def uninstall(self):
        manifest = self.load_manifest()
        for filename, recorded in manifest.items():
            self.remove_managed(filename, recorded, "uninstalled")
        self.save_manifest({})


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", required=True, type=pathlib.Path)
    parser.add_argument("--target", type=pathlib.Path, default=HOME / ".claude" / "agents")
    parser.add_argument("--backups", type=pathlib.Path, default=HOME / ".claude" / "agent-backups")
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    deployer = Deployer(args.repo.resolve(), args.target.expanduser(), args.backups.expanduser())
    try:
        deployer.uninstall() if args.uninstall else deployer.deploy()
    except (OSError, SystemExit) as exc:
        message = f"Team agents sync failed: {exc}"
        if args.hook:
            print(json.dumps({"systemMessage": message}))
            return 0
        print(message, file=sys.stderr)
        return 1

    if args.hook:
        for line in deployer.log:
            print(f"agent sync: {line}", file=sys.stderr)
        if deployer.backed_up:
            print(json.dumps({"systemMessage": (
                f"Team agents: moved {len(deployer.backed_up)} conflicting agent file(s) "
                f"({', '.join(deployer.backed_up)}) to {deployer.backup_dir}"
            )}))
    else:
        for line in deployer.log or ["agents already up to date"]:
            print(f"    {line}")
        if deployer.backup_dir:
            print(f"    backups: {deployer.backup_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
