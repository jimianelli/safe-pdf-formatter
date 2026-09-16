"""Add SAFE running furniture to a copy of a plain PDF.

Coordinates are physical PDF points (72 points/inch) in the *visible* page.
Original boxes, rotation, content, annotations, and document catalog are
retained. Existing tags are copied, but this is not PDF/UA certification.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
from tempfile import SpooledTemporaryFile
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from .models import Chapter, DISCLAIMER, FOOTERS, FormatOptions, STAGES

FORMATTER_VERSION = "1.0"
FORMATTER_MARKER = "/SAFEFormatterVersion"

# Letter defaults follow active menu.js coordinates. Baselines are explicit
# because Acrobat used automatically laid-out form fields.
DEFAULT_LAYOUT = {
    "font": "Times-Italic",
    "font_size": 10.0,
    "minimum_header_font_size": 8.0,
    "header_gap": 12.0,
    "left_margin": 62.0,
    "portrait_right_margin": 52.0,
    "landscape_right_margin": 68.0,
    "portrait_header_top_margin": 7.0,
    "landscape_header_top_margin": 5.0,
    "header_height": 18.0,
    "header_baseline_above_rule": 5.0,
    "header_rule_width": 1.0,
    "footer_baseline": 28.0,
    "page_number_baseline": 18.0,
    "disclaimer_bottom": 10.0,
    "disclaimer_height": 40.0,
    "disclaimer_width": 498.0,
    "disclaimer_font_size": 9.0,
    "disclaimer_leading": 10.8,
    "disclaimer_padding": 2.0,
    "disclaimer_border_width": 1.0,
}


def _validated_layout(values: dict | None) -> dict:
    if values is None:
        return DEFAULT_LAYOUT.copy()
    if not isinstance(values, dict):
        raise ValueError("Layout must be a JSON object of formatting settings.")
    unknown = set(values).difference(DEFAULT_LAYOUT)
    if unknown:
        raise ValueError("Unknown layout setting(s): " + ", ".join(sorted(unknown)))
    settings = {**DEFAULT_LAYOUT, **values}
    font = settings["font"]
    if not isinstance(font, str) or font not in pdfmetrics.standardFonts or font in ("Symbol", "ZapfDingbats"):
        raise ValueError("Layout font must be a standard Latin PDF font, such as Times-Italic.")
    for name, value in settings.items():
        if name == "font":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Layout setting '{name}' must be a number of PDF points.")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Layout setting '{name}' must be a finite, nonnegative number.")
        settings[name] = float(value)
    for name in (
        "font_size", "minimum_header_font_size", "header_height",
        "disclaimer_height", "disclaimer_width", "disclaimer_font_size", "disclaimer_leading",
    ):
        if settings[name] <= 0:
            raise ValueError(f"Layout setting '{name}' must be greater than zero.")
    if not 7 <= settings["minimum_header_font_size"] <= settings["font_size"] <= 24:
        raise ValueError("Header font sizes must be between 7 and 24 points; minimum must not exceed font_size.")
    if settings["header_baseline_above_rule"] + settings["font_size"] > settings["header_height"]:
        raise ValueError("The header baseline and font size must fit inside header_height.")
    if settings["disclaimer_leading"] < settings["disclaimer_font_size"]:
        raise ValueError("disclaimer_leading must be at least disclaimer_font_size.")
    if 2 * settings["disclaimer_padding"] >= min(settings["disclaimer_width"], settings["disclaimer_height"]):
        raise ValueError("Disclaimer padding leaves no room for text.")
    return settings


def load_layout(path: str | Path | None = None) -> dict:
    """Read optional JSON layout, merge defaults, and validate settings."""
    if path is None:
        return DEFAULT_LAYOUT.copy()
    try:
        with Path(path).open("r", encoding="utf-8-sig") as handle:
            values = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Layout JSON is invalid at line {exc.lineno}: {exc.msg}") from exc
    return _validated_layout(values)


def _deref(value):
    return value.get_object() if hasattr(value, "get_object") else value


def _check_source(reader: PdfReader) -> list[str]:
    if reader.is_encrypted:
        raise ValueError("This PDF is encrypted or password protected. Export an unencrypted plain PDF first.")
    if not len(reader.pages):
        raise ValueError("This PDF contains no pages.")
    if FORMATTER_MARKER in (reader.metadata or {}):
        raise ValueError("This PDF was already processed by SAFE PDF Formatter. Select its plain original to avoid duplicate formatting.")
    root = reader.root_object
    if "/Perms" in root and "/DocMDP" in _deref(root["/Perms"]):
        raise ValueError("This PDF has a certification signature. Obtain an unsigned plain PDF before formatting.")
    fields = list((reader.get_fields() or {}).items())
    for page in reader.pages:
        for ref in page.get("/Annots", []):
            annotation = _deref(ref)
            if annotation.get("/Subtype") == "/Widget":
                fields.append((str(annotation.get("/T", "")), annotation))
    warnings = []
    for name, field in fields:
        if field.get("/FT") == "/Sig":
            if field.get("/V"):
                raise ValueError("This PDF contains a digital signature. Formatting would invalidate it; obtain an unsigned plain PDF first.")
            warnings.append("An empty signature field was retained. Apply any signature after formatting.")
        names = (name, str(field.get("/T", "")))
        if any(re.fullmatch(r"(?:lhdr|rhdr|rftr|pageno)\d+|disclaimer", n, flags=re.I) for n in names):
            raise ValueError("This PDF contains legacy Acrobat SAFE header/footer fields. Select a plain PDF without existing SAFE formatting.")
    return list(dict.fromkeys(warnings))


def _visible_geometry(page) -> tuple[float, float, tuple]:
    """Physical visible dimensions and visible-to-original transform."""
    crop = page.cropbox
    x, y = float(crop.left), float(crop.bottom)
    w, h = float(crop.width), float(crop.height)
    unit = float(page.get("/UserUnit", 1))
    if not all(math.isfinite(v) for v in (x, y, w, h, unit)) or min(w, h, unit) <= 0:
        raise ValueError("Page has an invalid CropBox or UserUnit.")
    raw_rotation = float(page.get("/Rotate", 0))
    if not math.isfinite(raw_rotation) or raw_rotation % 90:
        raise ValueError("Page rotation must be a multiple of 90 degrees.")
    rotation = int(raw_rotation) % 360
    s = 1 / unit
    transforms = {
        0: (s, 0, 0, s, x, y),
        90: (0, s, -s, 0, x + w, y),
        180: (-s, 0, 0, -s, x + w, y + h),
        270: (0, -s, s, 0, x, y + h),
    }
    width, height = (h * unit, w * unit) if rotation in (90, 270) else (w * unit, h * unit)
    return width, height, transforms[rotation]


def _artifact_start(drawing, subtype: str) -> None:
    drawing.addLiteral(f"/Artifact <</Type /Pagination /Subtype /{subtype}>> BDC")


def _text_fits(text: str, font: str) -> None:
    # Standard PDF fonts use WinAnsi; reject unsupported heading characters
    # rather than silently substituting boxes in a published document.
    try:
        text.encode("cp1252")
    except UnicodeEncodeError as exc:
        raise ValueError(f"The heading contains '{text[exc.start:exc.end]}', which is not supported by the standard PDF font {font}. Use a supported character or a Latin-alphabet heading.") from exc
    if any(ord(character) < 32 for character in text):
        raise ValueError("Chapter headings must be a single line without control characters.")


def _wrap_disclaimer(font: str, font_size: float, available: float) -> list[str]:
    lines = []
    for paragraph in DISCLAIMER.splitlines():
        line = ""
        for word in paragraph.split():
            candidate = (line + " " + word).strip()
            if pdfmetrics.stringWidth(candidate, font, font_size) <= available:
                line = candidate
                continue
            if not line or pdfmetrics.stringWidth(word, font, font_size) > available:
                raise ValueError("Page is too narrow for the disclaimer at the configured font size.")
            lines.append(line)
            line = word
        if line:
            lines.append(line)
    return lines


def _make_overlay(width, height, number, chapter, options, layout, warnings):
    orientation = "landscape" if width >= height else "portrait"
    left = layout["left_margin"]
    right = width - layout[f"{orientation}_right_margin"]
    available = right - left
    if available <= 0:
        raise ValueError(f"Page {number} is too narrow for the configured margins.")
    font, size = layout["font"], layout["font_size"]
    stream = BytesIO()
    drawing = canvas.Canvas(stream, pagesize=(width, height), pageCompression=1)
    drawing.setFillColorRGB(0, 0, 0)
    drawing.setStrokeColorRGB(0, 0, 0)
    if options.headers_footers:
        rule_y = height - layout[f"{orientation}_header_top_margin"] - layout["header_height"]
        if rule_y < max(layout["footer_baseline"], layout["disclaimer_bottom"] + layout["disclaimer_height"]) + size:
            raise ValueError(f"Page {number} is too short for the configured header and footer.")
        heading, label = chapter.heading, options.meeting_label
        combined = pdfmetrics.stringWidth(label, font, size) + pdfmetrics.stringWidth(heading, font, size)
        header_size = min(size, size * (available - layout["header_gap"]) / combined)
        if header_size < layout["minimum_header_font_size"]:
            raise ValueError(f"Page {number}: the chapter heading and meeting label do not fit at {layout['minimum_header_font_size']:g} points. Shorten the heading or adjust the layout margins.")
        if header_size < size - 0.01:
            warnings.append(f"Page {number}: header text was reduced from {size:g} to {header_size:.1f} points to avoid overlap.")
        _artifact_start(drawing, "Header")
        drawing.setFont(font, header_size)
        baseline = rule_y + layout["header_baseline_above_rule"]
        left_text, right_text = (label, heading) if number % 2 else (heading, label)
        drawing.drawString(left, baseline, left_text)
        drawing.drawRightString(right, baseline, right_text)
        drawing.setLineWidth(layout["header_rule_width"])
        drawing.line(left, rule_y, right, rule_y)
        drawing.addLiteral("EMC")
        if number != 1 or not options.is_draft:
            footer = FOOTERS[chapter.region]
            if pdfmetrics.stringWidth(footer, font, size) > available:
                raise ValueError(f"Page {number}: the regional footer does not fit the configured margins.")
            if layout["footer_baseline"] + size > height:
                raise ValueError(f"Page {number}: the footer falls outside the visible page.")
            _artifact_start(drawing, "Footer")
            drawing.setFont(font, size)
            if number % 2:
                drawing.drawRightString(right, layout["footer_baseline"], footer)
            else:
                drawing.drawString(left, layout["footer_baseline"], footer)
            drawing.addLiteral("EMC")
        else:
            box_width = min(layout["disclaimer_width"], available)
            bottom, box_height = layout["disclaimer_bottom"], layout["disclaimer_height"]
            padding, disclaimer_size = layout["disclaimer_padding"], layout["disclaimer_font_size"]
            if bottom + box_height > height:
                raise ValueError(f"Page {number}: the disclaimer falls outside the visible page.")
            lines = _wrap_disclaimer(font, disclaimer_size, box_width - 2 * padding)
            if disclaimer_size + (len(lines) - 1) * layout["disclaimer_leading"] > box_height - 2 * padding:
                raise ValueError(f"Page {number}: the complete disclaimer does not fit. Increase disclaimer_height or supply a wider plain PDF.")
            # Border is an artifact. Substantive disclaimer is a separate
            # paragraph, never hidden as running furniture.
            drawing.addLiteral("/Artifact BMC")
            drawing.setStrokeColorRGB(1, 0, 0)
            drawing.setLineWidth(layout["disclaimer_border_width"])
            drawing.rect(left, bottom, box_width, box_height, stroke=1, fill=0)
            drawing.addLiteral("EMC")
            drawing.setStrokeColorRGB(0, 0, 0)
            drawing.addLiteral("/P BMC")
            drawing.setFont(font, disclaimer_size)
            for index, line in enumerate(lines):
                baseline = bottom + box_height - padding - disclaimer_size - index * layout["disclaimer_leading"]
                drawing.drawString(left + padding, baseline, line)
            drawing.addLiteral("EMC")
    if options.page_numbers and number > 1:
        if layout["page_number_baseline"] + size > height:
            raise ValueError(f"Page {number}: the page number falls outside the visible page.")
        _artifact_start(drawing, "Footer")
        drawing.setFont(font, size)
        drawing.drawCentredString((left + right) / 2, layout["page_number_baseline"], f"Page {number}")
        drawing.addLiteral("EMC")
    drawing.showPage()
    drawing.save()
    stream.seek(0)
    return PdfReader(stream).pages[0]


def format_pdf(input_path: str | Path, output_path: str | Path, chapter: Chapter,
               options: FormatOptions, layout: dict | None = None) -> dict:
    """Write a copy; return pages, warnings, and output (absolute path).

    Raises ValueError for unsafe/unsupported input or invalid settings. Never
    replaces an existing destination or modifies the original. Draft disclaimer
    is included only with headers_footers. Page 1 never receives a number.
    """
    source, destination = Path(input_path), Path(output_path)
    if source.resolve() == destination.resolve():
        raise ValueError("Choose a different output file. The plain original must not be overwritten.")
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}. Choose a new output file or folder.")
    if not source.is_file():
        raise FileNotFoundError(f"Input PDF was not found: {source}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Output folder was not found: {destination.parent}")
    if options.stage not in STAGES:
        raise ValueError("Choose a valid release stage.")
    if isinstance(options.year, bool) or not isinstance(options.year, int) or not 1900 <= options.year <= 2200:
        raise ValueError("Assessment year must be an integer between 1900 and 2200.")
    if not options.headers_footers and not options.page_numbers:
        raise ValueError("Select headers/footers, page numbers, or both.")
    if chapter.region not in FOOTERS:
        raise ValueError(f"Unknown region '{chapter.region}'. Use one of: {', '.join(FOOTERS)}.")
    if not isinstance(chapter.heading, str) or not chapter.heading.strip():
        raise ValueError("Chapter heading cannot be empty.")
    settings = _validated_layout(layout)
    _text_fits(chapter.heading, settings["font"])
    try:
        reader = PdfReader(source)
    except PdfReadError as exc:
        raise ValueError("This file could not be read as a PDF. Export a fresh plain PDF and try again.") from exc
    warnings = _check_source(reader)
    writer = PdfWriter(clone_from=reader)
    for number, page in enumerate(writer.pages, start=1):
        width, height, transform = _visible_geometry(page)
        overlay = _make_overlay(width, height, number, chapter, options, settings, warnings)
        page.merge_transformed_page(overlay, transform, over=True, expand=False)
    if options.headers_footers and options.is_draft:
        warnings.append("The draft disclaimer is readable text, but has not been connected to a document tag tree. Review its reading order and tagging before accessible publication.")
    if "/StructTreeRoot" in reader.root_object:
        warnings.append("Existing document tags were retained. Review accessibility after formatting; PDF/UA conformance is not certified.")
    writer.add_metadata({
        FORMATTER_MARKER: FORMATTER_VERSION,
        "/SAFEFormatterYear": str(options.year),
        "/SAFEFormatterStage": options.stage,
        "/SAFEFormatterChapter": chapter.heading,
        "/SAFEFormatterSourceName": source.name,
    })
    # Verify before creating the named destination; large assessments spill
    # to a temporary file instead of requiring a second full memory buffer.
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temporary:
        writer.write(temporary)
        temporary.seek(0)
        verified = PdfReader(temporary)
        if len(verified.pages) != len(reader.pages) or (verified.metadata or {}).get(FORMATTER_MARKER) != FORMATTER_VERSION:
            raise RuntimeError("Output verification failed; no formatted file was saved.")
        temporary.seek(0)
        created = False
        try:
            with destination.open("xb") as output:
                created = True
                shutil.copyfileobj(temporary, output)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return {"pages": len(reader.pages), "warnings": list(dict.fromkeys(warnings)), "output": str(destination.resolve())}
