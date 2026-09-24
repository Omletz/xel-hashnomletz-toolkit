# PyInstaller spec for a single-file Windows executable. MUST be run on Windows (or a Windows CI runner) --
# PyWebView's Windows backend (EdgeWebView2) and a real Windows PyInstaller build can't be produced from Linux.
# Usage on Windows:  pyinstaller build_windows.spec
#
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
    hiddenimports=['certifi'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='HashNOmletz-RigelMiner',
    console=False,
    onefile=True,
    icon='assets/hashnomletz.ico',   # Hash'n'Omletz dashboard logo (public-dashboard/logo.png), padded to
                                      # square and rendered at 16/32/48/256px -- see assets/ for how it was made
)
