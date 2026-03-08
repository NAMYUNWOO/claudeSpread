#!/usr/bin/env python3
"""
TCP server for sessions-share.
Reads a sessions catalog JSON, serves session list and individual .jsonl files.
Supports LAN (mDNS) and --relay modes.

Protocol (after HELLO → CHALLENGE → AUTH):
  Client: {"type": "LIST_SESSIONS"}  → Server: {"type": "SESSION_LIST", ...}
  Client: {"type": "SELECT_SESSION", "sessionId": "..."}  → Server: {"type": "PAYLOAD", ...}
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

# Reuse mDNS registration and relay URL from serve.py
DEFAULT_RELAY_URL = "wss://relay.fireamulet.com"

SESSION_MAX_SIZE = 50 * 1024 * 1024  # 50 MB for session .jsonl files


def register_mdns(service_name: str, port: int) -> subprocess.Popen | None:
    system = platform.system()
    if system == "Darwin" and shutil.which("dns-sd"):
        return subprocess.Popen(
            ["dns-sd", "-R", service_name, "_claude-sessions._tcp.", "local", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    elif system == "Linux" and shutil.which("avahi-publish"):
        return subprocess.Popen(
            ["avahi-publish", "-s", service_name, "_claude-sessions._tcp", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        print("Warning: no mDNS tool found. Receivers must connect directly via host:port.",
              file=sys.stderr, flush=True)
        return None


def load_catalog(catalog_path: str) -> dict:
    """Load catalog JSON with sessions metadata and fullPath mappings."""
    with open(catalog_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_session_list(catalog: dict) -> list[dict]:
    """Build sanitized session list for sending to clients (no fullPath)."""
    result = []
    for entry in catalog.get("sessions", []):
        item = {
            "sessionId": entry["sessionId"],
            "summary": entry.get("summary", ""),
            "firstPrompt": (entry.get("firstPrompt") or "")[:100],
            "messageCount": entry.get("messageCount", 0),
            "created": entry.get("created", ""),
            "modified": entry.get("modified", ""),
            "gitBranch": entry.get("gitBranch", ""),
            "projectPath": entry.get("projectPath", ""),
            "isSidechain": entry.get("isSidechain", False),
        }
        result.append(item)
    return result


def find_session_path(catalog: dict, session_id: str) -> str | None:
    """Find the fullPath for a given sessionId."""
    for entry in catalog.get("sessions", []):
        if entry["sessionId"] == session_id:
            return entry.get("fullPath")
    return None


def handle_session_request(send_fn, recv_fn, passphrase, catalog, session_list,
                           payload_salt, payload_key):
    """Handle LIST_SESSIONS or SELECT_SESSION after auth succeeds.
    send_fn/recv_fn abstract over TCP socket vs WebSocket.
    Returns True on success.
    """
    msg = recv_fn()
    if not msg:
        return False

    msg_type = msg.get("type", "")

    if msg_type == "LIST_SESSIONS":
        send_fn({"type": "SESSION_LIST", "sessions": session_list})
        return True

    elif msg_type == "SELECT_SESSION":
        session_id = msg.get("sessionId", "")
        full_path = find_session_path(catalog, session_id)
        if not full_path or not os.path.exists(full_path):
            send_fn({"type": "ERROR", "reason": "session_not_found"})
            return False

        # Read .jsonl content
        with open(full_path, "r", encoding="utf-8") as f:
            jsonl_content = f.read()

        # Encrypt
        enc_nonce, ciphertext = common.encrypt(payload_key, jsonl_content.encode("utf-8"))
        send_fn({
            "type": "PAYLOAD",
            "sessionId": session_id,
            "salt": payload_salt.hex(),
            "nonce": enc_nonce.hex(),
            "ciphertext": ciphertext.hex(),
        })

        # Wait for ACK
        recv_fn()
        return True

    else:
        send_fn({"type": "ERROR", "reason": "unknown_request"})
        return False


# --------------- LAN Mode ---------------

def lan_mode(passphrase, catalog):
    session_list = build_session_list(catalog)
    payload_salt = os.urandom(common.SALT_LEN)
    payload_key = common.derive_key(passphrase, payload_salt)

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("0.0.0.0", 0))
    server_sock.listen(5)
    port = server_sock.getsockname()[1]

    instance_id = uuid.uuid4().hex[:8]
    service_name = f"claude-sessions-{instance_id}"
    mdns_proc = register_mdns(service_name, port)

    total_served = 0
    total_lock = threading.Lock()
    failure_counts: dict[str, int] = {}
    failure_lock = threading.Lock()

    def handle_client(conn: socket.socket, addr):
        nonlocal total_served
        client_ip = addr[0]
        try:
            # 1. HELLO
            msg = common.recv_msg(conn)
            if not msg or msg.get("type") != "HELLO":
                return

            with failure_lock:
                if failure_counts.get(client_ip, 0) >= common.MAX_AUTH_FAILURES:
                    common.send_msg(conn, {"type": "DENIED", "reason": "too_many_failures"})
                    return

            # 2. CHALLENGE
            auth_salt = os.urandom(common.SALT_LEN)
            auth_nonce = os.urandom(16)
            common.send_msg(conn, {
                "type": "CHALLENGE",
                "salt": auth_salt.hex(),
                "nonce": auth_nonce.hex(),
            })

            # 3. AUTH
            msg = common.recv_msg(conn)
            if not msg or msg.get("type") != "AUTH":
                return

            auth_key = common.derive_key(passphrase, auth_salt)
            if not common.verify_hmac(auth_key, auth_nonce, msg.get("proof", "")):
                with failure_lock:
                    failure_counts[client_ip] = failure_counts.get(client_ip, 0) + 1
                    count = failure_counts[client_ip]
                common.send_msg(conn, {"type": "DENIED", "reason": "invalid_proof"})
                print(f"  [AUTH FAILED] {client_ip} (attempt {count}/{common.MAX_AUTH_FAILURES})",
                      flush=True)
                return

            # 4. Handle session request (LIST or SELECT)
            def send_fn(obj):
                common.send_msg(conn, obj)

            def recv_fn():
                return common.recv_msg(conn, max_size=SESSION_MAX_SIZE)

            ok = handle_session_request(send_fn, recv_fn, passphrase, catalog,
                                        session_list, payload_salt, payload_key)
            if ok:
                with total_lock:
                    total_served += 1
                    n = total_served
                print(f"  [OK] {client_ip} — Request served ({n} total)", flush=True)

        except Exception as e:
            print(f"  [ERROR] {client_ip}: {e}", file=sys.stderr, flush=True)
        finally:
            conn.close()

    def shutdown(signum, frame):
        print(f"\nSharing stopped. Total served: {total_served} request(s).", flush=True)
        if mdns_proc:
            mdns_proc.terminate()
        server_sock.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Sharing sessions '{service_name}' on port {port}", flush=True)
    print(f"Sharing {len(session_list)} session(s) until Ctrl+C...\n", flush=True)

    while True:
        try:
            conn, addr = server_sock.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except OSError:
            break


# --------------- Relay Mode ---------------

async def relay_mode(passphrase, catalog, relay_url):
    try:
        import websockets
    except ImportError:
        print("Error: websockets package required. Install with `pip install websockets`.",
              file=sys.stderr)
        sys.exit(1)

    session_list = build_session_list(catalog)
    payload_salt = os.urandom(common.SALT_LEN)
    payload_key = common.derive_key(passphrase, payload_salt)

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
        print(f"Tell the receiver to run: /sessions-receive --relay --room {room_id} <passphrase>",
              flush=True)
        print(f"Sharing {len(session_list)} session(s) until Ctrl+C...\n", flush=True)

        # Loop: wait for peers (same pattern as distill serve.py)
        while True:
            control = await common.recv_msg_ws(ws)
            if not control:
                break

            msg_type = control.get("type", "")

            if msg_type == "PEER_JOINED":
                try:
                    ok = await handle_peer_ws(ws, passphrase, catalog, session_list,
                                              payload_salt, payload_key)
                    if ok:
                        total_served += 1
                        print(f"  [OK] Request served ({total_served} total)", flush=True)
                except Exception as e:
                    print(f"  [ERROR] Error handling peer: {e}", file=sys.stderr, flush=True)

            elif msg_type == "PEER_DISCONNECTED":
                # Peer left before or after handshake, continue waiting
                continue
            else:
                print(f"  [RELAY] {control}", flush=True)


async def handle_peer_ws(ws, passphrase, catalog, session_list, payload_salt, payload_key):
    # 1. HELLO
    msg = await common.recv_msg_ws(ws)
    if not msg or msg.get("type") in ("PEER_DISCONNECTED",):
        return False
    if msg.get("type") != "HELLO":
        return False

    # 2. CHALLENGE
    auth_salt = os.urandom(common.SALT_LEN)
    auth_nonce = os.urandom(16)
    await common.send_msg_ws(ws, {
        "type": "CHALLENGE",
        "salt": auth_salt.hex(),
        "nonce": auth_nonce.hex(),
    })

    # 3. AUTH
    msg = await common.recv_msg_ws(ws)
    if not msg or msg.get("type") in ("PEER_DISCONNECTED",):
        return False
    if msg.get("type") != "AUTH":
        return False

    auth_key = common.derive_key(passphrase, auth_salt)
    if not common.verify_hmac(auth_key, auth_nonce, msg.get("proof", "")):
        await common.send_msg_ws(ws, {"type": "DENIED", "reason": "invalid_proof"})
        print("  [AUTH FAILED] Authentication failed", flush=True)
        return False

    # 4. Handle session requests (loop to support multiple requests per connection)
    while True:
        msg = await common.recv_msg_ws(ws)
        if not msg:
            return True

        msg_type = msg.get("type", "")

        # Handle relay control messages gracefully
        if msg_type in ("PEER_DISCONNECTED", "PEER_JOINED"):
            return True

        if msg_type == "LIST_SESSIONS":
            await common.send_msg_ws(ws, {"type": "SESSION_LIST", "sessions": session_list})

        elif msg_type == "SELECT_SESSION":
            session_id = msg.get("sessionId", "")
            full_path = find_session_path(catalog, session_id)
            if not full_path or not os.path.exists(full_path):
                await common.send_msg_ws(ws, {"type": "ERROR", "reason": "session_not_found"})
                continue

            with open(full_path, "r", encoding="utf-8") as f:
                jsonl_content = f.read()

            enc_nonce, ciphertext = common.encrypt(payload_key, jsonl_content.encode("utf-8"))
            await common.send_msg_ws(ws, {
                "type": "PAYLOAD",
                "sessionId": session_id,
                "salt": payload_salt.hex(),
                "nonce": enc_nonce.hex(),
                "ciphertext": ciphertext.hex(),
            })

            # Wait for ACK, but handle peer disconnect gracefully
            msg = await common.recv_msg_ws(ws)
            return True

        elif msg_type == "DONE":
            return True

        else:
            await common.send_msg_ws(ws, {"type": "ERROR", "reason": "unknown_request"})
            return False


def main():
    args = sys.argv[1:]
    relay_url = None
    use_relay = False

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
        else:
            filtered_args.append(args[i])
            i += 1

    if len(filtered_args) < 2:
        print("Usage: serve_sessions.py [--relay [url]] <passphrase> <catalog_file>",
              file=sys.stderr)
        sys.exit(1)

    passphrase = filtered_args[0]
    catalog_path = filtered_args[1]

    catalog = load_catalog(catalog_path)
    if not catalog.get("sessions"):
        print("Error: no sessions in catalog", file=sys.stderr)
        sys.exit(1)

    if use_relay:
        asyncio.run(relay_mode(passphrase, catalog, relay_url))
    else:
        lan_mode(passphrase, catalog)


if __name__ == "__main__":
    main()
