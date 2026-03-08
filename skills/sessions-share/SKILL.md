---
name: sessions-share
description: Share Claude Code sessions for another user to browse and resume
user-invocable: true
arguments:
  - name: passphrase
    description: Shared passphrase for encryption (required)
    required: true
  - name: --relay
    description: Use WebSocket relay server for remote sharing (optional)
    required: false
---

# Sessions Share

You are sharing your Claude Code sessions so another user can browse and resume them.

**Warning**: Session files contain full conversation history. Only share with trusted recipients.

## Step 1: Read the sessions index

Read the sessions index file to find available sessions:

```bash
cat ~/.claude/projects/$(pwd | sed 's|/|-|g')/sessions-index.json
```

If the file doesn't exist, tell the user there are no sessions to share and stop.

## Step 2: Show sessions to the user

Parse the sessions index and display the sessions list to the user, sorted by `modified` (newest first). For each session show:
- Summary (or first 40 chars of firstPrompt if no summary)
- Git branch, message count, and modified date
- Whether it's a sidechain

Ask the user to confirm which sessions to share (all, or a subset by number).

## Step 3: Build the catalog

Create a catalog JSON file at `${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json` with the selected sessions:

```json
{
  "sessions": [
    {
      "sessionId": "...",
      "fullPath": "/absolute/path/to/session.jsonl",
      "summary": "...",
      "firstPrompt": "...",
      "messageCount": 42,
      "created": "...",
      "modified": "...",
      "gitBranch": "main",
      "projectPath": "/path/to/project",
      "isSidechain": false
    }
  ]
}
```

Make sure to create the `.tmp` directory first:
```bash
mkdir -p ${CLAUDE_PLUGIN_ROOT}/.tmp
```

## Step 4: Start the sharing server

Run the serve_sessions.py script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve_sessions.py "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

This will:
1. Encrypt session data with AES-256-GCM using the passphrase
2. Register an mDNS service on the local network (`_claude-sessions._tcp.`)
3. Wait for receivers to connect — serves session list and individual sessions on demand
4. The server keeps running until Ctrl+C

Tell the user:
- The service name and port shown in the output
- Instruct the receiver to run: `/sessions-receive {{passphrase}}`
- The server stays open for multiple receivers until Ctrl+C

## Relay Mode (Remote Sharing)

If the user passes `--relay`, use the relay server:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve_sessions.py --relay "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

This will:
1. Connect to the relay server at `wss://relay.fireamulet.com`
2. Create a room and display a 6-character room code
3. Wait for receivers to join via the room code

Tell the user:
- The room code shown in the output
- Instruct the receiver to run: `/sessions-receive --relay --room <room_code> {{passphrase}}`
- Requires `pip install websockets` if not already installed
