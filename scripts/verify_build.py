"""Run the built executable's PDF self-test without developer Python imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "SAFE PDF Formatter"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gui", action="store_true", help="Also open and close a hidden Tk window.")
    parser.add_argument("--from-zip", action="store_true", help="Test the deliverable ZIP after extracting it into a path with spaces.")
    args = parser.parse_args()
    system_name = "macOS" if sys.platform == "darwin" else "Windows"
    release = ROOT / "release" / f"{APP_NAME}-{system_name}-{platform.machine()}"
    (ROOT / "build").mkdir(exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="frozen-self-test-", dir=ROOT / "build"))
    archive = release.with_suffix(".zip")
    archive_sha256 = None
    if args.from_zip:
        if not archive.is_file():
            raise SystemExit(f"Package the app first: missing {archive}")
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        extracted = output / "Portable app test"
        extracted.mkdir()
        if sys.platform == "darwin":
            subprocess.run(["ditto", "-x", "-k", str(archive), str(extracted)], check=True)
        else:
            with ZipFile(archive) as zipped:
                zipped.extractall(extracted)
        release = extracted / release.name
    if sys.platform == "darwin":
        executable = release / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    elif sys.platform == "win32":
        executable = release / f"{APP_NAME}.exe"
    else:
        raise SystemExit("Verify the app on macOS or Windows.")
    if not executable.is_file():
        raise SystemExit(f"Build and package the app first: missing {executable}")
    command = [str(executable), "--self-test", str(output)]
    if not args.gui:
        command.append("--no-gui")
    # A recipient has no developer Python environment; do not let the build
    # machine's Python settings or PATH hide missing bundled dependencies.
    environment = os.environ.copy()
    for variable in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "TCL_LIBRARY", "TK_LIBRARY"):
        environment.pop(variable, None)
    if sys.platform == "win32":
        system_root = environment.get("SystemRoot", r"C:\Windows")
        environment["PATH"] = os.pathsep.join((str(Path(system_root) / "System32"), system_root))
    else:
        environment["PATH"] = "/usr/bin:/bin"
    try:
        completed = subprocess.run(command, cwd=output, env=environment, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise SystemExit(f"Standalone test timed out: {executable}") from error
    report_path = output / "self-test.json"
    if completed.returncode != 0 or not report_path.is_file():
        raise SystemExit(f"Standalone test failed ({completed.returncode}).\n{completed.stdout}\n{completed.stderr}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("success") or not report.get("source_unchanged"):
        raise SystemExit(f"Standalone test did not pass: {report}")
    if args.gui and not report.get("gui_checked"):
        raise SystemExit("The requested standalone GUI test did not run.")
    verification = {
        "success": True,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "gui_checked": bool(report.get("gui_checked")),
        "zip_extracted": args.from_zip,
        "archive": archive.name if args.from_zip else None,
        "archive_sha256": archive_sha256,
        "developer_python_removed_from_environment": True,
        "catalog_rows": report.get("catalog_rows"),
        "pages": report.get("pages"),
    }
    (output / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    if archive_sha256:
        checksum = ROOT / "release" / f"SHA256SUMS-{system_name}-{platform.machine()}.txt"
        checksum.write_text(f"{archive_sha256}  {archive.name}\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"Standalone verification saved: {report_path}")


if __name__ == "__main__":
    main()
