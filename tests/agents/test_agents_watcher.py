import json

import pandas as pd
import synth
from agent_markers import needs_naija

from agents import events as EV
from agents import watcher as W


def caps():
    """SYNTHETIC caps rows: feeder f1 (linked to the test NERC row sn7) moves B to D; f2 unchanged; f3 (Kano unit)
    moves A to E; f4 only in the new month."""
    rows = [
        ("f1", "KEDCO", "KANO", "2026-09", "B", "11KV TEST ONE", "GWALE"),
        ("f1", "KEDCO", "KANO", "2026-10", "D", "11KV TEST ONE", "GWALE"),
        ("f2", "KEDCO", "KANO", "2026-09", "E", "11KV TEST TWO", "GWALE"),
        ("f2", "KEDCO", "KANO", "2026-10", "E", "11KV TEST TWO", "GWALE"),
        ("f3", "KEDCO", "KANO", "2026-09", "A", "11KV OTHER", "FAGGE"),
        ("f3", "KEDCO", "KANO", "2026-10", "E", "11KV OTHER", "FAGGE"),
        ("f4", "KEDCO", "KANO", "2026-10", "C", "11KV NEW", "FAGGE"),
    ]
    c = pd.DataFrame(rows, columns=["feeder_id", "disco", "state", "order_month", "band", "feeder_raw",
                                    "business_unit"])
    c["source_file"] = "test.pdf"
    c["source_page"] = "1"
    return c


def data_with_unit():
    fac, m, r, n, bh = synth.frames()
    m = m.copy()
    m.loc[m.unique_id == "T4", ["tier", "bands", "evidence"]] = [
        "c_unit_mixture", json.dumps({"C": 0.25, "D": 0.25, "E": 0.5}),
        json.dumps({"order_month": "2026-10", "unit": "state Kano",
                    "band_counts": {"A": 0, "B": 0, "C": 1, "D": 1, "E": 2}})]
    from agents.tools import WardlightData

    return WardlightData(facilities=fac, matches=m, results=r, nerc_rows=n, band_history=bh)


def stub_sim(lat, lon, bands, n_draws=16):
    bad = bands.get("D", 0) + bands.get("E", 0) if isinstance(bands, dict) else 1
    return {"fix_category": "ii" if bad >= 0.5 else "i", "today_domestic": {"point": 1 - bad, "lo": 0, "hi": 1},
            "today_pqs_ice_lined": {"point": 0.9, "lo": 0.8, "hi": 1}}


def test_diff_counts_only_real_changes():
    ch, counts = W.diff_months(caps(), "2026-09", "2026-10")
    assert sorted(ch.feeder_id) == ["f1", "f3"]
    assert counts == {"listed_old": 3, "listed_new": 4, "listed_both": 3, "changed": 2, "added": 1, "dropped": 0}


def test_link_by_exact_normalised_name():
    ch, _ = W.diff_months(caps(), "2026-09", "2026-10")
    ln = W.link_nerc(ch, synth.data().nerc_rows)
    f1 = ln[ln.feeder_id == "f1"].iloc[0]
    assert f1.linked and f1.row_keys == [f"{synth.ROW}#p3#sn7"] and f1.nerc_band == "B"
    assert not ln[ln.feeder_id == "f3"].iloc[0].linked


def test_votes_move_and_status():
    d = data_with_unit()
    ch, _ = W.diff_months(caps(), "2026-09", "2026-10")
    ch = W.link_nerc(ch, d.nerc_rows)
    aff, meta = W.affected_facilities(ch, d, caps(), "2026-09", "2026-10")
    a = aff.set_index("unique_id")
    # T1: one row (sn7, stored band B): old keeps B, new moves the whole vote to D; Wardlight shows the old band
    assert a.loc["T1", "bands_old"] == {"B": 1.0} and a.loc["T1", "bands_new"] == {"D": 1.0}
    assert a.loc["T1", "wardlight_status"] == "stale"
    # T3: two rows (sn7 B, sn9 D), equal votes: new mixture D only
    assert a.loc["T3", "bands_new"] == {"D": 1.0} and a.loc["T3", "bands_old"] == {"B": 0.5, "D": 0.5}
    # T4: Kano unit mixture recomputed for September (f1 B, f2 E, f3 A) against the stored October one
    assert a.loc["T4", "via"] == "unit_mixture"
    assert a.loc["T4", "bands_old"] == {"A": 0.3333, "B": 0.3333, "E": 0.3333}
    assert a.loc["T4", "wardlight_status"] == "current"
    assert "T2" not in a.index  # its feeder did not change


def test_report_events_and_files(tmp_path):
    d = data_with_unit()
    rec = W.run("2026-09", "2026-10", data=d, caps=caps(), out_dir=tmp_path, simulate=stub_sim,
                point=lambda la, lo: (round(la), round(lo)))
    evs = rec["events"]
    assert EV.validate(evs) == []
    assert [e["id"] for e in evs if e["type"] == "step_start"] == ["diff", "link", "affected", "rerun", "report"]
    chk = next(e for e in evs if e["type"] == "check")
    assert chk["ok"], chk["unmatched"]
    t = rec["report"]["totals"]
    assert t["changed"] == 2 and t["linked"] == 1 and t["facilities_affected"] == 3 and t["facilities_rerun"] == 3
    assert t["fix_changed"] >= 1
    md = (tmp_path / "band_changes_2026-09_to_2026-10.md").read_text()
    assert "11KV TEST ONE (KEDCO, KANO): Band B to Band D" in md and "\u2014" not in md
    assert json.loads((tmp_path / "band_changes_2026-09_to_2026-10.json").read_text())["totals"] == t


def test_missing_month_is_an_error_event():
    evs = list(W.run_events("2019-01", "2026-10", data=synth.data(), caps=caps()))
    assert EV.validate(evs) == [] and any(e["type"] == "error" for e in evs)


@needs_naija
def test_real_september_to_october_diff():
    from agents.tools import WardlightData

    c = W.load_caps()
    ch, counts = W.diff_months(c, "2026-09", "2026-10")
    assert counts["changed"] == len(ch) > 0
    assert (ch.band_old != ch.band_new).all()
    ln = W.link_nerc(ch, WardlightData().nerc_rows)
    assert ln.linked.any()
