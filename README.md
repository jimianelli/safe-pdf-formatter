# SAFE PDF Formatter

A local desktop application for adding SAFE headers, footers, draft disclaimers,
and page numbers to plain PDFs. Version 0.1 is a prototype for layout testing.

## Start on a Mac

Open **SAFE PDF Formatter.app** in the supplied release folder. Keep the adjacent
`config` and `examples` folders with the app. Everything needed to run it is
included; Python and Acrobat are not required.

1. Click **Sample PDFs** to load the included four-page demonstration, or choose
   **Add PDFs…** / **Add folder…** for your own plain documents.
2. Select the **Year** and **Release**. These choices determine the printed label
   and whether the first-page disclaimer is included.
3. Review the chapter heading and region beside each filename. For an unknown
   filename, select it and click **Edit selected details…**. Saving adds its
   details to the selected chapter CSV.
4. Select a document and click **Preview selected**. Use **Previous** / **Next**
   to check all page orientations. **Open preview in PDF viewer** opens the same
   formatted preview at full size in your usual PDF viewer.
5. Choose where to save results and click **Process all PDFs**.

Each batch is saved in a new dated subfolder. The source PDFs are never changed.
The output folder contains the PDFs, a processing report, and copies of the exact
chapter settings and layout used. A failed document is recorded in the report;
the remaining documents can still complete.

## Change chapter information

`config/chapters.csv` has three columns:

| filename | heading | region |
| --- | --- | --- |
| EBSpollock.pdf | EBS Walleye pollock | BSAI |
| GOApcod.pdf | GOA Pacific cod | GOA |
| sablefish.pdf | AK Sablefish | AK |

Use **Open CSV** to edit it in Excel or a text editor, save as UTF-8 CSV, then
click **Reload**. **Choose CSV…** switches to a different catalog. The app shows
the path of the catalog it is using. Filenames match without regard to letter
case; duplicate names that differ only in case are rejected.

Region codes select the footer wording: `GOA`, `BSAI`, `AK`, `ECO`, or `ECON`.
The year and release stage are selected in the app, not in the CSV.

The initial catalog combines the established headings from `menu.js` with a
documented filename alias from the [SAFE Chapter status worksheet](https://docs.google.com/spreadsheets/d/1bMCdYBVF-ZpJMp91ZJ2No5sOoXrWoKhrwEcDf5JuuCE/edit?gid=575468903#gid=575468903).
This is a local snapshot, not a live Google Sheets connection. See
`config/catalog-source.md` for source details and unresolved worksheet entries.
No author contact information is included.

## Change the layout

Use **Layout settings…** to adjust the local `config/layout.json`. Dimensions
are in PDF points (72 points = 1 inch). Save and create a new preview to see the
change. Changing the CSV or layout does not require rebuilding the application.

The default appearance follows the active behavior of the supplied Acrobat
script:

- Meeting label and chapter heading appear on every page and alternate sides.
- Headers are underlined; the SAFE footer alternates sides.
- Page 1 is always unnumbered. The second physical page reads **Page 2**.
- Draft page 1 has the exact pre-dissemination disclaimer in a red box, replacing
  the regional footer. Final page 1 has the regional footer and no disclaimer.
- Portrait and landscape pages use the established Letter-size margins, adapted
  to visible page dimensions and rotation.

PDFs must have empty space for the additions. The app does not reflow body text
or shrink pages automatically. The sample demonstrates a suitable layout.
The additions are ordinary PDF content rather than editable Acrobat form fields.
Use the plain original to make another release. PDFs already processed by this
app are rejected to prevent duplicate stamping.

## Validation and publication

Check representative first, odd, even, landscape, and final pages. Compare an
actual chapter against a trusted Acrobat-formatted version before adopting the
prototype for production; the synthetic sample is not a pixel-exact reference
for Acrobat's field rendering.

The program retains PDF page objects and adds vector text, without rasterizing
the document body. Running headers, footers, and numbers are marked as artifacts.
The substantive disclaimer remains content. Existing PDF accessibility tags,
links, bookmarks, and reading order still need checking on representative real
documents. The application does not certify PDF/UA or Section 508 compliance,
and adding a disclaimer may require a reading-order/tagging review.

## Windows version

Extract the Windows ZIP in full, then open **SAFE PDF Formatter.exe**. Keep its
`_internal`, `config`, and `examples` folders together. No Python or Acrobat
installation is needed. See **START HERE.txt** for staff instructions. The
unsigned test release may require approval through your organization's usual
software process on managed computers.

The same application source is built natively on each platform. The `scripts`
folder contains the Windows build script; `.github/workflows/build.yml` runs
tests and creates a portable ZIP on a Windows build machine. The validation
report accompanying a build records what was actually tested.

## For maintaining the application

`app.py` starts the application; `safe_pdf/gui.py` controls the interface,
`safe_pdf/engine.py` formats PDFs, and `safe_pdf/catalog.py` reads and validates
the CSV. Dependencies are pinned in `requirements.txt`; build dependencies are
in `requirements-build.txt`. Build scripts and the PyInstaller spec keep Mac and
Windows packages on the same codebase. The source remains editable alongside
the packaged Mac application.

Run automated checks from the project directory:

```sh
python -m unittest discover -s tests -v
python app.py --self-test /path/to/empty-test-folder
```

The self-test formats the bundled sample, checks source preservation, renders
a preview, and checks Tk/Pillow integration. `--no-gui` skips the display check
when running without a desktop session. Native GUI validation must still be run
before distributing a platform build.
