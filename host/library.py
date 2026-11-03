"""Private, user-granted Windows media roots and bounded opaque-ID browsing."""
from __future__ import annotations

import json
from itertools import islice
import os
from pathlib import Path
import secrets
import threading

MEDIA_SUFFIXES = {'.mkv', '.mp4', '.m2ts', '.ts'}
PAGE_SIZE = 100
MAX_BROWSE_ITEMS = 10000


class Library:
    """A small library index. Persist only root grants; item IDs are session-local."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.roots: dict[str, Path] = {}
        self.items: dict[str, tuple[str, Path]] = {}
        self.load_error = ''
        self._load()

    def _load(self):
        try:
            raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return
        except OSError:
            self.load_error = 'Saved Windows folder grants could not be read; the file was preserved'
            return
        try:
            doc = json.loads(raw)
            if not isinstance(doc, dict) or not isinstance(doc.get('roots'), list):
                raise ValueError('invalid saved library structure')
            roots = doc['roots']
            for row in roots:
                if (not isinstance(row, dict) or not isinstance(row.get('id'), str)
                    or not 16 <= len(row['id']) <= 64
                    or not all(c.isalnum() or c in '-_' for c in row['id'])
                    or not isinstance(row.get('path'), str)):
                    raise ValueError('invalid saved library grant')
                p = Path(row['path'])
                if not p.is_absolute(): raise ValueError('saved root path is not absolute')
                self.roots[row['id']] = p
        except (OSError, ValueError, TypeError):
            # Preserve unreadable/corrupt grants; never replace them on the next add.
            self.load_error = 'Saved Windows folder grants could not be read; the file was preserved'

    def _save(self):
        if self.load_error:
            raise ValueError(self.load_error)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'roots': [{'id': k, 'path': str(v)}
            for k, v in self.roots.items()]}, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, self.path)

    @staticmethod
    def _safe_root(path):
        p = Path(path).expanduser().resolve(strict=True)
        if not p.is_dir():
            raise ValueError('Choose an existing Windows folder')
        return p

    def add(self, path):
        p = self._safe_root(path)
        with self.lock:
            if self.load_error: raise ValueError(self.load_error)
            # Re-adding a root is idempotent and does not mint another grant.
            for ident, existing in self.roots.items():
                if os.path.normcase(str(existing)) == os.path.normcase(str(p)):
                    return ident
            if len(self.roots) >= 1000:
                raise ValueError('Remove an unused shared folder before adding another')
            ident = secrets.token_urlsafe(18)
            self.roots[ident] = p
            self._save()
            return ident

    def remove(self, ident):
        with self.lock:
            if self.load_error: raise ValueError(self.load_error)
            if ident not in self.roots:
                raise ValueError('Shared folder no longer exists')
            del self.roots[ident]
            self.items = {key: value for key, value in self.items.items() if value[0] != ident}
            self._save()

    def providers(self):
        return [{'id': 'windows', 'label': 'Windows folders', 'available': not bool(self.load_error)}]

    def roots_list(self):
        with self.lock:
            out = []
            for ident, root in self.roots.items():
                try:
                    current = root.resolve(strict=True)
                    available = current.is_dir() and self._same_path(current, root)
                except (OSError, RuntimeError):
                    available = False
                out.append({'id': ident, 'name': (root.name or str(root))[:255],
                            'directory': True, 'available': available})
            return out

    @staticmethod
    def _same_path(left, right):
        return os.path.normcase(str(left)) == os.path.normcase(str(right))

    def _resolve_id(self, ident):
        if not ident:
            raise ValueError('Invalid library entry')
        with self.lock:
            try:
                root_id, path = self.items[ident]
                root = self.roots[root_id]
            except KeyError as exc:
                if ident in self.roots:
                    root_id, root = ident, self.roots[ident]
                    path = root
                else:
                    raise ValueError('Library entry expired; browse again') from exc
            if root_id not in self.roots or self.roots[root_id] != root:
                raise ValueError('Shared folder was removed')
            try:
                root_current = root.resolve(strict=True)
                if not root_current.is_dir() or not self._same_path(root_current, root):
                    raise ValueError('Shared folder changed identity; remove and add it again')
                # Resolve on every use. Symlink/junction targets may change after browsing.
                resolved = path.resolve(strict=True)
                resolved.relative_to(root_current)
                if path.is_symlink() or not (resolved.is_dir() or (resolved.is_file() and resolved.suffix.lower() in MEDIA_SUFFIXES)):
                    raise ValueError('Library entry is unavailable')
            except (OSError, RuntimeError, ValueError) as exc:
                if isinstance(exc, ValueError) and (str(exc) == 'Library entry is unavailable'
                    or str(exc).startswith('Shared folder changed identity')):
                    raise
                raise ValueError('Library entry is outside the shared folder or unavailable') from exc
            return root_id, root, resolved

    def browse(self, entry='', cursor=0):
        if type(cursor) is not int or not 0 <= cursor <= MAX_BROWSE_ITEMS:
            raise ValueError('Invalid browse cursor')
        if not entry:
            if self.load_error: raise ValueError(self.load_error)
            rows = self.roots_list()
            return {'provider': 'windows', 'entry': '', 'parent': '', 'label': 'Windows folders',
                    'entries': rows[cursor:cursor + PAGE_SIZE],
                    'next_cursor': cursor + PAGE_SIZE if cursor + PAGE_SIZE < len(rows) else None}
        root_id, root, folder = self._resolve_id(entry)
        if not folder.is_dir():
            raise ValueError('Choose a folder to browse')
        parent = '' if folder == root else self._id_for(root_id, folder.parent)
        try:
            with os.scandir(folder) as scan:
                candidates = [folder / item.name for item in islice(scan, MAX_BROWSE_ITEMS + 1)]
            if len(candidates) > MAX_BROWSE_ITEMS:
                raise ValueError('This folder has too many items to browse; choose a smaller folder')
            candidates.sort(key=lambda p: (not p.is_dir(), p.name.casefold()))
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError('Could not browse this folder') from exc
        results = []
        for path in candidates:
            if path.name.startswith('.'):
                continue
            try:
                # Never issue a remote ID for a symlink/junction target.
                if path.is_symlink():
                    continue
                resolved = path.resolve(strict=True)
                resolved.relative_to(root.resolve(strict=True))
                is_dir = resolved.is_dir()
                if not is_dir and (not resolved.is_file() or resolved.suffix.lower() not in MEDIA_SUFFIXES):
                    continue
                row = {'id': self._id_for(root_id, resolved), 'name': path.name, 'directory': is_dir}
                if not is_dir:
                    row['size'] = resolved.stat().st_size
                results.append(row)
            except (OSError, RuntimeError, ValueError):
                continue
        page = results[cursor:cursor + PAGE_SIZE]
        return {'provider': 'windows', 'entry': entry, 'parent': parent,
                'label': folder.name or str(folder), 'entries': page,
                'next_cursor': cursor + PAGE_SIZE if cursor + PAGE_SIZE < len(results) else None}

    def _id_for(self, root_id, path):
        ident = secrets.token_urlsafe(18)
        with self.lock:
            while len(self.items) >= 10000:
                self.items.pop(next(iter(self.items)))
            self.items[ident] = (root_id, Path(path))
        return ident

    def resolve_file(self, ident):
        _, _, path = self._resolve_id(ident)
        if not path.is_file():
            raise ValueError('Choose a media file')
        return path
