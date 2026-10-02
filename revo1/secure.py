"""The encrypted channel between Revo1 and the knob over Wi-Fi or Bluetooth.

Pairing (over USB, which needs the device in hand) gives both sides one shared
32-byte key. Every wireless session then runs a mutual challenge-response with
fresh random nonces from each side, so neither end talks to anyone without the
key and an old session can't be replayed. Each direction gets its own session
key, and every frame is sealed with AES-256-GCM:

    app  -> knob   b"R1H1" + app nonce (16)
    knob -> app    knob nonce (16) + HMAC(key, "revo1-knob" | nonces)
    app  -> knob   HMAC(key, "revo1-app" | nonces)
    then frames    length (2, big-endian) + ciphertext + tag (16)

The GCM nonce is a per-direction frame counter, and the length is the
associated data, so frames can't be dropped, reordered, replayed or resized.
AES-GCM comes from Windows' own CNG, which every Windows build has, including
ARM64 where no `cryptography` wheel exists.
"""

import ctypes
import hashlib
import hmac
import os
import struct
import time
from ctypes import wintypes

KEY_BYTES = 32
NONCE_BYTES = 16
TAG_BYTES = 16
MAC_BYTES = 32
HELLO = b"R1H1"
FRAME_MAX = 8192


class SecureError(Exception):
    pass


def new_key():
    return os.urandom(KEY_BYTES)


def key_id(key):
    """A short fingerprint both sides show, so a mismatch can be spotted."""
    return hashlib.sha256(key).hexdigest()[:8].upper()


def _mac(key, label, client_nonce, knob_nonce):
    return hmac.new(key, label + client_nonce + knob_nonce, hashlib.sha256).digest()


# ----- AES-256-GCM through CNG -------------------------------------------------

class _AuthInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("dwInfoVersion", wintypes.ULONG),
                ("pbNonce", ctypes.c_void_p), ("cbNonce", wintypes.ULONG),
                ("pbAuthData", ctypes.c_void_p), ("cbAuthData", wintypes.ULONG),
                ("pbTag", ctypes.c_void_p), ("cbTag", wintypes.ULONG),
                ("pbMacContext", ctypes.c_void_p), ("cbMacContext", wintypes.ULONG),
                ("cbAAD", wintypes.ULONG), ("cbData", ctypes.c_ulonglong),
                ("dwFlags", wintypes.ULONG)]


_bcrypt = None
_algorithm = None


def _cng():
    global _bcrypt, _algorithm
    if _algorithm is None:
        _bcrypt = ctypes.WinDLL("bcrypt.dll")
        handle = ctypes.c_void_p()
        _check(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(handle), "AES", None, 0))
        mode = ctypes.create_unicode_buffer("ChainingModeGCM")
        _check(_bcrypt.BCryptSetProperty(handle, "ChainingMode", mode,
                                         ctypes.sizeof(mode), 0))
        _algorithm = handle
    return _bcrypt, _algorithm


def _check(status):
    if status != 0:
        raise SecureError(f"CNG error 0x{status & 0xFFFFFFFF:08X}")


class AesGcm:
    def __init__(self, key):
        if len(key) != KEY_BYTES:
            raise ValueError("AES-256 needs a 32-byte key")
        bcrypt, algorithm = _cng()
        self._bcrypt = bcrypt
        self._key_blob = ctypes.create_string_buffer(bytes(key))
        self._handle = ctypes.c_void_p()
        _check(bcrypt.BCryptGenerateSymmetricKey(algorithm, ctypes.byref(self._handle),
                                                 None, 0, self._key_blob, KEY_BYTES, 0))

    def __del__(self):
        if getattr(self, "_handle", None) and self._handle.value:
            self._bcrypt.BCryptDestroyKey(self._handle)
            self._handle = ctypes.c_void_p()

    def _run(self, function, nonce, data, aad, tag):
        nonce_buffer = ctypes.create_string_buffer(nonce, len(nonce))
        aad_buffer = ctypes.create_string_buffer(aad, len(aad))
        tag_buffer = ctypes.create_string_buffer(tag, TAG_BYTES)
        info = _AuthInfo(cbSize=ctypes.sizeof(_AuthInfo), dwInfoVersion=1,
                         pbNonce=ctypes.addressof(nonce_buffer), cbNonce=len(nonce),
                         pbAuthData=ctypes.addressof(aad_buffer), cbAuthData=len(aad),
                         pbTag=ctypes.addressof(tag_buffer), cbTag=TAG_BYTES)
        source = ctypes.create_string_buffer(data, max(1, len(data)))
        output = ctypes.create_string_buffer(max(1, len(data)))
        written = wintypes.ULONG()
        status = function(self._handle, source, len(data), ctypes.byref(info), None, 0,
                          output, len(data), ctypes.byref(written), 0)
        return status, output.raw[:written.value], tag_buffer.raw

    def seal(self, nonce, plaintext, aad=b""):
        status, ciphertext, tag = self._run(self._bcrypt.BCryptEncrypt, nonce,
                                            plaintext, aad, bytes(TAG_BYTES))
        _check(status)
        return ciphertext + tag

    def open(self, nonce, sealed, aad=b""):
        if len(sealed) < TAG_BYTES:
            raise SecureError("Frame too short")
        status, plaintext, _ = self._run(self._bcrypt.BCryptDecrypt, nonce,
                                         sealed[:-TAG_BYTES], aad, sealed[-TAG_BYTES:])
        if status != 0:
            raise SecureError("A frame failed its integrity check")
        return plaintext


