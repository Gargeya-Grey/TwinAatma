# PyInstaller spec for the single `twinaatma` binary.
# Build from the repo root:  pyinstaller pyinstaller.spec
# Output: dist/twinaatma/twinaatma (.exe on Windows)
# Core stays stdlib-only (sqlite FTS5 ships with Python), so no hidden imports needed.
# Starter files are bundled so `twinaatma init` can create a complete vault; they are
# located at runtime via knowledgeos.resources.toolkit_root().
import os

ROOT = SPECPATH

block_cipher = None

datas = [
    (os.path.join(ROOT, "Templates"), "Templates"),
    (os.path.join(ROOT, "AGENTS.md"), "."),
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "README.md"), "."),
    (os.path.join(ROOT, "knowledgeos.config.example.json"), "."),
    (os.path.join(ROOT, ".cursor", "hooks.json"), ".cursor"),
    (os.path.join(ROOT, ".cursor", "hooks"), os.path.join(".cursor", "hooks")),
    (os.path.join(ROOT, ".cursor", "rules"), os.path.join(".cursor", "rules")),
]

a = Analysis(
    [os.path.join(ROOT, "knowledgeos", "binary_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="twinaatma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="twinaatma",
)
