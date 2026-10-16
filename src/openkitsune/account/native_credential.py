"""Read the same-user credential created by the native desktop IPC command.

This credential authenticates native access to a local backend, not an Account
identity. It survives desktop restarts and works with independently started
backends. No HTTP endpoint publishes it. Windows stores a user-scoped DPAPI blob;
Unix stores an owner-only file. It deliberately lives outside workspace roots.
"""

import ctypes
import os
import re
from pathlib import Path


def _unprotect_windows(value: bytes) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptUnprotectData.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, output = Blob(len(value), buffer), Blob()
    if not crypt.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    ):
        raise OSError("native credential decryption failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def load_native_account_token() -> str:
    path = Path.home() / ".openkitsune" / ".desktop-account-token"
    try:
        info = path.lstat()
        if path.is_symlink() or info.st_size > 8192:
            return ""
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            return ""
        data = path.read_bytes()
        if os.name == "nt":
            prefix = b"OAKDPAPI1\0"
            if not data.startswith(prefix):
                return ""
            data = _unprotect_windows(data[len(prefix) :])
        token = data.decode("ascii")
        return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else ""
    except (OSError, ValueError, UnicodeError):
        return ""
