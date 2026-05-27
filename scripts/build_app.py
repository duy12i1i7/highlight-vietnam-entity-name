from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "PDF Entity Highlighter"


def main() -> int:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--collect-all",
        "underthesea",
        "--collect-all",
        "underthesea_core",
        "--collect-submodules",
        "underthesea",
        "src/pdf_entity_highlighter/gui.py",
    ]

    if platform.system() == "Darwin":
        command.extend(["--osx-bundle-identifier", "com.pdfentityhighlighter.app"])

    subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
