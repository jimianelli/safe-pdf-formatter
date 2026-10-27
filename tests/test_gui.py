"""Run with SAFE_GUI_TEST=1 in a desktop session; ordinary test runs skip."""
import os
import json
from pathlib import Path
import shutil
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from pypdf import PdfReader

from safe_pdf.gui import FormatterApp
from safe_pdf.models import FOOTERS

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("SAFE_GUI_TEST") == "1", "Requires a desktop session")
class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="safe-gui-tests-")
        self.path = Path(self.scratch.name)
        shutil.copytree(ROOT / "config", self.path / "config")
        (self.path / "config" / "user-settings.json").unlink(missing_ok=True)
        self.config_patch = patch("safe_pdf.gui.config_root", return_value=self.path / "config")
        self.config_patch.start()
        self.dialog_patch = patch("safe_pdf.gui.messagebox")
        self.dialogs = self.dialog_patch.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = FormatterApp(self.root)
        self.app.output.set(str(self.path / "results"))
        self.app._add([ROOT / "examples" / "EBSpollock.pdf"])
        self.root.update()

    def tearDown(self):
        self.wait_idle()
        self.app.close()
        self.dialog_patch.stop()
        self.config_patch.stop()
        self.scratch.cleanup()

    def wait_idle(self):
        end = time.monotonic() + 20
        while self.app.busy and time.monotonic() < end:
            self.root.update()
            time.sleep(0.02)
        self.root.update()
        self.assertFalse(self.app.busy, "Desktop worker did not finish")

    def test_preview_navigation_and_full_batch(self):
        self.app.preview()
        self.wait_idle()
        self.assertIsNotNone(self.app.preview_doc)
        self.assertEqual(len(self.app.preview_doc), 4)
        self.app.move_page(2)
        self.assertEqual(self.app.preview_index, 2)
        self.assertIn("Page 3 of 4", self.app.page_label.get())
        self.app.process()
        self.wait_idle()
        self.assertTrue((self.app.last_output / "EBSpollock.pdf").is_file())
        self.assertTrue((self.app.last_output / "processing-report.csv").is_file())
        self.assertTrue((self.app.last_output / "settings.json").is_file())
        settings = json.loads((self.app.last_output / "settings.json").read_text())
        self.assertFalse(settings["disclaimer"])
        self.assertEqual(settings["release_label"], self.app.options().meeting_label)

    def test_processing_controls_remain_visible_on_small_window(self):
        self.root.geometry("1024x700")
        self.root.deiconify()
        self.root.update()
        button_bottom = self.app.process_button.winfo_rooty() + self.app.process_button.winfo_height()
        window_bottom = self.root.winfo_rooty() + self.root.winfo_height()
        self.assertLess(button_bottom, window_bottom)
        self.assertGreater(self.app.canvas.winfo_height(), 100)
        for widget in (self.app.release_combo, self.app.disclaimer_check):
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
            self.assertTrue(widget.winfo_viewable())

    def test_release_change_discards_pending_and_existing_preview(self):
        self.app.preview()
        self.app.stage.set("Council")
        self.wait_idle()
        self.assertIsNone(self.app.preview_doc)
        self.assertIsNone(self.app.preview_path)
        self.app.preview()
        self.wait_idle()
        previous = self.app.preview_path
        self.assertTrue(previous.is_file())
        self.app.stage.set("October 2026 review")
        self.assertFalse(previous.exists())
        self.assertIsNone(self.app.preview_doc)

    def test_editable_release_and_council_processing(self):
        self.assertEqual(list(self.app.release_combo.cget("values")), ["September Plan Team draft", "November Plan Team draft", "Council"])
        self.assertFalse(self.app.add_disclaimer.get())
        self.app.year.set("2026")
        self.app.stage.set("Council")
        self.assertEqual(self.app.options().stage, "final")
        self.assertEqual(self.app.options().meeting_label, "December 2026")
        self.app.preview()
        self.wait_idle()
        reader = PdfReader(self.app.preview_path)
        self.assertIn("December 2026", reader.pages[0].extract_text())
        self.assertIn(FOOTERS["BSAI"], reader.pages[0].extract_text())
        self.assertNotIn("pre-dissemination", reader.pages[0].extract_text())
        self.app.release_combo.delete(0, "end")
        self.app.release_combo.insert(0, "October 2026 review")
        self.app.add_disclaimer.set(True)
        self.app.process()
        self.wait_idle()
        self.assertIsNotNone(self.app.last_output)
        reader = PdfReader(self.app.last_output / "EBSpollock.pdf")
        self.assertIn("October 2026 review", reader.pages[0].extract_text())
        self.assertIn("pre-dissemination", reader.pages[0].extract_text())
        settings = json.loads((self.app.last_output / "settings.json").read_text())
        self.assertEqual(settings["release_label"], "October 2026 review")
        self.assertTrue(settings["disclaimer"])

    def test_disclaimer_alone_and_preview_invalidation(self):
        self.app.add_headers.set(False)
        self.app.add_numbers.set(False)
        with self.assertRaisesRegex(ValueError, "Select"):
            self.app.options()
        self.app.disclaimer_check.invoke()
        self.assertTrue(self.app.options().disclaimer)
        self.app.preview()
        self.wait_idle()
        self.assertIsNotNone(self.app.preview_path)
        reader = PdfReader(self.app.preview_path)
        self.assertIn("pre-dissemination", reader.pages[0].extract_text())
        self.assertNotIn(FOOTERS["BSAI"], reader.pages[0].extract_text())
        previous = self.app.preview_path
        self.app.disclaimer_check.invoke()
        self.assertFalse(previous.exists())
        self.assertIsNone(self.app.preview_doc)

    def test_blank_release_gets_clear_validation(self):
        self.app.stage.set("  ")
        with self.assertRaisesRegex(ValueError, "Choose a release"):
            self.app.options()

    def test_invalid_csv_cannot_be_replaced_by_details_dialog(self):
        damaged = "filename,heading,region\nEBSpollock.pdf,Heading,WRONG\n"
        self.app.catalog_path.write_text(damaged)
        self.app.reload_catalog()
        self.app.tree.selection_set("0")
        self.app.edit_details()
        dialog = next(w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel))
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        widgets = list(descendants(dialog))
        entry = next(w for w in widgets if w.winfo_class() == "TEntry")
        entry.insert(0, "New title")
        next(w for w in widgets if isinstance(w, ttk.Button) and w.cget("text") == "Save details").invoke()
        self.assertEqual(self.app.catalog_path.read_text(), damaged)
        self.dialogs.showerror.assert_called()
        dialog.destroy()


if __name__ == "__main__":
    unittest.main()
