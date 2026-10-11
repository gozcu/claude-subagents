#!/usr/bin/env python3
"""Validate Claude Code subagent definitions in this repo.

Claude Code silently skips agent files with broken frontmatter, so this
catches problems before they reach anyone's machine.

Usage: python3 scripts/validate_agents.py [ROOT]
Exit code is non-zero when any error is found.
"""
import pathlib
import sys

import yaml

MODEL_ALIASES = {"haiku", "sonnet", "opus", "fable", "inherit"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
KNOWN_FIELDS = {
    "name", "description", "tools", "disallowedTools", "model", "permissionMode",
    "maxTurns", "skills", "mcpServers", "hooks", "memory", "background",
    "omitClaudeMd", "effort", "isolation", "color", "initialPrompt", "experimental",
}
SKIP_DIRS = {".git", ".github", "scripts", "setup", "node_modules"}
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_DESCRIPTION_CHARS = 600  # keeps the combined description budget small


def frontmatter(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None  # treated as documentation by Claude Code
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("frontmatter has no closing '---'")
    return yaml.safe_load(text[4:end]) or {}


def main(root: pathlib.Path) -> int:
    errors, warnings, names, colors = [], [], {}, {}
    files = [
        p for p in sorted(root.rglob("*.md"))
        if not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1])
    ]
    agents = 0
    for path in files:
        rel = path.relative_to(root)
        try:
            fm = frontmatter(path)
        except (ValueError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: invalid frontmatter: {exc}")
            continue
        if fm is None or "name" not in fm:
            continue  # documentation file
        agents += 1

        name = str(fm.get("name", ""))
        if name.startswith("-") or ":" in name or len(name) > 256 or not name:
            errors.append(f"{rel}: invalid name '{name}'")
        if name in names:
            errors.append(f"{rel}: duplicate name '{name}' (also in {names[name]})")
        names[name] = rel

        # Layout rules for this repo: sync-agents.sh installs only root-level
        # files, and matches existing agents by file name and by agent name.
        if root == REPO_ROOT:
            if path.parent != root:
                errors.append(f"{rel}: agents must be at the repo root; sync only installs root-level files")
            if path.stem != name:
                errors.append(f"{rel}: file name must match the agent name ({name}.md)")

        desc = fm.get("description")
        if not desc:
            errors.append(f"{rel}: missing description")
        elif len(str(desc)) > MAX_DESCRIPTION_CHARS:
            warnings.append(f"{rel}: description is {len(str(desc))} chars; keep it short")

        model = fm.get("model")
        if model is not None and model not in MODEL_ALIASES and not str(model).startswith("claude-"):
            errors.append(f"{rel}: unknown model '{model}'")

        effort = fm.get("effort")
        if effort is not None and effort not in EFFORTS:
            errors.append(f"{rel}: invalid effort '{effort}'")

        color = fm.get("color")
        if color is not None and color not in COLORS:
            errors.append(f"{rel}: invalid color '{color}'")
        if root == REPO_ROOT and color is not None:
            if color in colors:
                errors.append(f"{rel}: duplicate color '{color}' (also in {colors[color]})")
            colors.setdefault(color, rel)

        for field in ("tools", "disallowedTools"):
            value = fm.get(field)
            if value is not None and not isinstance(value, (str, list)):
                errors.append(f"{rel}: {field} must be a string or list")

        unknown = set(fm) - KNOWN_FIELDS
        if unknown:
            warnings.append(f"{rel}: unknown fields ignored by Claude Code: {sorted(unknown)}")

        body = path.read_text(encoding="utf-8").split("\n---", 2)[-1].strip()
        if not body:
            warnings.append(f"{rel}: empty system prompt")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print(f"{agents} agent(s) checked, {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
