"""Loads the pinned rule set (``ruleset/v<version>/``) into typed, Decimal-valued models.

``RULESET.md`` is the authority; ``rules.yaml`` is its machine-readable rate tables.
``tests/test_ruleset.py`` checks the two agree. ``Ruleset.fingerprint`` hashes both
files and is recorded in every result file, so results are never silently compared
across rule-set versions.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_VERSION = "1.0"

_REPO_RULESET_ROOT = Path(__file__).resolve().parent.parent / "ruleset"
_PACKAGED_RULESET_ROOT = Path(__file__).resolve().parent / "_ruleset"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Cited(_Frozen):
    """A single rate-table value and the clause that defines it."""

    value: Decimal
    clause: str


class Band(_Frozen):
    lower: Decimal
    upper: Decimal | None
    rate: Decimal


class Brackets(_Frozen):
    clause: str
    bands: tuple[Band, ...]


class RateTable(_Frozen):
    personal_allowance: Cited
    brackets: Brackets
    si_employee_rate: Cited
    si_employer_rate: Cited
    si_ceiling: Cited
    pension_rate: Cited
    meal_exemption: Cited
    non_resident_rate: Cited | None = None


class Jurisdiction(_Frozen):
    name: str
    currency: str
    minor_unit: Decimal
    day_count: Literal["calendar", "working"]
    required_inputs: tuple[str, ...]
    unused_inputs: tuple[str, ...]
    january_unused_inputs: tuple[str, ...] = ()
    si_ceiling_basis: Literal["monthly", "annual_cumulative"]
    si_deductible_from_tax: bool
    tax_method: Literal["monthly_brackets", "annualised_brackets"]
    tables: dict[int, RateTable]


class FxTable(_Frozen):
    clause: str
    rates: dict[int, dict[str, Decimal]]


class Ruleset(_Frozen):
    ruleset_id: str
    version: str
    jurisdictions: dict[str, Jurisdiction]
    fx: FxTable
    fingerprint: str = ""

    def table(self, jurisdiction: str, year: int) -> RateTable | None:
        """The rate table for a calendar year (GEN-§4.1), or None if there is none (GEN-§4.2)."""
        return self.jurisdictions[jurisdiction].tables.get(year)

    def fx_rate(self, from_currency: str, to_currency: str, year: int) -> Decimal | None:
        """Month-end FX rate for the pair in that year (FX-§1.1), or None if unsupported (GEN-§8.2)."""
        return self.fx.rates.get(year, {}).get(f"{from_currency}->{to_currency}")


def ruleset_dir(version: str = DEFAULT_VERSION) -> Path:
    for root in (_REPO_RULESET_ROOT, _PACKAGED_RULESET_ROOT):
        candidate = root / f"v{version}"
        if (candidate / "rules.yaml").is_file():
            return candidate
    raise FileNotFoundError(f"rule set v{version} not found under {_REPO_RULESET_ROOT} or {_PACKAGED_RULESET_ROOT}")


@lru_cache(maxsize=4)
def load_ruleset(version: str = DEFAULT_VERSION) -> Ruleset:
    directory = ruleset_dir(version)
    prose = (directory / "RULESET.md").read_bytes()
    tables = (directory / "rules.yaml").read_bytes()
    data = yaml.safe_load(tables)
    if str(data.get("version")) != version:
        raise ValueError(f"rules.yaml declares version {data.get('version')!r}, expected {version!r}")
    fingerprint = hashlib.sha256(prose + b"\0" + tables).hexdigest()[:16]
    return Ruleset.model_validate({**data, "fingerprint": fingerprint})
