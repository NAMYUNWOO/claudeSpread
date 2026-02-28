#!/usr/bin/env python3
"""
Install a memory bundle JSON into the Claude Code auto memory directory.
Reads JSON from stdin or a file argument.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_git_root() -> str | None:
    """Get the git repository root directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def encode_path(path: str) -> str:
    """Encode a path for use in the Claude projects directory (/ → -)."""
    return path.replace("/", "-")


def get_memory_dir() -> Path | None:
    """Find or create the auto memory directory for the current project."""
    git_root = get_git_root()
    if not git_root:
        print("Error: not in a git repository", file=sys.stderr)
        return None

    encoded = encode_path(git_root)
    memory_dir = Path.home() / ".claude" / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    return memory_dir


def install_bundle(bundle: dict, memory_dir: Path) -> list[str]:
    """Install memory bundle files into the memory directory.
    Returns list of installed file names.
    """
    installed = []
    files = bundle.get("files", {})

    for filename, content in files.items():
        # Sanitize filename - only allow .md files, no path traversal
        if not filename.endswith(".md") or "/" in filename or "\\" in filename:
            print(f"Warning: skipping invalid filename: {filename}", file=sys.stderr)
            continue

        target = memory_dir / filename

        # Back up existing file
        if target.exists():
            backup = target.with_suffix(target.suffix + ".bak")
            shutil.copy2(target, backup)
            print(f"  Backed up: {filename} → {filename}.bak", flush=True)

        target.write_text(content, encoding="utf-8")
        installed.append(filename)
        print(f"  Saved: {filename}", flush=True)

    return installed


def main():
    # Read JSON input
    if len(sys.argv) > 1 and sys.argv[1] != "-":
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        print("Error: empty input", file=sys.stderr)
        sys.exit(1)

    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if bundle.get("type") != "memory_bundle":
        print("Error: not a memory bundle (missing or wrong 'type' field)", file=sys.stderr)
        sys.exit(1)

    memory_dir = get_memory_dir()
    if memory_dir is None:
        sys.exit(1)

    project = bundle.get("project", "unknown")
    print(f"Installing memory bundle from project '{project}'...", flush=True)

    installed = install_bundle(bundle, memory_dir)

    if not installed:
        print("Warning: no files were installed", file=sys.stderr)
        sys.exit(1)

    print(f"\nInstalled {len(installed)} file(s) to {memory_dir}", flush=True)


if __name__ == "__main__":
    main()
