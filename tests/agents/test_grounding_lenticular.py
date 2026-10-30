from agents import grounding as G


def test_lenticular_citations_glued_to_numbers_are_split_and_matched():
    pool = ['{"budget_ngn": 80000000, "spent_ngn": 79086656.08, "funded": 68}']
    rep = G.check("Budget N80,000,000【S1】, spent N79,086,656.08【S1†L4-L6】, 68【S1】 clinics.", pool, ["S1"])
    assert rep.ok, (rep.unmatched, rep.unknown_tokens, rep.bad_citations)
    assert rep.citations_used == ["S1"]


def test_normalise_keeps_unmatched_numbers_blocked():
    pool = ['{"funded": 68}']
    rep = G.check("Fund 69【S1】 clinics.", pool, ["S1"])
    assert not rep.ok


def test_non_ascii_hyphen_ranges():
    assert G.normalise("1‑5") == "1-5"


def test_nbsp_thousands_separators_rejoin():
    pool = ['{"spent_ngn": 79086656.08, "budget_ngn": 80000000}']
    rep = G.check("Spent N79 086 656.08 of N80 000 000 [S1].", pool, ["S1"])
    assert rep.ok, ([c.text for c in rep.unmatched], rep.unknown_tokens)
