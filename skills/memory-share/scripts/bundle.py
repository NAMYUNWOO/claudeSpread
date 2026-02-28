#!/usr/bin/env python3
"""
Bundle all .md files from the Claude Code auto memory directory into a JSON file.
"""

import json
import os
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
    """Find the auto memory directory for the current project."""
    git_root = get_git_root()
    if not git_root:
        print("Error: not in a git repository", file=sys.stderr)
        return None

    encoded = encode_path(git_root)
    memory_dir = Path.home() / ".claude" / "projects" / encoded / "memory"

    if not memory_dir.is_dir():
        print(f"Error: memory directory not found: {memory_dir}", file=sys.stderr)
        return None

    return memory_dir


def bundle_memory(memory_dir: Path) -> dict:
    """Read all .md files from memory directory and create a bundle."""
    files = {}
    for md_file in sorted(memory_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            files[md_file.name] = content
        except Exception as e:
            print(f"Warning: could not read {md_file.name}: {e}", file=sys.stderr)

    # Extract project name from git root
    git_root = get_git_root()
    project_name = os.path.basename(git_root) if git_root else "unknown"

    return {
        "type": "memory_bundle",
        "project": project_name,
        "files": files,
    }


def main():
    memory_dir = get_memory_dir()
    if memory_dir is None:
        sys.exit(1)

    bundle = bundle_memory(memory_dir)

    if not bundle["files"]:
        print("Error: no .md files found in memory directory", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(bundle, ensure_ascii=False, indent=2)

    # Write to file if path provided, otherwise stdout
    if len(sys.argv) > 1:
        output_path = sys.argv[1]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Bundled {len(bundle['files'])} file(s) → {output_path}", flush=True)
    else:
        print(output)


if __name__ == "__main__":
    main()
