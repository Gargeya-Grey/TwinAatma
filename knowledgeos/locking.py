"""Cross-process writer ownership, released by the OS when a process exits."""
from __future__ import annotations
import contextlib
import errno
import json
import os
from pathlib import Path
import secrets
import stat
import threading
import time

_MUTEXES = {}
_MUTEX_GUARD = threading.Lock()
_HELD = threading.local()


def _dead(pid):
    if not isinstance(pid,int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        if not handle:
            return ctypes.get_last_error()==87
        try:
            return kernel.WaitForSingleObject(handle,0)==0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        return True
    except (PermissionError,OSError):
        pass
    return False


def _plain(path):
    if not path.exists() and not path.is_symlink():
        return
    info=path.lstat()
    reparse = bool(getattr(info,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0))
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or reparse:
        raise OSError(f'Lock is not a file or is not a plain single-link file: {path}')


@contextlib.contextmanager
def file_lock(path: Path, timeout=10.0, message='Another writer is busy; try again shortly'):
    path=Path(path).absolute()
    key=str(path)
    with _MUTEX_GUARD:
        mutex=_MUTEXES.setdefault(key,threading.RLock())
    if not mutex.acquire(timeout=max(0.0,timeout)):
        raise TimeoutError(message)
    held=getattr(_HELD,'paths',set())
    _HELD.paths=held
    if key in held:
        try:
            yield
        finally:
            mutex.release()
        return
    deadline=time.monotonic()+timeout
    fd=None
    owned=False
    token=json.dumps({'pid':os.getpid(),'nonce':secrets.token_hex(16)}).encode()
    guard=path.with_name(path.name+'.guard')
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        _plain(guard)
        fd=os.open(guard,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise OSError('Unsafe lock guard')
        if info.st_size==0:
            os.write(fd,b'0')
        while True:
            try:
                os.lseek(fd,0,0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                owned=True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):
                    raise
                if time.monotonic()>=deadline:
                    raise TimeoutError(message) from exc
                time.sleep(0.025)
        while path.exists() or path.is_symlink():
            _plain(path)
            before=path.read_bytes()
            try:
                owner=json.loads(before)
                pid=owner.get('pid') if isinstance(owner,dict) else owner
            except (ValueError,UnicodeError):
                pid=None
            if _dead(pid) and path.read_bytes()==before:
                path.unlink()
                continue
            if time.monotonic()>=deadline:
                raise TimeoutError(message)
            time.sleep(0.025)
        marker=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        marker_info=os.fstat(marker)
        try:
            offset=0
            while offset<len(token):
                written=os.write(marker,token[offset:])
                if written<=0:
                    raise OSError(errno.EIO,'Could not write lock owner')
                offset+=written
        except BaseException:
            os.close(marker)
            # Only remove the exact marker this attempt created, under our OS
            # guard. A partial token cannot identify its own owner on retry.
            with contextlib.suppress(OSError):
                current=path.lstat()
                if (current.st_dev,current.st_ino)==(marker_info.st_dev,marker_info.st_ino):
                    path.unlink()
            raise
        else:
            os.close(marker)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
            with contextlib.suppress(OSError):
                if path.read_bytes()==token:
                    path.unlink()
    finally:
        if fd is not None:
            if owned:
                with contextlib.suppress(OSError):
                    os.lseek(fd,0,0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(fd,fcntl.LOCK_UN)
            os.close(fd)
        mutex.release()
