"""Catalog checks that guard user edits and portable filename matching."""

from pathlib import Path
import tempfile
import unittest

from safe_pdf.catalog import read_catalog, write_catalog
from safe_pdf.models import Chapter


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "chapters.csv"

    def test_round_trip_preserves_text_and_csv_quoting(self):
        chapters = [Chapter("EBSpollock.pdf", 'EBS Walleye pollock, "example"', "BSAI"),
                    Chapter("example.PDF", "Café chapter", "GOA")]
        write_catalog(self.path, chapters)
        self.assertEqual(read_catalog(self.path), chapters)

    def test_utf8_bom_and_reordered_columns(self):
        self.path.write_text("\ufeffregion,filename,heading\nAK,sablefish.pdf,AK Sablefish\n", encoding="utf-8")
        self.assertEqual(read_catalog(self.path), [Chapter("sablefish.pdf", "AK Sablefish", "AK")])

    def test_duplicate_filename_is_case_insensitive(self):
        self.path.write_text("filename,heading,region\nSablefish.pdf,AK Sablefish,AK\nsablefish.pdf,AK Sablefish,AK\n")
        with self.assertRaisesRegex(ValueError, "duplicate filename"):
            read_catalog(self.path)

    def test_filename_must_be_a_pdf_basename(self):
        for filename in ("../stock.pdf", "folder/stock.pdf", "folder\\stock.pdf", "C:stock.pdf", "stock.docx", ".pdf", " stock.pdf", "stock\x00.pdf"):
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, "PDF basename"):
                write_catalog(self.path, [Chapter(filename, "Stock", "GOA")])

    def test_blank_heading_and_unknown_region_are_rejected(self):
        for chapter in (Chapter("stock.pdf", " \t", "GOA"), Chapter("stock.pdf", "Stock", "Both")):
            with self.subTest(chapter=chapter), self.assertRaises(ValueError):
                write_catalog(self.path, [chapter])

    def test_invalid_catalog_never_replaces_existing_file(self):
        original = b"original user catalog\n"
        self.path.write_bytes(original)
        with self.assertRaises(ValueError):
            write_catalog(self.path, [Chapter("invalid.txt", "Stock", "GOA")])
        self.assertEqual(self.path.read_bytes(), original)

    def test_malformed_csv_headers_or_rows_are_rejected(self):
        for text in ("", "filename,heading\nstock.pdf,Stock\n", "filename,heading,region\nstock.pdf,Stock\n", "filename,heading,region\nstock.pdf,Stock,GOA,extra\n", "filename,heading,heading\nstock.pdf,Stock,GOA\n"):
            with self.subTest(text=text):
                self.path.write_text(text)
                with self.assertRaises(ValueError):
                    read_catalog(self.path)

    def test_bundled_catalog_is_valid_and_has_demonstration_filename(self):
        catalog = Path(__file__).resolve().parents[1] / "config" / "chapters.csv"
        chapters = read_catalog(catalog)
        self.assertIn(Chapter("EBSpollock.pdf", "EBS Walleye pollock", "BSAI"), chapters)
        self.assertIn(Chapter("Sculpins.pdf", "Alaska-wide Sculpins", "AK"), chapters)
        self.assertGreaterEqual(len(chapters), 65)


if __name__ == "__main__":
    unittest.main()
