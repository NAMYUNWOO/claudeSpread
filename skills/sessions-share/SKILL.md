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
  - name: --keep-open
    description: "Keep server open for N minutes (optional). Without this, server stops after first session download."
    required: false
---

# Sessions Share

You are sharing your Claude Code sessions so another user can browse and resume them.

**Warning**: Session files contain full conversation history. Only share with trusted recipients.

## Step 1: Build the sessions catalog

Scan all session `.jsonl` files and build a catalog:

```bash
mkdir -p ${CLAUDE_PLUGIN_ROOT}/.tmp
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/build_sessions_catalog.py ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

If no sessions are found, tell the user there are no sessions to share and stop.

## Step 2: Show sessions to the user

Read the generated catalog file:

```bash
cat ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

Display the sessions list to the user, sorted by `modified` (newest first). For each session show:
- Summary (or first 40 chars of firstPrompt if no summary)
- Git branch, message count, and modified date
- Whether it's a sidechain

Ask the user to confirm which sessions to share (all, or a subset by number).

If the user picks a subset, update the catalog file to include only the selected sessions.

## Step 4: Start the sharing server

Run the serve_sessions.py script:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve_sessions.py "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

This will:
1. Encrypt session data with AES-256-GCM using the passphrase
2. Register an mDNS service on the local network (`_claude-sessions._tcp.`)
3. Wait for a receiver to connect, serve the session, then **automatically shut down**

Tell the user:
- The service name and port shown in the output
- Instruct the receiver to run: `/sessions-receive {{passphrase}}`
- The server will automatically stop after the first session download

### Sharing with multiple receivers (`--keep-open`)

If the user wants to share with multiple people, use `--keep-open <minutes>`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/serve_sessions.py --keep-open 10 "{{passphrase}}" ${CLAUDE_PLUGIN_ROOT}/.tmp/claude-sessions-catalog.json
```

This keeps the server open for the specified number of minutes, allowing multiple receivers to connect. The server shuts down automatically when time expires.

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
- The server will automatically stop after the first session download
- For sharing with multiple receivers, add `--keep-open <minutes>`
- Requires `pip install websockets` if not already installed
