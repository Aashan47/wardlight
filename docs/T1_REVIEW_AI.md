# T1 first-pass review (AI, not yet confirmed by a human)

**This is not the T1 result.** An AI reviewer (Claude) did this pass. A human must confirm it, at least on
the wrong and unclear rows and a spot check of the correct ones, before T1 is reported in `docs/RESULTS.md`.

## Method

The 200 rows of `docs/T1_SAMPLE.csv` (seed 20261030) were checked against the row crop named in
`crop_path` (`data/work/nerc_crops/`). Each crop is about 3,200 px wide, so it was cut into three
overlapping strips, stacked and viewed at native resolution. The six fields (S/N, band, feeder name,
location, streets, minimum hours) were compared one by one with the extracted values. Doubtful cells were
re-cropped and enlarged. A row counts as correct only if S/N, band and hours match exactly and feeder name,
location and streets differ by no more than spacing or punctuation. No page re-render was needed because no
crop was cut or unreadable. Row-level verdicts are in `docs/T1_REVIEW_AI.csv`.

## Counts

| Verdict | Rows |
|---|---|
| correct | 190 |
| wrong | 8 |
| unclear | 2 |
| **Total** | **200** |

Share correct: 190/200 = **95.0%**, 95% Wilson interval **91.0% to 97.3%**. If a human rules both unclear
rows correct, the result is 192/200 = 96.0% (Wilson 92.3% to 98.0%). Either way the point estimate is
**below the 97% target**, although the interval still includes 97%.

No S/N, band or hours value was wrong in any of the 200 rows. All the errors are in text fields.

## Wrong rows

| Sample | File, page, S/N | Field | Printed | Extracted |
|---|---|---|---|---|
| 17 | AEDC p18, 153 | feeder name | ...FDR D6_PL_PL | ...FDR DÉ_PL_PL |
| 30 | APLE p7, 27 | location | OGBORHILL ISS | OGBORHILL JSS |
| 47 | BEDC p14, 110 | location, streets | IJAW QUARTERS; IJAW QTRS 1, 2, 3 | JAW QUARTERS; UAW QTRS 1, 2, 3 |
| 70 | EEDC p14, 117 | feeder name | NNEWI-OBA 33KV | NNEWLOBA 33KV |
| 98 | IBEDC p20, 263 | location | IDI-OGUN AREA... | IDIL-OGUN AREA... |
| 102 | IBEDC p24, 350 | location | AGO-IWOYE 1X15MVA... | AGO-WOYE 1X15MVA... |
| 103 | IBEDC p25, 362 | streets | ...ISALE IJAGBE/SABINTU ROAD. | ...ISALE JAGBE/SABINTU ROAD. |
| 110 | IKEDC p11, 7 | streets | WATER WORKS COMPOUND IJU | WATER WORKS COMPOUND WU |

Four of the eight (47, 102, 103, 110) are the "IJ" confusion already listed in `docs/sources/nerc.md`,
section 5. The rest are single-glyph errors.

## Unclear rows

| Sample | File, page, S/N | Issue |
|---|---|---|
| 26 | AEDC p21, 244 | Source prints "33OKV" with a round letter O. The OCR read "330KV", which is the intended text. All other fields match. |
| 29 | AEDC p23, 295 | Same source typo and same reading. |

The rule does not say whether a source typo corrected in the extraction counts as correct. A human should
decide.

## Side effect

The 190 rows judged correct were appended to `docs/VERIFIED_ROWS.csv` with checked_by "AI review (Claude);
human check pending". None was already there. No row is marked as checked by a human.
