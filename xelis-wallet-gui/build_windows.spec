# PyInstaller spec for a single-file Windows executable. MUST be run on Windows (or a Windows CI runner) --
# PyWebView's Windows backend (EdgeWebView2) and a real Windows PyInstaller build can't be produced from Linux.
# Usage on Windows:  pyinstaller build_windows.spec
#
# hiddenimports: pgpy (same reason as the sibling xelis/miner-gui spec -- PyInstaller's static analysis
# doesn't reliably pick it up) and winpty (app/pty_compat.py imports it lazily, inside an `if os.name ==
# "nt":` branch at runtime, which PyInstaller's import scanner can miss).
#
# winpty native binaries: CONFIRMED LIVE 2026-09-23 that without this, the packaged exe's wallet-creation
# raw ConPTY escape sequences (e.g. "\x1b[?9001h\x1b[?1004h") leaked through as literal error text instead
# of being consumed by a real console host -- the pty was never actually initializing correctly. Root
# cause (confirmed against a documented, known PyInstaller+pywinpty gap, not guessed): PyInstaller's DLL
# import-table scanning bundles conpty.dll/winpty.dll (real imports) but MISSES OpenConsole.exe/
# winpty-agent.exe, because conpty.dll locates that helper exe via a runtime string path, not a static
# import PyInstaller can see. There is no pyinstaller-hooks-contrib hook for winpty to fill this gap
# automatically (checked 2026-09-23), so it's done explicitly below. The destination folder inside the
# bundle MUST be named 'winpty' -- conpty.dll looks for the helper exe right next to itself at that path.
import os
try:
    import winpty
    _winpty_dir = os.path.dirname(os.path.abspath(winpty.__file__))
    _winpty_native_files = ['OpenConsole.exe', 'winpty-agent.exe', 'conpty.dll', 'winpty.dll']
    _winpty_binaries = [
        (os.path.join(_winpty_dir, f), 'winpty')
        for f in _winpty_native_files
        if os.path.exists(os.path.join(_winpty_dir, f))
    ]
    if not _winpty_binaries:
        print("WARNING: no winpty native binaries found to bundle -- wallet creation will likely break "
              "in the packaged exe the same way it did on 2026-09-23. Check the installed winpty "
              "package's actual directory layout (this build's pywinpty version may differ).")
except ImportError:
    _winpty_binaries = []  # building on non-Windows for some reason; nothing to bundle

# certifi's cacert.pem: bundled explicitly rather than relying on PyInstaller's static analysis to find it
# (it's a data file, not an import, so hiddenimports alone won't pull it in). app/downloader.py uses this
# bundle instead of the OS cert store for GitHub downloads -- see its module docstring for the real
# outside-miner failure (CERTIFICATE_VERIFY_FAILED on a fresh Windows box) this closes.
import certifi

block_cipher = None
a = Analysis(
    ['app/main.py'],
    pathex=['app'],
    datas=[('app/web', 'web'), (certifi.where(), 'certifi')],
    binaries=_winpty_binaries,
    hiddenimports=['pgpy', 'winpty', 'certifi'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='HashNOmletz-XelisWallet',
    console=False,
    onefile=True,
    icon='assets/hashnomletz.ico',   # same Hash'n'Omletz dashboard logo as the Rigel miner GUI's icon
)
