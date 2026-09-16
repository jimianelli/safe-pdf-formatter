"""Create the editable project ZIP without environments or user settings."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "release" / "SAFE-PDF-Formatter-source-v0.1.0.zip"
TOP_LEVEL = (
    "app.py", "README.md", "QUICK_START.md", "START HERE.txt", "requirements.txt",
    "requirements-build.txt", "SAFE PDF Formatter.spec", ".gitignore", ".gitattributes",
)
DIRECTORIES = ("safe_pdf", "scripts", "tests", "examples", ".github")
CONFIG_FILES = ("chapters.csv", "layout.json", "catalog-source.md")


def main():
    files = [ROOT / name for name in TOP_LEVEL if (ROOT / name).is_file()]
    files.extend(ROOT / "config" / name for name in CONFIG_FILES if (ROOT / "config" / name).is_file())
    for directory in DIRECTORIES:
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                if path.name not in ("user-settings.json", ".DS_Store"):
                    files.append(path)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(DESTINATION, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, Path("safe-pdf-formatter") / path.relative_to(ROOT))
    with ZipFile(DESTINATION) as archive:
        assert archive.testzip() is None
        assert not any(part in name.split("/") for name in archive.namelist() for part in (".venv", "build", "dist", "release", "__pycache__", "user-settings.json"))
    print(f"{DESTINATION} ({len(files)} files)")


if __name__ == "__main__":
    main()
