"""Optional, process-private Windows font resources; never install system fonts."""
import atexit
import sys
from tkinter import font as tkfont
from ..runtime import resource_path

_loaded = set()


def _register_private(path):
    import ctypes
    from ctypes import wintypes
    gdi = ctypes.WinDLL('gdi32')
    add = gdi.AddFontResourceExW
    add.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
    add.restype = ctypes.c_int
    remove = gdi.RemoveFontResourceExW
    remove.argtypes = add.argtypes
    remove.restype = wintypes.BOOL
    private = 0x10  # FR_PRIVATE: usable only by this process, removed at exit.
    if not add(str(path), private, None):
        return False
    atexit.register(remove, str(path), private, None)
    return True


def register_cinzel(root):
    """Return availability; any resource, platform or font error is harmless."""
    try:
        path = resource_path('assets/fonts/Cinzel.ttf')
        if sys.platform != 'win32' or not path.is_file():
            return False
        if path not in _loaded:
            if not _register_private(path):
                return False
            _loaded.add(path)
        probe = tkfont.Font(root=root, family='Cinzel', size=15)
        return probe.actual('family').casefold() == 'cinzel'
    except Exception:
        return False
