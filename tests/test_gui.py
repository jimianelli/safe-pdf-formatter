"""Run with SAFE_GUI_TEST=1 in a desktop session; ordinary test runs skip."""
import os
from pathlib import Path
import shutil
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from safe_pdf.gui import FormatterApp

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

    def test_processing_controls_remain_visible_on_small_window(self):
        self.root.geometry("1024x700")
        self.root.deiconify()
        self.root.update()
        button_bottom = self.app.process_button.winfo_rooty() + self.app.process_button.winfo_height()
        window_bottom = self.root.winfo_rooty() + self.root.winfo_height()
        self.assertLess(button_bottom, window_bottom)
        self.assertGreater(self.app.canvas.winfo_height(), 100)

    def test_release_change_discards_pending_and_existing_preview(self):
        self.app.preview()
        self.app.stage.set("Final")
        self.wait_idle()
        self.assertIsNone(self.app.preview_doc)
        self.assertIsNone(self.app.preview_path)
        self.app.preview()
        self.wait_idle()
        previous = self.app.preview_path
        self.assertTrue(previous.is_file())
        self.app.stage.set("Council draft")
        self.assertFalse(previous.exists())
        self.assertIsNone(self.app.preview_doc)

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
