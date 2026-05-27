from __future__ import annotations

import platform
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pdf_entity_highlighter.ner import download_vncorenlp_model, vncorenlp_model_exists


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "PDF Entity Highlighter"
BUILD_RESOURCES = ROOT / "build" / "app-resources"


def main() -> int:
    env = os.environ.copy()
    if "JAVA_HOME" not in env:
        java_home = detect_java_home()
        if java_home:
            env["JAVA_HOME"] = str(java_home)
    java_home = Path(env["JAVA_HOME"]).resolve() if env.get("JAVA_HOME") else detect_java_home()
    if java_home:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = f"{java_home / 'bin'}{os.pathsep}{env.get('PATH', '')}"

    model_dir = prepare_vncorenlp_model()
    java_runtime_dir = prepare_java_runtime(java_home)

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
        "py_vncorenlp",
        "--collect-all",
        "jnius",
        "--add-data",
        f"{model_dir}{os.pathsep}vncorenlp",
        "--add-data",
        f"{java_runtime_dir}{os.pathsep}java-runtime",
        "src/pdf_entity_highlighter/gui.py",
    ]

    if platform.system() == "Darwin":
        command.extend(["--osx-bundle-identifier", "com.pdfentityhighlighter.app"])

    subprocess.run(command, cwd=ROOT, check=True, env=env)
    return 0


def prepare_vncorenlp_model() -> Path:
    model_dir = BUILD_RESOURCES / "vncorenlp"
    if not vncorenlp_model_exists(model_dir):
        download_vncorenlp_model(model_dir)
    return model_dir


def prepare_java_runtime(java_home: Path | None) -> Path:
    if not java_home or not (java_home / "bin").exists():
        raise RuntimeError("JAVA_HOME must point to a Java 17 runtime before building the app.")

    destination = BUILD_RESOURCES / "java-runtime"
    executable = "java.exe" if platform.system() == "Windows" else "java"
    if not (destination / "bin" / executable).exists():
        if destination.exists():
            shutil.rmtree(destination)
        ignore = shutil.ignore_patterns("src.zip", "*.diz", "demo", "sample", "man")
        shutil.copytree(java_home, destination, ignore=ignore)
    return destination


def detect_java_home() -> Path | None:
    env_home = os.environ.get("JAVA_HOME")
    if env_home and (Path(env_home) / "bin").exists():
        return Path(env_home)

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
