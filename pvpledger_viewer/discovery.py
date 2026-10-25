from pathlib import Path


def discover(root):
    """Accept installation, retail, WTF, or Account root; only known layouts."""
    root = Path(root)
    candidates = [root / '_retail_/WTF/Account', root / 'WTF/Account', root / 'Account', root]
    found = set()
    for base in candidates:
        for name in ('PvPLedger.lua', 'REFlex.lua'):
            for pattern in (f'*/SavedVariables/{name}', f'*/*/*/SavedVariables/{name}'):
                found.update(p.resolve() for p in base.glob(pattern) if p.is_file())
    return sorted(found)
