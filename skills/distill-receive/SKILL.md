---
name: distill-receive
description: Receive a shared session distillation from the local network or via relay
user-invocable: true
arguments:
  - name: passphrase
    description: Shared passphrase for decryption (required)
    required: true
  - name: --relay
    description: Use WebSocket relay server for remote receiving (optional)
    required: false
  - name: --room
    description: Room code to join (required with --relay)
    required: false
---

# Distill Receive

You are receiving a session distillation from another Claude Code instance on the local network.

## Step 1: Receive the distillation

Run the receive.py script with the user's passphrase:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive.py "{{passphrase}}"
```

This will:
1. Discover the sharing service via mDNS on the local network
2. Authenticate using the passphrase (challenge-response)
3. Decrypt and output the distillation content

## Step 2: Present the distillation

Display the received distillation content to the user in full. This is a handoff document from another session.

## Relay Mode (Remote Receiving)

If the user passes `--relay --room <room_code>`, use the relay server instead of LAN/mDNS.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive.py --relay --room "{{room_code}}" "{{passphrase}}"
```

This will:
1. Connect to the relay server at `wss://relay.fireamulet.com`
2. Join the room using the provided room code
3. Authenticate and decrypt the payload over WebSocket
4. Requires `pip install websockets` if not already installed

## Step 3: Offer to continue

After showing the distillation, ask the user:

> "Distillation data received. What would you like to continue working on?"

Use the distillation context (especially **Open TODOs** and **Context for Next Session**) to understand what work remains and be ready to continue where the previous session left off.
