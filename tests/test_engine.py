"""End-to-end checks using real PDFs, not mocks of the PDF libraries."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DictionaryObject, NameObject, NumberObject,
    RectangleObject, TextStringObject,
)
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from safe_pdf.engine import DEFAULT_LAYOUT, FORMATTER_MARKER, format_pdf, load_layout
from safe_pdf.models import Chapter, DISCLAIMER, FOOTERS, FormatOptions


def text_positions(page):
    """Text anchors in the original unrotated PDF coordinate system."""
    result = {}
    def visit(text, cm, tm, font, size):
        if text.strip():
            point = (tm[4] * cm[0] + tm[5] * cm[2] + cm[4],
                     tm[4] * cm[1] + tm[5] * cm[3] + cm[5])
            result.setdefault(text.strip(), []).append((point, size))
    page.extract_text(visitor_text=visit)
    return result


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.chapter = Chapter("EBSpollock.pdf", "EBS Walleye pollock", "BSAI")

    def source(self, name="plain.pdf", sizes=None, tagged=False):
        sizes = sizes or [(612, 792), (612, 792), (792, 612)]
        target = self.folder / name
        drawing = Canvas(str(target), pagesize=sizes[0])
        drawing.setTitle("Original assessment title")
        drawing.setAuthor("Original author")
        for index, size in enumerate(sizes):
            drawing.setPageSize(size)
            drawing.bookmarkPage(f"chapter-{index}")
            drawing.addOutlineEntry(f"Body section {index + 1}", f"chapter-{index}")
            if tagged and index == 0:
                drawing.addLiteral("/P <</MCID 0>> BDC")
            drawing.setFont("Helvetica", 12)
            drawing.drawString(80, size[1] / 2, f"Original body text {index + 1}.")
            if tagged and index == 0:
                drawing.addLiteral("EMC")
            drawing.linkURL("https://www.fisheries.noaa.gov/", (80, 200, 280, 218), relative=0)
            drawing.showPage()
        drawing.save()
        return target

    def format(self, source=None, options=None, heading=None, layout=None, output="result.pdf"):
        source = source or self.source()
        target = self.folder / output
        chapter = self.chapter if heading is None else Chapter(source.name, heading, "BSAI")
        result = format_pdf(source, target, chapter, options or FormatOptions(), layout)
        return PdfReader(target), result

    def test_draft_content_and_numbering(self):
        reader, result = self.format()
        self.assertEqual(result["pages"], 3)
        self.assertEqual(len(reader.pages), 3)
        texts = [page.extract_text() for page in reader.pages]
        for index, text in enumerate(texts):
            self.assertIn(f"Original body text {index + 1}.", text)
            self.assertIn("September 2026 Plan Team Draft", text)
            self.assertIn(self.chapter.heading, text)
        self.assertNotIn("Page 1", texts[0])
        self.assertNotIn(FOOTERS["BSAI"], texts[0])
        self.assertIn(" ".join(DISCLAIMER.split()), " ".join(texts[0].split()))
        self.assertIn("Page 2", texts[1])
        self.assertIn("Page 3", texts[2])
        self.assertNotIn("pre-dissemination", texts[1])
        self.assertIn(FOOTERS["BSAI"], texts[1])
        self.assertTrue(any("disclaimer" in warning for warning in result["warnings"]))

    def test_all_release_labels_and_final_first_page_footer(self):
        source = self.source()
        expected = {
            "september": "September 2024 Plan Team Draft",
            "november": "November 2024 Plan Team Draft",
            "council": "November 2024 Council Draft",
            "final": "December 2024",
        }
        for stage, label in expected.items():
            with self.subTest(stage=stage):
                reader, _ = self.format(source, FormatOptions(year=2024, stage=stage), output=stage + ".pdf")
                text = reader.pages[0].extract_text()
                self.assertIn(label, text)
                self.assertNotIn("Page 1", text)
                if stage == "final":
                    self.assertIn(FOOTERS["BSAI"], text)
                    self.assertNotIn("pre-dissemination", text)

    def test_all_regional_footer_wording(self):
        source = self.source()
        for region, expected in FOOTERS.items():
            output = self.folder / (region + ".pdf")
            format_pdf(source, output, Chapter(source.name, "Assessment", region), FormatOptions(stage="final"))
            self.assertIn(expected, PdfReader(output).pages[0].extract_text())

    def test_alternation_and_letter_positions(self):
        reader, _ = self.format(options=FormatOptions(stage="final"))
        label = "December 2026"
        odd, even, landscape = [text_positions(page) for page in reader.pages]
        self.assertEqual(odd[label][0][0], (62.0, 772.0))
        self.assertEqual(even[self.chapter.heading][0][0], (62.0, 772.0))
        self.assertAlmostEqual(odd[self.chapter.heading][0][0][0], 560 - stringWidth(self.chapter.heading, "Times-Italic", 10), places=3)
        self.assertAlmostEqual(even[label][0][0][0], 560 - stringWidth(label, "Times-Italic", 10), places=3)
        self.assertEqual(even[FOOTERS["BSAI"]][0][0], (62.0, 28.0))
        self.assertEqual(landscape[label][0][0], (62.0, 594.0))
        self.assertAlmostEqual(landscape[self.chapter.heading][0][0][0], 724 - stringWidth(self.chapter.heading, "Times-Italic", 10), places=3)
        for data, number, center in [(even, 2, 311), (landscape, 3, 393)]:
            position, size = data[f"Page {number}"][0]
            self.assertEqual(size, 10)
            self.assertEqual(position[1], 18)
            self.assertAlmostEqual(position[0] + stringWidth(f"Page {number}", "Times-Italic", 10) / 2, center, places=3)

    def test_rotated_cropped_offset_and_userunit_pages(self):
        # Explicit known original-space anchors for a top-left visible header.
        cases = [
            ("rot0", (612, 792), None, 0, 1, (62, 772)),
            ("rot90", (612, 792), None, 90, 1, (18, 62)),
            ("rot180", (612, 792), None, 180, 1, (550, 20)),
            ("rot270", (612, 792), None, 270, 1, (594, 730)),
            ("offset", (696, 900), (30, 40, 642, 832), 0, 1, (92, 812)),
            ("offsetrot90", (696, 900), (30, 40, 642, 832), 90, 1, (48, 102)),
            ("unit2", (306, 396), None, 0, 2, (31, 386)),
        ]
        for name, size, crop, rotation, unit, expected in cases:
            with self.subTest(name=name):
                source = self.source(name + "-raw.pdf", [size])
                edited = PdfWriter(clone_from=source)
                page = edited.pages[0]
                page[NameObject("/Rotate")] = NumberObject(rotation)
                if crop:
                    page.cropbox = RectangleObject(crop)
                if unit != 1:
                    page[NameObject("/UserUnit")] = NumberObject(unit)
                source = self.folder / (name + "-input.pdf")
                edited.write(source)
                reader, _ = self.format(source, FormatOptions(stage="final"), output=name + "-output.pdf")
                output_page = reader.pages[0]
                position = text_positions(output_page)["December 2026"][0][0]
                for actual, target in zip(position, expected):
                    self.assertAlmostEqual(actual, target, places=3)
                self.assertEqual(output_page.rotation, rotation)
                self.assertEqual(list(output_page.cropbox), list(PdfReader(source).pages[0].cropbox))
                self.assertEqual(list(output_page.mediabox), list(PdfReader(source).pages[0].mediabox))

    def test_original_unchanged_metadata_links_and_bookmarks_preserved(self):
        source = self.source()
        before = sha256(source.read_bytes()).hexdigest()
        reader, result = self.format(source)
        self.assertEqual(before, sha256(source.read_bytes()).hexdigest())
        self.assertEqual(reader.metadata.title, "Original assessment title")
        self.assertEqual(reader.metadata.author, "Original author")
        self.assertEqual(reader.metadata[FORMATTER_MARKER], "1.0")
        self.assertEqual(reader.metadata["/SAFEFormatterSourceName"], source.name)
        self.assertEqual(reader.metadata["/SAFEFormatterStage"], "september")
        self.assertEqual(Path(result["output"]), (self.folder / "result.pdf").resolve())
        self.assertEqual(len(reader.outline), 3)
        for index, destination in enumerate(reader.outline):
            self.assertEqual(destination.title, f"Body section {index + 1}")
            self.assertEqual(reader.get_destination_page_number(destination), index)
        for page in reader.pages:
            link = page["/Annots"][0].get_object()
            self.assertEqual(link["/A"]["/URI"], "https://www.fisheries.noaa.gov/")
            self.assertEqual(list(link["/Rect"]), [80, 200, 280, 218])

    def test_artifacts_and_disclaimer_are_separate(self):
        reader, _ = self.format()
        for index, page in enumerate(reader.pages):
            stack, stamps, disclaimers, body = [], [], [], []
            for operands, operator in page.get_contents().operations:
                if operator in (b"BDC", b"BMC"):
                    stack.append(str(operands[0]))
                elif operator == b"EMC":
                    stack.pop()
                elif operator == b"Tj":
                    text = str(operands[0])
                    if text.startswith(("September", "EBS Walleye", "NPFMC", "Page ")):
                        stamps.append(text)
                        self.assertIn("/Artifact", stack)
                    if "pre-dissemination" in text:
                        disclaimers.append(text)
                        self.assertNotIn("/Artifact", stack)
                        self.assertIn("/P", stack)
                    if "Original body text" in text:
                        body.append(text)
                        self.assertNotIn("/Artifact", stack)
            self.assertFalse(stack)
            self.assertTrue(stamps)
            self.assertEqual(len(body), 1)
            self.assertEqual(len(disclaimers), 1 if index == 0 else 0)
        operations = reader.pages[0].get_contents().operations
        self.assertTrue(any(operator == b"RG" and list(operands) == [1, 0, 0] for operands, operator in operations))
        self.assertTrue(any(operator == b"re" and list(operands) == [62, 10, 498, 40] for operands, operator in operations))

    def test_existing_tag_tree_and_page_references_survive_clone(self):
        plain = self.source("tagged-raw.pdf", [(612, 792)], tagged=True)
        writer = PdfWriter(clone_from=plain)
        struct = DictionaryObject({NameObject("/Type"): NameObject("/StructTreeRoot")})
        struct_ref = writer._add_object(struct)
        element = DictionaryObject({
            NameObject("/Type"): NameObject("/StructElem"),
            NameObject("/S"): NameObject("/P"), NameObject("/P"): struct_ref,
            NameObject("/Pg"): writer.pages[0].indirect_reference,
            NameObject("/K"): NumberObject(0),
        })
        element_ref = writer._add_object(element)
        struct[NameObject("/K")] = ArrayObject([element_ref])
        struct[NameObject("/ParentTree")] = writer._add_object(DictionaryObject({
            NameObject("/Nums"): ArrayObject([NumberObject(0), ArrayObject([element_ref])]),
        }))
        struct[NameObject("/ParentTreeNextKey")] = NumberObject(1)
        writer.pages[0][NameObject("/StructParents")] = NumberObject(0)
        writer.root_object[NameObject("/StructTreeRoot")] = struct_ref
        writer.root_object[NameObject("/MarkInfo")] = DictionaryObject({NameObject("/Marked"): BooleanObject(True)})
        writer.root_object[NameObject("/Lang")] = TextStringObject("en-US")
        source = self.folder / "tagged.pdf"
        writer.write(source)
        reader, result = self.format(source)
        self.assertEqual(reader.root_object["/Lang"], "en-US")
        self.assertTrue(reader.root_object["/MarkInfo"]["/Marked"])
        element = reader.root_object["/StructTreeRoot"]["/K"][0].get_object()
        self.assertEqual(element["/S"], "/P")
        self.assertEqual(element["/K"], 0)
        self.assertEqual(element.raw_get("/Pg"), reader.pages[0].indirect_reference)
        parent_element = reader.root_object["/StructTreeRoot"]["/ParentTree"]["/Nums"][1][0]
        self.assertEqual(parent_element.get_object().raw_get("/Pg"), reader.pages[0].indirect_reference)
        self.assertTrue(any("Existing document tags" in warning for warning in result["warnings"]))

    def test_number_only_and_headers_only(self):
        source = self.source()
        reader, result = self.format(source, FormatOptions(headers_footers=False), output="number-only.pdf")
        self.assertEqual(reader.pages[0].extract_text().strip(), "Original body text 1.")
        self.assertIn("Page 2", reader.pages[1].extract_text())
        self.assertNotIn("September", reader.pages[1].extract_text())
        self.assertEqual(result["warnings"], [])
        reader, _ = self.format(source, FormatOptions(page_numbers=False), output="headers-only.pdf")
        self.assertIn("September", reader.pages[1].extract_text())
        self.assertNotIn("Page 2", reader.pages[1].extract_text())

    def test_duplicate_and_overwrite_protection(self):
        source = self.source()
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "original must not be overwritten"):
            format_pdf(source, source, self.chapter, FormatOptions())
        self.assertEqual(source.read_bytes(), before)
        output = self.folder / "existing.pdf"
        output.write_bytes(b"Existing file remains intact")
        with self.assertRaises(FileExistsError):
            format_pdf(source, output, self.chapter, FormatOptions())
        self.assertEqual(output.read_bytes(), b"Existing file remains intact")
        self.format(source)
        with self.assertRaisesRegex(ValueError, "already processed"):
            self.format(self.folder / "result.pdf", output="twice.pdf")
        self.assertFalse((self.folder / "twice.pdf").exists())

    def test_reject_encrypted_input(self):
        writer = PdfWriter(clone_from=self.source())
        writer.encrypt("password")
        encrypted = self.folder / "encrypted.pdf"
        writer.write(encrypted)
        with self.assertRaisesRegex(ValueError, "encrypted"):
            self.format(encrypted)
        self.assertFalse((self.folder / "result.pdf").exists())

    def test_reject_legacy_acrobat_fields_and_signed_documents(self):
        source = self.source()
        for field_name, field_type, value, message in [
            ("lhdr11", "/Tx", TextStringObject("December 2025"), "legacy Acrobat"),
            ("pageno11", "/Tx", TextStringObject("Page 2"), "legacy Acrobat"),
            ("disclaimer", "/Tx", TextStringObject("Existing text"), "legacy Acrobat"),
            ("Signature", "/Sig", DictionaryObject({NameObject("/ByteRange"): ArrayObject([NumberObject(0), NumberObject(20)])}), "digital signature"),
        ]:
            with self.subTest(field=field_name):
                writer = PdfWriter(clone_from=source)
                field = DictionaryObject({NameObject("/T"): TextStringObject(field_name), NameObject("/FT"): NameObject(field_type), NameObject("/V"): value})
                writer.root_object[NameObject("/AcroForm")] = writer._add_object(DictionaryObject({NameObject("/Fields"): ArrayObject([writer._add_object(field)])}))
                field_pdf = self.folder / (field_name + ".pdf")
                writer.write(field_pdf)
                with self.assertRaisesRegex(ValueError, message):
                    self.format(field_pdf)

    def test_fit_long_headers_and_reject_unreadable_size(self):
        source = self.source()
        # A moderately long heading fits after a reduction, preserving a gap.
        heading = "Long assessment heading " * 4
        _, result = self.format(source, heading=heading)
        self.assertTrue(any("reduced" in warning for warning in result["warnings"]))
        with self.assertRaisesRegex(ValueError, "do not fit"):
            self.format(source, heading="Very long heading " * 40, output="too-long.pdf")
        self.assertFalse((self.folder / "too-long.pdf").exists())

    def test_failed_later_page_leaves_no_partial_output(self):
        source = self.source(sizes=[(612, 792), (612, 792), (90, 90)])
        before = sha256(source.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "Page 3 is too narrow"):
            self.format(source)
        self.assertFalse((self.folder / "result.pdf").exists())
        self.assertEqual(before, sha256(source.read_bytes()).hexdigest())

    def test_layout_overrides_and_validation(self):
        config = self.folder / "layout.json"
        config.write_text(json.dumps({"footer_baseline": 31}), encoding="utf-8-sig")
        layout = load_layout(config)
        self.assertEqual(layout["footer_baseline"], 31)
        self.assertEqual(layout["font_size"], 10)
        self.assertEqual(DEFAULT_LAYOUT["footer_baseline"], 28)
        reader, _ = self.format(options=FormatOptions(stage="final"), layout=layout)
        self.assertEqual(text_positions(reader.pages[1])[FOOTERS["BSAI"]][0][0][1], 31)
        for invalid in [[], {"unknown": 1}, {"font_size": "10"}, {"font_size": True}, {"left_margin": -1}, {"font_size": 1}, {"disclaimer_leading": 5}, {"left_margin": float("nan")}]:
            config.write_text(json.dumps(invalid), encoding="utf-8")
            with self.subTest(layout=invalid), self.assertRaises(ValueError):
                load_layout(config)

    def test_invalid_options_and_missing_glyphs(self):
        source = self.source()
        for options in [FormatOptions(year=1800), FormatOptions(stage="not-a-stage"), FormatOptions(headers_footers=False, page_numbers=False)]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.format(source, options)
        with self.assertRaisesRegex(ValueError, "not supported"):
            self.format(source, heading="Pollock 🐟")
        with self.assertRaisesRegex(ValueError, "single line"):
            self.format(source, heading="Pollock\nChapter")


if __name__ == "__main__":
    unittest.main()
