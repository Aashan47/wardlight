import pytest
from agent_markers import needs_engine_data

from agents import events as EV
from agents import verifier as V
from agents.llm import ScriptedModel, assistant, tool_call

FAC = V.Facility("T3", "Gamma PHC", 12.0, 8.5, "c_lga_mixture", {"A": 0.5, "E": 0.5})


def fake_sim(lat, lon, bands, n_draws=16):
    """Stub engine for the band model: Band A lanes hold better than Band E lanes; the mixture sets the interval."""
    wa = bands.get("A", 0.0) if isinstance(bands, dict) else 0.0
    lo, hi = 0.05 + 0.5 * wa, 0.30 + 0.6 * wa
    return {"today_pqs_ice_lined": {"point": 0.9, "lo": 0.8, "hi": 0.99},
            "today_domestic": {"point": (lo + hi) / 2, "lo": lo, "hi": hi},
            "solar_direct_drive": {"point": 0.95, "lo": 0.9, "hi": 0.98},
            "fix_label": "PQS solar direct-drive fridge", "fix_category": "ii"}


def fake_hours(lat, lon, hours, sd, n_draws=16):
    """Stub engine for an observed day: a tight supply gives a tight interval centred by the hours."""
    c = hours / 24
    return {"today_pqs_ice_lined": {"point": 0.9, "lo": 0.85, "hi": 0.95},
            "today_domestic": {"point": c, "lo": max(0, c - 0.05), "hi": min(1, c + 0.05)},
            "solar_direct_drive": {"point": 0.95, "lo": 0.9, "hi": 0.98},
            "fix_label": "PQS mains ice-lined fridge on the existing grid", "fix_category": "i"}


def fake_pred(bands, hours, sd):
    """Stub prior predictive: share of the mixture whose promise is at least the reported hours."""
    if bands is None:
        return None
    if bands == "OFFGRID":
        return 1.0 if hours <= sd else 0.0
    promise = {"A": 20, "B": 16, "C": 12, "D": 8, "E": 4}
    return sum(w for b, w in bands.items() if promise[b] + sd >= hours) * 0.5


STUBS = {"simulate": fake_sim, "simulate_hours": fake_hours, "predictive": fake_pred}


def session(fac=FAC, **kw):
    return V.VerifierSession(fac, **STUBS, **kw)


def widths(s):
    return [st["interval"]["width"] for st in s.steps if st["interval"]]


# ---------------------------------------------------------------- parsers


@pytest.mark.parametrize("text,val", [("1", "ice_lined"), (" 2 ", "solar"), ("3.", "household"), ("4", "none"),
                                      ("ice lined", "ice_lined"), ("We use SOLAR", "solar"),
                                      ("household fridge", "household"), ("no fridge", "none")])
def test_parse_fridge(text, val):
    p = V.parse_fridge(text)
    assert p.status == "ok" and p.value == val


@pytest.mark.parametrize("text", ["1 or 2", "solar and household", "5", "12"])
def test_parse_fridge_ambiguous(text):
    assert V.parse_fridge(text).status == "ambiguous"


def test_parse_fridge_free_text_is_unparsed():
    assert V.parse_fridge("the blue one UNICEF brought").status == "unparsed"


@pytest.mark.parametrize("text,val", [("9", 9.0), ("about 9 hours", 9.0), ("nine hours", 9.0), ("0", 0.0),
                                      ("no light at all", 0.0), ("all day", 24.0), ("12hrs", 12.0)])
def test_parse_hours(text, val):
    p = V.parse_hours(text)
    assert p.status == "ok" and p.value == val


@pytest.mark.parametrize("text", ["6 to 8", "between 6 and 8", "30", "6-8"])
def test_parse_hours_ambiguous(text):
    assert V.parse_hours(text).status == "ambiguous"


def test_parse_typical():
    assert V.parse_typical("1").value == "yes" and V.parse_typical("no").value == "no"
    assert V.parse_typical("skip").value == "skip" and V.parse_typical("maybe").status == "unparsed"


def test_questions_fit_one_sms():
    assert all(len(q) <= V.MAX_SMS for q in [*V.QUESTIONS.values(), *V.REASK.values()])


