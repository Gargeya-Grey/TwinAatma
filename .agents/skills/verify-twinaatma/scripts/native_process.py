"""Read-only Windows process identity and owned-descendant shutdown evidence."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import threading
import time


class Entry(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                ("exe", wintypes.WCHAR * 260)]


class Basic(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_void_p), ("peb", ctypes.c_void_p),
                ("reserved2", ctypes.c_void_p * 2), ("pid", ctypes.c_size_t),
                ("parent", ctypes.c_void_p)]


class Unicode(ctypes.Structure):
    _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT), ("buffer", ctypes.c_void_p)]


class Kernel:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.nt = ctypes.WinDLL("ntdll", use_last_error=True)
        declarations = {
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)], wintypes.BOOL),
            "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL),
            "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL),
            "ReadProcessMemory": ([wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.POINTER(ctypes.c_size_t)], wintypes.BOOL),
            "QueryFullProcessImageNameW": ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                           ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        }
        for name, (arguments, result) in declarations.items():
            call = getattr(self.api, name)
            call.argtypes, call.restype = arguments, result
        self.nt.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                                                     wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        self.nt.NtQueryInformationProcess.restype = wintypes.LONG

    def table(self):
        handle = self.api.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot")
        try:
            result = []
            entry = Entry()
            entry.size = ctypes.sizeof(entry)
            more = self.api.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                result.append((int(entry.pid), int(entry.parent), entry.exe))
                more = self.api.Process32NextW(handle, ctypes.byref(entry))
            return result
        finally:
            self.api.CloseHandle(handle)

    def read(self, handle, address, size):
        buffer = ctypes.create_string_buffer(size)
        received = ctypes.c_size_t()
        if not self.api.ReadProcessMemory(handle, address, buffer, size, ctypes.byref(received)) or received.value != size:
            raise OSError(ctypes.get_last_error(), "ReadProcessMemory")
        return buffer.raw

    def parameters(self, handle):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise ValueError("Native observer requires a 64-bit Windows Python process")
        basic, returned = Basic(), wintypes.ULONG()
        result = self.nt.NtQueryInformationProcess(handle, 0, ctypes.byref(basic), ctypes.sizeof(basic), ctypes.byref(returned))
        if result != 0 or not basic.peb:
            raise OSError(result, "NtQueryInformationProcess")
        pointer = int.from_bytes(self.read(handle, basic.peb + 0x20, 8), "little")
        values = {}
        for name, offset in (("cwd", 0x38), ("image_parameter", 0x60), ("command_line", 0x70)):
            raw = Unicode.from_buffer_copy(self.read(handle, pointer + offset, ctypes.sizeof(Unicode)))
            if raw.length % 2 or raw.length > 65534:
                raise ValueError("Invalid remote UNICODE_STRING")
            values[name] = self.read(handle, raw.buffer, raw.length).decode("utf-16-le") if raw.length else ""
        return values

    def open(self, pid, parent, name):
        observed = time.time_ns()
        handle = self.api.OpenProcess(0x1000 | 0x100000 | 0x10 | 0x400 | 0x1, False, pid)
        record = {"pid": pid, "parent_pid": parent, "name": name, "observed_ns": observed,
                  "handle_open_error": None if handle else ctypes.get_last_error(),
                  "creation_filetime_100ns": None, "identity_error": None}
        if not handle:
            return handle, record
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if self.api.GetProcessTimes(handle, *(ctypes.byref(value) for value in (created, exited, kernel, user))):
            record["creation_filetime_100ns"] = (created.dwHighDateTime << 32) | created.dwLowDateTime
        length, image = wintypes.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if self.api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(length)):
            record["image"] = image.value
            try:
                with open(image.value, "rb") as stream:
                    record["image_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            except OSError as error:
                record["image_hash_error"] = str(error)
        try:
            record.update(self.parameters(handle))
        except (OSError, ValueError) as error:
            record["identity_error"] = str(error)
        return handle, record

    def stopped(self, handle):
        code = wintypes.DWORD()
        observed = time.time_ns()
        wait = self.api.WaitForSingleObject(handle, 0)
        ok = self.api.GetExitCodeProcess(handle, ctypes.byref(code))
        return {"stopped": wait == 0, "exit_code": int(code.value) if ok else None,
                "shutdown_observed_ns": observed, "wait_result": int(wait),
                "shutdown_method": "WaitForSingleObject and GetExitCodeProcess on the original retained kernel handle"}


class Tree:
    def __init__(self, root_pid, root_parent):
        self.kernel, self.records, self.handles = Kernel(), {}, {}
        self.root = root_pid
        handle, record = self.kernel.open(root_pid, root_parent, "direct-process")
        self.handles[root_pid], self.records[root_pid] = handle, record
        self.done, self.errors = threading.Event(), []
        self.lock = threading.RLock()
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    def sample(self):
        with self.lock:
            entries = self.kernel.table()
            for _ in range(6):
                added = False
                for pid, parent, name in entries:
                    if parent in self.records and pid not in self.records:
                        handle, record = self.kernel.open(pid, parent, name)
                        self.handles[pid], self.records[pid] = handle, record
                        added = True
                if not added:
                    break

    def _watch(self):
        while not self.done.is_set():
            try:
                self.sample()
            except Exception as error:
                self.errors.append(str(error))
            self.done.wait(0.02)

    def finish(self):
        self.sample()
        self.done.set()
        self.thread.join(timeout=5)
        records = []
        for pid, item in self.records.items():
            record = dict(item)
            handle = self.handles[pid]
            if handle:
                record.update(self.kernel.stopped(handle))
                if not record["stopped"]:
                    self.kernel.api.WaitForSingleObject(handle, 5000)
                    record.update(self.kernel.stopped(handle))
                if not record["stopped"] and pid != self.root:
                    record["verifier_forced_termination"] = bool(self.kernel.api.TerminateProcess(handle, 1))
                    self.kernel.api.WaitForSingleObject(handle, 5000)
                    record.update(self.kernel.stopped(handle))
                self.kernel.api.CloseHandle(handle)
            else:
                record.update(stopped=False, exit_code=None, shutdown_method="No retained handle. Shutdown unknown.")
            records.append(record)
        return {"processes": records, "errors": self.errors,
                "monitor_stopped": not self.thread.is_alive(),
                "scope": "Original retained kernel handles for the direct process and descendants observed in 20ms Toolhelp snapshots and synchronous protocol-boundary snapshots. Very short unseen descendants remain outside this scope."}
