# One-folder Windows build. Only application/dependency resources; no archives or fixtures.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks.tcl_tk import tcltk_info
if not tcltk_info.available:
    raise RuntimeError('A usable Tcl/Tk installation is required. Build with the full Python 3.12 runtime and access to its Tcl/Tk resources.')
root = Path(SPECPATH)
a = Analysis([str(root / 'packaging' / 'launcher.py')],
             pathex=[str(root), str(root / '.deps')], binaries=[],
             datas=collect_data_files('tzdata') + [
                 (str(root / 'pvpledger_viewer' / 'assets' / 'fonts' / 'Cinzel.ttf'), 'assets/fonts'),
                 (str(root / 'pvpledger_viewer' / 'assets' / 'fonts' / 'OFL.txt'), 'assets/fonts')],
             hiddenimports=['matplotlib.backends.backend_tkagg', 'matplotlib.backends.backend_agg', 'tzdata'],
             hookspath=[], hooksconfig={'matplotlib': {'backends': ['TkAgg', 'Agg']}},
             runtime_hooks=[], excludes=['pytest', 'slpp'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PvPLedgerViewer',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PvPLedgerViewer')
