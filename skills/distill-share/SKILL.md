---
name: distill-share
description: Distill the current session and share it securely over the local network or via relay
user-invocable: true
arguments:
  - name: passphrase
    description: Shared passphrase for encryption (required)
    required: true
  - name: --relay
    description: Use WebSocket relay server for remote sharing (optional, default relay URL used if no URL provided)
    required: false
---

# Distill & Share

You are sharing a distillation of the current Claude Code session over the local network.

## Step 1: Generate Distillation

Analyze the full conversation history and produce a Markdown document in the following format:

```markdown
# Session Distillation

## Metadata
- **Timestamp**: (current date/time)
- **Project**: (working directory path)
- **Git Branch**: (current branch, if applicable)

## Summary
(One-paragraph summary of what was accomplished in this session)

## Completed Work
- [x] (completed item 1)
- [x] (completed item 2)
- [ ] (incomplete item, if any)

## Key Decisions
| Decision | Rationale |
|----------|-----------|
| ... | ... |

## File Changes
| File | Action | Description |
|------|--------|-------------|
| ... | created/modified/deleted | ... |

## Current State
- **Build**: (passes/fails/not applicable)
- **Tests**: (passes/fails/not applicable)

## Open TODOs
- (remaining work items)

## Context for Next Session
(Critical context that the next person needs to know to continue this work effectively)
```

Write this distillation to a temporary file at `/tmp/claude-distill-payload.md`.

## Step 2: Start the sharing server

Run the serve.py script with the user's passphrase:

```bash
python3 skills/distill-share/scripts/serve.py "{{passphrase}}" /tmp/claude-distill-payload.md
```

This will:
1. Encrypt the distillation with AES-256-GCM using the passphrase
2. Register an mDNS service on the local network
3. Wait for receivers to connect (supports multiple receivers)
4. The server keeps running until the user presses Ctrl+C

Tell the user:
- The service name and port shown in the output
- Instruct the receiver to run: `/distill-receive {{passphrase}}`
- The server stays open for multiple receivers until Ctrl+C

## Relay Mode (Remote Sharing)

If the user passes `--relay`, use the relay server for remote sharing instead of LAN/mDNS.

```bash
python3 skills/distill-share/scripts/serve.py --relay "{{passphrase}}" /tmp/claude-distill-payload.md
```

This will:
1. Connect to the relay server at `wss://relay.fireamulet.com`
2. Create a room and display a 6-character room code
3. Wait for receivers to join via the room code
4. Authenticate and send encrypted payload over WebSocket

Tell the user:
- The room code shown in the output (e.g., `a7f3b2`)
- Instruct the receiver to run: `/distill-receive --relay --room <room_code> {{passphrase}}`
- The server stays open for multiple receivers until Ctrl+C
- Requires `pip install websockets` if not already installed
