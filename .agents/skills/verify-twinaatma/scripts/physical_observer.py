"""Retain physical identity and Python audit observations for protected Self."""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path


def physical(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    row = {"kind": "link" if linked else "file" if stat.S_ISREG(info.st_mode) else "directory" if stat.S_ISDIR(info.st_mode) else "other",
           "device": info.st_dev, "inode": info.st_ino, "size": info.st_size, "links": info.st_nlink}
    if row["kind"] == "file":
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if linked:
        row["target"] = os.readlink(path)
        try:
            target = path.stat()
            row["effective"] = {"device": target.st_dev, "inode": target.st_ino, "size": target.st_size, "links": target.st_nlink}
            if stat.S_ISREG(target.st_mode):
                row["effective"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            row["effective"] = None
    return row


def alias_relative(name, specs):
    for spec in specs:
        if name in {"hard-" + spec["id"], "symlink-" + spec["id"]}:
            return spec["path"]
    for host, relative in (("cursor", ".cursor/mcp.json"), ("vscode", ".vscode/mcp.json"), ("codex", ".codex/config.toml")):
        if name in {"hard-setup-" + host, "symlink-setup-" + host}:
            return "vault/" + relative
    return None


def snapshot(scope, name, specs):
    relative = alias_relative(name, specs)
    return {"self": physical(Path(scope) / "vault/People/Self.md"), "alias_relative": relative,
            "alias": physical(Path(scope) / relative) if relative else None}


PROTECTED_IO_OBSERVER = r'''
import hashlib as _writer_hash, stat as _writer_stat
_writer_self = _writer_os.path.abspath(_writer_os.path.join(_writer_os.environ.get('KNOWLEDGEOS_VAULT', ''), 'People', 'Self.md'))
def _writer_identity(_path):
    try:
        _info = _writer_os.stat(_path)
        _row = {'device': _info.st_dev, 'inode': _info.st_ino, 'size': _info.st_size, 'links': _info.st_nlink}
        if not isinstance(_path, int) and _writer_stat.S_ISREG(_info.st_mode):
            with open(_path, 'rb') as _stream:
                _row['sha256'] = _writer_hash.sha256(_stream.read()).hexdigest()
        return _row
    except (OSError, ValueError, TypeError):
        return None
_writer_original = _writer_identity(_writer_self)
print('IDENTITY_PROTECTED_AUDIT_START=' + _writer_json.dumps({'pid': _writer_os.getpid(), 'self_path': _writer_self, 'self': _writer_original}), file=_writer_sys.stderr)
def _writer_protected(_path):
    _identity = _writer_identity(_path)
    _lexical = not isinstance(_path, int) and _writer_os.path.normcase(_writer_os.path.abspath(_path)) == _writer_os.path.normcase(_writer_self)
    _same = bool(_writer_original and _identity and all(_identity.get(_key) == _writer_original[_key] for _key in ('device', 'inode')))
    return _lexical or _same, _identity
def _writer_audit(_event, _args):
    if _writer_original is None:
        return
    _paths = []
    if _event == 'open':
        _path, _mode, _flags = _args
        if not (_flags & (_writer_os.O_WRONLY | _writer_os.O_RDWR | _writer_os.O_TRUNC | _writer_os.O_APPEND | _writer_os.O_CREAT)):
            return
        _paths = [_path]
    elif _event in ('os.truncate', 'os.remove', 'os.chmod', 'os.utime'):
        _paths = [_args[0]]
    elif _event == 'os.rename':
        _paths = [_args[0], _args[1]]
    else:
        return
    _observed = []
    _touches = False
    for _path in _paths:
        _protected, _identity = _writer_protected(_path)
        _touches = _touches or _protected
        _observed.append({'path': _path if isinstance(_path, (str, int)) else _writer_os.fsdecode(_path), 'protected': _protected, 'identity': _identity})
    if _touches:
        print('IDENTITY_PROTECTED_IO=' + _writer_json.dumps({'pid': _writer_os.getpid(), 'event': _event, 'paths': _observed}), file=_writer_sys.stderr)
_writer_sys.addaudithook(_writer_audit)
'''
