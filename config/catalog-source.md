# Chapter catalog sources

The editable `chapters.csv` is a starting catalog for PDF formatting, not a
statement of the current official SAFE contents or approval status.

## Sources checked on 2026-09-16

- The user-supplied `/Users/jim/menu.js`, lines 208-271, contains 63 filename,
  chapter-heading, and region mappings. All 63 are retained with their exact
  headings and regions, including older filename aliases. Historical spellings
  and trailing spaces in three ecosystem headings are preserved.
- The user's [Google worksheet, SAFE Chapter status](https://docs.google.com/spreadsheets/d/1bMCdYBVF-ZpJMp91ZJ2No5sOoXrWoKhrwEcDf5JuuCE/edit?gid=575468903#gid=575468903)
  was inspected read-only. The tab ID is `575468903`; D3 is `Doc name (case sens)`.
  A1:H80 and I3:AG6 were read for column labels and surrounding context. There
  are 56 nonempty document-name cells in D4:D63. The worksheet supplies filenames,
  team assignments, and processing status, but does not supply chapter-header
  wording in the inspected columns. No worksheet edits or sharing changes were
  made. Author contact information is not copied into this catalog.

The one added alias is `EBSmultispp.pdf` (D6), using the existing BSAI
`Multi-species supplement` heading from `Multispp.pdf`. This association is based
on the worksheet's BSAI chapter 1.01 and the unique legacy multispecies record;
the heading itself is copied exactly from `menu.js`. The user confirmed that
the combined `Sculpins.pdf` chapter is Alaska-wide; its heading is
`Alaska-wide Sculpins`, with region `AK` and the Alaska-wide SAFE footer.
The initial catalog had 65 records. The Windows handoff also retains the Mac
tester's `BOGpollock_Sept 2026.pdf` alias, heading `Bogoslof Walleye pollock`,
region `BSAI`, for a total of 66 records. Only its filename mapping is included;
the actual PDF is not distributed. Retained legacy names are compatibility
entries, not an assertion that they remain active chapters.

## Differences requiring attention

| Worksheet cell | Observed value | Catalog handling |
| --- | --- | --- |
| D6 | `EBSmultispp.pdf` | Added as an alias of the legacy `Multispp.pdf` record as described above. |
| D11 and D38 | `Sablefish.pdf` and `sablefish.pdf` | Retained the legacy `sablefish.pdf`, heading `AK Sablefish`, region `AK`. The formatter deliberately matches filenames without regard to capitalization, so both spellings resolve to that entry. Two records differing only in capitalization are rejected to prevent conflicting matches on macOS and Windows. |
| D32 | `AIecosys` | Missing `.pdf`; not added as an invalid filename. Legacy `AIecosys.pdf` remains available with its original BSAI region and heading. |
| D62 | `Sculpins.pdf`, team `xBoth` | User-confirmed Alaska-wide chapter: heading `Alaska-wide Sculpins`, region `AK`. The older separate BSAI and GOA sculpins mappings remain as compatibility entries. |

Worksheet Team values are not automatically substituted for footer regions:
for example, sablefish uses `AK`, and `economic.pdf` uses `ECON` in the script.
Blank document names and non-PDF entries are not invented. The catalog file
contains no meeting year or release stage; those are explicit formatting options.

## Editing the catalog

Use the three CSV columns `filename,heading,region`. Filenames must be PDF
basenames without directories, headings must contain text, and regions must be
one of `GOA`, `BSAI`, `AK`, `ECO`, or `ECON`. Preserve the intended filename case.
Duplicate filenames are checked without regard to capitalization. UTF-8 CSV
files with or without a byte-order mark are accepted. Saving validates all rows
before replacing the previous file.

`examples/EBSpollock.pdf` is a synthetic four-page layout demonstration, not an
assessment. Its filename selects the established EBS Walleye pollock catalog
entry so orientation and first-page conventions can be previewed without using
scientific content.
