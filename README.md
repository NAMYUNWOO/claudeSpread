# Claude Spread

Securely share [Claude Code](https://claude.ai/claude-code) session distillations between machines — over LAN or the internet.

## What It Does

Claude Spread adds two skills to Claude Code:

- **`/claude-spread:distill-share`** — Generates a structured summary (distillation) of the current session and serves it to receivers, encrypted with a shared passphrase.
- **`/claude-spread:distill-receive`** — Discovers and receives a distillation from a sender, decrypts it, and presents it so you can continue where the previous session left off.

All data is encrypted end-to-end with AES-256-GCM. The passphrase never leaves your machines.

## Sharing Modes

### LAN Mode (default)

Uses mDNS (Bonjour) for zero-config discovery on the local network.

```bash
# Sender
/claude-spread:distill-share mypassphrase

# Receiver (same network)
/claude-spread:distill-receive mypassphrase
```

### Relay Mode (remote)

Uses a WebSocket relay server for sharing across different networks. The relay is a dumb pipe — it cannot decrypt your data.

```bash
# Sender
/claude-spread:distill-share --relay mypassphrase
# → displays a 6-character room code

# Receiver (anywhere)
/claude-spread:distill-receive --relay --room <room_code> mypassphrase
```

## Installation

### From GitHub (recommended)

In Claude Code, run:

```bash
# 1. Add the marketplace
/plugin marketplace add NAMYUNWOO/claudeSpread

# 2. Install the plugin
/plugin install claude-spread@claude-spread
```

For relay mode, also install the `websockets` package:

```bash
pip install websockets
```

### Local Development

```bash
git clone https://github.com/NAMYUNWOO/claudeSpread.git
claude --plugin-dir ./claudeSpread
```

## Dependencies

- **Python 3.10+**
- **macOS** (LAN mode uses `dns-sd` for mDNS)
- **websockets** (only for relay mode): `pip install websockets`

## Project Structure

```
claudeSpread/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── skills/
│   ├── distill-share/
│   │   ├── SKILL.md             # Skill definition for sharing
│   │   └── scripts/
│   │       ├── common.py        # Shared crypto & protocol utilities
│   │       └── serve.py         # TCP/WebSocket server
│   └── distill-receive/
│       ├── SKILL.md             # Skill definition for receiving
│       └── scripts/
│           ├── common.py        # Shared crypto & protocol utilities
│           └── receive.py       # TCP/WebSocket client
├── RELAY_SERVER_SPEC.md         # Relay server implementation spec
└── README.md
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
