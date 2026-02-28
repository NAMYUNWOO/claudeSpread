# Claude Spread

Securely share [Claude Code](https://claude.com/product/claude-code) session distillations between machines — over LAN or the internet.

## What It Does

Claude Spread adds skills to Claude Code for sharing session context and project memory:

- **`/claude-spread:distill-share`** — Generates a structured summary (distillation) of the current session and serves it to receivers, encrypted with a shared passphrase.
- **`/claude-spread:distill-receive`** — Discovers and receives a distillation from a sender, decrypts it, and presents it so you can continue where the previous session left off.
- **`/claude-spread:memory-share`** — Shares your project's auto memory (`~/.claude/projects/<project>/memory/`) over the network. Supports distilled (default) and raw (`--raw`) modes.
- **`/claude-spread:memory-receive`** — Receives shared project memory and installs it into your local auto memory directory.

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

> **Firewall note:** The sender opens a random TCP port for the receiver to connect. If your firewall blocks incoming connections, the receiver will discover the service via mDNS but fail to connect (timeout). Make sure the sender's firewall allows inbound TCP on the assigned port:
>
> ```bash
> # Linux (ufw)
> sudo ufw allow <port>/tcp
>
> # Linux (iptables)
> sudo iptables -A INPUT -p tcp --dport <port> -j ACCEPT
>
> # macOS
> # macOS will show a "Allow incoming connections?" dialog automatically.
> ```
>
> Alternatively, use **Relay Mode** to bypass firewall restrictions entirely.

### Relay Mode (remote)

Uses a WebSocket relay server for sharing across different networks. The relay is a dumb pipe — it cannot decrypt your data.

```bash
# Sender
/claude-spread:distill-share --relay mypassphrase
# → displays a 6-character room code

# Receiver (anywhere)
/claude-spread:distill-receive --relay --room <room_code> mypassphrase
```

### Memory Sharing

Share your project's accumulated auto memory (patterns, conventions, debugging insights) with another machine or team member.

```bash
# Share memory (Claude distills and organizes it first)
/claude-spread:memory-share mypassphrase

# Share memory raw (all .md files as-is)
/claude-spread:memory-share --raw mypassphrase

# Receive memory
/claude-spread:memory-receive mypassphrase
```

Relay mode works the same way — add `--relay` to share across networks.

## Installation

### From GitHub (recommended)

In Claude Code, run:

```bash
# 1. Add the marketplace
/plugin marketplace add NAMYUNWOO/claudeSpread

# 2. Install the plugin
/plugin install claude-spread@ai-spread
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
- **cryptography**: `pip install cryptography`
- **macOS or Linux** (LAN mode uses `dns-sd` on macOS, `avahi-utils` on Linux)
  - Linux: `sudo apt install avahi-utils`
- **websockets** (only for relay mode): `pip install websockets`

## Project Structure

```
claudeSpread/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Marketplace metadata
├── scripts/                     # Shared scripts
│   ├── common.py                # Crypto, protocol, message framing
│   ├── serve.py                 # TCP/WebSocket server
│   └── receive.py               # TCP/WebSocket client
├── skills/
│   ├── distill-share/SKILL.md
│   ├── distill-receive/SKILL.md
│   ├── memory-share/
│   │   ├── SKILL.md
│   │   └── scripts/bundle.py   # Memory directory → JSON bundle
│   └── memory-receive/
│       ├── SKILL.md
│       └── scripts/install.py  # JSON bundle → memory directory
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
