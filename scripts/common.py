"""
Shared cryptography, protocol, and message framing module for distill-share/receive.
"""

import hashlib
import hmac
import json
import os
import struct

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    raise ImportError(
        "The 'cryptography' package is required. Install it with:\n"
        "  pip install cryptography"
    )

PROTOCOL_VERSION = 1
PBKDF2_ITERATIONS = 600_000
SALT_LEN = 32
NONCE_LEN = 12
KEY_LEN = 32
MAX_AUTH_FAILURES = 3


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 key derivation (stdlib, no external deps)."""
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=KEY_LEN,
    )


def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ct


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, None)


# --------------- HMAC helper ---------------

def compute_hmac(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()

def verify_hmac(key: bytes, message: bytes, proof: str) -> bool:
    expected = compute_hmac(key, message)
    return hmac.compare_digest(expected, proof)


# --------------- Message framing ---------------
# Each message: 4-byte big-endian length prefix + UTF-8 JSON body.

def send_msg(sock, obj: dict) -> None:
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)

def recv_msg(sock) -> dict | None:
    raw_len = _recv_exact(sock, 4)
    if raw_len is None:
        return None
    (length,) = struct.unpack("!I", raw_len)
    if length > 10 * 1024 * 1024:  # 10 MB sanity limit
        return None
    raw_body = _recv_exact(sock, length)
    if raw_body is None:
        return None
    return json.loads(raw_body.decode("utf-8"))

def _recv_exact(sock, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


# --------------- WebSocket message framing ---------------
# For relay mode: JSON text frames over WebSocket.

async def send_msg_ws(ws, obj: dict) -> None:
    await ws.send(json.dumps(obj))

async def recv_msg_ws(ws) -> dict | None:
    data = await ws.recv()
    return json.loads(data)
