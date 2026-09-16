"""Small, offline Mac/Windows interface for the SAFE finishing workflow."""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk
import pypdfium2 as pdfium

from . import __version__
from .catalog import read_catalog, write_catalog
from .engine import DEFAULT_LAYOUT, format_pdf, load_layout
from .models import Chapter, FormatOptions, FOOTERS, STAGES

SOURCE_URL = "https://docs.google.com/spreadsheets/d/1bMCdYBVF-ZpJMp91ZJ2No5sOoXrWoKhrwEcDf5JuuCE/edit?gid=575468903#gid=575468903"


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def distribution_root() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[1]
    executable = Path(sys.executable).resolve()
    return executable.parents[3] if sys.platform == "darwin" else executable.parent


def config_root() -> Path:
    sidecar = distribution_root() / "config"
    if sidecar.is_dir() and os.access(sidecar, os.W_OK):
        return sidecar
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    destination = base / "SAFE PDF Formatter"
    destination.mkdir(parents=True, exist_ok=True)
    for source in (resource_root() / "config").glob("*"):
        if source.is_file() and not (destination / source.name).exists():
            shutil.copy2(source, destination / source.name)
    return destination


def open_file(path: Path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path)])


class FormatterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("SAFE PDF Formatter")
        root.geometry("1240x840")
        root.minsize(980, 700)
        self.config_dir = config_root()
        self.catalog_path = self.config_dir / "chapters.csv"
        self.settings_path = self.config_dir / "user-settings.json"
        self.paths: list[Path] = []
        self.catalog: list[Chapter] = []
        self.catalog_map: dict[str, Chapter] = {}
        self.events = queue.Queue()
        self.busy = False
        self.preview_doc = None
        self.preview_path = None
        self.preview_photo = None
        self.preview_index = 0
        self.last_output = None
        self.temp = tempfile.TemporaryDirectory(prefix="safe-pdf-preview-", ignore_cleanup_errors=True)
        self.preview_counter = 0
        self.preview_revision = 0
        today = dt.date.today()
        self.year = tk.StringVar(value=str(today.year))
        stage = "september" if today.month < 10 else "november" if today.month < 11 or today.day < 15 else "council"
        if today.month == 12 and today.day >= 10:
            stage = "final"
        self.stage = tk.StringVar(value=STAGES[stage])
        self.add_headers = tk.BooleanVar(value=True)
        self.add_numbers = tk.BooleanVar(value=True)
        self.output = tk.StringVar(value="")
        self.status = tk.StringVar(value="Add plain PDFs, choose a release, then preview or process.")
        self.page_label = tk.StringVar(value="No preview")
        self.catalog_label = tk.StringVar()
        self._load_settings()
        self._style()
        self._build()
        self.reload_catalog()
        root.after(100, self._poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        self.root.configure(bg="#f2f4f7")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f4f7")
        style.configure("TLabel", background="#f2f4f7", foreground="#263447", font=("Helvetica", 12))
        style.configure("Title.TLabel", font=("Helvetica", 23, "bold"), foreground="#143a4c")
        style.configure("Sub.TLabel", foreground="#617183", font=("Helvetica", 11))
        style.configure("TLabelframe", background="#f2f4f7", bordercolor="#d7dfe6")
        style.configure("TLabelframe.Label", background="#f2f4f7", foreground="#143a4c", font=("Helvetica", 12, "bold"))
        style.configure("TButton", font=("Helvetica", 11), padding=(11, 7))
        style.configure("Primary.TButton", background="#14675f", foreground="white", font=("Helvetica", 12, "bold"))
        style.map("Primary.TButton", background=[("active", "#10574f"), ("disabled", "#b0babd")])
        style.configure("TCheckbutton", background="#f2f4f7", font=("Helvetica", 11))
        style.configure("Treeview", rowheight=30, font=("Helvetica", 11), background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Helvetica", 10, "bold"), padding=(4, 7))

    def _build(self):
        outer = ttk.Frame(self.root, padding=22)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        head = ttk.Frame(outer)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text="SAFE PDF Formatter", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=f"Mac / Windows  ·  v{__version__}", style="Sub.TLabel").pack(side="right")
        ttk.Label(outer, text="Finish plain assessment PDFs with consistent headers, footers and page numbers.", style="Sub.TLabel").grid(row=1, column=0, sticky="w", pady=(5, 16))
        options = ttk.LabelFrame(outer, text="1  Release settings", padding=12)
        options.grid(row=2, column=0, sticky="ew")
        ttk.Label(options, text="Year").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(options, from_=1990, to=2100, textvariable=self.year, width=7).grid(row=0, column=1, padx=(7, 20))
        ttk.Label(options, text="Release").grid(row=0, column=2)
        ttk.Combobox(options, textvariable=self.stage, values=list(STAGES.values()), state="readonly", width=27).grid(row=0, column=3, padx=(7, 24))
        ttk.Checkbutton(options, text="Headers, footers & disclaimer", variable=self.add_headers).grid(row=0, column=4, padx=(0, 16))
        ttk.Checkbutton(options, text="Page numbers", variable=self.add_numbers).grid(row=0, column=5)
        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.grid(row=3, column=0, sticky="nsew", pady=14)
        left = ttk.Frame(panes)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        right = ttk.LabelFrame(panes, text="3  Preview", padding=10)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        panes.add(left, weight=5)
        panes.add(right, weight=4)
        files = ttk.LabelFrame(left, text="2  Documents", padding=10)
        files.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        files.columnconfigure(0, weight=1)
        files.rowconfigure(1, weight=1)
        actions = ttk.Frame(files)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        ttk.Button(actions, text="Add PDFs…", command=self.add_files).pack(side="left")
        ttk.Button(actions, text="Add folder…", command=self.add_folder).pack(side="left", padx=5)
        ttk.Button(actions, text="Remove", command=self.remove_files).pack(side="right")
        self.tree = ttk.Treeview(files, columns=("file", "heading", "region", "status"), show="headings", selectmode="extended", height=7)
        for name, title, width in [("file", "PDF filename", 150), ("heading", "Chapter heading", 210), ("region", "Region", 58), ("status", "Status", 95)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=45)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.tag_configure("missing", foreground="#a14820")
        self.tree.bind("<Double-1>", lambda event: self.edit_details())
        self.tree.bind("<<TreeviewSelect>>", self.invalidate_preview)
        bottom = ttk.Frame(files)
        bottom.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        ttk.Button(bottom, text="Edit selected details…", command=self.edit_details).pack(side="left")
        self.preview_button = ttk.Button(bottom, text="Preview selected", command=self.preview)
        self.preview_button.pack(side="right")
        catalog = ttk.LabelFrame(left, text="Chapter catalog", padding=10)
        catalog.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(12, 0))
        ttk.Label(catalog, textvariable=self.catalog_label, style="Sub.TLabel", wraplength=520).pack(anchor="w")
        cat_actions = ttk.Frame(catalog)
        cat_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(cat_actions, text="Choose CSV…", command=self.choose_catalog).pack(side="left")
        ttk.Button(cat_actions, text="Open CSV", command=lambda: open_file(self.catalog_path)).pack(side="left", padx=5)
        ttk.Button(cat_actions, text="Reload", command=self.reload_catalog).pack(side="left")
        ttk.Button(cat_actions, text="Sample PDFs", command=self.add_samples).pack(side="right")
        self.canvas = tk.Canvas(right, background="#dce2e7", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda event: self._schedule_render())
        self.canvas.create_text(190, 170, text="Select a PDF and click\nPreview selected", justify="center", fill="#607282", font=("Helvetica", 14), tags="placeholder")
        nav = ttk.Frame(right)
        nav.grid(row=1, column=0, sticky="ew", pady=(9, 0))
        ttk.Button(nav, text="‹ Previous", command=lambda: self.move_page(-1)).pack(side="left")
        ttk.Label(nav, textvariable=self.page_label, anchor="center").pack(side="left", expand=True)
        ttk.Button(nav, text="Next ›", command=lambda: self.move_page(1)).pack(side="right")
        ttk.Button(right, text="Open preview in PDF viewer", command=self.open_preview).grid(row=2, column=0, pady=(8, 0))
        destination = ttk.Frame(outer)
        destination.grid(row=4, column=0, sticky="ew")
        ttk.Label(destination, text="Save to").pack(side="left", padx=(0, 10))
        ttk.Entry(destination, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(destination, text="Choose…", command=self.choose_output).pack(side="left", padx=(7, 0))
        run = ttk.Frame(outer)
        run.grid(row=5, column=0, sticky="ew", pady=(12, 8))
        ttk.Button(run, text="Open results", command=self.open_results).pack(side="left")
        ttk.Button(run, text="Layout settings…", command=self.edit_layout).pack(side="left", padx=7)
        self.process_button = ttk.Button(run, text="Process all PDFs", style="Primary.TButton", command=self.process)
        self.process_button.pack(side="right")
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=6, column=0, sticky="ew")
        ttk.Label(outer, textvariable=self.status, style="Sub.TLabel", wraplength=900).grid(row=7, column=0, sticky="w", pady=(8, 0))
        for variable in (self.year, self.stage, self.add_headers, self.add_numbers):
            variable.trace_add("write", self.invalidate_preview)

    def _load_settings(self):
        try:
            settings = json.loads(self.settings_path.read_text())
            saved = Path(settings.get("catalog", str(self.catalog_path)))
            if saved.is_file():
                self.catalog_path = saved
            self.output.set(settings.get("output", ""))
        except (OSError, ValueError, TypeError):
            pass

    def _save_settings(self):
        try:
            self.settings_path.write_text(json.dumps({"catalog": str(self.catalog_path), "output": self.output.get()}, indent=2))
        except OSError:
            pass

    def reload_catalog(self):
        if self.busy:
            return
        try:
            rows = read_catalog(self.catalog_path)
        except Exception as exc:
            self.catalog, self.catalog_map = [], {}
            self.refresh_tree()
            self.catalog_label.set(f"Catalog could not be loaded: {self.catalog_path}")
            messagebox.showerror("Check the chapter CSV", str(exc))
            return
        self.catalog = rows
        self.catalog_map = {c.filename.casefold(): c for c in rows}
        self.catalog_label.set(f"{len(rows)} chapters  ·  {self.catalog_path}")
        self.refresh_tree()
        self.invalidate_preview()

    def choose_catalog(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(title="Choose chapter catalog", filetypes=[("CSV files", "*.csv")])
        if path:
            try:
                read_catalog(path)
            except Exception as exc:
                messagebox.showerror("Check the chapter CSV", str(exc))
                return
            self.catalog_path = Path(path)
            self.reload_catalog()
            self._save_settings()

    def refresh_tree(self):
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for i, path in enumerate(self.paths):
            chapter = self.catalog_map.get(path.name.casefold())
            self.tree.insert("", "end", iid=str(i), values=(path.name, chapter.heading if chapter else "Enter chapter details", chapter.region if chapter else "", "Ready" if chapter else "Needs details"), tags=() if chapter else ("missing",))
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

    def _add(self, paths):
        if self.busy:
            return
        for name in paths:
            path = Path(name).resolve()
            if path.suffix.lower() == ".pdf" and path not in self.paths:
                self.paths.append(path)
        self.refresh_tree()
        if self.paths:
            if not self.output.get():
                self.output.set(str(self.paths[0].parent / "Formatted PDFs"))
            self.tree.selection_set(str(len(self.paths) - 1))
        self.status.set(f"{len(self.paths)} PDF(s) selected. Review chapter details before processing.")

    def add_files(self):
        self._add(filedialog.askopenfilenames(title="Add plain PDFs", filetypes=[("PDF files", "*.pdf")]))

    def add_folder(self):
        path = filedialog.askdirectory(title="Choose folder of plain PDFs")
        if path:
            self._add(sorted(p for p in Path(path).iterdir() if p.is_file()))

    def add_samples(self):
        sample_dir = distribution_root() / "examples"
        if not sample_dir.is_dir():
            sample_dir = resource_root() / "examples"
        self._add(sorted(sample_dir.glob("*.pdf")))

    def remove_files(self):
        if not self.busy:
            indices = {int(i) for i in self.tree.selection()}
            self.paths = [p for i, p in enumerate(self.paths) if i not in indices]
            self.refresh_tree()
            self.invalidate_preview()

    def selected_path(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Choose a PDF", "Select a document in the list first.")
            return None
        return self.paths[int(selected[0])]

    def edit_details(self):
        if self.busy:
            return
        path = self.selected_path()
        if not path:
            return
        existing = self.catalog_map.get(path.name.casefold())
        dialog = tk.Toplevel(self.root)
        dialog.title("Chapter details")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=path.name, font=("Helvetica", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
        heading = tk.StringVar(value=existing.heading if existing else "")
        region = tk.StringVar(value=existing.region if existing else "BSAI")
        ttk.Label(frame, text="Chapter heading").grid(row=1, column=0, sticky="w", padx=(0, 12))
        entry = ttk.Entry(frame, textvariable=heading, width=48)
        entry.grid(row=1, column=1, pady=5)
        ttk.Label(frame, text="Region").grid(row=2, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=region, values=list(FOOTERS), state="readonly", width=14).grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(frame, text="Saving updates the selected chapter CSV.", style="Sub.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=12)
        def save():
            try:
                # Re-read before writing so an external CSV edit or a failed
                # reload cannot replace the catalog with a stale/empty list.
                fresh = read_catalog(self.catalog_path)
                updated = [c for c in fresh if c.filename.casefold() != path.name.casefold()]
                updated.append(Chapter(path.name, heading.get().strip(), region.get()))
                write_catalog(self.catalog_path, updated)
            except Exception as exc:
                messagebox.showerror("Could not save details", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.reload_catalog()
        ttk.Button(frame, text="Save details", style="Primary.TButton", command=save).grid(row=4, column=1, sticky="e")
        entry.focus_set()

    def options(self):
        try:
            year = int(self.year.get())
        except ValueError:
            raise ValueError("Enter a four-digit assessment year.") from None
        if not 1990 <= year <= 2100:
            raise ValueError("Choose an assessment year between 1990 and 2100.")
        if not self.add_headers.get() and not self.add_numbers.get():
            raise ValueError("Select headers and footers, page numbers, or both.")
        return FormatOptions(year, next(k for k, v in STAGES.items() if v == self.stage.get()), self.add_headers.get(), self.add_numbers.get())

    def _set_busy(self, value):
        self.busy = value
        for widget in (self.preview_button, self.process_button):
            widget.configure(state="disabled" if value else "normal")
        if value:
            self.progress.start(15)
        else:
            self.progress.stop()

    def preview(self):
        if self.busy:
            return
        path = self.selected_path()
        if not path:
            return
        chapter = self.catalog_map.get(path.name.casefold())
        if not chapter:
            self.edit_details()
            return
        try:
            options = self.options()
            layout = load_layout(self.config_dir / "layout.json")
        except Exception as exc:
            messagebox.showerror("Check settings", str(exc))
            return
        self.preview_counter += 1
        destination = Path(self.temp.name) / f"preview-{self.preview_counter}.pdf"
        revision = self.preview_revision
        self._set_busy(True)
        self.status.set(f"Preparing preview of {path.name}…")
        def worker():
            try:
                result = format_pdf(path, destination, chapter, options, layout)
                self.events.put(("preview", destination, result, path.name, revision))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "error":
                    self._set_busy(False)
                    self.status.set("Processing stopped. Check the message and try again.")
                    messagebox.showerror("Could not process PDF", event[1])
                elif event[0] == "preview":
                    self._set_busy(False)
                    if event[4] != self.preview_revision:
                        event[1].unlink(missing_ok=True)
                        self.status.set("Settings or document selection changed. Click Preview selected again.")
                        continue
                    self._release_preview()
                    self.preview_path = event[1]
                    self.preview_doc = pdfium.PdfDocument(str(self.preview_path))
                    self.preview_index = 0
                    self.render_preview()
                    self.status.set(f"Preview: {event[3]} · {event[2]['pages']} pages. Originals are unchanged.")
                elif event[0] == "progress":
                    self.status.set(event[1])
                elif event[0] == "complete":
                    self._set_busy(False)
                    self.last_output, count, failed = event[1:]
                    self.status.set(f"Finished: {count} PDF(s) saved; {failed} failed. Results: {self.last_output}")
                    messagebox.showinfo("Batch complete", f"{count} PDF(s) saved.\n{failed} failed.\n\nResults and processing report:\n{self.last_output}")
                elif event[0] == "report_failed":
                    self._set_busy(False)
                    self.last_output, count, failed, error = event[1:]
                    self.status.set(f"{count} PDF(s) saved; {failed} failed. Report could not be saved. Results: {self.last_output}")
                    messagebox.showwarning("PDFs saved; report unavailable", f"{count} PDF(s) saved in:\n{self.last_output}\n\nThe processing report could not be saved:\n{error}")
        except queue.Empty:
            pass
        except Exception as exc:
            self._set_busy(False)
            messagebox.showerror("Preview problem", str(exc))
        self.root.after(100, self._poll)

    def _schedule_render(self):
        if hasattr(self, "render_after"):
            self.root.after_cancel(self.render_after)
        self.render_after = self.root.after(160, self.render_preview)

    def render_preview(self):
        if not self.preview_doc:
            return
        page = self.preview_doc[self.preview_index]
        width, height = page.get_size()
        scale = min(max(1, self.canvas.winfo_width() - 24) / width, max(1, self.canvas.winfo_height() - 24) / height, 2.5)
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil().copy()
        bitmap.close()
        page.close()
        self.preview_photo = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.canvas.create_image(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, image=self.preview_photo)
        self.page_label.set(f"Page {self.preview_index + 1} of {len(self.preview_doc)}")

    def move_page(self, step):
        if self.preview_doc:
            self.preview_index = max(0, min(len(self.preview_doc) - 1, self.preview_index + step))
            self.render_preview()

    def _release_preview(self):
        if self.preview_doc:
            self.preview_doc.close()
            self.preview_doc = None
        if self.preview_path:
            try:
                self.preview_path.unlink(missing_ok=True)
            except OSError:
                pass  # An external PDF viewer may still have the file open.
        self.preview_path = None

    def invalidate_preview(self, *_):
        self.preview_revision += 1
        self._release_preview()
        if hasattr(self, "canvas"):
            self.canvas.delete("all")
            self.canvas.create_text(max(190, self.canvas.winfo_width() / 2), 170, text="Select a PDF and click\nPreview selected", justify="center", fill="#607282", font=("Helvetica", 14))
            self.page_label.set("No preview")

    def open_preview(self):
        if self.preview_path:
            open_file(self.preview_path)

    def choose_output(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.output.set(path)
            self._save_settings()

    def open_results(self):
        if not self.last_output and not self.output.get():
            messagebox.showinfo("No results yet", "Process a batch to create the results folder.")
            return
        path = self.last_output or Path(self.output.get())
        if path and path.is_dir():
            open_file(path)

    def process(self):
        if self.busy:
            return
        if not self.paths:
            messagebox.showinfo("Add PDFs", "Add one or more plain PDFs first.")
            return
        try:
            options = self.options()
            layout = load_layout(self.config_dir / "layout.json")
            jobs = []
            names = set()
            for path in self.paths:
                chapter = self.catalog_map.get(path.name.casefold())
                if not chapter:
                    raise ValueError(f"Enter chapter details for {path.name} before processing.")
                if path.name.casefold() in names:
                    raise ValueError(f"Two input PDFs have the same filename: {path.name}. Process them in separate batches.")
                names.add(path.name.casefold())
                jobs.append((path, chapter))
            if not self.output.get().strip():
                raise ValueError("Choose an output folder.")
            base = Path(self.output.get()).expanduser()
            base.mkdir(parents=True, exist_ok=True)
            stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            destination = base / f"{options.year}_{options.stage}_{stamp}"
            suffix = 2
            while destination.exists():
                destination = base / f"{options.year}_{options.stage}_{stamp}_{suffix}"
                suffix += 1
            destination.mkdir()
            # Record the exact choices used for this batch.
            (destination / "settings.json").write_text(json.dumps({"app_version": __version__, "year": options.year, "stage": options.stage, "headers_footers": options.headers_footers, "page_numbers": options.page_numbers, "layout": layout, "catalog": str(self.catalog_path)}, indent=2))
            write_catalog(destination / "chapters-used.csv", [c for _, c in jobs])
        except Exception as exc:
            messagebox.showerror("Check the batch", str(exc))
            return
        self._save_settings()
        self._set_busy(True)
        def worker():
            success, failed = 0, 0
            records = []
            for i, (source, chapter) in enumerate(jobs, start=1):
                self.events.put(("progress", f"Processing {i} of {len(jobs)}: {source.name}…"))
                try:
                    result = format_pdf(source, destination / source.name, chapter, options, layout)
                    records.append({"filename": source.name, "status": "Saved", "pages": result["pages"], "notes": " | ".join(result.get("warnings", []))})
                    success += 1
                except Exception as exc:
                    records.append({"filename": source.name, "status": "Failed", "pages": "", "notes": str(exc)})
                    failed += 1
            try:
                with (destination / "processing-report.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=["filename", "status", "pages", "notes"])
                    writer.writeheader()
                    writer.writerows(records)
            except Exception as exc:
                self.events.put(("report_failed", destination, success, failed, str(exc)))
                return
            self.events.put(("complete", destination, success, failed))
        threading.Thread(target=worker, daemon=True).start()

    def edit_layout(self):
        if self.busy:
            return
        path = self.config_dir / "layout.json"
        try:
            current = load_layout(path)
        except Exception as exc:
            messagebox.showerror("Check layout settings", str(exc))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Layout settings")
        dialog.geometry("640x590")
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Adjust spacing and typography", font=("Helvetica", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Measurements are in points (72 points = 1 inch). Preview after saving.", style="Sub.TLabel", wraplength=600).pack(anchor="w", pady=(6, 12))
        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True)
        groups = {
            "Text & rules": [
                ("font", "Typeface"), ("font_size", "Header, footer and number size"),
                ("minimum_header_font_size", "Smallest size for long headings"),
                ("header_gap", "Minimum space between headings"),
                ("header_height", "Header box height"),
                ("header_baseline_above_rule", "Header text above underline"),
                ("header_rule_width", "Header underline thickness"),
            ],
            "Page margins": [
                ("left_margin", "Left margin"),
                ("portrait_right_margin", "Portrait right margin"),
                ("landscape_right_margin", "Landscape right margin"),
                ("portrait_header_top_margin", "Portrait header: distance from top"),
                ("landscape_header_top_margin", "Landscape header: distance from top"),
                ("footer_baseline", "Footer baseline: distance from bottom"),
                ("page_number_baseline", "Page-number baseline: from bottom"),
            ],
            "Disclaimer": [
                ("disclaimer_bottom", "Box: distance from bottom"),
                ("disclaimer_height", "Box height"),
                ("disclaimer_width", "Maximum box width"),
                ("disclaimer_font_size", "Text size"),
                ("disclaimer_leading", "Line spacing"),
                ("disclaimer_padding", "Space inside box"),
                ("disclaimer_border_width", "Red border thickness"),
            ],
        }
        fields = {}
        for title, pairs in groups.items():
            tab = ttk.Frame(notebook, padding=18)
            notebook.add(tab, text=title)
            for row, (key, label) in enumerate(pairs):
                ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", padx=(0, 20), pady=9)
                fields[key] = tk.StringVar(value=str(current[key]))
                if key == "font":
                    ttk.Combobox(tab, textvariable=fields[key], values=["Times-Italic", "Times-Roman", "Times-Bold", "Times-BoldItalic", "Helvetica", "Helvetica-Oblique", "Helvetica-Bold", "Courier", "Courier-Oblique"], state="readonly", width=19).grid(row=row, column=1, sticky="e")
                else:
                    ttk.Entry(tab, textvariable=fields[key], width=12).grid(row=row, column=1, sticky="e")
        def save():
            candidate = Path(self.temp.name) / "candidate-layout.json"
            try:
                value = {key: variable.get() if key == "font" else float(variable.get()) for key, variable in fields.items()}
                candidate.write_text(json.dumps(value, indent=2))
                load_layout(candidate)
                path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                messagebox.showerror("Check layout settings", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.invalidate_preview()
            self.status.set("Layout saved. Preview a PDF to check the change.")
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))
        def defaults():
            for key, variable in fields.items():
                variable.set(str(DEFAULT_LAYOUT[key]))
        ttk.Button(buttons, text="Use original layout values", command=defaults).pack(side="left")
        ttk.Button(buttons, text="Save layout", style="Primary.TButton", command=save).pack(side="right")

    def close(self):
        if self.busy:
            messagebox.showinfo("Processing PDFs", "Please wait for the current operation to finish.")
            return
        self._save_settings()
        if self.preview_doc:
            self.preview_doc.close()
        self.temp.cleanup()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = FormatterApp(root)
    # Useful for opening a plain PDF with the application from a file association.
    inputs = [arg for arg in sys.argv[1:] if not arg.startswith("-") and Path(arg).is_file()]
    if inputs:
        app._add(inputs)
    root.mainloop()
