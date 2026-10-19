"""Seeded task generator (brief Phase 02).

Each task has its own seed and is generated from ``numpy.random.PCG64(seed)`` alone, so a
task never depends on how many others were generated (prefix-stable) and the same seed
always gives the identical task. Ground truth comes only from the reference implementation.

Splits use disjoint seed ranges (``SPLITS``), so a held-out task can never be a training task.
Traps are always emitted together with a determinable *twin* that differs minimally.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

from paygym.reference import Allowance, Payslip, PayslipCase, SalaryChange, SourceRecord, compute_payslip
from paygym.render import Style, context_for, lookup_prompt, payslip_prompt
from paygym.ruleset import Ruleset, load_ruleset
from paygym.schema import Lookup, Task, TrapReason
from paygym.truth import truth_for_case, truth_for_lookup

RULESET_VERSION = "1.0"
LOCAL = {"VAL": "VLD", "KES": "KSD", "NRD": "NMK"}

# Disjoint per-task seed ranges. A task's seed is range start + index.
SPLITS: dict[str, tuple[int, int]] = {
    "train": (0, 10_000),
    "val": (500_000, 510_000),
    "heldout": (1_000_000, 1_010_000),
    "eval": (2_000_000, 2_010_000),
}

FIRST = ["Ada", "Bram", "Cora", "Dmitri", "Elsa", "Fintan", "Greta", "Hugo", "Ines", "Joran", "Kaia", "Lior",
         "Maren", "Niko", "Oona", "Pavel", "Quill", "Rhea", "Soren", "Tamsin", "Ulla", "Viggo", "Wren", "Yara"]
LAST = ["Abbot", "Brightwater", "Calloway", "Dunmore", "Everly", "Fairholm", "Garrow", "Hollis", "Ivers",
        "Juniper", "Kestwick", "Lowell", "Marchetti", "Norrell", "Ostrander", "Pell", "Quayle", "Rennick",
        "Stroud", "Thorne", "Underhill", "Vasquez", "Whitlock", "Yardley"]
TITLES = ["Payroll Analyst", "Operations Lead", "Software Engineer", "Account Manager", "Data Scientist",
          "Office Coordinator", "Product Designer", "Finance Associate"]
DEPARTMENTS = ["Finance", "Engineering", "Sales", "Operations", "People", "Legal"]
UNSUPPORTED = ["GBP", "JPY", "CHF", "SEK"]


@dataclass(frozen=True)
class Knobs:
    """Difficulty knobs (brief p.8). Probabilities are per generated task."""

    tier_mix: tuple[float, float, float] = (0.25, 0.50, 0.25)  # retrieval, payslip, trap+twin pair
    jurisdictions: tuple[str, ...] = ("VAL", "KES", "NRD")  # number of jurisdictions in play
    years: tuple[int, ...] = (2025, 2026)
    p_ceiling_binds: float = 0.5  # contribution ceilings (the key difficulty, brief p.5)
    p_proration: float = 0.3  # mid-period start or end
    p_salary_change: float = 0.2  # mid-period salary change
    p_retro: float = 0.2  # retroactive adjustment
    p_fx: float = 0.3  # currency mix
    max_allowances: int = 2  # more interacting rules (meal cap, taxable/non-taxable)
    p_split_sources: float = 0.5  # spread inputs over several documents = more lookups
    p_irrelevant: float = 0.5  # irrelevant facts (job title, department, unused inputs)
    p_format_variation: float = 0.3  # stated date / number conventions (GEN-§2.4–2.5)
    p_annual_salary: float = 0.15  # salary stated as an annual figure (GEN-§2.6)


# --------------------------------------------------------------------------- helpers


def _amount(rng: np.random.Generator, lo: float, hi: float, step: int = 10) -> Decimal:
    return Decimal(int(rng.uniform(lo, hi) / step) * step)


def _pick(rng: np.random.Generator, items):
    return items[int(rng.integers(len(items)))]


def _rand_date(rng: np.random.Generator, first: date, last: date) -> date:
    return first + timedelta(days=int(rng.integers((last - first).days + 1)))


def _style(rng: np.random.Generator, knobs: Knobs) -> Style:
    style = Style()
    if rng.random() < knobs.p_format_variation:
        style = replace(style, date_format=_pick(rng, ["dmy", "mdy"]), number_format=_pick(rng, ["comma_dot", "dot_comma"]))
    if rng.random() < knobs.p_annual_salary:
        style = replace(style, annual_salary=True)
    return style


@dataclass
class Draft:
    """A determinable payslip case under construction, plus what the agent is shown."""

    jurisdiction: str
    year: int
    month: int
    fields: dict  # resolved inputs (SourceRecord field -> value)
    sources: dict[str, set[str]]  # source name -> which fields it states
    extras: dict[str, dict[str, str]]
    name: str
    employee_id: str
    style: Style
    tags: list[str]
    overrides: dict[str, dict] = field(default_factory=dict)  # per-source values that differ (conflict traps)

    def copy(self) -> "Draft":
        return replace(self, fields=dict(self.fields), sources={k: set(v) for k, v in self.sources.items()},
                       extras={k: dict(v) for k, v in self.extras.items()},
                       overrides={k: dict(v) for k, v in self.overrides.items()}, tags=list(self.tags))

    def case(self) -> PayslipCase:
        records = {}
        for source, names in self.sources.items():
            values = {k: self.overrides.get(source, {}).get(k, self.fields.get(k)) for k in names}
            records[source] = SourceRecord(**{k: v for k, v in values.items() if v is not None})
        return PayslipCase(jurisdiction=self.jurisdiction, pay_period=f"{self.year}-{self.month:02d}", sources=records)


def _draft(rng: np.random.Generator, knobs: Knobs, rs: Ruleset) -> Draft:
    """A random *determinable* case with the knobs applied."""
    code = _pick(rng, list(knobs.jurisdictions))
    year = _pick(rng, list(knobs.years))
    month = int(rng.integers(1, 13))
    table = rs.table(code, year)
    jur = rs.jurisdictions[code]
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    tags: list[str] = []
    f: dict = {}

    # Salary relative to the ceiling (monthly ceilings); KES uses YTD for its annual ceiling.
    monthly_ceiling = table.si_ceiling.value if jur.si_ceiling_basis == "monthly" else table.si_ceiling.value / 12
    binds = rng.random() < knobs.p_ceiling_binds
    if jur.si_ceiling_basis == "monthly":
        lo, hi = (1.05, 3.0) if binds else (0.3, 0.9)
        local_salary = _amount(rng, float(monthly_ceiling) * lo, float(monthly_ceiling) * hi)
    else:
        local_salary = _amount(rng, float(monthly_ceiling) * 0.4, float(monthly_ceiling) * 1.6)

    currency = jur.currency
    salary = local_salary
    if rng.random() < knobs.p_fx:
        currency = _pick(rng, ["USD", "EUR"])
        rate = rs.fx_rate(currency, jur.currency, year)
        salary = max(Decimal(100), Decimal(int(local_salary / rate / 10) * 10))
        tags.append("fx")
    f["monthly_salary"] = salary
    f["salary_currency"] = currency

    if rng.random() < knobs.p_proration:
        if rng.random() < 0.5:
            f["start_date"] = date(year, month, int(rng.integers(2, 26)))
            tags.append("proration_start")
        else:
            f["start_date"] = _rand_date(rng, date(year - 3, 1, 1), first - timedelta(days=1))
            f["end_date"] = date(year, month, int(rng.integers(3, 27)))
            tags.append("proration_end")
    else:
        f["start_date"] = _rand_date(rng, date(year - 4, 1, 1), first - timedelta(days=1))

    if rng.random() < knobs.p_salary_change:
        start = f["start_date"]
        effective = date(year, month, int(rng.integers(max(start.day + 1, 2) if start >= first else 2, 28)))
        f["salary_change"] = SalaryChange(effective_date=effective, monthly_salary=_amount(rng, float(salary) * 1.03, float(salary) * 1.25))
        tags.append("mid_period_change")

    if rng.random() < knobs.p_retro:
        f["retro_pay"] = _amount(rng, 50, 1500)
        tags.append("retro")

    allowances = []
    for _ in range(int(rng.integers(0, knobs.max_allowances + 1))):
        kind = _pick(rng, ["meal", "transport", "housing"])
        bounds = {"meal": (40, 300), "transport": (30, 200), "housing": (100, 800)}[kind]
        allowances.append(Allowance(type=kind, amount=_amount(rng, *bounds)))
    if allowances:
        f["allowances"] = tuple(allowances)
        tags.append("allowances")

    # Residency: required in KES; unused (and so irrelevant) in VAL/NRD.
    if code == "KES" or rng.random() < knobs.p_irrelevant:
        f["tax_residency"] = "resident" if rng.random() < 0.75 else "non_resident"
    # YTD: required in KES outside January.
    if code == "KES" and month > 1:
        ceiling = float(table.si_ceiling.value)
        if binds:
            f["ytd_contributory_earnings"] = _amount(rng, ceiling - float(local_salary) * 0.9, ceiling * 1.1)
        else:
            f["ytd_contributory_earnings"] = _amount(rng, 0, min(ceiling * 0.6, float(local_salary) * (month - 1)))
        tags.append("annual_ceiling")

    # Sources: everything in the HR record, optionally spread over more documents (more lookups).
    names = set(f)
    sources: dict[str, set[str]] = {"hr_record": set(names)}
    if rng.random() < knobs.p_split_sources:
        moved = {k for k in ("retro_pay", "allowances") if k in names}
        if moved:
            sources["payroll_note"] = moved
            sources["hr_record"] -= moved
        sources["contract"] = {"monthly_salary", "salary_currency", "start_date"} & names
        tags.append("multi_source")

    name = f"{_pick(rng, FIRST)} {_pick(rng, LAST)}"
    employee_id = f"{code}-{int(rng.integers(1000, 9999))}"
    extras: dict[str, dict[str, str]] = {"hr_record": {"employee_id": employee_id, "name": name}}
    if rng.random() < knobs.p_irrelevant:
        extras["hr_record"].update(job_title=_pick(rng, TITLES), department=_pick(rng, DEPARTMENTS))
        tags.append("irrelevant_context")
    style = _style(rng, knobs)
    if style.date_format != "iso" or style.number_format != "plain":
        tags.append(f"format:{style.date_format}/{style.number_format}")
    if style.annual_salary:
        tags.append("annual_salary_stated")
    return Draft(code, year, month, f, sources, extras, name, employee_id, style, tags)


def _case_task(task_id: str, seed: int, d: Draft, difficulty: int, tags, twin_of=None, trap_reason=None) -> Task:
    case = d.case()
    truth = truth_for_case(case)
    result = compute_payslip(case)
    if isinstance(result, Payslip):
        # Tag from what actually happened (proration can pull earnings back under the ceiling).
        binds = result.trace.get("contribution_base").value < result.trace.get("contributory_earnings").value
        tags = list(tags) + ["ceiling_binds" if binds else "ceiling_slack"]
    return Task(
        id=task_id, difficulty=difficulty, prompt=payslip_prompt(case, d.extras, d.name, d.employee_id, d.style),
        context_files=context_for(case.jurisdiction), employee_id=d.employee_id, case=case, documents=d.extras,
        ground_truth=truth, verifier="refusal" if truth.kind == "refusal" else "payslip_lines",
        tags=tuple(tags), ruleset_version=RULESET_VERSION, twin_of=twin_of, trap_reason=trap_reason,
        provenance="generated", seed=seed,
    )


# --------------------------------------------------------------------------- traps and twins


TRAP_KINDS = ("MISSING_INPUT", "CONFLICTING_RECORDS", "NO_APPLICABLE_TABLE", "UNSUPPORTED_CURRENCY")


def _trap_pair(rng: np.random.Generator, d: Draft) -> tuple[Draft, Draft, TrapReason, list[str]]:
    """Mutate a determinable draft into a trap; the twin is a minimally different determinable case."""
    kind = _pick(rng, list(TRAP_KINDS))
    trap, twin = d.copy(), d.copy()

    if kind == "MISSING_INPUT":
        if d.jurisdiction == "KES":
            missing = "ytd_contributory_earnings" if d.month > 1 and rng.random() < 0.5 else "tax_residency"
        else:
            missing = _pick(rng, ["start_date", "salary_currency"])
        for names in trap.sources.values():
            names.discard(missing)
        reason = TrapReason(category="input_absent", reason_code=kind, clause="GEN-§9.1",
                            explanation=f"`{missing}` is required in {d.jurisdiction} but no document states it.")
        tags = ["trap", "missing_input", f"missing:{missing}"]
        # Twin variety: in VAL/NRD drop an *unused* input instead, which must not block the payslip.
        if d.jurisdiction != "KES" and "tax_residency" in twin.fields:
            for names in twin.sources.values():
                names.discard("tax_residency")

    elif kind == "CONFLICTING_RECORDS":
        conflicted = _pick(rng, ["start_date", "monthly_salary"])
        if conflicted == "start_date":
            other = d.fields["start_date"] + timedelta(days=int(rng.integers(3, 15)))
        else:
            other = d.fields["monthly_salary"] + _amount(rng, 100, 900)
        # The HR record keeps the true value; the contract states a different one.
        trap.sources.setdefault("contract", set()).add(conflicted)
        trap.overrides.setdefault("contract", {})[conflicted] = other
        reason = TrapReason(category="records_contradictory", reason_code=kind, clause="GEN-§9.2",
                            explanation=f"The HR record and the contract state different `{conflicted}` values; the rule set gives no precedence.")
        tags = ["trap", "conflicting_records", f"conflict:{conflicted}"]
        # Twin: both documents state the same value; they disagree only on a non-input (job title).
        twin.sources.setdefault("contract", set()).add(conflicted)
        twin.extras["hr_record"]["job_title"] = _pick(rng, TITLES[:4])
        twin.extras.setdefault("contract", {})["job_title"] = _pick(rng, TITLES[4:])

    elif kind == "NO_APPLICABLE_TABLE":
        stale = max(d.year, 2026) + 1 if rng.random() < 0.7 else min(d.year, 2025) - 1
        trap = _shift_year(trap, stale)
        reason = TrapReason(category="rules_silent", reason_code=kind, clause="GEN-§9.3",
                            explanation=f"The rule set has no {d.jurisdiction} rate table for {stale}; using another year's table would apply a stale rate.")
        tags = ["trap", "no_table", "stale_rate"]

    else:  # UNSUPPORTED_CURRENCY
        currency = _pick(rng, UNSUPPORTED)
        trap.fields["salary_currency"] = currency
        if twin.fields["salary_currency"] == LOCAL[d.jurisdiction]:
            twin.fields["salary_currency"] = _pick(rng, ["USD", "EUR"])
        reason = TrapReason(category="rules_silent", reason_code=kind, clause="GEN-§9.4",
                            explanation=f"The salary is in {currency}; the FX table has no {currency}->{LOCAL[d.jurisdiction]} rate.")
        tags = ["trap", "unsupported_currency", "fx"]
    return trap, twin, reason, tags


def _shift_year(d: Draft, year: int) -> Draft:
    delta = year - d.year
    fields = dict(d.fields)
    for key in ("start_date", "end_date"):
        if fields.get(key) is not None:
            fields[key] = _same_day(fields[key], fields[key].year + delta)
    if fields.get("salary_change") is not None:
        sc = fields["salary_change"]
        fields["salary_change"] = SalaryChange(effective_date=_same_day(sc.effective_date, sc.effective_date.year + delta),
                                               monthly_salary=sc.monthly_salary)
    shifted = d.copy()
    shifted.year, shifted.fields = year, fields
    return shifted


def _same_day(d: date, year: int) -> date:
    return date(year, d.month, min(d.day, calendar.monthrange(year, d.month)[1]))


# --------------------------------------------------------------------------- entry points


def generate_one(seed: int, knobs: Knobs = Knobs(), ruleset: Ruleset | None = None, id_prefix: str = "gen") -> list[Task]:
    """All tasks for one seed: one retrieval or payslip task, or a trap plus its twin."""
    rs = ruleset or load_ruleset(RULESET_VERSION)
    rng = np.random.Generator(np.random.PCG64(seed))
    tid = f"{id_prefix}-{seed:07d}"
    roll = rng.random()
    t1, t2, _ = knobs.tier_mix
    total = sum(knobs.tier_mix)

    if roll < t1 / total:
        code = _pick(rng, list(knobs.jurisdictions))
        year = _pick(rng, list(knobs.years))
        fields = ["personal_allowance", "si_employee_rate", "si_employer_rate", "si_ceiling", "pension_rate",
                  "meal_exemption", "fx:USD", "fx:EUR"] + (["non_resident_rate"] if code == "KES" else [])
        field = _pick(rng, fields)
        lookup = Lookup(jurisdiction=code, year=year, field=field)
        return [Task(
            id=tid, difficulty=1, prompt=lookup_prompt(code, year, field), context_files=context_for(code),
            lookup=lookup, ground_truth=truth_for_lookup(lookup, rs), verifier="value_match",
            tags=("retrieval", f"field:{field}"), ruleset_version=RULESET_VERSION, provenance="generated", seed=seed,
        )]

    draft = _draft(rng, knobs, rs)
    if roll < (t1 + t2) / total:
        return [_case_task(tid, seed, draft, 2, draft.tags)]

    trap, twin, reason, trap_tags = _trap_pair(rng, draft)
    trap_task = _case_task(f"{tid}-trap", seed, trap, 3, trap_tags + draft.tags, trap_reason=reason)
    twin_task = _case_task(f"{tid}-twin", seed, twin, 2, ["twin"] + draft.tags, twin_of=f"{tid}-trap")
    # Guard: the mutation must produce exactly the intended refusal, and the twin must be determinable.
    if trap_task.ground_truth.kind != "refusal" or trap_task.ground_truth.reason_code != reason.reason_code:
        raise AssertionError(f"seed {seed}: trap did not produce {reason.reason_code}: {trap_task.ground_truth}")
    if twin_task.ground_truth.kind != "payslip":
        raise AssertionError(f"seed {seed}: twin is not determinable: {twin_task.ground_truth}")
    return [trap_task, twin_task]


def content_key(task: Task) -> str:
    """What makes two tasks the same question: the lookup, or the structured case."""
    return task.lookup.model_dump_json() if task.lookup is not None else task.case.model_dump_json()


def generate(start_seed: int, n_seeds: int, knobs: Knobs = Knobs(), id_prefix: str = "gen") -> list[Task]:
    """Tasks for seeds ``start_seed .. start_seed + n_seeds - 1`` (a trap seed yields trap + twin).

    A seed whose task repeats one already generated is skipped, so duplicates never inflate
    the sample (brief p.7). The result still depends only on (start_seed, n_seeds, knobs).
    """
    rs = load_ruleset(RULESET_VERSION)
    tasks: list[Task] = []
    seen: set[str] = set()
    for seed in range(start_seed, start_seed + n_seeds):
        produced = generate_one(seed, knobs, rs, id_prefix)
        key = content_key(produced[0])
        if key in seen:
            continue
        seen.add(key)
        tasks.extend(produced)
    return tasks


# Train has no retrieval tasks: there are only ~50 distinct retrieval questions, so they cannot
# be kept disjoint from the held-out split, and they teach the policy nothing about payroll logic.
SPLIT_KNOBS: dict[str, Knobs] = {
    "train": Knobs(tier_mix=(0.0, 0.67, 0.33)),
    "val": Knobs(),
    "heldout": Knobs(),
    "eval": Knobs(),
}


# Presets for the RL difficulty pilot (plan: if base Qwen-0.5B scores ~0%, make the *training tasks*
# easier rather than using a bigger model). Only the train split uses these; eval/held-out keep the defaults.
KNOB_PRESETS: dict[str, Knobs] = {
    "default": Knobs(tier_mix=(0.0, 0.67, 0.33)),
    "easy": Knobs(tier_mix=(0.0, 0.67, 0.33), p_ceiling_binds=0.3, p_proration=0.15, p_salary_change=0.05,
                  p_retro=0.1, p_fx=0.15, max_allowances=1, p_split_sources=0.2, p_irrelevant=0.2,
                  p_format_variation=0.1, p_annual_salary=0.0),
    "easier": Knobs(tier_mix=(0.0, 0.67, 0.33), jurisdictions=("VAL", "NRD"), p_ceiling_binds=0.3, p_proration=0.0,
                    p_salary_change=0.0, p_retro=0.0, p_fx=0.0, max_allowances=0, p_split_sources=0.0,
                    p_irrelevant=0.0, p_format_variation=0.0, p_annual_salary=0.0),
}


def generate_split(split: str, n_seeds: int, knobs: Knobs | None = None, preset: str = "default") -> list[Task]:
    """A split from its seed range. A non-default difficulty preset prefixes the ids (``gen-easy-…``) so sets
    generated from the same seeds under different presets never collide."""
    start, end = SPLITS[split]
    if n_seeds > end - start:
        raise ValueError(f"split {split} has room for {end - start} seeds")
    prefix = "gen" if preset == "default" else f"gen-{preset}"
    return generate(start, n_seeds, knobs or SPLIT_KNOBS[split], prefix)
