# Claude Spread

Securely share [Claude Code](https://claude.ai/claude-code) session distillations between machines — over LAN or the internet.

## What It Does

Claude Spread adds two skills to Claude Code:

- **`/distill-share`** — Generates a structured summary (distillation) of the current session and serves it to receivers, encrypted with a shared passphrase.
- **`/distill-receive`** — Discovers and receives a distillation from a sender, decrypts it, and presents it so you can continue where the previous session left off.

All data is encrypted end-to-end with AES-256-GCM. The passphrase never leaves your machines.

## Sharing Modes

### LAN Mode (default)

Uses mDNS (Bonjour) for zero-config discovery on the local network.

```bash
# Sender
/distill-share mypassphrase

# Receiver (same network)
/distill-receive mypassphrase
```

### Relay Mode (remote)

Uses a WebSocket relay server for sharing across different networks. The relay is a dumb pipe — it cannot decrypt your data.

```bash
# Sender
/distill-share --relay mypassphrase
# → displays a 6-character room code

# Receiver (anywhere)
/distill-receive --relay --room <room_code> mypassphrase
```

## Installation

1. Copy this repository into your project (or clone it):
   ```bash
   git clone git@github.com:NAMYUNWOO/claudeSpread.git .claude-spread
   ```

2. The `.claude/skills/` directory contains the skill definitions that Claude Code discovers automatically.

3. For relay mode, install the `websockets` package:
   ```bash
   pip install websockets
   ```

## Dependencies

- **Python 3.10+**
- **macOS** (LAN mode uses `dns-sd` for mDNS)
- **websockets** (only for relay mode): `pip install websockets`

## Project Structure

```
.claude/skills/
├── distill-share/
│   ├── SKILL.md              # Skill definition for sharing
│   └── scripts/
│       ├── common.py         # Shared crypto & protocol utilities
│       └── serve.py          # TCP/WebSocket server
└── distill-receive/
    ├── SKILL.md              # Skill definition for receiving
    └── scripts/
        ├── common.py         # Shared crypto & protocol utilities
        └── receive.py        # TCP/WebSocket client

RELAY_SERVER_SPEC.md          # Relay server implementation spec
```

## Security

- **AES-256-GCM** encryption with PBKDF2-derived keys
- **Challenge-response** authentication (HMAC-based)
- The relay server never sees plaintext — it forwards encrypted bytes only
- Brute-force protection: IP-based rate limiting in LAN mode

## Relay Server

The default relay server is `wss://relay.fireamulet.com`. To self-host, see [RELAY_SERVER_SPEC.md](RELAY_SERVER_SPEC.md) for the full implementation specification.

## License

MIT