# ----- Session ------------------------------------------------------------------

class Channel:
    """Runs the handshake and then seals and opens frames over a raw byte
    transport given as `send(bytes)` and `receive(count, timeout) -> bytes`
    (which returns fewer bytes, possibly none, on timeout)."""

    def __init__(self, key, send, receive):
        self.key = bytes(key)
        self.send_raw = send
        self.receive_raw = receive
        self.pending = b""
        self.tx = self.rx = None
        self.tx_count = self.rx_count = 0

    def handshake(self, timeout=6.0):
        client_nonce = os.urandom(NONCE_BYTES)
        self.send_raw(HELLO + client_nonce)
        reply = self._read_exact(NONCE_BYTES + MAC_BYTES, timeout)
        if reply is None:
            raise SecureError("The knob did not answer the handshake")
        knob_nonce, proof = reply[:NONCE_BYTES], reply[NONCE_BYTES:]
        expected = _mac(self.key, b"revo1-knob", client_nonce, knob_nonce)
        if not hmac.compare_digest(proof, expected):
            raise SecureError("The knob is paired with a different key")
        self.send_raw(_mac(self.key, b"revo1-app", client_nonce, knob_nonce))
        self.tx = AesGcm(_mac(self.key, b"revo1-c2k", client_nonce, knob_nonce))
        self.rx = AesGcm(_mac(self.key, b"revo1-k2c", client_nonce, knob_nonce))

    def send(self, plaintext):
        for start in range(0, len(plaintext), FRAME_MAX - TAG_BYTES):
            piece = plaintext[start:start + FRAME_MAX - TAG_BYTES]
            header = struct.pack(">H", len(piece) + TAG_BYTES)
            sealed = self.tx.seal(_frame_nonce(self.tx_count), piece, header)
            self.tx_count += 1
            self.send_raw(header + sealed)

    def receive(self, timeout):
        """One frame's plaintext, or None if nothing complete arrived in time."""
        header = self._read_exact(2, timeout)
        if header is None:
            return None
        (length,) = struct.unpack(">H", header)
        if not TAG_BYTES <= length <= FRAME_MAX:
            raise SecureError("Bad frame length")
        body = self._read_exact(length, max(timeout, 5.0))
        if body is None:
            raise SecureError("The link stalled mid-frame")
        plaintext = self.rx.open(_frame_nonce(self.rx_count), body, header)
        self.rx_count += 1
        return plaintext

    def _read_exact(self, count, timeout):
        """`count` bytes, or None (keeping what came) if they didn't all
        arrive in time."""
        deadline = time.monotonic() + timeout
        while len(self.pending) < count:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            self.pending += self.receive_raw(count - len(self.pending), left)
        data, self.pending = self.pending[:count], self.pending[count:]
        return data


def _frame_nonce(counter):
    return b"\0\0\0\0" + struct.pack(">Q", counter)


# ----- Key storage ------------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    """Windows DPAPI: ties the stored pairing key to this Windows user."""
    crypt32 = ctypes.WinDLL("crypt32.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")
    source_buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not function(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(result)):
        raise SecureError("Windows could not protect the pairing key")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def protect_key(key):
    import base64
    return base64.b64encode(_dpapi(bytes(key), True)).decode("ascii")


def unprotect_key(text):
    import base64
    if not text:
        return None
    try:
        key = _dpapi(base64.b64decode(text), False)
    except (SecureError, ValueError):
        return None
    return key if len(key) == KEY_BYTES else None
