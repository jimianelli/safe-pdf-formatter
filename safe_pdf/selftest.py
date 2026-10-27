"""Exercise the installed application without relying on developer paths."""
import hashlib
import json
from pathlib import Path
import tempfile

from pypdf import PdfReader
import pypdfium2 as pdfium

from . import __version__
from .catalog import read_catalog
from .engine import format_pdf, load_layout
from .models import FOOTERS, STAGES, FormatOptions


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
    layout = load_layout(config / "layout.json")
    result = format_pdf(source, target, chapter, FormatOptions(2026, "september"), layout)
    reader = PdfReader(target)
    assert len(reader.pages) == 4
    assert "September 2026 Plan Team Draft" in reader.pages[0].extract_text()
    assert FOOTERS[chapter.region] in reader.pages[0].extract_text()
    assert "pre-dissemination" not in reader.pages[0].extract_text()
    assert "Page 2" in reader.pages[1].extract_text()
    assert STAGES["final"] == "Council" and "council" not in STAGES
    for name, options in (
        ("Council", FormatOptions(2026, "final")),
        ("Custom-release", FormatOptions(2026, "final", release_label="October 2026 review", disclaimer=True)),
        ("Disclaimer-only", FormatOptions(headers_footers=False, page_numbers=False, disclaimer=True)),
    ):
        output_pdf = directory / f"{name}.pdf"
        format_pdf(source, output_pdf, chapter, options, layout)
        check = PdfReader(output_pdf)
        texts = [p.extract_text() for p in check.pages]
        assert len(check.pages) == 4
        assert ("pre-dissemination" in texts[0]) == options.disclaimer
        assert all("pre-dissemination" not in text for text in texts[1:])
        assert (FOOTERS[chapter.region] in texts[0]) == (options.headers_footers and not options.disclaimer)
        assert ("Page 2" in texts[1]) == options.page_numbers
        if options.headers_footers:
            assert all(options.meeting_label in text for text in texts)
        else:
            assert all(FOOTERS[chapter.region] not in text for text in texts)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
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
        from .gui import FormatterApp
        root = tk.Tk()
        root.withdraw()
        photo = ImageTk.PhotoImage(image, master=root)
        assert photo.width() > 0
        app = FormatterApp(root)
        assert not app.add_disclaimer.get()
        assert list(app.release_combo.cget("values")) == list(STAGES.values())
        app.year.set("2026")
        app.stage.set("Council")
        assert app.options().stage == "final"
        assert app.options().meeting_label == "December 2026"
        app.release_combo.delete(0, "end")
        app.release_combo.insert(0, "October 2026 review")
        assert app.options().meeting_label == "October 2026 review"
        app.add_headers.set(False)
        app.add_numbers.set(False)
        app.disclaimer_check.invoke()
        assert app.options().disclaimer
        root.update()
        app.close()
    report = {"success": True, "app_version": __version__, "release_settings_checked": True, "catalog_rows": len(catalog), "pages": result["pages"], "gui_checked": gui, "config": str(config), "source_unchanged": True, "pdf": str(target), "warnings": result.get("warnings", [])}
    (directory / "self-test.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return report
