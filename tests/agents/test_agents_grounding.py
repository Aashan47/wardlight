import pytest

from agents.grounding import ToolPool, check, extract, numbers_in

TOOLS = [{
    "budget_ngn": 80000000, "spent_ngn": 79612345.6, "remaining_ngn": 387654.4, "uptime": 0.9314,
    "funded_count": 5, "benefit_total": 9136.51, "capex_usd": 12056.25, "cite": "S1",
    "unique_id": "SN_BEFC69FA4D", "order_file": "AEDC_HOLDCO_YSS_September_2026_088.pdf", "month": "2026-09",
    "reason": "12,271 doses/yr protected for N1,163,039 (10,550.8 per N1m); fridge held 0% of days today, 94% with the fix",
    "range_c": [2, 8], "model": "E003-040e", "negative": -0.004,
}]
CITES = {"S1", "S2"}


def ok(text, tools=TOOLS, cites=CITES, **kw):
    return check(text, tools, cites, **kw)


# ---------------------------------------------------------------- formats that must pass


@pytest.mark.parametrize("text", [
    "Budget N80 million [S1].",
    "Budget N80m [S1].",
    "Budget NGN 80,000,000 [S1].",
    "Budget ₦80,000,000 [S1].",
    "Budget 80 million naira [S1].",
    "Spent N79.6m of N80m [S1].",
    "Spent N79,612,346 [S1].",
    "Spent N79,612,345.6 [S1].",
    "Spent about N79.61 million [S1].",
    "Uptime 93% [S1].",
    "Uptime 93.1% [S1].",
    "Uptime 93 percent [S1].",
    "Uptime 93 per cent [S1].",
    "Uptime 0.93 [S1].",
    "Capex US$12,056 [S1].",
    "Capex $12k [S1].",
    "Capex USD 12,056.25 [S1].",
    "Five facilities funded [S1].",
    "five facilities funded [S1].",
    "Gain of 9,137 doses [S1].",
    "Gain of 9.1k doses [S1].",
    "Held between 2 and 8 °C [S1].",
    "Held at 2-8 °C [S1].",
    "Held at 2–8 °C [S1].",
    "Facility SN_BEFC69FA4D [S1].",
    "Model E003-040e [S1].",
    "Order AEDC_HOLDCO_YSS_September_2026_088.pdf [S1].",
    "The September 2026 order [S1].",
    "The 2026-09 order [S1].",
    "**N80,000,000** (budget) [S1]",
    "Coefficient -0.004 [S1].",
    "Ranked 5th [S1].",
    "1. first\n2. second\n3. third [S1]",
    "| a | b |\n|---|---|\n| 93% | N80m |\n[S1]",
    "Spent 79.6 million [S1][S2].",
    "Spent 79.6 million [S1, S2].",
    "No numbers here, and none needed.",
])
def test_grounded_formats_pass(text):
    r = ok(text)
    assert r.ok, r.problems()


def test_rounding_at_written_precision():
    assert ok("Spent N80 million [S1].").ok  # 79.6m rounds to 80m at the written precision
    assert ok("Spent N16,300,000 [S1].", [{"x": 16304523}]).ok  # trailing zeros, within 1%
    assert not ok("Spent N16,000,000 [S1].", [{"x": 16304523}]).ok  # trailing zeros but 1.9% off
    assert not ok("Spent N79.5 million [S1].").ok  # one decimal written: must be within 0.05m
    assert ok("Uptime 100% [S1].", [{"u": 0.9996}]).ok
    assert not ok("Uptime 99% [S1].", [{"u": 0.9996}]).ok


# ---------------------------------------------------------------- what must block


@pytest.mark.parametrize("text,bad", [
    ("Budget N81 million [S1].", "81"),
    ("Uptime 94.5% [S1].", "94.5%"),
    ("Uptime 95% [S1].", "95%"),
    ("Reaches 987,654 children [S1].", "987,654"),
    ("Saves N1.2bn [S1].", "1.2bn"),
    ("Saves 3 billion naira [S1].", "3"),
    ("Six facilities funded [S1].", "Six"),
    ("Ninety million naira [S1].", "Ninety million"),
    ("Capex US$13,000 [S1].", "13,000"),
    ("Held at 2-9 °C here [S1].", None),
    ("12kWh per day [S1].", "12kWh"),
    ("about 7 doses [S1].", "7"),
    ("4. first\n7. second [S1]", "7"),
])
def test_ungrounded_numbers_block(text, bad):
    pool = [{k: v for k, v in TOOLS[0].items() if k not in ("order_file", "month")}]
    r = ok(text, pool)
    assert not r.ok
    if bad:
        assert any(bad in p for p in r.problems()), r.problems()


@pytest.mark.parametrize("text", [
    "Facility SN_BEFC69FA4X [S1].",  # one character changed in an id
    "Model E003-041e [S1].",
    "Fridge VC250SDD [S1].",
    "Order AEDC_HOLDCO_YSS_October_2026_099.pdf [S1].",
])
def test_unknown_identifiers_block(text):
    r = ok(text)
    assert not r.ok and r.unknown_tokens, r.problems()


def test_invented_and_missing_citations():
    assert not ok("Budget N80m [S9].").ok  # citation not in the session
    r = ok("Budget N80m.")
    assert not r.ok and r.missing_citation
    assert ok("Budget N80m.", require_citation=False).ok


def test_adversarial_disguises():
    # a number hidden behind punctuation or glued to text still gets checked
    for text in ["(N81m) [S1]", "~81% [S1]", "≈81 [S1]", "*81* [S1]", "x81 [S1]", "N81million [S1]",
                 "81st [S1]", "8,1 [S1]"]:
        assert not ok(text).ok, text
    # a list that does not count 1, 2, 3 is not treated as list markers
    assert not ok("2. only item [S1]", [{"a": 5}]).ok
    # a number inside a markdown link label still counts
    assert not ok("[N81m](http://x) [S1]").ok


def test_extract_values_and_percent_flags():
    claims, unknown, cites = extract("N80 million, 93%, US$12k, twenty-five, 2–8 [S1]")
    vals = [(c.value, c.percent) for c in claims]
    assert (80e6, False) in vals and (93.0, True) in vals and (12e3, False) in vals and (25, False) in vals
    assert (2.0, False) in vals and (8.0, False) in vals
    assert cites == ["S1"] and unknown == []


def test_pool_reads_json_strings_and_nested_values():
    pool = ToolPool(['{"a": {"b": [1.5, "N2,000,000 spent"]}}', "plain text 42 h"])
    assert {1.5, 2e6, 42.0} <= set(pool.values)
    assert check("1.5 and N2m and 42 hours [S1]", pool, {"S1"}).ok


def test_nan_inf_and_bools_are_not_numbers():
    pool = ToolPool([{"x": float("nan"), "y": float("inf"), "z": True}])
    assert pool.values == []
    assert not check("1 [S1]", pool, {"S1"}).ok


def test_numbers_in_for_sms():
    assert numbers_in("about 9 hours") == [9.0]
    assert numbers_in("between 6 and 8") == [6.0, 8.0]
    assert numbers_in("nine hours") == [9.0]


def test_report_counts():
    r = ok("N80m and 93% and N81m [S1]")
    assert r.n_total == 3 and r.n_traced == 2
    d = r.to_dict()
    assert d["unmatched"] == ["N81m"] and not d["ok"]
    assert "GROUNDING CHECK FAILED" in r.retry_message()
