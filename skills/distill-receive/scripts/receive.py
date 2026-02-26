#!/usr/bin/env python3
"""
TCP client for distill-receive.
Discovers mDNS service via macOS dns-sd, authenticates, and decrypts the payload.

Supports --relay mode for remote receiving via WebSocket relay server.
"""

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import common

DEFAULT_RELAY_URL = "wss://relay.fireamulet.com"


def discover_service(timeout: int = 10) -> tuple[str, str, int] | None:
    """Use dns-sd -B to browse, then dns-sd -L to resolve."""

    # Step 1: Browse for service instances
    print("Searching for service on local network...", flush=True)
    browse_proc = subprocess.Popen(
        ["dns-sd", "-B", "_claude-distill._tcp.", "local"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    service_name = None
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            line = browse_proc.stdout.readline()
            if not line:
                break
            # Look for Add lines: "... Add ... claude-distill-XXXXXXXX"
            if "Add" in line and "claude-distill-" in line:
                # Extract the service instance name (last column)
                parts = line.strip().split()
                # Service name is typically the last field(s)
                for i, part in enumerate(parts):
                    if part.startswith("claude-distill-"):
                        service_name = " ".join(parts[i:])
                        break
                if service_name:
                    break
    finally:
        browse_proc.terminate()
        browse_proc.wait()

    if not service_name:
        return None

    print(f"Found '{service_name}', connecting...", flush=True)

    # Step 2: Resolve to get host and port
    resolve_proc = subprocess.Popen(
        ["dns-sd", "-L", service_name, "_claude-distill._tcp.", "local"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    host = None
    port = None
    deadline = time.time() + 5
    try:
        while time.time() < deadline:
            line = resolve_proc.stdout.readline()
            if not line:
                break
            # Look for: "... can be reached at hostname:port ..."
            match = re.search(r'can be reached at\s+(\S+?):(\d+)', line)
            if match:
                host = match.group(1)
                port = int(match.group(2))
                break
    finally:
        resolve_proc.terminate()
        resolve_proc.wait()

    if host and port:
        return service_name, host, port
    return None


def receive(passphrase: str, host: str, port: int) -> str | None:
    """Connect, authenticate, and decrypt the payload."""

    # Resolve hostname (may be .local mDNS name)
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        print(f"Error: cannot resolve {host}", file=sys.stderr)
        return None

    sock = None
    for family, socktype, proto, canonname, sockaddr in infos:
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(15)
            sock.connect(sockaddr)
            break
        except OSError:
            if sock:
                sock.close()
                sock = None
            continue

    if sock is None:
        print(f"Error: cannot connect to {host}:{port}", file=sys.stderr)
        return None

    try:
        # 1. Send HELLO
        common.send_msg(sock, {"type": "HELLO", "version": common.PROTOCOL_VERSION})

        # 2. Receive CHALLENGE
        msg = common.recv_msg(sock)
        if not msg:
            print("Error: no response from server", file=sys.stderr)
            return None

        if msg.get("type") == "DENIED":
            print(f"Denied: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None

        if msg.get("type") != "CHALLENGE":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        auth_salt = bytes.fromhex(msg["salt"])
        auth_nonce = bytes.fromhex(msg["nonce"])

        # 3. Compute and send AUTH proof
        auth_key = common.derive_key(passphrase, auth_salt)
        proof = common.compute_hmac(auth_key, auth_nonce)
        common.send_msg(sock, {"type": "AUTH", "proof": proof})

        # 4. Receive PAYLOAD or DENIED
        msg = common.recv_msg(sock)
        if not msg:
            print("Error: connection closed", file=sys.stderr)
            return None

        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None

        if msg.get("type") != "PAYLOAD":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        # Decrypt
        payload_salt = bytes.fromhex(msg["salt"])
        enc_nonce = bytes.fromhex(msg["nonce"])
        ciphertext = bytes.fromhex(msg["ciphertext"])

        payload_key = common.derive_key(passphrase, payload_salt)
        plaintext = common.decrypt(payload_key, enc_nonce, ciphertext)

        # 5. Send ACK
        common.send_msg(sock, {"type": "ACK"})

        return plaintext.decode("utf-8")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None
    finally:
        sock.close()


async def relay_receive(passphrase: str, relay_url: str, room_id: str) -> str | None:
    """Connect to relay server, join room, authenticate, and decrypt payload."""
    try:
        import websockets
    except ImportError:
        print("Error: websockets package is required. Install with `pip install websockets`.", file=sys.stderr)
        return None

    print(f"Connecting to relay server... ({relay_url})", flush=True)

    async with websockets.connect(relay_url) as ws:
        # Join room
        await common.send_msg_ws(ws, {"type": "JOIN_ROOM", "room_id": room_id})
        response = await common.recv_msg_ws(ws)

        if not response or response.get("type") != "ROOM_JOINED":
            reason = response.get("reason", "") if response else ""
            if "not_found" in reason:
                print(f"Error: Room '{room_id}' not found.", file=sys.stderr)
            else:
                print(f"Error: Failed to join room: {response}", file=sys.stderr)
            return None

        print(f"Joined room {room_id}", flush=True)

        # 1. Send HELLO
        await common.send_msg_ws(ws, {"type": "HELLO", "version": common.PROTOCOL_VERSION})

        # 2. Receive CHALLENGE
        msg = await common.recv_msg_ws(ws)
        if not msg:
            print("Error: no response from server", file=sys.stderr)
            return None

        if msg.get("type") == "DENIED":
            print(f"Denied: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None

        if msg.get("type") != "CHALLENGE":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        auth_salt = bytes.fromhex(msg["salt"])
        auth_nonce = bytes.fromhex(msg["nonce"])

        # 3. Compute and send AUTH proof
        auth_key = common.derive_key(passphrase, auth_salt)
        proof = common.compute_hmac(auth_key, auth_nonce)
        await common.send_msg_ws(ws, {"type": "AUTH", "proof": proof})

        # 4. Receive PAYLOAD or DENIED
        msg = await common.recv_msg_ws(ws)
        if not msg:
            print("Error: connection closed", file=sys.stderr)
            return None

        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None

        if msg.get("type") != "PAYLOAD":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        # Decrypt
        payload_salt = bytes.fromhex(msg["salt"])
        enc_nonce = bytes.fromhex(msg["nonce"])
        ciphertext = bytes.fromhex(msg["ciphertext"])

        payload_key = common.derive_key(passphrase, payload_salt)
        plaintext = common.decrypt(payload_key, enc_nonce, ciphertext)

        # 5. Send ACK
        await common.send_msg_ws(ws, {"type": "ACK"})

        return plaintext.decode("utf-8")


def main():
    # Parse arguments
    args = sys.argv[1:]
    relay_url = None
    room_id = None
    use_relay = False

    # Extract --relay and --room flags
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--relay":
            use_relay = True
            # Check if next arg is a URL
            if i + 1 < len(args) and args[i + 1].startswith("ws"):
                relay_url = args[i + 1]
                i += 2
            else:
                relay_url = DEFAULT_RELAY_URL
                i += 1
        elif args[i] == "--room":
            if i + 1 < len(args):
                room_id = args[i + 1]
                i += 2
            else:
                print("Error: --room requires a room_id argument", file=sys.stderr)
                sys.exit(1)
        else:
            filtered_args.append(args[i])
            i += 1

    if use_relay:
        if not room_id:
            print("Error: --relay mode requires --room <room_id>.", file=sys.stderr)
            sys.exit(1)
        if len(filtered_args) < 1:
            print("Usage: receive.py --relay --room <room_id> <passphrase>", file=sys.stderr)
            sys.exit(1)
        passphrase = filtered_args[0]
        payload = asyncio.run(relay_receive(passphrase, relay_url, room_id))
    else:
        if len(filtered_args) < 1:
            print("Usage: receive.py <passphrase> [host:port]", file=sys.stderr)
            sys.exit(1)

        passphrase = filtered_args[0]

        # Optional direct connection (skip mDNS)
        if len(filtered_args) >= 2 and ":" in filtered_args[1]:
            host, port_str = filtered_args[1].rsplit(":", 1)
            host = host
            port = int(port_str)
        else:
            result = discover_service()
            if result is None:
                print("Service not found. Make sure the sender is running /distill-share.", file=sys.stderr)
                sys.exit(1)
            _, host, port = result

        payload = receive(passphrase, host, port)

    if payload is None:
        sys.exit(1)

    print("Authentication successful, distillation data received\n", flush=True)
    # Output the decrypted distillation to stdout
    print(payload)


if __name__ == "__main__":
    main()
