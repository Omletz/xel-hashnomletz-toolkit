# PyInstaller spec for a single-file Windows executable. MUST be run on Windows (or a Windows CI runner) --
# PyWebView's Windows backend (EdgeWebView2) and a real Windows PyInstaller build can't be produced from Linux.
# Usage on Windows:  pyinstaller build_windows.spec
block_cipher = None
a = Analysis(
    ['app/main.py'],
    pathex=['app'],
    datas=[('app/web', 'web')],
    hiddenimports=[],
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
