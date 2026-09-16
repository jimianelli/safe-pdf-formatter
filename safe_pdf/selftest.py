"""Exercise the installed application without relying on developer paths."""
import hashlib
import json
from pathlib import Path
import tempfile

from pypdf import PdfReader
import pypdfium2 as pdfium

from .catalog import read_catalog
from .engine import format_pdf, load_layout
from .models import FormatOptions


def run(output=None, gui=True):
    from .gui import resource_root, distribution_root, config_root
    directory = Path(output).resolve() if output else Path(tempfile.mkdtemp(prefix="safe-pdf-selftest-"))
    directory.mkdir(parents=True, exist_ok=True)
    config = config_root()
    catalog = read_catalog(config / "chapters.csv")
    chapter = next(c for c in catalog if c.filename.casefold() == "ebspollock.pdf")
    samples = distribution_root() / "examples"
    if not samples.exists():
        samples = resource_root() / "examples"
    source = samples / "EBSpollock.pdf"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    target = directory / "EBSpollock-formatted.pdf"
    if target.exists():
        raise ValueError(f"Choose an empty self-test output folder: {directory}")
    result = format_pdf(source, target, chapter, FormatOptions(2026, "september"), load_layout(config / "layout.json"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    reader = PdfReader(target)
    assert len(reader.pages) == 4
    assert "September 2026 Plan Team Draft" in reader.pages[0].extract_text()
    assert "Page 2" in reader.pages[1].extract_text()
    document = pdfium.PdfDocument(str(target))
    page = document[0]
    bitmap = page.render(scale=0.8)
    image = bitmap.to_pil().copy()
    image.save(directory / "preview.png")
    bitmap.close()
    page.close()
    document.close()
    if gui:
        import tkinter as tk
        from PIL import ImageTk
        root = tk.Tk()
        root.withdraw()
        photo = ImageTk.PhotoImage(image, master=root)
        assert photo.width() > 0
        root.update()
        root.destroy()
    report = {"success": True, "catalog_rows": len(catalog), "pages": result["pages"], "gui_checked": gui, "config": str(config), "source_unchanged": True, "pdf": str(target), "warnings": result.get("warnings", [])}
    (directory / "self-test.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report
