---
name: memory-receive
description: Receive shared project memory from LAN or relay
user-invocable: true
arguments:
  - name: passphrase
    description: Shared passphrase for decryption (required)
    required: true
  - name: --relay
    description: Use WebSocket relay server for remote receiving
    required: false
  - name: --room
    description: Room code to join (required with --relay)
    required: false
---

# Memory Receive

You are receiving project memory shared from another Claude Code instance.

## Step 1: Receive the payload

Run the receive.py script with the user's passphrase:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive.py "{{passphrase}}"
```

This will:
1. Discover the sharing service via mDNS on the local network
2. Authenticate using the passphrase (challenge-response)
3. Decrypt and output the memory payload

## Step 2: Process the payload

Check if the received payload is a JSON memory bundle or plain Markdown.

### If JSON memory bundle (`{"type": "memory_bundle", ...}`)

Run the install script to save files to the local memory directory:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/memory-receive/scripts/install.py
```

Feed the received JSON payload via stdin. The script will:
- Save each file to `~/.claude/projects/<project>/memory/`
- Back up existing files with `.bak` extension before overwriting
- Display the list of saved files

After installation, tell the user which files were saved and that the memory is now active.

### If plain Markdown (distilled mode)

Display the received memory content to the user in full. Then offer to save it:
- Write the content to `~/.claude/projects/<project>/memory/MEMORY.md` (back up existing file first)
- Or let the user decide where to incorporate the information

## Relay Mode (Remote Receiving)

If the user passes `--relay --room <room_code>`, use the relay server:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive.py --relay --room "{{room_code}}" "{{passphrase}}"
```

This will:
1. Connect to the relay server at `wss://relay.fireamulet.com`
2. Join the room using the provided room code
3. Authenticate and decrypt the payload over WebSocket
4. Requires `pip install websockets` if not already installed

## Step 3: Confirm to the user

After processing, tell the user:
- What memory was received (file list or distilled summary)
- That the memory is now available in their auto memory directory
- They can review and edit the files in `~/.claude/projects/<project>/memory/`
