#!/usr/bin/env python3
"""
TCP server for distill-share.
Registers an mDNS service (macOS dns-sd or Linux avahi), accepts multiple clients,
authenticates via challenge-response, and sends AES-256-GCM encrypted payload.

Supports --relay mode for remote sharing via WebSocket relay server.
"""

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import platform
import shutil
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import common


def register_mdns(service_name: str, port: int) -> subprocess.Popen:
    """Register mDNS service. Uses dns-sd on macOS, avahi-publish on Linux."""
    system = platform.system()
    if system == "Darwin" and shutil.which("dns-sd"):
        return subprocess.Popen(
            ["dns-sd", "-R", service_name, "_claude-distill._tcp.", "local", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif system == "Linux" and shutil.which("avahi-publish"):
        return subprocess.Popen(
            ["avahi-publish", "-s", service_name, "_claude-distill._tcp", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        print(f"Warning: no mDNS tool found (dns-sd or avahi-publish). "
              f"Receivers must connect directly via host:port.", file=sys.stderr, flush=True)
        return None

DEFAULT_RELAY_URL = "wss://relay.fireamulet.com"


async def relay_mode(passphrase, payload_text, relay_url):
    """Run in relay mode: connect to relay server via WebSocket."""
    try:
        import websockets
    except ImportError:
        print("Error: websockets package is required. Install with `pip install websockets`.", file=sys.stderr)
        sys.exit(1)

    # Derive encryption key (with a fresh salt for the payload)
    payload_salt = os.urandom(common.SALT_LEN)
    payload_key = common.derive_key(passphrase, payload_salt)
    enc_nonce, ciphertext = common.encrypt(payload_key, payload_text.encode("utf-8"))

    total_served = 0

    print(f"Connecting to relay server... ({relay_url})", flush=True)

    async with websockets.connect(relay_url) as ws:
        # Create room
        await common.send_msg_ws(ws, {"type": "CREATE_ROOM"})
        response = await common.recv_msg_ws(ws)

        if not response or response.get("type") != "ROOM_CREATED":
            print(f"Error: failed to create room: {response}", file=sys.stderr)
            sys.exit(1)

        room_id = response["room_id"]
        print(f"Room created: {room_id}", flush=True)
        print(f"Tell the receiver to run: /distill-receive --relay --room {room_id} <passphrase>", flush=True)
        print(f"Sharing until Ctrl+C...\n", flush=True)

        # Loop: wait for peers
        while True:
            control = await common.recv_msg_ws(ws)
            if not control:
                break

            msg_type = control.get("type", "")

            if msg_type == "PEER_JOINED":
                try:
                    await handle_peer_ws(ws, passphrase, payload_salt, payload_key, enc_nonce, ciphertext)
                    total_served += 1
                    print(f"  [OK] Transfer complete ({total_served} receiver(s) served)", flush=True)
                except Exception as e:
                    print(f"  [ERROR] Error handling peer: {e}", file=sys.stderr, flush=True)

            elif msg_type == "PEER_DISCONNECTED":
                # Peer left before or after handshake, continue waiting
                continue
            else:
                # Unknown control message, log and continue
                print(f"  [RELAY] {control}", flush=True)


async def handle_peer_ws(ws, passphrase, payload_salt, payload_key, enc_nonce, ciphertext):
    """Handle a single peer connection over WebSocket relay."""

    # 1. Receive HELLO
    msg = await common.recv_msg_ws(ws)
    if not msg or msg.get("type") != "HELLO":
        return

    # 2. Send CHALLENGE
    auth_salt = os.urandom(common.SALT_LEN)
    auth_nonce = os.urandom(16)
    await common.send_msg_ws(ws, {
        "type": "CHALLENGE",
        "salt": auth_salt.hex(),
        "nonce": auth_nonce.hex(),
    })

    # 3. Receive AUTH
    msg = await common.recv_msg_ws(ws)
    if not msg or msg.get("type") != "AUTH":
        return

    # Verify proof
    auth_key = common.derive_key(passphrase, auth_salt)
    if not common.verify_hmac(auth_key, auth_nonce, msg.get("proof", "")):
        await common.send_msg_ws(ws, {"type": "DENIED", "reason": "invalid_proof"})
        print(f"  [AUTH FAILED] Authentication failed", flush=True)
        return

    # 4. Send encrypted PAYLOAD
    await common.send_msg_ws(ws, {
        "type": "PAYLOAD",
        "salt": payload_salt.hex(),
        "nonce": enc_nonce.hex(),
        "ciphertext": ciphertext.hex(),
    })

    # 5. Wait for ACK
    msg = await common.recv_msg_ws(ws)
    # ACK is optional — we count success regardless


def lan_mode(passphrase, payload_text):
    """Run in LAN mode: mDNS + TCP (original behavior)."""
    # Derive encryption key (with a fresh salt for the payload)
    payload_salt = os.urandom(common.SALT_LEN)
    payload_key = common.derive_key(passphrase, payload_salt)
    enc_nonce, ciphertext = common.encrypt(payload_key, payload_text.encode("utf-8"))

    # Bind TCP server on ephemeral port
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", 0))
    server_sock.listen(5)
    port = server_sock.getsockname()[1]

    # Generate service instance name
    instance_id = uuid.uuid4().hex[:8]
    service_name = f"claude-distill-{instance_id}"

    # Register mDNS service
    mdns_proc = register_mdns(service_name, port)

    total_served = 0
    total_lock = threading.Lock()
    failure_counts: dict[str, int] = {}  # IP -> failure count
    failure_lock = threading.Lock()

    def handle_client(conn: socket.socket, addr):
        nonlocal total_served
        client_ip = addr[0]
        try:
            # 1. Receive HELLO
            msg = common.recv_msg(conn)
            if not msg or msg.get("type") != "HELLO":
                return

            # Check if this IP is banned
            with failure_lock:
                if failure_counts.get(client_ip, 0) >= common.MAX_AUTH_FAILURES:
                    common.send_msg(conn, {"type": "DENIED", "reason": "too_many_failures"})
                    return

            # 2. Send CHALLENGE
            auth_salt = os.urandom(common.SALT_LEN)
            auth_nonce = os.urandom(16)
            common.send_msg(conn, {
                "type": "CHALLENGE",
                "salt": auth_salt.hex(),
                "nonce": auth_nonce.hex(),
            })

            # 3. Receive AUTH
            msg = common.recv_msg(conn)
            if not msg or msg.get("type") != "AUTH":
                return

            # Verify proof
            auth_key = common.derive_key(passphrase, auth_salt)
            if not common.verify_hmac(auth_key, auth_nonce, msg.get("proof", "")):
                with failure_lock:
                    failure_counts[client_ip] = failure_counts.get(client_ip, 0) + 1
                    count = failure_counts[client_ip]
                common.send_msg(conn, {"type": "DENIED", "reason": "invalid_proof"})
                print(f"  [AUTH FAILED] {client_ip} (attempt {count}/{common.MAX_AUTH_FAILURES})", flush=True)
                return

            # 4. Send encrypted PAYLOAD
            common.send_msg(conn, {
                "type": "PAYLOAD",
                "salt": payload_salt.hex(),
                "nonce": enc_nonce.hex(),
                "ciphertext": ciphertext.hex(),
            })

            # 5. Wait for ACK
            msg = common.recv_msg(conn)
            # ACK is optional — we count success regardless
            with total_lock:
                total_served += 1
                n = total_served
            print(f"  [OK] {client_ip} — Transfer complete ({n} receiver(s) served)", flush=True)

        except Exception as e:
            print(f"  [ERROR] {client_ip}: {e}", file=sys.stderr, flush=True)
        finally:
            conn.close()

    # Graceful shutdown
    def shutdown(signum, frame):
        print(f"\nSharing stopped. Total served: {total_served} receiver(s).", flush=True)
        if mdns_proc:
            mdns_proc.terminate()
        server_sock.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Sharing '{service_name}' on port {port}", flush=True)
    print(f"Tell the receiver to run /distill-receive with the same passphrase", flush=True)
    print(f"Sharing until Ctrl+C...\n", flush=True)

    # Accept loop
    while True:
        try:
            conn, addr = server_sock.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except OSError:
            break  # socket closed


def main():
    # Parse arguments
    args = sys.argv[1:]
    relay_url = None
    use_relay = False

    # Extract --relay flag/option
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--relay":
            use_relay = True
            # Check if next arg is a URL (not another flag and not the passphrase)
            if i + 1 < len(args) and args[i + 1].startswith("ws"):
                relay_url = args[i + 1]
                i += 2
            else:
                relay_url = DEFAULT_RELAY_URL
                i += 1
        else:
            filtered_args.append(args[i])
            i += 1

    if len(filtered_args) < 1:
        print("Usage: serve.py [--relay [url]] <passphrase> [distill_file]", file=sys.stderr)
        sys.exit(1)

    passphrase = filtered_args[0]
    distill_file = filtered_args[1] if len(filtered_args) > 1 else None

    # Read distillation payload
    if distill_file and distill_file != "-":
        with open(distill_file, "r") as f:
            payload_text = f.read()
    else:
        payload_text = sys.stdin.read()

    if not payload_text.strip():
        print("Error: empty distillation payload", file=sys.stderr)
        sys.exit(1)

    if use_relay:
        asyncio.run(relay_mode(passphrase, payload_text, relay_url))
    else:
        lan_mode(passphrase, payload_text)


if __name__ == "__main__":
    main()
