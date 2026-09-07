# SPDX-License-Identifier: GPL-3.0-or-later
"""Private local control channel, separate from overlay IPC.

Loopback TCP carries bounded JSON (never pickle). A fresh 256-bit bearer secret
is stored under a private application directory; POSIX checks ownership/mode,
Windows applies a protected user-only ACL before publishing it. Persistent
connections get an unforgeable owner identity, released on EOF or idle expiry.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import stat
import subprocess
import threading
from pathlib import Path

_LIMIT = 16384


def _private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise PermissionError("Control directory must be a real private directory")
    if os.name == "nt":
        # whoami returns the current token SID, independent of environment names.
        identity = (
            subprocess.run(
                ["whoami", "/user", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            .stdout.strip()
            .split(",")[-1]
            .strip('"')
        )
        if not identity.startswith("S-1-"):
            raise PermissionError("Cannot establish control endpoint ownership")
        import ctypes
        from ctypes import wintypes

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        descriptor = ctypes.c_void_p()
        acl = ctypes.c_void_p()
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        convert.restype = wintypes.BOOL
        get_acl = advapi.GetSecurityDescriptorDacl
        get_acl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        ]
        get_acl.restype = wintypes.BOOL
        apply_acl = advapi.SetNamedSecurityInfoW
        apply_acl.argtypes = [
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        apply_acl.restype = wintypes.DWORD
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        # Replace, rather than merge with, any existing explicit DACL. Inherit
        # only this user's full access to endpoint files and disable inheritance.
        if not convert(f"D:P(A;OICI;FA;;;{identity})", 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not get_acl(
                descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            error = apply_acl(str(path), 1, 0x80000004, None, None, acl, None)
            if error:
                raise ctypes.WinError(error)
        finally:
            kernel.LocalFree(descriptor)
    else:
        if info.st_uid != os.getuid():
            raise PermissionError("Control directory is owned by another user")
        path.chmod(0o700)


def _windows_private_acl(path: Path) -> bool:
    """Validate the exact protected, single-user ACL created by the server."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    descriptor, acl = ctypes.c_void_p(), ctypes.c_void_p()
    get_info = advapi.GetNamedSecurityInfoW
    get_info.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_info.restype = wintypes.DWORD
    convert = advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.c_void_p,
    ]
    convert.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if get_info(str(path), 1, 4, None, None, ctypes.byref(acl), None, ctypes.byref(descriptor)):
        return False
    rendered = wintypes.LPWSTR()
    try:
        if not convert(descriptor, 1, 4, ctypes.byref(rendered), None):
            return False
        identity = (
            subprocess.run(
                ["whoami", "/user", "/fo", "csv", "/nh"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            .stdout.strip()
            .split(",")[-1]
            .strip('"')
        )
        # Windows may add the auto-inheritance metadata flag; permissions and
        # sole permitted SID must still match exactly, with inheritance blocked.
        return rendered.value in {f"D:P(A;OICI;FA;;;{identity})", f"D:PAI(A;OICI;FA;;;{identity})"}
    finally:
        if rendered:
            kernel.LocalFree(ctypes.cast(rendered, ctypes.c_void_p))
        kernel.LocalFree(descriptor)


def _read_endpoint(path: Path) -> dict:
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or stat.S_ISLNK(parent.st_mode):
        raise PermissionError("Control directory must be a real private directory")
    if os.name != "nt" and (parent.st_uid != os.getuid() or parent.st_mode & 0o077):
        raise PermissionError("Control directory must be accessible only by its owner")
    if os.name == "nt" and not _windows_private_acl(path.parent):
        raise PermissionError("Control directory must have a protected user-only ACL")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > _LIMIT:
        raise PermissionError("Invalid control endpoint file")
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise PermissionError("Control endpoint must be readable only by its owner")
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("token"), str):
        raise ValueError("Malformed control endpoint")
    return data


def _encode(value: dict) -> bytes:
    data = json.dumps(value, allow_nan=False, separators=(",", ":")).encode() + b"\n"
    if len(data) > _LIMIT:
        raise ValueError("Control frame is too large")
    return data


def _decode(stream) -> dict:
    line = stream.readline(_LIMIT + 1)
    if not line:
        raise EOFError("Control connection closed")
    if len(line) > _LIMIT or not line.endswith(b"\n"):
        raise ValueError("Invalid control frame length")
    value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict):
        raise ValueError("Control frame must be an object")
    return value


class LocalClient:
    def __init__(self, endpoint: dict, timeout: float):
        self._socket = socket.create_connection(("127.0.0.1", endpoint["port"]), timeout)
        self._stream = self._socket.makefile("rwb")
        self._token = endpoint["token"]
        self._lock = threading.Lock()

    def request(self, message: dict) -> dict:
        with self._lock:
            self._stream.write(_encode({"token": self._token, "message": message}))
            self._stream.flush()
            return _decode(self._stream)

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)
        self._stream.close()
        self._socket.close()


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # Never print exception/frame contents: requests may eventually carry
        # settings values. The core reports fixed structural errors itself.
        pass


class LocalServer:
    def __init__(self, directory: Path, handler, disconnected):
        _private_directory(directory)
        self._path = directory / "endpoint.json"
        self._token = secrets.token_hex(32)
        self._clients: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(8)
        owner = self

        class RequestHandler(socketserver.StreamRequestHandler):
            def handle(self):
                if not owner._slots.acquire(blocking=False):
                    return
                session = secrets.token_hex(16)
                with owner._lock:
                    owner._clients.add(self.request)
                try:
                    self.request.settimeout(30)
                    while True:
                        frame = _decode(self.rfile)
                        token = frame.get("token")
                        if not isinstance(token, str) or not hmac.compare_digest(
                            token, owner._token
                        ):
                            return
                        message = frame.get("message")
                        if not isinstance(message, dict):
                            return
                        response = handler(message, session)
                        self.wfile.write(_encode(response))
                        self.wfile.flush()
                except (OSError, EOFError, ValueError, RecursionError):
                    pass
                finally:
                    with owner._lock:
                        owner._clients.discard(self.request)
                    owner._slots.release()
                    disconnected(session)

        self._server = _TCPServer(("127.0.0.1", 0), RequestHandler)
        # The daemon's instance lock precedes serve. O_EXCL also refuses a live
        # endpoint if a different caller accidentally tries to bind twice.
        try:
            if self._path.exists():
                import psutil

                old = _read_endpoint(self._path)
                try:
                    process = psutil.Process(old["pid"])
                    live = process.create_time() == old["started_epoch"]
                except psutil.NoSuchProcess:
                    live = False
                if live:
                    raise OSError("A control server is already running")
                self._path.unlink()
            import psutil

            current = psutil.Process()
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    {
                        "port": self._server.server_address[1],
                        "token": self._token,
                        "pid": current.pid,
                        "started_epoch": current.create_time(),
                    },
                    stream,
                )
        except Exception:
            self._server.server_close()
            raise
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            clients = tuple(self._clients)
        for client in clients:
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
        self._thread.join(timeout=1)
        try:
            if _read_endpoint(self._path)["token"] == self._token:
                self._path.unlink()
        except (OSError, ValueError):
            pass


class LocalControlTransport:
    def __init__(self, directory: Path):
        self.directory = directory

    def serve(self, handler, disconnected) -> LocalServer:
        return LocalServer(self.directory, handler, disconnected)

    def connect(self, timeout: float = 2.0) -> LocalClient:
        return LocalClient(_read_endpoint(self.directory / "endpoint.json"), timeout)
