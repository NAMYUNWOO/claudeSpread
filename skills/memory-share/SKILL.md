---
name: memory-share
description: Share project auto memory over LAN or relay
user-invocable: true
arguments:
  - name: passphrase
    description: Shared passphrase for encryption (required)
    required: true
  - name: --raw
    description: Send memory files as-is without distillation
    required: false
  - name: --relay
    description: Use WebSocket relay server for remote sharing
    required: false
---

# Memory Share

You are sharing the project's Claude Code auto memory with another machine or person.

There are two modes: **distilled** (default) and **raw** (`--raw`).

## Distilled Mode (default)

### Step 1: Read memory files

Read all files from your auto memory directory (`~/.claude/projects/<project>/memory/`):
- `MEMORY.md` (always present)
- Any additional topic files (`debugging.md`, `patterns.md`, etc.)

### Step 2: Distill the memory

Analyze all memory files and produce a single, well-organized Markdown document:

```markdown
# Project Memory Distillation

## Project Overview
(Brief description of the project based on accumulated memory)

## Key Patterns & Conventions
- (coding conventions, architectural patterns, etc.)

## Important File Paths
- (critical files and their roles)

## Debugging Insights
- (known issues, solutions, workarounds)

## Workflow Preferences
- (user preferences for tools, testing, deployment)

## Architecture Notes
- (key architectural decisions and their rationale)
```

Consolidate, deduplicate, and organize the information clearly. Remove session-specific noise and keep only stable, reusable knowledge.

Write the distilled memory to `${CLAUDE_PLUGIN_ROOT}/.tmp/claude-memory-payload.md`.

### Step 3: Start the sharing server

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve.py "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-memory-payload.md
```

Tell the user:
- Instruct the receiver to run: `/claude-spread:memory-receive {{passphrase}}`
- The server stays open for multiple receivers until Ctrl+C

## Raw Mode (`--raw`)

### Step 1: Bundle memory files

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/memory-share/scripts/bundle.py ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-memory-payload.json
```

This bundles all `.md` files from the auto memory directory into a JSON file.

### Step 2: Start the sharing server

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve.py "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-memory-payload.json
```

Tell the user:
- Instruct the receiver to run: `/claude-spread:memory-receive {{passphrase}}`
- The server stays open for multiple receivers until Ctrl+C

## Relay Mode (Remote Sharing)

If the user passes `--relay`, add the `--relay` flag to the serve.py command:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve.py --relay "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-memory-payload.md
```

Tell the user:
- The room code shown in the output
- Instruct the receiver to run: `/claude-spread:memory-receive --relay --room <room_code> {{passphrase}}`
- Requires `pip install websockets` if not already installed
