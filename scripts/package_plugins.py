#!/usr/bin/env python3
"""Package DamIT QGIS plugins into installable zip files.

Each plugin becomes <name>.zip in the output directory, structured as QGIS expects:
<name>/metadata.txt, <name>/__init__.py, <name>/plugin.py, etc.

Usage:
    python3 scripts/package_plugins.py [output_dir]

Output_dir defaults to dist/.
"""
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGINS = [
    "damit_core",
    "damit_setup",
    "damit_data",
    "damit_catalog",
    "damit_screener",
    "damit_runner",
    "damit_hazard",
    "damit_hazardlite",
    "damit_pmp",
]

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "tests"}
EXCLUDE_EXTS = {".pyc", ".pyo", ".egg-info"}
EXCLUDE_FILES = {".gitignore", ".DS_Store", "Thumbs.db"}


def _version(plugin_dir):
    meta = os.path.join(plugin_dir, "metadata.txt")
    if not os.path.isfile(meta):
        return "0.0.0"
    with open(meta, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^version\s*=\s*(.+)$", line.strip())
            if m:
                return m.group(1).strip()
    return "0.0.0"


def _should_include(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return False
    name = parts[-1]
    if name in EXCLUDE_FILES:
        return False
    _, ext = os.path.splitext(name)
    if ext in EXCLUDE_EXTS:
        return False
    return True


def package_plugin(name, out_dir):
    src = os.path.join(ROOT, name)
    if not os.path.isdir(src):
        print("  SKIP {}: directory not found".format(name))
        return None
    meta = os.path.join(src, "metadata.txt")
    if not os.path.isfile(meta):
        print("  SKIP {}: no metadata.txt".format(name))
        return None

    version = _version(src)
    zip_name = "{}_{}.zip".format(name, version.replace(".", "_"))
    zip_path = os.path.join(out_dir, zip_name)

    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirs, files in os.walk(src):
            # Prune excluded dirs in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in sorted(files):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, ROOT)
                if _should_include(rel):
                    zf.write(full, rel)
                    count += 1

    size_kb = os.path.getsize(zip_path) / 1024
    print("  {} v{}: {} files, {:.0f} KB → {}".format(name, version, count, size_kb, zip_name))
    return zip_path


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    print("Packaging DamIT QGIS plugins → {}\n".format(out_dir))

    results = []
    for name in PLUGINS:
        path = package_plugin(name, out_dir)
        if path:
            results.append(path)

    print("\n{} plugin(s) packaged.".format(len(results)))
    total_kb = sum(os.path.getsize(p) for p in results) / 1024
    print("Total: {:.0f} KB".format(total_kb))


if __name__ == "__main__":
    main()
