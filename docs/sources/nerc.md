# NERC feeder appendices: what was read, how, and what is wrong with it

Written by build agent A. Code in `data_build/nerc/`, tests in `tests/nerc/`. Outputs go to `data/work/`
(gitignored; the orders are NERC's, all rights reserved, so they are cited and linked, never re-hosted).

Run: `cd build/wardlight && .venv/bin/python -m data_build.nerc.build --sample` (about 8 minutes on 15
cores; `--reuse` re-assembles from the cached page reads without OCR). Accuracy on the hand-transcribed
pages: `.venv/bin/python -m data_build.nerc.evaluate`. Tests: `.venv/bin/python -m pytest tests/nerc`.

## 1. Files and pages

Source PDFs in `data-local/nerc/` (URLs and SHA-256 in `data-local/MANIFEST.md`, section 3). All twelve
are image-only scans; no text layer was used. The eleven NERC-regulated DisCos' supplementary orders share
one template: tariff tables on pages 4 to 7, the customer classification table on page 9 or 10, then the
feeder appendices from page 10 or 11 to the end. Aba Power's order is older and differently laid out.

| DisCo (naija-grid code) | File | Appendix pages read | Service-level appendix | Shortfall appendices |
|---|---|---|---|---|
| AEDC | AEDC_HOLDCO_YSS_September_2026_088.pdf | 11 to 23 | Appendix 4, p14 to 23 | Appendix 2 (downgrade and compensation), Appendix 3 (compensation only), p11 to 14 |
| APLE (Aba Power) | APLE-MYTO_-FEB-2025_014.pdf | 7 to 8 | Appendix 2, p7 to 8 | none |
| BEDC | BEDC_HOLDCO_YSS_September_2026_089.pdf | 11 to 18 | Appendix 3 | Appendix 2, p11 |
| EEDC | EEDC_HOLDCO_YSS_September_2026_090.pdf | 11 to 16 | Appendix 3 | Appendix 2, p11 |
| EKEDC (file prefix EKEDP) | EKEDP_HOLDCO_YSS_September_2026_091.pdf | 10 | Appendix 2 | none |
| IBEDC | IBEDC_HOLDCO_YSS_September_2026_092.pdf | 11 to 27 | Appendix 3 | Appendix 2, p11 |
| IKEDC (file prefix IE) | IE_HOLDCO_YSS_September_2026_093.pdf | 11 to 12 | Appendix 2 | none |
| JEDC (file prefix JED) | JED_HOLDCO_YSS_September_2026_094.pdf | 11 to 15 | Appendix 3 | Appendix 2, p11 |
| KAEDC | KAEDC_HOLDCO_YSS_September_2026_095.pdf | 11 to 16 | Appendix 3 | Appendix 2, p11 |
| KEDCO | KEDCO_HOLDCO_YSS_Septmeber_2026_096.pdf | 11 to 15 | Appendix 3 | Appendix 2, p11 |
| PHED | PHED_HOLDCO_YSS_September_2026_097.pdf | 11 to 18 | Appendix 3 | Appendix 2, p11 |
| YEDC | YEDC_HOLDCO_YSS_September_2026_098.pdf | 11 to 15 | Appendix 3 | Appendix 2, p11 |

Every page of every file is rendered and scanned for ruled tables; tables whose header has no feeder
column (tariffs, remittances, customer classes) are skipped. `disco` uses naija-grid's codes so the matcher
can join on it. `order_month` is the order's month as `YYYY-MM`; Aba Power's is the older order.

## 2. Row counts

`nerc_rows.parquet` (service-level commitments, one row per feeder) and `nerc_shortfalls.parquet`:

| DisCo | Rows | Band A | B | C | D | E | Shortfall rows | naija-grid feeders last seen in the newest cap order |
|---|---|---|---|---|---|---|---|---|
| AEDC | 295 | 191 | 53 | 18 | 33 | 0 | 83 | 635 |
| APLE | 38 | 12 | 2 | 23 | 1 | 0 | 0 | not in that order |
| BEDC | 262 | 90 | 18 | 30 | 69 | 55 | 3 | 243 |
| EEDC | 210 | 106 | 27 | 49 | 22 | 6 | 10 | 17 |
| EKEDC | 7 | 1 | 3 | 0 | 2 | 1 | 0 | 17 |
| IBEDC | 399 | 136 | 75 | 41 | 71 | 76 | 2 | 509 |
| IKEDC | 41 | 10 | 7 | 18 | 5 | 1 | 0 | 34 |
| JEDC | 184 | 78 | 45 | 33 | 14 | 14 | 6 | 98 |
| KAEDC | 192 | 93 | 5 | 23 | 37 | 34 | 1 | 199 |
| KEDCO | 190 | 52 | 44 | 57 | 29 | 8 | 13 | 158 |
| PHED | 237 | 82 | 24 | 68 | 48 | 15 | 2 | 236 |
| YEDC | 135 | 31 | 34 | 45 | 25 | 0 | 1 | 149 |
| **Total** | **2,190** | | | | | | **121** | 2,295 |

Coverage check: in every DisCo the serial numbers read run from 1 to the last one with no gap and no
repeat (`data/work/nerc_build_log.json`, `coverage`). The plain-page probe before this build caught about
727 rows. The naija-grid column counts feeders in the monthly energy cap orders, a different NERC document:
the two lists are not the same population (EEDC lists 210 feeders here against 17 there; AEDC 295 against
635), so the comparison is a sanity check on scale only.

Shortfalls: 32 rows carry a measured average (16.29 to 19.95 hours, all Band A feeders against a promise of
20); 79 AEDC rows come from Appendix 3, which has no measured column (period and hours null); 10 rows print
"AFFECTED BY LOW GENERATION" (or a fragment of it) in place of a number, kept null. Actions: 4 AEDC rows
`downgrade+compensation`, the rest `compensation`; none ordered an upgrade.

## 3. Method

1. Render each page at 300 dpi, greyscale (pypdfium2). Deskew from the long horizontal rulings (only the
   Aba scan is rotated, 1.6 and 2.1 degrees on the table pages).
2. Grid: binarise at grey 200 (not Otsu: EEDC p11 draws rulings at grey 156 to 161, which Otsu dropped),
   close 1 to 6 px gaps vertically, open with 60 px horizontal and 40 px vertical kernels. Row and column
   boundaries are clustered line positions; a column boundary must run down at least 30% of the table.
   Merged cells are resolved per cell from the rulings actually present.
3. Columns are mapped by header text: S/N, FEEDER NAME, BAND or CURRENT BAND, DESCRIPTION OF FEEDER
   LOCATION or FEEDER LOCATION, NAME OF MAJOR STREETS SERVED BY THE FEEDER, MIN. SUPPLY DURATION (HRS),
   the measured-performance column (its header gives the period), and REMARK. A table with minimum hours is a
   service-level appendix; one with a remark or measured column is a shortfall appendix.
4. One record per S/N cell. Where a row rule is drawn in only some columns (EEDC p16, S/N 202 and 203), the
   S/N cell is split where the S/N column is blank across an internal grid line, and the other merged
   cells are clipped at the same line.
5. Each cell is cropped, ruling pixels are whited out, and the cell is OCRed alone with tesseract 5.5.3:
   text cells at 1x and 2x, keeping the read with the higher mean word confidence; band with a line read
   and an A to E single-character fallback; numbers with a digit whitelist.
6. Numbers (S/N, hours) are then re-read glyph by glyph against a template bank built per order from cells
   whose two tesseract reads agree. Tesseract alone read "41" as "4" and "71" as "7" in almost every DisCo
   and missed a lone "4"; the bank read 4,519 of 4,543 number cells and changed 88: a lone "4" that
   tesseract left empty (54 hours cells, 40 of them BEDC band E; 11 S/N cells), S/N "41" from "4" (11) and
   "71" from "7" (8), three Aba S/N cells and one EEDC "9". Each pattern was checked by eye on example
   crops, and the S/N sequences now run without a gap in every DisCo.
7. Normalisation: band to A to E only when exactly one band letter is read; hours only when the whole cell
   is a number from 0 to 24; S/N only when the cell is a number. Anything else stays null with the raw
   text kept. Tables are set in capitals, so lower-case OCR output is a confusion and is mapped back
   ("l" to "1" next to digits, otherwise "I"); voltage tokens are repaired ("1 1KV", "1TKV", "33KY" to
   "11KV", "11KV", "33KV"); braces become parentheses; dash variants become hyphens.
8. Evidence: every row of both files has a crop of its full table row, `data/work/nerc_crops/` (2,311
   PNGs). `nerc_rows.crop_path` names it. `data/work/nerc_raw.parquet` keeps, for every row of both
   files, the raw OCR text of each cell, the header text that mapped each column, the appendix title,
   per-field confidences, the tesseract and template reads of each number, the crop path, `row_index`
   into its target file, and `checks`.

`ocr_confidence` is tesseract's mean word confidence over the S/N, band, feeder name and hours cells, as a
fraction (median 0.94; 61 rows below 0.8). No vision model was used and nothing was spent: no page needed
one.

## 4. Accuracy on hand-transcribed pages

Three pages transcribed by eye from the renders before comparing (`tests/nerc/fixture_*.json`): IKEDC p12
(10 rows), PHED p11 (27 rows and 2 shortfall rows), Aba Power p8 (7 rows, the paper scan).

| Field | Exact | Within 2 edits |
|---|---|---|
| S/N | 44/44 | 44/44 |
| Band | 44/44 | 44/44 |
| Min. hours | 44/44 | 44/44 |
| Feeder name | 40/44 | 44/44 |
| Location | 44/44 | 44/44 |
| Streets | 40/44 | 43/44 |
| Shortfall rows (feeder, measured hours, action, period) | 2/2 | |

Text is compared after upper-casing and removing spaces around punctuation. This is a check on three
pages, not the T1 result: T1 is the 200-row sample in `docs/T1_SAMPLE.csv` (seed 20261030), drawn and
**not yet checked**; columns `band_ok` to `min_hours_ok` are for the person who checks it against the
crops.

## 5. Known problems

- **OCR confusions left in text.** In this font "4" inside words reads as "A" ("4POINT SHERATON" as
  "APOINT SHERATON", PHED); "NJ" reads as "NSJ" or "NS" ("ODOGUNYANINJ" as "ODOGUNYANINSJ", IKEDC); "IJ"
  loses its "I" ("IJOKO" as "JOKO"); the Aba scan reads "AL)" as "AI)". Not corrected, since a rule for
  them would be guessing. The matcher should use fuzzy matching.
- **The source disagrees with itself** in three rows, kept as printed and flagged `band_hours_mismatch`
  in `nerc_raw.checks`: IBEDC S/N 398 and 399 (p27) are band E with 20 hours; Aba Power S/N 38 (p8) is band
  D with 4 hours.
- **Aba Power's streets column is headed "1ST - 25TH JANUARY AVE PERFORMANCE"** in the order but holds
  street lists; it is read as streets. So Aba has no measured hours.
- **Thin DisCos.** EKEDC's appendix has 7 feeders, all Agbara; IKEDC's has 41, Abule Egba and Ikorodu only.
  Most of Lagos is not covered by these orders.
- **JEDC's shortfall table has an empty REMARK column**; its action (`compensation`) comes from the
  appendix title ("Feeders for Compensation only due to poor service delivery").
- **Measured hours not printed as numbers** in 10 shortfall rows ("AFFECTED BY LOW GENERATION"); null.
- **`nerc_shortfalls` has no `band` or `crop_path` column** in the runbook contract. Both are in
  `nerc_raw.parquet` (`target == "shortfalls"`, joined by `row_index`).
- **Shortfall measuring window**: the period header reads "1st to 21st" of the month before the order;
  `period` is that window as ISO start/end.
