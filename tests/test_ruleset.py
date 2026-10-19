"""The structured tables (rules.yaml) must match the prose authority (RULESET.md) exactly.

These tests parse the Markdown rate tables in RULESET.md independently of rules.yaml
and compare every value, so a change to one without the other fails CI.
"""

import re
from decimal import Decimal

import pytest

from paygym.ruleset import load_ruleset, ruleset_dir

RS = load_ruleset("1.0")
PROSE = (ruleset_dir("1.0") / "RULESET.md").read_text()

ROW_KEYS = {
    "personal allowance": "personal_allowance",
    "brackets": "brackets",
    "non-resident flat rate": "non_resident_rate",
    "social insurance employee rate": "si_employee_rate",
    "social insurance employer rate": "si_employer_rate",
    "social insurance ceiling": "si_ceiling",
    "employee pension rate": "pension_rate",
    "meal exemption": "meal_exemption",
}


def _num(text: str) -> Decimal:
    text = text.strip().replace(",", "")
    if text.endswith("%"):
        return Decimal(text[:-1]) / 100
    return Decimal(text)


def _parse_brackets(cell: str) -> list[tuple[Decimal, Decimal | None, Decimal]]:
    bands = []
    for part in cell.split("·"):
        bounds, rate = part.rsplit(":", 1)
        bounds = bounds.strip()
        if bounds.startswith("over "):
            bands.append((_num(bounds[5:]), None, _num(rate)))
        else:
            lo, hi = bounds.split("–")
            bands.append((_num(lo), _num(hi), _num(rate)))
    return bands


def _prose_table(code: str) -> dict[str, dict[int, str]]:
    """Rows of the '| <Name> table | 2025 | 2026 |' Markdown table in a jurisdiction's section."""
    section = PROSE.split(f"### {code}:")[1].split("\n### ")[0]
    rows: dict[str, dict[int, str]] = {}
    lines = [ln for ln in section.splitlines() if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    years = [int(y) for y in header[1:]]
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        label = re.sub(r"[*]", "", cells[0]).lower()
        key = next(v for k, v in ROW_KEYS.items() if k in label)
        rows[key] = dict(zip(years, cells[1:]))
    return rows


@pytest.mark.parametrize("code", ["VAL", "KES", "NRD"])
def test_yaml_tables_match_prose_tables(code):
    prose = _prose_table(code)
    jur = RS.jurisdictions[code]
    assert set(jur.tables) == {2025, 2026}
    for key, by_year in prose.items():
        for year, cell in by_year.items():
            table = jur.tables[year]
            if key == "brackets":
                yaml_bands = [(b.lower, b.upper, b.rate) for b in table.brackets.bands]
                assert yaml_bands == _parse_brackets(cell), (code, year, key)
            else:
                assert getattr(table, key).value == _num(cell), (code, year, key)
    # Every value in the YAML appears in the prose table (no YAML-only rules).
    for year, table in jur.tables.items():
        for field, value in table:
            if value is not None:
                assert field in prose, f"{code} {year}: '{field}' is in rules.yaml but not in RULESET.md"


def test_fx_table_matches_prose():
    rows = re.findall(r"\| `(\w+) → (\w+)` \| ([\d.]+) \| ([\d.]+) \|", PROSE)
    assert len(rows) == 6
    for src, dst, r2025, r2026 in rows:
        assert RS.fx_rate(src, dst, 2025) == Decimal(r2025)
        assert RS.fx_rate(src, dst, 2026) == Decimal(r2026)
    assert sum(len(v) for v in RS.fx.rates.values()) == 12


def test_every_value_cites_an_existing_clause():
    clause_ids = set(re.findall(r"\*\*((?:GEN|VAL|KES|NRD|FX)-§[\d.]+)", PROSE))
    for code, jur in RS.jurisdictions.items():
        for year, table in jur.tables.items():
            cited = [v.clause for _, v in table if hasattr(v, "clause")]
            for clause in cited:
                assert clause in clause_ids, f"{code} {year} cites unknown clause {clause}"
    assert RS.fx.clause in clause_ids


def test_jurisdiction_metadata_matches_prose():
    for code, jur in RS.jurisdictions.items():
        section = PROSE.split(f"### {code}:")[1].split("\n### ")[0]
        assert f"`{jur.currency}`" in section.splitlines()[0]
        assert ("calendar days" in section) == (jur.day_count == "calendar")
        assert ("working days" in section) == (jur.day_count == "working")
        assert ("**monthly** wage ceiling" in section) == (jur.si_ceiling_basis == "monthly")
        required_line = next(ln for ln in section.splitlines() if "Required inputs." in ln)
        for field in jur.required_inputs:
            assert f"`{field}`" in required_line, (code, field)


def test_lookups_and_missing_cases():
    assert RS.table("VAL", 2026).si_ceiling.value == Decimal("6000.00")
    assert RS.table("VAL", 2027) is None  # GEN-§4.2: no table -> undetermined
    assert RS.fx_rate("GBP", "VLD", 2026) is None  # GEN-§8.2: unsupported currency
    assert RS.jurisdictions["KES"].si_ceiling_basis == "annual_cumulative"
    assert RS.jurisdictions["NRD"].minor_unit == Decimal("1")


def test_fingerprint_is_stable_and_versioned():
    assert RS.version == "1.0" and RS.ruleset_id == "paygym-payroll"
    assert len(RS.fingerprint) == 16
    assert load_ruleset("1.0").fingerprint == RS.fingerprint
