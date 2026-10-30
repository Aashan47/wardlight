"""Build nerc_rows.parquet and nerc_shortfalls.parquet from the scanned NERC orders.

Run from build/wardlight:

    .venv/bin/python -m data_build.nerc.build            # render, read, write parquet and crops
    .venv/bin/python -m data_build.nerc.build --sample   # also draw docs/T1_SAMPLE.csv

Inputs: ../../data-local/nerc/*.pdf (never copied into the repo). Outputs, all under data/work/
(gitignored): nerc_pages/ (300 dpi renders), nerc_crops/ (one PNG per extracted row),
nerc_rows.parquet, nerc_shortfalls.parquet (runbook contract columns only), nerc_raw.parquet (raw OCR
text, header mapping, confidences and checks for every row of both files) and nerc_build_log.json.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pypdfium2 as pdfium

from .digits import Bank
from .reader import KEY_ROLES, NUM_ROLES, clean_text, read_page
from .schema import (
    BAND_HOURS,
    DEFAULT_ORDER_MONTH,
    ORDER_MONTH,
    disco_from_file,
    parse_action,
    parse_band,
    parse_hours,
    parse_period,
    parse_sn,
)

ROOT = Path(__file__).resolve().parents[2]  # build/wardlight
SRC = ROOT.parent.parent / "data-local" / "nerc"
WORK = ROOT / "data" / "work"
PAGES = WORK / "nerc_pages"
CROPS = WORK / "nerc_crops"
DPI = 300

ROW_COLS = ["disco", "order_file", "order_month", "page", "sn", "band", "feeder_name", "location",
            "streets", "min_hours", "ocr_confidence", "crop_path"]
SHORT_COLS = ["disco", "order_file", "page", "feeder_name", "period", "measured_avg_hours", "action"]

# Pages that carry the feeder appendices (checked by eye on contact sheets). Every page is
# still scanned for tables; this list only feeds the coverage log.
FIRST_APPENDIX_PAGE = {"APLE": 7}
DEFAULT_FIRST_APPENDIX_PAGE = 10


def render_all(src: Path = SRC, out: Path = PAGES) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for pdf_path in sorted(src.glob("*.pdf")):
        pdf = pdfium.PdfDocument(str(pdf_path))
        for i in range(len(pdf)):
            p = out / f"{pdf_path.stem}_p{i + 1:02d}.png"
            if not p.exists():
                pdf[i].render(scale=DPI / 72, grayscale=True).to_pil().save(p)
            paths.append(p)
    return paths


def _page_job(path: str) -> dict:
    p = Path(path)
    res = read_page(p)
    disco = disco_from_file(res.file_stem)
    out = []
    for k, rec in enumerate(res.records):
        crop_name = f"{disco}_p{res.page:02d}_t{rec.table_idx}_r{k:03d}.png"
        x0, y0, x1, y1 = rec.row_box
        h, w = res.image.shape
        crop = res.image[max(y0, 0):min(y1, h), max(x0, 0):min(x1, w)]
        cv2.imwrite(str(CROPS / crop_name), crop, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        out.append({
            "kind": rec.kind, "title": clean_text(rec.title), "roles": rec.roles,
            "raw": {k2: clean_text(v) for k2, v in rec.raw.items()}, "conf": rec.conf,
            "crop_path": f"data/work/nerc_crops/{crop_name}", "table_idx": rec.table_idx,
            "grid_rows": list(rec.grid_rows), "num": rec.extra.get("num", {}),
        })
    return {"stem": res.file_stem, "page": res.page, "skew_deg": res.skew_deg,
            "tables_seen": res.tables_seen, "notes": res.notes, "records": out}


def read_all(paths: list[Path], workers: int | None = None) -> list[dict]:
    CROPS.mkdir(parents=True, exist_ok=True)
    for old in CROPS.glob("*.png"):
        old.unlink()
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # one tesseract thread per worker process
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(workers) as ex:
        return list(ex.map(_page_job, [str(p) for p in paths], chunksize=1))


def apply_digit_templates(pages: list[dict]) -> None:
    """Re-read S/N and hours cells with a per-order glyph template bank (see digits.py).

    Sets rec["raw"][role] to the template read when it is confident, keeps tesseract's otherwise, and
    records both in rec["num_reads"].
    """
    by_stem: dict[str, list[dict]] = {}
    for pg in pages:
        by_stem.setdefault(pg["stem"], []).append(pg)
    for pgs in by_stem.values():
        bank = Bank()
        for pg in pgs:
            for rec in pg["records"]:
                for img, digits_txt, plain in rec.get("num", {}).values():
                    bank.add(img, digits_txt, plain)
        bank.build()
        for pg in pgs:
            for rec in pg["records"]:
                reads = {}
                for role in NUM_ROLES:
                    entry = rec.get("num", {}).get(role)
                    if entry is None:
                        continue
                    img, digits_txt, plain = entry
                    if sum(ch.isalpha() for ch in plain) >= 3:
                        reads[role] = {"tesseract": digits_txt, "plain": plain, "template": None,
                                       "score": 0.0, "worded": True}
                        continue  # a worded cell, not a number (see reader._read_cell)
                    tpl, score = bank.read(img)
                    reads[role] = {"tesseract": digits_txt, "template": tpl, "score": round(score, 3)}
                    if tpl is not None:
                        rec["raw"][role] = tpl
                rec["num_reads"] = reads
                rec.pop("num", None)


def assemble(pages: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    apply_digit_templates(pages)
    rows, shorts, raws = [], [], []
    for pg in sorted(pages, key=lambda d: (d["stem"], d["page"])):
        disco = disco_from_file(pg["stem"])
        order_file = pg["stem"] + ".pdf"
        month = ORDER_MONTH.get(disco, DEFAULT_ORDER_MONTH)
        for rec in pg["records"]:
            # braces never occur in these tables; on the Aba scan ')' reads as '}'
            raw = {k: v.replace("{", "(").replace("}", ")") for k, v in rec["raw"].items()}
            band = parse_band(raw.get("band", ""))
            sn = parse_sn(raw.get("sn", ""))
            measured = parse_hours(raw.get("measured", "")) if "measured" in raw else None
            checks = []
            base = {
                "target": "rows" if rec["kind"] == "service_level" else "shortfalls",
                "disco": disco, "order_file": order_file, "page": pg["page"],
                "table_idx": rec["table_idx"], "appendix_title": rec["title"],
                "header_map": json.dumps(rec["roles"]),
                "sn_raw": raw.get("sn", ""), "band_raw": raw.get("band", ""),
                "feeder_name_raw": raw.get("feeder_name", ""), "location_raw": raw.get("location", ""),
                "streets_raw": raw.get("streets", ""), "min_hours_raw": raw.get("min_hours", ""),
                "measured_raw": raw.get("measured", ""), "remark_raw": raw.get("remark", ""),
                "sn": sn, "band": band, "measured_avg_hours": measured,
                "conf_json": json.dumps({k: round(v, 1) for k, v in rec["conf"].items()}),
                "num_reads_json": json.dumps(rec.get("num_reads", {})),
                "crop_path": rec["crop_path"], "skew_deg": round(pg["skew_deg"], 2),
            }
            key_conf = [rec["conf"][k] for k in KEY_ROLES if rec["conf"].get(k, -1) >= 0]
            conf = round(float(np.mean(key_conf)) / 100.0, 3) if key_conf else None
            if rec["kind"] == "service_level":
                hours = parse_hours(raw.get("min_hours", ""))
                if band is None:
                    checks.append("band_unread")
                if hours is None:
                    checks.append("hours_unread")
                if band and hours is not None and BAND_HOURS[band] != hours:
                    checks.append("band_hours_mismatch")
                if sn is None:
                    checks.append("sn_unread")
                if not raw.get("feeder_name"):
                    checks.append("feeder_name_empty")
                base["row_index"] = len(rows)
                rows.append({
                    "disco": disco, "order_file": order_file, "order_month": month, "page": pg["page"],
                    "sn": sn, "band": band, "feeder_name": raw.get("feeder_name", ""),
                    "location": raw.get("location", ""), "streets": raw.get("streets", ""),
                    "min_hours": hours, "ocr_confidence": conf, "crop_path": rec["crop_path"],
                })
            else:
                period = parse_period(rec["roles"].get("measured", ""), month) if "measured" in rec["roles"] else None
                action = parse_action(raw.get("remark", ""), rec["title"])
                if action is None:
                    checks.append("action_unread")
                if "measured" in rec["roles"] and measured is None:
                    checks.append("measured_unread")
                base["row_index"] = len(shorts)
                shorts.append({
                    "disco": disco, "order_file": order_file, "page": pg["page"],
                    "feeder_name": raw.get("feeder_name", ""), "period": period,
                    "measured_avg_hours": measured, "action": action,
                })
            base["checks"] = ";".join(checks)
            raws.append(base)
    df_rows = pd.DataFrame(rows, columns=ROW_COLS)
    df_rows["sn"] = df_rows["sn"].astype("Int64")
    df_rows["page"] = df_rows["page"].astype("int32")
    df_short = pd.DataFrame(shorts, columns=SHORT_COLS)
    df_raw = pd.DataFrame(raws)
    df_raw["sn"] = df_raw["sn"].astype("Int64")
    _sn_checks(df_raw)
    return df_rows, df_short, df_raw


def _sn_checks(df_raw: pd.DataFrame) -> None:
    """Flag serial-number gaps and repeats within each DisCo's service-level appendix."""
    df_raw["sn_flag"] = ""
    for (_, _), g in df_raw[df_raw["target"] == "rows"].groupby(["disco", "target"]):
        sns = g["sn"].tolist()
        prev = None
        for idx, s in zip(g.index, sns):
            if pd.isna(s):
                prev = None
                continue
            if prev is not None and s != prev + 1:
                df_raw.loc[idx, "sn_flag"] = f"after_{prev}"
            prev = s


