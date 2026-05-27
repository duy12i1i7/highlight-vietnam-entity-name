from __future__ import annotations

import platform
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "PDF Entity Highlighter"


def main() -> int:
    env = os.environ.copy()
    if "JAVA_HOME" not in env:
        java_home = detect_java_home()
        if java_home:
            env["JAVA_HOME"] = str(java_home)
            env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH', '')}"

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
        "--collect-all",
        "py_vncorenlp",
        "--collect-all",
        "jnius",
        "--collect-submodules",
        "underthesea",
        "src/pdf_entity_highlighter/gui.py",
    ]

    if platform.system() == "Darwin":
        command.extend(["--osx-bundle-identifier", "com.pdfentityhighlighter.app"])

    subprocess.run(command, cwd=ROOT, check=True, env=env)
    return 0


def detect_java_home() -> Path | None:
    candidates = [
        Path("/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"),
        Path("/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
        Path("/usr/local/opt/openjdk/libexec/openjdk.jdk/Contents/Home"),
    ]
    for candidate in candidates:
        if (candidate / "bin" / "java").exists():
            return candidate
    return None


if __name__ == "__main__":
    raise SystemExit(main())
