#!/usr/bin/env python3
"""
TCP client for sessions-receive.
Discovers mDNS service, authenticates, and either lists sessions or downloads a selected one.

Modes:
  - List (default): outputs SESSION_LIST JSON to stdout
  - Select (--select <sessionId>): downloads and outputs session .jsonl to stdout

Supports LAN (mDNS) and --relay modes.
"""

import asyncio
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import common

DEFAULT_RELAY_URL = "wss://relay.fireamulet.com"
SESSION_MAX_SIZE = 50 * 1024 * 1024  # 50 MB


def discover_service(timeout: int = 10) -> tuple[str, str, int] | None:
    system = platform.system()
    if system == "Darwin" and shutil.which("dns-sd"):
        return _discover_dns_sd(timeout)
    elif system == "Linux" and shutil.which("avahi-browse"):
        return _discover_avahi(timeout)
    else:
        print("Error: no mDNS tool found (dns-sd or avahi-browse).", file=sys.stderr)
        return None


def _discover_dns_sd(timeout: int) -> tuple[str, str, int] | None:
    print("Searching for sessions service on local network (dns-sd)...", flush=True)
    browse_proc = subprocess.Popen(
        ["dns-sd", "-B", "_claude-sessions._tcp.", "local"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )

    service_name = None
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            line = browse_proc.stdout.readline()
            if not line:
                break
            if "Add" in line and "claude-sessions-" in line:
                parts = line.strip().split()
                for i, part in enumerate(parts):
                    if part.startswith("claude-sessions-"):
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

    resolve_proc = subprocess.Popen(
        ["dns-sd", "-L", service_name, "_claude-sessions._tcp.", "local"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )

    host = None
    port = None
    deadline = time.time() + 5
    try:
        while time.time() < deadline:
            line = resolve_proc.stdout.readline()
            if not line:
                break
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


def _discover_avahi(timeout: int) -> tuple[str, str, int] | None:
    print("Searching for sessions service on local network (avahi)...", flush=True)
    try:
        result = subprocess.run(
            ["avahi-browse", "-t", "-r", "-p", "_claude-sessions._tcp"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None

    for line in result.stdout.splitlines():
        if not line.startswith("="):
            continue
        fields = line.split(";")
        if len(fields) < 9:
            continue
        name = fields[3]
        if "claude-sessions-" not in name:
            continue
        print(f"Found '{name}', connecting...", flush=True)
        return name, fields[7], int(fields[8])
    return None


def authenticate(sock, passphrase: str) -> bool:
    """Perform HELLO → CHALLENGE → AUTH handshake. Returns True on success."""
    common.send_msg(sock, {"type": "HELLO", "version": common.PROTOCOL_VERSION})

    msg = common.recv_msg(sock)
    if not msg:
        print("Error: no response from server", file=sys.stderr)
        return False
    if msg.get("type") == "DENIED":
        print(f"Denied: {msg.get('reason', 'unknown')}", file=sys.stderr)
        return False
    if msg.get("type") != "CHALLENGE":
        print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
        return False

    auth_salt = bytes.fromhex(msg["salt"])
    auth_nonce = bytes.fromhex(msg["nonce"])
    auth_key = common.derive_key(passphrase, auth_salt)
    proof = common.compute_hmac(auth_key, auth_nonce)
    common.send_msg(sock, {"type": "AUTH", "proof": proof})
    return True


def connect_to_host(host: str, port: int) -> socket.socket | None:
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        print(f"Error: cannot resolve {host}", file=sys.stderr)
        return None

    for family, socktype, proto, canonname, sockaddr in infos:
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(15)
            sock.connect(sockaddr)
            return sock
        except OSError:
            sock.close()
            continue

    print(f"Error: cannot connect to {host}:{port}", file=sys.stderr)
    print("Hint: The sender's firewall may be blocking the port. "
          "Use --relay mode to bypass firewall restrictions.", file=sys.stderr)
    return None


def list_sessions(passphrase: str, host: str, port: int) -> str | None:
    """Connect, auth, request LIST_SESSIONS, return JSON string."""
    sock = connect_to_host(host, port)
    if not sock:
        return None
    try:
        if not authenticate(sock, passphrase):
            return None

        # After AUTH, server either sends DENIED (on failure) or waits for
        # our request (on success). Send request immediately — if auth failed,
        # we'll get DENIED back instead of SESSION_LIST.
        common.send_msg(sock, {"type": "LIST_SESSIONS"})

        msg = common.recv_msg(sock, max_size=SESSION_MAX_SIZE)
        if not msg:
            print("Error: no response", file=sys.stderr)
            return None
        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") == "ERROR":
            print(f"Error: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") != "SESSION_LIST":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        return json.dumps(msg)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None
    finally:
        sock.close()


def select_session(passphrase: str, host: str, port: int, session_id: str) -> str | None:
    """Connect, auth, request SELECT_SESSION, decrypt and return .jsonl content."""
    sock = connect_to_host(host, port)
    if not sock:
        return None
    try:
        if not authenticate(sock, passphrase):
            return None

        common.send_msg(sock, {"type": "SELECT_SESSION", "sessionId": session_id})

        msg = common.recv_msg(sock, max_size=SESSION_MAX_SIZE)
        if not msg:
            print("Error: no response", file=sys.stderr)
            return None
        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") == "ERROR":
            print(f"Error: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") != "PAYLOAD":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        payload_salt = bytes.fromhex(msg["salt"])
        enc_nonce = bytes.fromhex(msg["nonce"])
        ciphertext = bytes.fromhex(msg["ciphertext"])

        payload_key = common.derive_key(passphrase, payload_salt)
        plaintext = common.decrypt(payload_key, enc_nonce, ciphertext)

        common.send_msg(sock, {"type": "ACK"})
        return plaintext.decode("utf-8")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return None
    finally:
        sock.close()


# --------------- Relay Mode ---------------

async def relay_authenticate(ws, passphrase: str) -> bool:
    await common.send_msg_ws(ws, {"type": "HELLO", "version": common.PROTOCOL_VERSION})

    msg = await common.recv_msg_ws(ws)
    if not msg:
        print("Error: no response from server", file=sys.stderr)
        return False
    if msg.get("type") == "DENIED":
        print(f"Denied: {msg.get('reason', 'unknown')}", file=sys.stderr)
        return False
    if msg.get("type") != "CHALLENGE":
        print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
        return False

    auth_salt = bytes.fromhex(msg["salt"])
    auth_nonce = bytes.fromhex(msg["nonce"])
    auth_key = common.derive_key(passphrase, auth_salt)
    proof = common.compute_hmac(auth_key, auth_nonce)
    await common.send_msg_ws(ws, {"type": "AUTH", "proof": proof})
    return True


async def relay_connect_and_auth(passphrase: str, relay_url: str, room_id: str):
    """Connect to relay, join room, authenticate. Returns (ws, None) on success or (None, error_str)."""
    try:
        import websockets
    except ImportError:
        return None, "websockets package required. Install with `pip install websockets`."

    print(f"Connecting to relay server... ({relay_url})", flush=True)

    ws = await websockets.connect(relay_url)
    await common.send_msg_ws(ws, {"type": "JOIN_ROOM", "room_id": room_id})
    response = await common.recv_msg_ws(ws)

    if not response or response.get("type") != "ROOM_JOINED":
        reason = response.get("reason", "") if response else ""
        await ws.close()
        if "not_found" in reason:
            return None, f"Room '{room_id}' not found."
        return None, f"Failed to join room: {response}"

    print(f"Joined room {room_id}", flush=True)

    if not await relay_authenticate(ws, passphrase):
        await ws.close()
        return None, "Authentication failed."

    return ws, None


async def relay_list_sessions(passphrase: str, relay_url: str, room_id: str) -> str | None:
    ws, err = await relay_connect_and_auth(passphrase, relay_url, room_id)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return None

    try:
        await common.send_msg_ws(ws, {"type": "LIST_SESSIONS"})

        msg = await common.recv_msg_ws(ws)
        if not msg:
            print("Error: no response", file=sys.stderr)
            return None
        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") != "SESSION_LIST":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        return json.dumps(msg)
    finally:
        await ws.close()


async def relay_select_session(passphrase: str, relay_url: str, room_id: str,
                               session_id: str) -> str | None:
    ws, err = await relay_connect_and_auth(passphrase, relay_url, room_id)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return None

    try:
        await common.send_msg_ws(ws, {"type": "SELECT_SESSION", "sessionId": session_id})

        msg = await common.recv_msg_ws(ws)
        if not msg:
            print("Error: no response", file=sys.stderr)
            return None
        if msg.get("type") == "DENIED":
            print(f"Authentication failed: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") == "ERROR":
            print(f"Error: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") != "PAYLOAD":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        payload_salt = bytes.fromhex(msg["salt"])
        enc_nonce = bytes.fromhex(msg["nonce"])
        ciphertext = bytes.fromhex(msg["ciphertext"])

        payload_key = common.derive_key(passphrase, payload_salt)
        plaintext = common.decrypt(payload_key, enc_nonce, ciphertext)

        await common.send_msg_ws(ws, {"type": "ACK"})
        return plaintext.decode("utf-8")
    finally:
        await ws.close()


async def relay_list_and_select(passphrase: str, relay_url: str, room_id: str,
                                 session_id: str) -> str | None:
    """List sessions then select one, all in a single relay connection."""
    ws, err = await relay_connect_and_auth(passphrase, relay_url, room_id)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return None

    try:
        # First list to validate session exists
        await common.send_msg_ws(ws, {"type": "LIST_SESSIONS"})

        msg = await common.recv_msg_ws(ws)
        if not msg or msg.get("type") != "SESSION_LIST":
            print(f"Error: unexpected response: {msg}", file=sys.stderr)
            return None

        # Now select in the same connection
        await common.send_msg_ws(ws, {"type": "SELECT_SESSION", "sessionId": session_id})

        msg = await common.recv_msg_ws(ws)
        if not msg:
            print("Error: no response", file=sys.stderr)
            return None
        if msg.get("type") == "ERROR":
            print(f"Error: {msg.get('reason', 'unknown')}", file=sys.stderr)
            return None
        if msg.get("type") != "PAYLOAD":
            print(f"Error: unexpected message type: {msg.get('type')}", file=sys.stderr)
            return None

        payload_salt = bytes.fromhex(msg["salt"])
        enc_nonce = bytes.fromhex(msg["nonce"])
        ciphertext = bytes.fromhex(msg["ciphertext"])

        payload_key = common.derive_key(passphrase, payload_salt)
        plaintext = common.decrypt(payload_key, enc_nonce, ciphertext)

        await common.send_msg_ws(ws, {"type": "ACK"})
        return plaintext.decode("utf-8")
    finally:
        await ws.close()


def main():
    args = sys.argv[1:]
    relay_url = None
    room_id = None
    use_relay = False
    select_id = None

    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--relay":
            use_relay = True
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
        elif args[i] == "--select":
            if i + 1 < len(args):
                select_id = args[i + 1]
                i += 2
            else:
                print("Error: --select requires a sessionId argument", file=sys.stderr)
                sys.exit(1)
        else:
            filtered_args.append(args[i])
            i += 1

    if len(filtered_args) < 1:
        print("Usage: receive_sessions.py [--relay [url]] [--room <room_id>] "
              "[--select <sessionId>] <passphrase> [host:port]", file=sys.stderr)
        sys.exit(1)

    passphrase = filtered_args[0]

    if use_relay:
        if not room_id:
            print("Error: --relay mode requires --room <room_id>.", file=sys.stderr)
            sys.exit(1)

        if select_id:
            result = asyncio.run(relay_list_and_select(passphrase, relay_url, room_id, select_id))
        else:
            result = asyncio.run(relay_list_sessions(passphrase, relay_url, room_id))
    else:
        # LAN mode
        if len(filtered_args) >= 2 and ":" in filtered_args[1]:
            host, port_str = filtered_args[1].rsplit(":", 1)
            port = int(port_str)
        else:
            disc = discover_service()
            if disc is None:
                print("Service not found. Make sure the sender is running /sessions-share.",
                      file=sys.stderr)
                sys.exit(1)
            _, host, port = disc

        if select_id:
            result = select_session(passphrase, host, port, select_id)
        else:
            result = list_sessions(passphrase, host, port)

    if result is None:
        sys.exit(1)

    print(result)


if __name__ == "__main__":
    main()
