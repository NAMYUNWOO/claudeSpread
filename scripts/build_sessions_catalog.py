#!/usr/bin/env python3
"""
Build a sessions catalog JSON from raw .jsonl session files.
Scans ~/.claude/projects/<encoded-path>/*.jsonl and extracts metadata.
Outputs catalog JSON to stdout or a specified file.

Usage:
  build_sessions_catalog.py [output_file]
  build_sessions_catalog.py              # stdout
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


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


def get_sessions_dir() -> str | None:
    git_root = get_git_root()
    if not git_root:
        # Fallback: use CWD
        git_root = os.getcwd()
    encoded = encode_path(git_root)
    sessions_dir = os.path.join(os.path.expanduser("~"), ".claude", "projects", encoded)
    if not os.path.isdir(sessions_dir):
        return None
    return sessions_dir


def extract_session_metadata(jsonl_path: str) -> dict | None:
    """Extract metadata from a .jsonl session file."""
    session_id = os.path.splitext(os.path.basename(jsonl_path))[0]
    first_prompt = ""
    message_count = 0
    summary = ""

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message_count += 1

                # Extract first user prompt
                if not first_prompt and obj.get("type") == "user":
                    msg = obj.get("message", {})
                    if isinstance(msg, dict):
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    text = c["text"]
                                    # Skip skill invocation markers
                                    if not text.startswith("<command"):
                                        first_prompt = text[:200]
                                        break
                        elif isinstance(content, str) and not content.startswith("<command"):
                            first_prompt = content[:200]

                # Extract summary from summary-type messages if present
                if obj.get("type") == "summary":
                    summary = (obj.get("summary") or "")[:200]

    except Exception as e:
        print(f"Warning: failed to read {jsonl_path}: {e}", file=sys.stderr)
        return None

    if message_count == 0:
        return None

    stat = os.stat(jsonl_path)
    created = datetime.fromtimestamp(stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_ctime,
                                     tz=timezone.utc).isoformat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    return {
        "sessionId": session_id,
        "fullPath": os.path.abspath(jsonl_path),
        "summary": summary,
        "firstPrompt": first_prompt,
        "messageCount": message_count,
        "created": created,
        "modified": modified,
        "gitBranch": "",
        "projectPath": get_git_root() or os.getcwd(),
        "isSidechain": False,
    }


def main():
    sessions_dir = get_sessions_dir()
    if not sessions_dir:
        print("Error: sessions directory not found", file=sys.stderr)
        sys.exit(1)

    jsonl_files = glob.glob(os.path.join(sessions_dir, "*.jsonl"))
    if not jsonl_files:
        print("Error: no session .jsonl files found", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {len(jsonl_files)} session file(s)...", file=sys.stderr, flush=True)

    sessions = []
    for path in jsonl_files:
        meta = extract_session_metadata(path)
        if meta:
            sessions.append(meta)

    # Sort by modified (newest first)
    sessions.sort(key=lambda s: s.get("modified", ""), reverse=True)

    catalog = {"sessions": sessions}

    output_file = sys.argv[1] if len(sys.argv) > 1 else None
    catalog_json = json.dumps(catalog, indent=2, ensure_ascii=False)

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(catalog_json)
        print(f"Catalog written to {output_file} ({len(sessions)} sessions)", file=sys.stderr, flush=True)
    else:
        print(catalog_json)

    print(f"Found {len(sessions)} session(s)", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