# ---------------------------------------------------------------- band update


def test_hours_never_become_a_band_promise():
    s = session()
    s.start()
    s.handle("3")
    s.handle("9")
    assert s.observed_hours == 9.0 and "reported 9 h" in s.current["supply"]
    assert s.current["bands"] == '{"A": 0.5, "E": 0.5}'  # the matched mixture is kept as the prior, never reweighted
    # the stub's observed-hours model was used, not the Band A promise
    assert s.current["sim"]["today_domestic"]["point"] == fake_hours(0, 0, 9, 2)["today_domestic"]["point"]
    assert "20" not in s.current["supply"]


# ---------------------------------------------------------------- the state machine


def test_full_flow_narrows_the_interval_and_events_are_valid():
    s = session()
    evs = s.start()
    assert s.outbox == V.QUESTIONS["fridge"]
    evs += s.handle("3")
    assert s.outbox == V.QUESTIONS["grid_hours"]
    evs += s.handle("9 hours")
    evs += s.handle("1")
    assert s.finished and s.outbox is None
    assert EV.validate(evs) == []
    ans = next(e for e in evs if e["type"] == "answer")
    b, a = ans["totals"]["before"], ans["totals"]["after"]
    assert b["width"] > a["width"] and ans["totals"]["narrowed_by"] == pytest.approx(b["width"] - a["width"])
    assert a["scenario"] == V.FRIDGE_LABEL["household"]
    assert ans["totals"]["supply_after"].startswith("reported 9 h")
    assert V.LABEL in ans["markdown"]
    chk = next(e for e in evs if e["type"] == "check")
    assert chk["ok"] and chk["numbers_checked"] > 0
    # an ask_clinic call stays open until the reply arrives, then its result carries the parsed reply
    asks = [e for e in evs if e["type"] == "tool_call" and e["name"] == "ask_clinic"]
    assert len(asks) == 3
    assert [e["type"] for e in evs][-1] == "done" and evs[-1]["recorded"] is False


def test_interval_never_widens_for_consistent_answers():
    for fridge in ("1", "2", "3"):
        for hours in ("4", "9", "12"):
            s = session()
            s.start()
            s.handle(fridge)
            s.handle(hours)
            w = widths(s)
            assert all(b <= a + 1e-12 for a, b in zip(w, w[1:])), (fridge, hours, w)
            assert not any(st["widened"] for st in s.steps)


def test_contradicting_reply_is_said_in_the_event():
    fac = V.Facility("Z", "Zeta", 1, 1, "a_named", {"E": 1.0})  # promise 4 h
    s = session(fac)
    evs = s.start() + s.handle("3") + s.handle("20")
    res = [e for e in evs if e["type"] == "tool_result" and e.get("contradicts_prior") is not None]
    last = res[-1]
    assert last["contradicts_prior"] is True and last["prior_predictive"] < V.CONTRADICTION_P
    assert any("contradicts the prior" in n for n in s.notes)
    if last["widened"]:
        assert "contradicts" in last["note"]


def test_every_widening_carries_a_reason():
    s = session()
    evs = s.start() + s.handle("3") + s.handle("9") + s.handle("2")  # not a usual day: evidence withdrawn
    for e in evs:
        if e["type"] == "tool_result" and e.get("widened"):
            assert e["note"].startswith("the interval widened because") or "contradicts" in e["note"]
    assert s.steps[-1]["widened"] and "withdrawn" in s.steps[-1]["note"]


def test_reask_once_then_unknown():
    s = session()
    s.start()
    s.handle("1 or 2")
    assert s.outbox == V.REASK["fridge"] and s.field == "fridge"
    s.handle("maybe both")
    assert s.answers["fridge"] is None and s.field == "grid_hours"
    assert any("re-ask" in n for n in s.notes)


def test_unusual_day_withdraws_the_hours_reply():
    s = session()
    s.start()
    s.handle("3")
    s.handle("9")
    assert s.observed_hours == 9.0
    s.handle("2")
    assert s.observed_hours is None and any("not a usual day" in n for n in s.notes)


