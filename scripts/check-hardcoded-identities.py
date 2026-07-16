#!/usr/bin/env python3
"""CI check: ensure no hardcoded identity/business defaults remain in source.

Scans source files for known TMS-specific hardcoded values (renyumeng,
SemiTech Manufacturing, etc.) and reports them. Exits with code 1 if any
are found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Patterns that should not appear in engine/source code.
# Each is a (regex, description) pair.
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\brenyumeng\b", "Hardcoded user identifier"),
    (r"\bSemiTech\s+Manufacturing\b", "Hardcoded organization name"),
    (r"\bTJSEMI_TMS\b", "Hardcoded TMS connection alias"),
    (r"\"TMS Oracle Production\"", "Hardcoded TMS datasource display name"),
]

# File extensions to scan (engine code, configs)
INCLUDE_EXTENSIONS = {".py", ".yaml", ".yml", ".ts", ".tsx", ".jsx", ".json", ".toml", ".md"}

# Directories to skip entirely
SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".git",
    ".worktrees",
    ".local",
    "node_modules",
    ".pytest_cache",
    "dist",
    "build",
    # gitignored local-only content; never part of a release
    "demo",
}

# File paths to skip specifically (this script embeds the patterns it hunts)
SKIP_FILES: set[str] = {str(Path(__file__).resolve())}


def main() -> int:
    found = False
    extensions = INCLUDE_EXTENSIONS
    skip_dirs = SKIP_DIRS
    skip_files = SKIP_FILES

    for path in REPO_ROOT.rglob("*"):
        # Skip directories
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix not in extensions:
            continue
        if str(path.resolve()) in skip_files:
            continue

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        rel = path.relative_to(REPO_ROOT)
        for pattern, desc in FORBIDDEN_PATTERNS:
            if re.search(pattern, text):
                print(f"{desc} found in {rel}: {pattern}", file=sys.stderr)
                found = True

    if found:
        print("\nHardcoded identity/organization values remain. Remove them before release.", file=sys.stderr)
        return 1

    print("OK: No hardcoded identity/organization values found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
