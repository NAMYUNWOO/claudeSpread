#!/usr/bin/env python3
"""
Install a received session .jsonl into the local Claude Code project.
Reads JSON from stdin: {"sessionId", "metadata": {...}, "jsonl_content": "..."}
Creates a new session with a fresh UUID to avoid collisions,
saves the .jsonl file, and updates sessions-index.json atomically.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def get_git_root() -> str | None:
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
    return path.replace("/", "-")


def get_sessions_dir() -> Path | None:
    git_root = get_git_root()
    if not git_root:
        print("Error: not in a git repository", file=sys.stderr)
        return None
    encoded = encode_path(git_root)
    sessions_dir = Path.home() / ".claude" / "projects" / encoded
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


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
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    original_session_id = data.get("sessionId", "")
    metadata = data.get("metadata", {})
    jsonl_content = data.get("jsonl_content", "")

    if not jsonl_content:
        print("Error: no jsonl_content in input", file=sys.stderr)
        sys.exit(1)

    sessions_dir = get_sessions_dir()
    if sessions_dir is None:
        sys.exit(1)

    # Generate new UUID to avoid collisions
    new_session_id = str(uuid.uuid4())
    jsonl_path = sessions_dir / f"{new_session_id}.jsonl"

    # Write .jsonl file
    jsonl_path.write_text(jsonl_content, encoding="utf-8")
    print(f"  Saved session file: {jsonl_path.name}", flush=True)

    # Update sessions-index.json
    index_path = sessions_dir / "sessions-index.json"

    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    else:
        git_root = get_git_root() or os.getcwd()
        index = {
            "version": 1,
            "entries": [],
            "originalPath": git_root,
        }

    # Build new entry from metadata
    new_entry = {
        "sessionId": new_session_id,
        "fullPath": str(jsonl_path),
        "summary": metadata.get("summary", f"(received from {original_session_id[:8]})"),
        "firstPrompt": metadata.get("firstPrompt", ""),
        "messageCount": metadata.get("messageCount", 0),
        "created": metadata.get("created", ""),
        "modified": metadata.get("modified", ""),
        "gitBranch": metadata.get("gitBranch", ""),
        "projectPath": metadata.get("projectPath", ""),
        "isSidechain": metadata.get("isSidechain", False),
    }

    index["entries"].append(new_entry)

    # Atomic write: tmpfile → rename
    fd, tmp_path = tempfile.mkstemp(dir=str(sessions_dir), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
        os.rename(tmp_path, str(index_path))
    except Exception:
        os.unlink(tmp_path)
        raise

    print(f"  Updated sessions-index.json ({len(index['entries'])} entries)", flush=True)
    print(f"  New session ID: {new_session_id}", flush=True)

    # Output the new session ID for the caller
    print(json.dumps({"newSessionId": new_session_id}))


if __name__ == "__main__":
    main()