def test_no_fridge_has_no_interval():
    s = session()
    for r in ("4", "9", "0"):
        (s.start() if not s.log.events else None)
        s.handle(r)
    assert s.current["interval"] is None
    assert "no vaccine fridge" in [e for e in s.log.events if e["type"] == "answer"][0]["markdown"]


def test_refused_facility_does_not_model_hours_and_offgrid_report_contradicts():
    s = session(V.Facility("X", "X", 1, 1, "d_refused", None))
    s.start()
    s.handle("3")
    s.handle("6")
    assert s.observed_hours is None and any("unknown" in n for n in s.notes)
    s = session(V.Facility("Y", "Y", 1, 1, "offgrid", "OFFGRID"))
    s.start()
    s.handle("3")
    s.handle("6")
    assert s.steps[-1]["contradicts_prior"] is True


# ---------------------------------------------------------------- free text through the model


def extractor(value, quote, text=None):
    m = ScriptedModel([assistant(text, [tool_call("record_answer", {"value": value, "quote": quote}, "r")])])
    return V.ModelExtractor(m)


def test_model_reads_free_text_when_grounded():
    s = session(extractor=extractor(2, "plates on the roof feed it", "The reply describes a solar unit."))
    evs = s.start() + s.handle("UNICEF brought it, plates on the roof feed it")
    assert s.answers["fridge"] == "solar"
    res = [e for e in evs if e["type"] == "tool_result" and e.get("parsed_by") == "model"]
    assert res and res[0]["quote"] == "plates on the roof feed it"
    assert [e["text"] for e in evs if e["type"] == "reasoning"] == ["The reply describes a solar unit."]


def test_model_answer_rejected_when_quote_not_in_reply():
    s = session(extractor=extractor(2, "solar panels"))
    s.start()
    s.handle("the blue one UNICEF brought")
    assert s.outbox == V.REASK["fridge"]


def test_model_hours_must_appear_in_the_quote():
    p = extractor(10, "since morning")("grid_hours", "light came since morning")
    assert p.status == "ambiguous"
    p = extractor(7, "about 7 hours")("grid_hours", "it came for about 7 hours")
    assert p.status == "ok" and p.value == 7.0 and p.by == "model"


def test_ussd_flow():
    assert V.ussd(FAC, "", **STUBS).startswith("CON " + V.QUESTIONS["fridge"][:20])
    assert V.ussd(FAC, "3", **STUBS) == "CON " + V.QUESTIONS["grid_hours"]
    end = V.ussd(FAC, "3*9*1", **STUBS)
    assert end.startswith("END ") and "sandbox" in end


@needs_engine_data
def test_real_engine_session():
    from agents.tools import Toolbox

    tb = Toolbox()
    t = tb.data.table
    uid = t[(t.match_tier == "c_lga_mixture") & t.has_result].iloc[0].unique_id
    s = V.VerifierSession(V.facility_from_data(tb.data, uid), n_draws=4)
    evs = s.start() + s.handle("3") + s.handle("9") + s.handle("1")
    assert EV.validate(evs) == []
    ans = next(e for e in evs if e["type"] == "answer")
    assert ans["totals"]["before"] is not None
    assert next(e for e in evs if e["type"] == "check")["ok"]
    # consistent answers on the real engine: no step widens unless the event says the reply contradicts the prior
    for st in s.steps:
        assert not st["widened"] or st["contradicts_prior"], st


@needs_engine_data
def test_real_engine_nine_hours_is_not_band_a():
    from agents import engine_adapter as EA

    lat, lon = 8.58, 5.18
    obs = EA.coldchain_observed_hours(lat, lon, 9, 2.0, n_draws=4)
    band_a = EA.coldchain(lat, lon, {"A": 1.0}, n_draws=4)
    assert obs["supply_observed"] == {"hours": 9.0, "sd": 2.0}
    # a domestic fridge on about 9 h of grid fares far worse than on a Band A (20 h) promise
    assert obs["today_domestic"]["hi"] < band_a["today_domestic"]["lo"] or \
        obs["today_domestic"]["point"] < band_a["today_domestic"]["point"]
