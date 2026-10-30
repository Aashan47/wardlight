"""The cold-chain answer per facility: today's uptime under equipment scenarios, and the cheapest fix that meets
the target.

Today (equipment per facility is unknown, so three stated scenarios):
  (a) a PQS mains ice-lined fridge (holdover from the PQS sheets, an upper bound);
  (b) a domestic or non-PQS fridge (4 h, range 1.5 to 6 h, NIST lab test): the HEADLINE "today";
  (c) no fridge: vaccines come from an outreach carrier. Not modelled, stated.

Fixes, cheapest first among those meeting the target (technical uptime, 5th percentile >= target):
  (i)   a PQS mains ice-lined fridge on the grid the facility has (needs a known grid supply);
  (ii)  a PQS solar direct-drive fridge (works without grid);
  (iii) (ii) plus the separate clinic system, where the facility has no grid at all (off-grid tier): nothing else
        can power the delivery room at night. The clinic system is always its own optional line with its own
        cost and is never in the cold-chain price.
The target is applied to technical uptime because no purchase fixes breakdowns; reported uptimes carry the
availability scenario. Prices: PQS product sheets (EXW, base year as printed; exclude freight, installation and,
for Haier units, the voltage regulator). Fridge cost per month = price / (10-year life x 12), undiscounted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import constants as C
from . import econ as E
from . import fridge as F
from . import sim as SM

ILR_FIX_MODELS = ("E003-089e", "E003-088e", "E003-087e", "E003-097e")  # priced PQS ice-lined units
SDD_FIX_MODELS = ("E003-040e", "E003-048e")  # priced, usable PQS SDD units
FIX_LABEL = {
    "i": "PQS mains ice-lined fridge on the existing grid",
    "ii": "PQS solar direct-drive fridge",
    "iii": "PQS solar direct-drive fridge, plus the separate clinic system (no grid at the facility)",
    "none": "no listed fix meets the target; the best option is shown",
}


@dataclass
class FixOption:
    fix: str  # "i" or "ii"
    code: str
    name: str
    uptime: SM.Interval  # with availability scenario (reported)
    uptime_technical: SM.Interval
    capex_usd: E.Range
    meets_target: bool
    array_kwp: float | None = None


@dataclass
class ColdChain:
    today_b_domestic: SM.Interval | None
    today_a_pqs: SM.Interval | None
    today_b_technical: SM.Interval | None
    category: str
    chosen: FixOption
    options: list[FixOption]
    target: float
    target_met: bool
    capex_ngn: E.Range
    monthly_cost_ngn: E.Range
    label: str

    def to_dict(self) -> dict:
        return asdict(self)


def fix_monthly_cost_ngn(capex_usd: E.Range) -> E.Range:
    return E.to_ngn(capex_usd) * (1.0 / (C.FRIDGE_LIFE_YEARS.value * 12.0))


def assess(pp: SM.Prepared, offgrid: bool, cfg: SM.SimConfig = SM.SimConfig(), target: float = 0.99) -> ColdChain:
    dom, _ = SM.domestic_on_grid(pp)
    pqs, _ = SM.ilr_on_grid(pp, cfg.fridge_today, cfg.thermal)
    opts: list[FixOption] = []
    if pp.known and not offgrid:
        for code in ILR_FIX_MODELS:
            u, _ = SM.ilr_on_grid(pp, code, cfg.thermal)
            m = F.CATALOGUE[code]
            opts.append(FixOption("i", code, m.name, u.available, u.technical, E.fridge_capex_usd(m),
                                  u.technical.lo >= target))
    for code in SDD_FIX_MODELS:
        u, _, arr = SM.sdd_fridge(pp, code)
        m = F.CATALOGUE[code]
        opts.append(FixOption("ii", code, m.name, u.available, u.technical, E.fridge_capex_usd(m),
                              u.technical.lo >= target, arr))
    ok = sorted([o for o in opts if o.meets_target], key=lambda o: o.capex_usd.point)
    if ok:
        chosen, met = ok[0], True
        category = "iii" if (chosen.fix == "ii" and offgrid) else chosen.fix
    else:
        chosen = max(opts, key=lambda o: (o.uptime_technical.lo, -o.capex_usd.point))
        met, category = False, "none"
    return ColdChain(dom.available if dom else None, pqs.available if pqs else None,
                     dom.technical if dom else None, category, chosen, opts, target, met,
                     E.to_ngn(chosen.capex_usd), fix_monthly_cost_ngn(chosen.capex_usd), FIX_LABEL[category])
