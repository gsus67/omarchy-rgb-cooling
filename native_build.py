#!/usr/bin/env python3
"""Build rgbcd directly with C++20, Qt6 and libudev, using only Python's stdlib."""
# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
MODULES = ("Qt6Core", "Qt6Network", "Qt6DBus", "libudev")
BUILD_FLAGS = ("-std=c++20", "-O2", "-fPIC", "-Wall", "-Wextra", "-Wpedantic")
SANITIZE_FLAGS = (
    "-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined",
    "-fno-sanitize-recover=all",
)


def run(*command, env=None, cwd=None):
    """Run an argument vector without a shell and report useful diagnostics."""
    result = subprocess.run(command, capture_output=True, text=True, timeout=180,
                            env=env, cwd=cwd)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise RuntimeError(f"{command[0]}: {detail[-8000:]}")
    return result.stdout


def discover():
    """Resolve the compiler and pkg-config before doing any compilation."""
    names = (os.environ["CXX"],) if os.environ.get("CXX") else ("g++", "clang++", "c++")
    compiler = next((path for name in names if (path := shutil.which(name))), None)
    pkg_config = shutil.which("pkg-config")
    if compiler is None or pkg_config is None:
        raise RuntimeError("A C++20 compiler and pkg-config are required")
    run(pkg_config, "--print-errors", "--exists", *MODULES)
    return {"compiler": str(Path(compiler).resolve()), "pkg_config": pkg_config}


def versions(tools):
    """Describe every linked module for the installation fingerprint."""
    return run(tools["pkg_config"], "--modversion", *MODULES)


def effective_flags(tools, sanitize=False):
    """Preserve pkg-config and user flag quoting without invoking a shell."""
    flags = [*BUILD_FLAGS]
    for variable in ("CPPFLAGS", "CXXFLAGS"):
        flags.extend(shlex.split(os.environ.get(variable, "")))
    flags.append("-std=c++20")
    if sanitize:
        flags.extend(SANITIZE_FLAGS)
    libraries = shlex.split(run(tools["pkg_config"], "--cflags", "--libs", *MODULES))
    libraries.extend(shlex.split(os.environ.get("LDFLAGS", "")))
    if sanitize:
        libraries.extend(SANITIZE_FLAGS)
    return flags, libraries


def fingerprint(source, tools=None, sanitize=False):
    """Hash sources, tool identities, module versions and effective flags."""
    source = Path(source).resolve()
    tools = tools or discover()
    identity = {
        "format": "rgbcd-direct-cxx-1",
        "tools": tools,
        "compiler_version": run(tools["compiler"], "--version"),
        "modules": versions(tools),
        "include_directory": str(source / "src"),
        "working_directory": str(source),
        "flags": effective_flags(tools, sanitize),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
    paths = [source / "native_build.py", *sorted((source / "src").rglob("*"))]
    for path in paths:
        if path.is_file():
            digest.update(str(path.relative_to(source)).encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()


def build(source, output, *, tools=None, tests=False, sanitize=False):
    """Serialize builders and atomically publish a fully linked executable."""
    source = Path(source).resolve()
    output = Path(output).resolve()
    tools = tools or discover()
    output.mkdir(parents=True, exist_ok=True)
    # Lock the directory itself: no persistent extra lock file in the footprint.
    directory_fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        flags, libraries = effective_flags(tools, sanitize)
        with tempfile.TemporaryDirectory(prefix="build-", dir=output) as temporary:
            candidate = Path(temporary) / "rgbcd"
            sources = sorted(str(path) for path in (source / "src").glob("*.cpp"))
            if not sources:
                raise RuntimeError("No C++ sources found")
            libexec = run(tools["pkg_config"], "--variable=libexecdir", "Qt6Core").strip()
            moc = str(Path(libexec) / "moc")
            for path in (source / "src").glob("*.cpp"):
                if "Q_OBJECT" in path.read_text():
                    run(moc, str(path), "-o", str(Path(temporary) / (path.stem + ".moc")))
            run(tools["compiler"], *flags, "-I", temporary, "-I", str(source / "src"),
                *sources, *libraries, "-o", str(candidate), cwd=source)
            if tests:
                environment = os.environ.copy()
                environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1:abort_on_error=1"
                environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                print(run(str(candidate), "--self-test", env=environment), end="")
            binary = output / "rgbcd"
            candidate.replace(binary)
        return binary
    finally:
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    try:
        source = Path(__file__).resolve().parent
        if args.output:
            print(build(source, args.output, tests=args.test, sanitize=args.sanitize))
        else:
            with tempfile.TemporaryDirectory(prefix="rgbcd-build-") as directory:
                build(source, directory, tests=args.test, sanitize=args.sanitize)
            print("Build completed; temporary files removed.")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
