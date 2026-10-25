"""Read-only bundled resources are independent of persistent APPDATA storage."""
from pathlib import Path
import sys


def resource_path(relative):
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Resource path must stay within the application bundle')
    return path
