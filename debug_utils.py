import os
import json
import threading

_MAP_FILE = '.map.json'
_COUNTER_FILE = '.counter'

DEBUG_DIR = os.environ.get('DOIREF_DEBUG_DIR', 'debug')

# Global debug toggle: disabled by default unless explicitly enabled via env
# Set DOIREF_DEBUG to one of: 1, true, yes, on (case-insensitive) to enable
_DEBUG_ENABLED = str(os.environ.get('DOIREF_DEBUG', '')).lower() in {'1', 'true', 'yes', 'on'}

def set_debug_enabled(enabled: bool):
    global _DEBUG_ENABLED
    _DEBUG_ENABLED = bool(enabled)

def is_debug_enabled() -> bool:
    return bool(_DEBUG_ENABLED)

# In-memory cache and lock for thread-safety
_lock = threading.Lock()
_mapping = None  # lazy-loaded dict: base_name -> canonical_name
_counter = None  # lazy-loaded int


def _ensure_debug_dir():
    if not os.path.exists(DEBUG_DIR):
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
        except Exception:
            pass


def _load_state():
    global _mapping, _counter
    if _mapping is not None and _counter is not None:
        return
    # Only prepare state files when debug is enabled
    if not _DEBUG_ENABLED:
        _mapping = {}
        _counter = 0
        return
    _ensure_debug_dir()
    map_path = os.path.join(DEBUG_DIR, _MAP_FILE)
    counter_path = os.path.join(DEBUG_DIR, _COUNTER_FILE)
    try:
        if os.path.exists(map_path):
            with open(map_path, 'r', encoding='utf-8') as mf:
                _mapping = json.load(mf)
        else:
            _mapping = {}
    except Exception:
        _mapping = {}
    try:
        if os.path.exists(counter_path):
            with open(counter_path, 'r', encoding='utf-8') as cf:
                _counter = int(cf.read().strip() or '0')
        else:
            _counter = 0
    except Exception:
        _counter = 0


def _save_state():
    if not _DEBUG_ENABLED:
        return
    _ensure_debug_dir()
    map_path = os.path.join(DEBUG_DIR, _MAP_FILE)
    counter_path = os.path.join(DEBUG_DIR, _COUNTER_FILE)
    try:
        with open(map_path, 'w', encoding='utf-8') as mf:
            json.dump(_mapping or {}, mf, indent=2, ensure_ascii=False)
    except Exception:
        pass
    try:
        with open(counter_path, 'w', encoding='utf-8') as cf:
            cf.write(str(_counter or 0))
    except Exception:
        pass


def _alloc_canonical(base_name: str) -> str:
    """Allocate or return a canonical filename for base_name.

    Canonical form: zero-padded 3-digit sequence + '_' + base_name
    e.g. '001_doiref_1_raw_lines.txt'
    """
    global _mapping, _counter
    with _lock:
        _load_state()
        base = os.path.basename(base_name)
        if base in _mapping:
            return _mapping[base]
        # increment counter
        _counter = (_counter or 0) + 1
        seq = f"{_counter:03d}"
        canonical = f"{seq}_{base}"
        # ensure uniqueness on filesystem
        dest = os.path.join(DEBUG_DIR, canonical)
        i = 1
        while os.path.exists(dest):
            canonical = f"{seq}_{i:02d}_{base}"
            dest = os.path.join(DEBUG_DIR, canonical)
            i += 1
        _mapping[base] = canonical
        _save_state()
        return canonical


def _migrate_existing():
    """Migrate existing files in debug/ into the canonical mapping.

    This scans files in DEBUG_DIR, infers base names by stripping leading
    numeric prefixes if present, and registers them in the mapping while
    renaming them to the canonical form if necessary.
    """
    if not _DEBUG_ENABLED:
        return
    _ensure_debug_dir()
    global _mapping, _counter
    with _lock:
        _load_state()
        entries = []
        for name in os.listdir(DEBUG_DIR):
            if name in (_MAP_FILE, _COUNTER_FILE):
                continue
            p = os.path.join(DEBUG_DIR, name)
            if not os.path.isfile(p):
                continue
            # derive base by removing a leading numeric prefix like '001_' or '001_01_'
            parts = name.split('_', 1)
            if parts and parts[0].isdigit() and len(parts[0]) >= 1:
                base = parts[1] if len(parts) > 1 else name
            else:
                base = name
            entries.append((name, base))
        # sort so numeric-prefixed files come first (stable)
        entries.sort()
        for orig_name, base in entries:
            if base in _mapping:
                # already mapped; skip
                continue
            # allocate next canonical name but preserve original file by
            # renaming it to the canonical filename
            _counter = (_counter or 0) + 1
            seq = f"{_counter:03d}"
            canonical = f"{seq}_{base}"
            dest = os.path.join(DEBUG_DIR, canonical)
            src = os.path.join(DEBUG_DIR, orig_name)
            i = 1
            while os.path.exists(dest):
                canonical = f"{seq}_{i:02d}_{base}"
                dest = os.path.join(DEBUG_DIR, canonical)
                i += 1
            try:
                # rename only if necessary
                if src != dest:
                    os.rename(src, dest)
            except Exception:
                # if rename fails, try copying
                try:
                    import shutil
                    shutil.copy2(src, dest)
                except Exception:
                    pass
            _mapping[base] = canonical
        _save_state()


