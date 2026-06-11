"""
Server-side folder browser for the in-app path picker.

Browsers hide absolute filesystem paths, and the app runs in a container, so a
native OS file dialog can't supply the server path the backend needs. Instead the
UI walks the server's directories through this lister. Everything is constrained
to a set of allowed roots (Config.BROWSE_ROOTS + the configured e-book folder) so
the picker can never escape into the rest of the container filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path

from .config import Config
from .ebookmeta import BOOK_EXTENSIONS


def allowed_roots() -> list[str]:
    """Real, existing roots the picker may traverse."""
    from .settings import get_ebooks_dir
    raw = list(Config.BROWSE_ROOTS)
    ebooks = get_ebooks_dir()
    if ebooks:
        raw.append(ebooks)
    roots = []
    for r in raw:
        try:
            rp = os.path.realpath(r)
        except OSError:
            continue
        if os.path.isdir(rp) and rp not in roots:
            roots.append(rp)
    return roots


def _within_roots(path: str, roots: list[str]) -> bool:
    try:
        rp = os.path.realpath(path)
    except OSError:
        return False
    for root in roots:
        try:
            if os.path.commonpath([rp, root]) == root:
                return True
        except ValueError:
            continue  # different drives / relative — not under this root
    return False


def list_dir(path: str | None = None, roots: list[str] | None = None) -> dict:
    """List sub-folders and book files under *path*.

    With no path (or an out-of-bounds one) returns the allowed roots as shortcuts.
    Returns {path, parent, shortcuts:[{name,path}], dirs:[{name,path}],
    files:[{name,path,size}]}. Raises NotADirectoryError if path isn't a directory.
    """
    roots = roots if roots is not None else allowed_roots()
    shortcuts = [{"name": r, "path": r} for r in roots]

    # No path, or a path outside the roots → present the roots to choose from.
    if not path or not _within_roots(path, roots):
        return {"path": None, "parent": None, "shortcuts": shortcuts,
                "dirs": [], "files": []}

    real = os.path.realpath(path)
    if not os.path.isdir(real):
        raise NotADirectoryError(f"Not a directory: {path}")

    dirs, files = [], []
    try:
        entries = sorted(os.scandir(real), key=lambda e: e.name.lower())
    except PermissionError:
        entries = []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                dirs.append({"name": e.name, "path": e.path})
            elif e.is_file(follow_symlinks=False) and Path(e.name).suffix.lower() in BOOK_EXTENSIONS:
                files.append({"name": e.name, "path": e.path, "size": e.stat().st_size})
        except OSError:
            continue

    parent = os.path.dirname(real)
    if not _within_roots(parent, roots) or parent == real:
        parent = None
    return {"path": real, "parent": parent, "shortcuts": shortcuts,
            "dirs": dirs, "files": files}