def coverage(df_rows: pd.DataFrame, df_raw: pd.DataFrame) -> dict:
    """Serial numbers expected (1 to max per DisCo) against those read."""
    out = {}
    for disco, g in df_rows.groupby("disco"):
        sns = {int(s) for s in g["sn"].dropna()}
        top = max(sns) if sns else 0
        missing = sorted(set(range(1, top + 1)) - sns)
        dup = int(g["sn"].dropna().duplicated().sum())
        out[disco] = {"rows": len(g), "max_sn": top, "missing_sn": missing, "duplicate_sn": dup,
                      "band_unread": int(g["band"].isna().sum()),
                      "hours_unread": int(g["min_hours"].isna().sum())}
    return out


def draw_t1_sample(df_rows: pd.DataFrame, n: int = 200, seed: int = 20261030) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = np.sort(rng.choice(len(df_rows), size=min(n, len(df_rows)), replace=False))
    s = df_rows.iloc[idx][["order_file", "page", "sn", "disco", "band", "feeder_name", "location",
                           "streets", "min_hours", "crop_path"]].copy()
    s.insert(0, "sample_id", range(1, len(s) + 1))
    for col in ("checked_by", "band_ok", "feeder_name_ok", "location_ok", "streets_ok",
                "min_hours_ok", "notes"):
        s[col] = ""
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="also write docs/T1_SAMPLE.csv")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--reuse", action="store_true", help="reuse the cached page reads (skip OCR)")
    args = ap.parse_args()
    cache = WORK / "nerc_read_cache.pkl"
    if args.reuse and cache.exists():
        pages = pickle.loads(cache.read_bytes())
    else:
        paths = render_all()
        pages = read_all(paths, args.workers)
        cache.write_bytes(pickle.dumps(pages))
    df_rows, df_short, df_raw = assemble(pages)
    WORK.mkdir(parents=True, exist_ok=True)
    df_rows.to_parquet(WORK / "nerc_rows.parquet", index=False)
    df_short.to_parquet(WORK / "nerc_shortfalls.parquet", index=False)
    df_raw.to_parquet(WORK / "nerc_raw.parquet", index=False)
    log = {
        "pages": [{k: v for k, v in pg.items() if k != "records"} | {"records": len(pg["records"])}
                  for pg in sorted(pages, key=lambda d: (d["stem"], d["page"]))],
        "coverage": coverage(df_rows, df_raw),
        "rows": len(df_rows), "shortfalls": len(df_short),
    }
    (WORK / "nerc_build_log.json").write_text(json.dumps(log, indent=1))
    if args.sample:
        draw_t1_sample(df_rows).to_csv(ROOT / "docs" / "T1_SAMPLE.csv", index=False)
    print(f"rows {len(df_rows)}, shortfalls {len(df_short)}")
    print(df_rows.groupby("disco").size().to_string())


if __name__ == "__main__":
    main()