def write_debug(name: str, content, encoding='utf-8', canonicalize=True):
    """Write debug output to a canonical file under the debug directory.

    If canonicalize is True (default), the filename will be allocated a
    zero-padded numeric prefix and persisted in an internal mapping so
    subsequent calls that reference the base name can find the same file.
    """
    if not _DEBUG_ENABLED:
        return
    _ensure_debug_dir()
    base = os.path.basename(name)
    try:
        if canonicalize:
            canonical = _alloc_canonical(base)
        else:
            canonical = base
        path = os.path.join(DEBUG_DIR, canonical)
        if isinstance(content, str):
            with open(path, 'w', encoding=encoding) as f:
                f.write(content)
        else:
            with open(path, 'w', encoding=encoding) as f:
                for line in content:
                    f.write(line.rstrip('\n') + '\n')
    except Exception:
        # Non-fatal: debugging should not crash the pipeline
        return


def debug_path(name: str) -> str:
    """Return the full path for a debug file name under the debug dir.

    If a canonical mapping exists, return the canonical file path. If not,
    fall back to returning a safe path in the debug dir (without creating
    a mapping).
    """
    _ensure_debug_dir()
    base = os.path.basename(name)
    with _lock:
        _load_state()
        if base in (_mapping or {}):
            return os.path.join(DEBUG_DIR, _mapping[base])
    # Fallback: try to find a file that endswith '_' + base or equals base
    for fn in os.listdir(DEBUG_DIR):
        if fn == base or fn.endswith('_' + base):
            return os.path.join(DEBUG_DIR, fn)
    return os.path.join(DEBUG_DIR, base)


# Run migration once on import to canonicalize any existing debug files (only if enabled).
try:
    _migrate_existing()
except Exception:
    pass


def clear_debug_txt():
    """Remove all existing .txt debug files from the debug directory.

    This is a convenience used by the main pipelines to ensure that each
    run starts with a clean debug/ folder so the presence of debug
    snapshots unambiguously indicates files produced by the current run.

    The function only removes files whose names end with '.txt' and
    intentionally preserves internal state files (like the mapping and
    counter files) to avoid disturbing canonicalization logic. Non-fatal
    on any error.
    """
    if not _DEBUG_ENABLED:
        return
    _ensure_debug_dir()
    try:
        for name in os.listdir(DEBUG_DIR):
            # Preserve internal JSON/counter files and only remove text
            # snapshots created by the pipeline.
            if not name.lower().endswith('.txt'):
                continue
            if name in (_MAP_FILE, _COUNTER_FILE):
                continue
            path = os.path.join(DEBUG_DIR, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                # Non-fatal: continue cleaning other files
                continue
    except Exception:
        # Swallow any filesystem errors; debugging cleanup must not
        # abort the pipeline.
        return


def reset_debug_sequence(remove_prefixed_files=False):
    """Reset the debug file canonicalization sequence.

    This clears the in-memory mapping and counter and removes the persisted
    mapping files (.map.json and .counter) so that subsequent calls to
    `write_debug` will allocate filenames starting from 001 again.

    If `remove_prefixed_files` is True, files in the debug directory whose
    names start with a numeric prefix (e.g. '001_') will be removed to avoid
    filename collisions with newly allocated canonical names. This is
    optional and defaults to False to avoid accidental data loss.
    """
    global _mapping, _counter
    if not _DEBUG_ENABLED:
        return
    _ensure_debug_dir()
    with _lock:
        # Remove persisted state files
        map_path = os.path.join(DEBUG_DIR, _MAP_FILE)
        counter_path = os.path.join(DEBUG_DIR, _COUNTER_FILE)
        try:
            if os.path.exists(map_path):
                os.remove(map_path)
        except Exception:
            pass
        try:
            if os.path.exists(counter_path):
                os.remove(counter_path)
        except Exception:
            pass

        # Optionally remove files that already have numeric prefixes to
        # avoid collisions with freshly allocated canonical names.
        if remove_prefixed_files:
            try:
                for name in os.listdir(DEBUG_DIR):
                    if name in (_MAP_FILE, _COUNTER_FILE):
                        continue
                    parts = name.split('_', 1)
                    if parts and parts[0].isdigit():
                        path = os.path.join(DEBUG_DIR, name)
                        try:
                            if os.path.isfile(path):
                                os.remove(path)
                        except Exception:
                            pass
            except Exception:
                pass

        # Reset in-memory state
        _mapping = {}
        _counter = 0
        # Persist the cleared state so subsequent imports start fresh
        _save_state()
