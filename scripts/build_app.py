from __future__ import annotations

import platform
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pdf_entity_highlighter.ner import download_vncorenlp_model, vncorenlp_model_exists
from pdf_entity_highlighter.ocr import download_tessdata, tessdata_language_exists


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
    tessdata_dir = prepare_tessdata()
    tesseract_runtime_dir = prepare_tesseract_runtime()

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
        "--add-data",
        f"{tessdata_dir}{os.pathsep}tessdata",
        "--add-data",
        f"{tesseract_runtime_dir}{os.pathsep}tesseract-runtime",
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


def prepare_tessdata() -> Path:
    destination = BUILD_RESOURCES / "tessdata"
    if not tessdata_language_exists(destination, "vie"):
        download_tessdata(destination)
    return destination


def prepare_tesseract_runtime() -> Path:
    source = detect_tesseract_executable()
    if not source:
        raise RuntimeError("Tesseract must be installed before building the app.")

    destination = BUILD_RESOURCES / "tesseract-runtime"
    if destination.exists():
        shutil.rmtree(destination)

    system = platform.system()
    if system == "Windows":
        copy_windows_tesseract_runtime(source, destination)
    elif system == "Darwin":
        copy_macos_tesseract_runtime(source, destination)
    else:
        copy_linux_tesseract_runtime(source, destination)
    return destination


def detect_tesseract_executable() -> Path | None:
    env_path = os.environ.get("TESSERACT_CMD")
    if env_path and Path(env_path).exists():
        return Path(env_path).resolve()

    found = shutil.which("tesseract")
    if found:
        return Path(found).resolve()

    candidates = [
        Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path("/opt/homebrew/bin/tesseract"),
        Path("/usr/local/bin/tesseract"),
        Path("/usr/bin/tesseract"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def copy_windows_tesseract_runtime(source: Path, destination: Path) -> None:
    ignore = shutil.ignore_patterns("tessdata")
    shutil.copytree(source.parent, destination, ignore=ignore)


def copy_macos_tesseract_runtime(source: Path, destination: Path) -> None:
    bin_dir = destination / "bin"
    lib_dir = destination / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    binary = bin_dir / "tesseract"
    shutil.copy2(source, binary)
    binary.chmod(0o755)

    copied: dict[str, Path] = {}
    copied_by_resolved: dict[Path, Path] = {}
    queue = list(macos_dependency_paths(source))
    while queue:
        dependency = queue.pop(0)
        resolved = dependency.resolve()
        if resolved in copied_by_resolved:
            copied[str(dependency)] = copied_by_resolved[resolved]
            continue
        if not dependency.exists():
            continue
        target = lib_dir / dependency.name
        shutil.copy2(resolved, target)
        target.chmod(0o755)
        copied[str(dependency)] = target
        copied_by_resolved[resolved] = target
        queue.extend(path for path in macos_dependency_paths(resolved) if path.resolve() not in copied_by_resolved)

    rewrite_macos_dependencies(binary, copied, in_bin=True)
    for target in set(copied.values()):
        run_command(["install_name_tool", "-id", f"@rpath/{target.name}", str(target)])
        rewrite_macos_dependencies(target, copied, in_bin=False)


def macos_dependency_paths(path: Path) -> list[Path]:
    result = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True)
    dependencies: list[Path] = []
    for line in result.stdout.splitlines()[1:]:
        value = line.strip().split(" ", 1)[0]
        if value.startswith(("/usr/lib/", "/System/Library/")):
            continue
        if value.startswith(("@rpath/", "@loader_path/")):
            resolved = resolve_macos_relative_dependency(path, value)
            if resolved:
                dependencies.append(resolved)
            continue
        if value.startswith("@"):
            continue
        dependencies.append(Path(value))
    return dependencies


def resolve_macos_relative_dependency(loader: Path, value: str) -> Path | None:
    basename = Path(value).name
    candidates = [
        loader.parent / basename,
        Path("/opt/homebrew/lib") / basename,
        Path("/usr/local/lib") / basename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    for root in (Path("/opt/homebrew/opt"), Path("/usr/local/opt")):
        if not root.exists():
            continue
        for candidate in root.glob(f"*/lib/{basename}"):
            if candidate.exists():
                return candidate
    return None


def rewrite_macos_dependencies(path: Path, copied: dict[str, Path], in_bin: bool) -> None:
    for original, target in macos_rewrite_targets(path, copied):
        replacement = f"@executable_path/../lib/{target.name}" if in_bin else f"@loader_path/{target.name}"
        run_command(["install_name_tool", "-change", original, replacement, str(path)], check=False)


def macos_rewrite_targets(path: Path, copied: dict[str, Path]) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    for value in macos_load_values(path):
        target = copied.get(value)
        if not target and value.startswith(("@rpath/", "@loader_path/")):
            basename = Path(value).name
            target = next((candidate for candidate in set(copied.values()) if candidate.name == basename), None)
        if target:
            targets.append((value, target))
    return targets


def macos_load_values(path: Path) -> list[str]:
    result = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True)
    values: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        values.append(line.strip().split(" ", 1)[0])
    return values


def copy_linux_tesseract_runtime(source: Path, destination: Path) -> None:
    bin_dir = destination / "bin"
    lib_dir = destination / "lib"
    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    binary = bin_dir / "tesseract"
    shutil.copy2(source, binary)
    binary.chmod(0o755)

    copied: set[Path] = set()
    queue = list(linux_dependency_paths(source))
    while queue:
        dependency = queue.pop(0).resolve()
        if dependency in copied or not dependency.exists() or is_linux_core_library(dependency):
            continue
        target = lib_dir / dependency.name
        shutil.copy2(dependency, target)
        target.chmod(0o755)
        copied.add(dependency)
        queue.extend(path for path in linux_dependency_paths(dependency) if path.resolve() not in copied)


def linux_dependency_paths(path: Path) -> list[Path]:
    result = subprocess.run(["ldd", str(path)], capture_output=True, text=True, check=True)
    dependencies: list[Path] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if "=>" in line:
            _, right = line.split("=>", 1)
            candidate = right.strip().split(" ", 1)[0]
        else:
            candidate = line.split(" ", 1)[0]
        if candidate.startswith("/"):
            dependencies.append(Path(candidate))
    return dependencies


def is_linux_core_library(path: Path) -> bool:
    name = path.name
    return (
        name.startswith("libc.so")
        or name.startswith("libm.so")
        or name.startswith("libpthread.so")
        or name.startswith("libdl.so")
        or name.startswith("librt.so")
        or name.startswith("ld-linux")
    )


def run_command(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


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
