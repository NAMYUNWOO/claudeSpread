"""
Shared cryptography, protocol, and message framing module for distill-share/receive.
"""

import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys

PROTOCOL_VERSION = 1
PBKDF2_ITERATIONS = 600_000
SALT_LEN = 32
NONCE_LEN = 12
KEY_LEN = 32
MAX_AUTH_FAILURES = 3

# Try to use the `cryptography` library; fall back to openssl CLI.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    def derive_key(passphrase: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LEN,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_LEN)
        ct = AESGCM(key).encrypt(nonce, plaintext, None)
        return nonce, ct

    def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        return AESGCM(key).decrypt(nonce, ciphertext, None)

    CRYPTO_BACKEND = "cryptography"

except ImportError:
    # ---------- openssl CLI fallback ----------

    def derive_key(passphrase: str, salt: bytes) -> bytes:
        # PBKDF2 via openssl
        result = subprocess.run(
            [
                "openssl", "kdf", "-keylen", str(KEY_LEN),
                "-kdfopt", f"pass:{passphrase}",
                "-kdfopt", f"hexsalt:{salt.hex()}",
                "-kdfopt", f"iter:{PBKDF2_ITERATIONS}",
                "-kdfopt", "digest:SHA256",
                "PBKDF2",
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # Older openssl: use `dgst -pbkdf2` trick
            raw = subprocess.run(
                [
                    "openssl", "enc", "-aes-256-gcm", "-pbkdf2",
                    "-iter", str(PBKDF2_ITERATIONS),
                    "-S", salt.hex(),
                    "-k", passphrase,
                    "-P",
                ],
                input=b"", capture_output=True, text=True,
            )
            for line in raw.stdout.splitlines():
                if line.startswith("key="):
                    return bytes.fromhex(line.split("=", 1)[1])
            raise RuntimeError("openssl PBKDF2 key derivation failed")
        hex_key = result.stdout.strip().replace(":", "")
        return bytes.fromhex(hex_key)

    def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(NONCE_LEN)
        proc = subprocess.run(
            [
                "openssl", "enc", "-aes-256-gcm",
                "-K", key.hex(),
                "-iv", nonce.hex(),
                "-nosalt",
            ],
            input=plaintext, capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError("openssl encryption failed")
        return nonce, proc.stdout

    def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        proc = subprocess.run(
            [
                "openssl", "enc", "-aes-256-gcm", "-d",
                "-K", key.hex(),
                "-iv", nonce.hex(),
                "-nosalt",
            ],
            input=ciphertext, capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError("openssl decryption failed")
        return proc.stdout

    CRYPTO_BACKEND = "openssl"


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
