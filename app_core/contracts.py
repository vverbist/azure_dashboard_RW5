"""Effective-dated official commercial terms and Official-vs-Scenario classification
(roadmap Phase 0.5).

The dashboard supports both official contract reporting and user what-if scenarios. Official
Greenchoice terms are stored here with effective dates; when the active controls match the
effective terms the result is labelled "Official", otherwise "Scenario". The strike price is
always a user scenario (decision D2), never an official contract term.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class GreenchoiceTerms:
    afslag_pct: float          # percentage number: 17 == 17%
    afslag_floor: float        # EUR/MWh
    gvo_value: float           # EUR/MWh
    effective_from: date
    effective_to: date | None = None  # None = open-ended


# PROVISIONAL official Greenchoice terms — these mirror the current app defaults and MUST be
# confirmed (values and effective dates) with the commercial owner before derived figures are
# treated as official KPIs. One fixed set applies across the covered period (decision D2).
OFFICIAL_GREENCHOICE_TERMS: list[GreenchoiceTerms] = [
    GreenchoiceTerms(
        afslag_pct=17.0,
        afslag_floor=10.0,
        gvo_value=0.0,
        effective_from=date(2026, 1, 1),
    ),
]

_TOLERANCE = 1e-9


def official_terms_on(day: date) -> GreenchoiceTerms | None:
    for terms in OFFICIAL_GREENCHOICE_TERMS:
        if terms.effective_from <= day and (terms.effective_to is None or day <= terms.effective_to):
            return terms
    return None


def default_official_day() -> date:
    return min(terms.effective_from for terms in OFFICIAL_GREENCHOICE_TERMS)


def _close(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= _TOLERANCE


def greenchoice_basis(
    afslag_pct: float,
    afslag_floor: float,
    gvo_value: float,
    on_day: date | None = None,
) -> dict:
    """Classify the active Greenchoice inputs as Official or Scenario versus the effective
    contract terms, listing any differences. `afslag_pct` is a percentage number (17 == 17%)."""
    terms = official_terms_on(on_day or default_official_day())
    if terms is None:
        return {"basis": "Scenario", "official": None, "differences": ["No official terms are defined for this period."]}

    differences = []
    if not _close(afslag_pct, terms.afslag_pct):
        differences.append(f"Afslag {afslag_pct:g}% vs official {terms.afslag_pct:g}%")
    if not _close(afslag_floor, terms.afslag_floor):
        differences.append(f"Floor €{afslag_floor:g} vs official €{terms.afslag_floor:g}")
    if not _close(gvo_value, terms.gvo_value):
        differences.append(f"GvO €{gvo_value:g} vs official €{terms.gvo_value:g}")

    return {
        "basis": "Official" if not differences else "Scenario",
        "official": {
            "afslag_pct": terms.afslag_pct,
            "afslag_floor": terms.afslag_floor,
            "gvo_value": terms.gvo_value,
            "effective_from": terms.effective_from.isoformat(),
            "effective_to": terms.effective_to.isoformat() if terms.effective_to else None,
        },
        "differences": differences,
    }


def commercial_basis(
    afslag_pct: float,
    afslag_floor: float,
    gvo_value: float,
    on_day: date | None = None,
) -> dict:
    """Basis for each commercial diagnostic: Greenchoice (Official/Scenario) and strike
    (always Scenario)."""
    return {
        "greenchoice": greenchoice_basis(afslag_pct, afslag_floor, gvo_value, on_day),
        "strike": {"basis": "Scenario"},
    }
