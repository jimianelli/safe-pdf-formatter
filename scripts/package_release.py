"""Assemble a portable, self-contained app folder and ZIP after PyInstaller."""
from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "SAFE PDF Formatter"


def copy_licenses(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    lines = ["Bundled third-party components", ""]
    for package in (
        "pypdf", "reportlab", "Pillow", "pypdfium2", "charset-normalizer",
        "PyInstaller", "pyinstaller-hooks-contrib",
    ):
        distribution = importlib.metadata.distribution(package)
        lines.append(f"{distribution.metadata['Name']} {distribution.version}")
        for entry in distribution.files or []:
            if any(word in str(entry).lower() for word in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    # Drop any parent components: package files can use ../../../.
                    target = destination / package / Path(*[p for p in entry.parts if p not in ("..", ".")])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    for python_license in (
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
    ):
        if python_license.is_file():
            shutil.copy2(python_license, destination / "Python-LICENSE.txt")
            break
    (destination / "COMPONENTS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if sys.platform not in ("darwin", "win32"):
        raise SystemExit("Release packaging is supported on macOS and Windows.")
    system_name = "macOS" if sys.platform == "darwin" else "Windows"
    suffix = f"{system_name}-{platform.machine()}"
    destination = ROOT / "release" / f"{APP_NAME}-{suffix}"
    if destination.exists():
        # A tester may have edited this release's CSV/layout or saved PDFs
        # beside it. Preserve the whole previous release before replacing it.
        import datetime
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        previous = destination.parent / "previous-builds" / f"{destination.name}-{stamp}"
        previous.parent.mkdir(parents=True, exist_ok=True)
        destination.rename(previous)
        print(f"Previous release preserved: {previous}")
    destination.mkdir(parents=True)
    if sys.platform == "darwin":
        source = ROOT / "dist" / f"{APP_NAME}.app"
        if not source.is_dir():
            raise SystemExit(f"Build the app first; missing {source}")
        # APFS clones avoid duplicating the large runtime during local builds;
        # preserve PyInstaller's symlinks in either case.
        target = destination / source.name
        copied = subprocess.run(["cp", "-cR", str(source), str(target)], capture_output=True)
        if copied.returncode:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target, symlinks=True)
    else:
        source = ROOT / "dist" / APP_NAME
        if not source.is_dir():
            raise SystemExit(f"Build the app first; missing {source}")
        shutil.copytree(source, destination, dirs_exist_ok=True)
    for directory in ("config", "examples"):
        if (ROOT / directory).is_dir():
            shutil.copytree(ROOT / directory, destination / directory)
    for filename in ("README.md", "QUICK_START.md", "START HERE.txt"):
        if (ROOT / filename).is_file():
            shutil.copy2(ROOT / filename, destination / filename)
    copy_licenses(destination / "LICENSES")
    archive = destination.with_suffix(".zip")
    if archive.exists():
        archive.unlink()
    if sys.platform == "darwin":
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(destination), str(archive)],
            check=True,
        )
    else:
        shutil.make_archive(str(destination), "zip", root_dir=destination.parent, base_dir=destination.name)
    print(destination)
    print(archive)


if __name__ == "__main__":
    main()
