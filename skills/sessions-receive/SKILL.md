---
name: sessions-receive
description: Browse and receive Claude Code sessions from another user
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

# Sessions Receive

You are receiving Claude Code sessions from another user on the network.

**Note**: Received sessions contain full conversation history from the sender.

## Step 1: Fetch the session list

Run the receive_sessions.py script in list mode:

**LAN mode:**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive_sessions.py "{{passphrase}}"
```

**Relay mode** (if `--relay` and `--room` are provided):
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive_sessions.py --relay --room "{{room}}" "{{passphrase}}"
```

This will output a JSON object with `{"type": "SESSION_LIST", "sessions": [...]}`.

Parse the sessions from stdout (ignore any status lines on stderr).

## Step 2: Let the user choose a session

Sort the sessions by `modified` (newest first).

Use **AskUserQuestion** to let the user pick a session. Show up to 4 recent sessions as options:
- **Label**: The session `summary` (or first 40 chars of `firstPrompt` if summary is empty)
- **Description**: `{gitBranch} · {messageCount} msgs · {relative time of modified}`

If there are more than 4 sessions, add an "Other..." option. When selected, display the full numbered list and ask the user to enter a number.

If there are 4 or fewer sessions, just show them all directly as AskUserQuestion options.

## Step 3: Download the selected session

Run receive_sessions.py in select mode:

**LAN mode:**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive_sessions.py --select "SELECTED_SESSION_ID" "{{passphrase}}"
```

**Relay mode:**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/receive_sessions.py --relay --room "{{room}}" --select "SELECTED_SESSION_ID" "{{passphrase}}"
```

This outputs the decrypted .jsonl content to stdout.

## Step 4: Install the session locally

Capture the .jsonl output and the session metadata, then pipe to install_session.py:

Create a JSON payload with the session info and pipe it:

```bash
echo '{"sessionId": "ORIGINAL_ID", "metadata": {SELECTED_SESSION_METADATA}, "jsonl_content": "ESCAPED_JSONL"}' | python3 ${CLAUDE_PLUGIN_ROOT}/skills/sessions-receive/scripts/install_session.py
```

**Important**: The jsonl_content can be very large. Instead of piping through echo, write the install payload to a temporary file first, then pass it as an argument:

```python
# Pseudocode for the install step:
# 1. Save received .jsonl content to a temp file
# 2. Build install JSON with metadata + jsonl_content
# 3. Write to temp file, pass to install_session.py
```

Use a bash approach like:
```bash
python3 -c "
import json, sys
metadata = json.loads(sys.argv[1])
jsonl_path = sys.argv[2]
with open(jsonl_path) as f:
    jsonl = f.read()
payload = {'sessionId': metadata['sessionId'], 'metadata': metadata, 'jsonl_content': jsonl}
json.dump(payload, sys.stdout)
" 'SESSION_METADATA_JSON' /path/to/temp.jsonl | python3 ${CLAUDE_PLUGIN_ROOT}/skills/sessions-receive/scripts/install_session.py
```

## Step 5: Confirm and guide the user

After successful installation, tell the user:
- The session has been installed successfully
- They can resume it with `/resume` — it will appear in the session list
- Show the session summary and key details (branch, message count)
