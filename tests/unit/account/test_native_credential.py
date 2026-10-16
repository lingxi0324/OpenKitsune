import ctypes
import os
from pathlib import Path

import pytest

from openkitsune.account.native_credential import load_native_account_token


def protected_windows(value):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt.CryptProtectData.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    crypt.CryptProtectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
    source, output = Blob(len(value), buffer), Blob()
    assert crypt.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
    )
    try:
        return b"OAKDPAPI1\0" + ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def test_native_credential_is_optional_and_never_created_by_http_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_native_account_token() == ""
    assert not (tmp_path / ".openkitsune").exists()


def test_persistent_credential_format_and_tamper_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".openkitsune" / ".desktop-account-token"
    path.parent.mkdir()
    token = b"a" * 43
    encrypted = protected_windows(token) if os.name == "nt" else token
    path.write_bytes(encrypted)
    path.chmod(0o600)
    assert load_native_account_token() == token.decode()
    if os.name == "nt":
        assert token not in encrypted
        path.write_bytes(encrypted[:-8] + b"tampered")
        assert load_native_account_token() == ""
    path.write_bytes(b"bad")
    assert load_native_account_token() == ""


@pytest.mark.skipif(os.name == "nt", reason="Unix file permissions")
def test_world_readable_credential_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".openkitsune" / ".desktop-account-token"
    path.parent.mkdir()
    path.write_bytes(b"a" * 43)
    path.chmod(0o644)
    assert load_native_account_token() == ""
