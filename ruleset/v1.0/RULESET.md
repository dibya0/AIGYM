# PayGym Payroll Rule Set — version 1.0

**Rule set ID:** `paygym-payroll` · **Version:** `1.0` · **Status:** pinned · **Date:** 2026-10-17

This document is the authority for every PayGym task. It describes three **fictional** jurisdictions (Valdoria, Kestrel Isles, Nordmark) and how to compute one employee's monthly payslip in each. The reference implementation (`paygym/reference/`) is only a claim about what this document says: every rule in code cites the clause it implements, and **where the code and this document disagree, this document is right and the code has a bug.**

Clause IDs are stable. General rules are `GEN-§n.m`; jurisdiction rules are `VAL-§n.m`, `KES-§n.m` and `NRD-§n.m`. The rate tables in Part B are part of this document; `rules.yaml` is a machine-readable copy of them and must match them exactly.

---

## Part A: General rules (all jurisdictions)

### GEN-§1 Scope, units and precision

- **GEN-§1.1 Pay period.** A payslip covers exactly one calendar month (the *pay period*), identified as `YYYY-MM`. The period runs from the first to the last calendar day of the month, inclusive.
- **GEN-§1.2 Local currency.** Every payslip is computed and reported in the local currency of the employee's jurisdiction: Valdorian lira (`VLD`), Kestrel dollar (`KSD`) or Nordmark krone (`NMK`).
- **GEN-§1.3 Rounding.** Each payslip line (GEN-§10) is computed at full precision and then rounded **half-up** to the jurisdiction's *minor unit*: `0.01` in Valdoria and Kestrel Isles, `1` in Nordmark (NRD-§1.1). Intermediate values (ratios, converted amounts, taxable income, contribution bases) are **not** rounded. Where a later step uses an amount that is also a payslip line (for example employee social insurance deducted from Valdorian taxable income, VAL-§4.1), it uses the **full-precision** amount, not the rounded line. Only `gross_pay` and `net_pay` are computed from the rounded lines (GEN-§10.2, GEN-§10.3).
- **GEN-§1.4 Accepted tolerance.** A reported amount is accepted as correct if it differs from the amount computed under this rule set by **no more than one minor unit** (`0.01` in Valdoria and Kestrel Isles; `1` in Nordmark). This tolerance exists because an implementation that rounds some intermediate value differently can legitimately differ by one minor unit; it does not permit any other deviation.

### GEN-§2 Inputs

- **GEN-§2.1 Employee inputs.** A payslip is computed from these inputs:

  | Input | Meaning |
  |---|---|
  | `jurisdiction` | `VAL`, `KES` or `NRD` |
  | `pay_period` | `YYYY-MM` |
  | `monthly_salary` | Contractual gross salary for a full month, in `salary_currency` |
  | `salary_currency` | ISO-style code of the currency the salary is stated in |
  | `start_date` | First day of employment |
  | `end_date` | Last day of employment, if the employment ends (optional) |
  | `salary_change` | Optional: a new `monthly_salary` and its `effective_date` |
  | `allowances` | Zero or more allowances, each with a `type` (`meal`, `transport`, `housing`) and a monthly `amount` in local currency |
  | `retro_pay` | Optional: back pay for an earlier period, in local currency, paid in this period |
  | `tax_residency` | `resident` or `non_resident` |
  | `ytd_contributory_earnings` | Contributory earnings (GEN-§5.1) already paid in earlier months of the same calendar year, in local currency |

- **GEN-§2.2 Required, optional and unused inputs.** Every input is in exactly one of three classes for a given jurisdiction:
  - **Required:** listed in the jurisdiction's Part B section. The payslip cannot be computed without it (GEN-§9.1).
  - **Optional:** `end_date`, `salary_change`, `allowances`, `retro_pay`. If no source states one, its default applies: no end date, no salary change, no allowances, retro pay of 0.
  - **Unused:** any input the jurisdiction's Part B section lists as not used. An unused input does not affect the payslip, whether it is present, absent, or stated inconsistently.
- **GEN-§2.3 Several sources.** An input may be stated in more than one source document (for example an HR record and an employment contract). If at least one source states an input and every source that states it gives the same value, that value is used. An input stated in only one source is used as stated.
- **GEN-§2.4 Date conventions.** Dates are calendar dates. Where a task presents dates in a numeric day-month form, the task states its convention (`DD/MM/YYYY` or `MM/DD/YYYY`); the stated convention governs.
- **GEN-§2.5 Number formats.** Where a task presents amounts with a stated number format (for example `1,000.50` or `1.000,50`), the stated format governs.
- **GEN-§2.6 Annual figures.** If a task states a salary as an annual amount, `monthly_salary` is the annual amount divided by 12.
- **GEN-§2.7 Salary change currency.** The new salary in a `salary_change` is stated in the same `salary_currency` as `monthly_salary`.

### GEN-§3 Order of computation

A payslip is computed in this order. Later steps use the results of earlier steps.

1. Resolve the pay period's rate table (GEN-§4).
2. Convert the salary to local currency (GEN-§8).
3. Compute earned salary, with proration and any salary change (GEN-§6).
4. Classify allowances into taxable and non-taxable parts (GEN-§7).
5. Compute contributory earnings and social insurance (GEN-§5 and the jurisdiction's rules).
6. Compute the employee pension contribution (jurisdiction rules).
7. Compute taxable income and income tax (jurisdiction rules).
8. Compute net pay (GEN-§10.3).

### GEN-§4 Effective-dated rate tables

- **GEN-§4.1 Applicable table.** Each jurisdiction has one rate table per calendar year (Part B). The applicable table is the one for the **calendar year of the pay period**. All rates, ceilings, brackets, allowances and exemptions for the payslip come from that one table.
- **GEN-§4.2 No table.** If the jurisdiction has no rate table for the pay period's calendar year, this rule set does not determine the payslip (GEN-§9.3). A table for a different year must not be used in its place.

### GEN-§5 Social insurance: common definitions

- **GEN-§5.1 Contributory earnings.** For a pay period, *contributory earnings* = earned salary (GEN-§6) + retro pay + the taxable part of allowances (GEN-§7). Non-taxable allowance amounts are not contributory.
- **GEN-§5.2 Contribution base.** Employee and employer social insurance are each the jurisdiction's rate multiplied by the *contribution base*. The contribution base is contributory earnings **limited by the jurisdiction's wage ceiling**, as defined in its Part B section. A contribution is never computed on earnings above the ceiling.
- **GEN-§5.3 Employer contribution.** The employer contribution is reported on the payslip (GEN-§10.1) but is paid by the employer and does **not** reduce net pay.

### GEN-§6 Earned salary, proration and salary changes

- **GEN-§6.1 Full month.** If the employee is employed on every day of the pay period at one salary, earned salary = `monthly_salary` (converted, GEN-§8).
- **GEN-§6.2 Partial month.** If employment starts after the first day of the period, or ends before its last day, earned salary = converted `monthly_salary` × (*employed days in the period* ÷ *days in the period*), where both day counts use the jurisdiction's day-count method (Part B). Employed days run from the later of `start_date` and the period's first day to the earlier of `end_date` and the period's last day, inclusive.
- **GEN-§6.3 Salary change.** If a `salary_change` has an `effective_date` inside the pay period, the old salary applies to employed days before the effective date and the new salary applies from the effective date inclusive. Earned salary is the sum of each salary × (its employed days ÷ days in the period). A change effective on or before the period's first day means the new salary applies to the whole period; one effective after the period's last day does not apply.
- **GEN-§6.4 Not employed.** If the employee has no employed days in the period, earned salary is zero.

### GEN-§7 Allowances

- **GEN-§7.1 Transport.** Transport allowance is non-taxable in full.
- **GEN-§7.2 Meal.** Meal allowance is non-taxable up to the jurisdiction's monthly meal exemption in the applicable table; any amount above the exemption is taxable.
- **GEN-§7.3 Housing.** Housing allowance is taxable in full.
- **GEN-§7.4 Several allowances of one type.** Several allowances of the same type are added together before applying GEN-§7.1–§7.3.
- **GEN-§7.5 Not prorated.** Allowance amounts are paid as stated; they are not prorated.

### GEN-§8 Currency conversion

- **GEN-§8.1 Conversion.** If `salary_currency` differs from the local currency, `monthly_salary` (and any new salary in a `salary_change`) is converted to local currency by multiplying by the exchange rate in the FX table (Part B, §FX) for that currency pair, for the **last calendar day of the pay period**. The converted amount is not rounded (GEN-§1.3).
- **GEN-§8.2 Unsupported currency.** If the FX table has no rate for the currency pair and that date, this rule set does not determine the payslip (GEN-§9.4).

### GEN-§9 When the payslip is undetermined

A payslip must be refused, not computed, in exactly these cases. In each case the correct output is a refusal that gives the reason code below and identifies the missing, conflicting or unsupported input. Computing a payslip in any of these cases is an error. Refusing in any other case is also an error: if the rules determine the payslip, it must be computed.

- **GEN-§9.1 Missing required input (`MISSING_INPUT`).** A required input for the jurisdiction (Part B) is absent from every source.
- **GEN-§9.2 Conflicting records (`CONFLICTING_RECORDS`).** Two sources state **different values for a required or optional input** (GEN-§2.2). This rule set gives no precedence between sources, so the payslip is undetermined. A disagreement about an unused input, or about information that is not an input at all (for example a job title), does not make the payslip undetermined.
- **GEN-§9.3 No applicable rate table (`NO_APPLICABLE_TABLE`).** The pay period's calendar year has no rate table for the jurisdiction (GEN-§4.2).
- **GEN-§9.4 Unsupported currency (`UNSUPPORTED_CURRENCY`).** The salary currency differs from the local currency and the FX table has no rate for that pair on the period's last day (GEN-§8.2).
- **GEN-§9.5 Precedence of reasons.** If several reasons apply, report the first that applies in the order §9.3, §9.4, §9.1, §9.2.

### GEN-§10 Payslip format

- **GEN-§10.1 Lines.** A computed payslip reports these lines, each rounded per GEN-§1.3:

  | Line | Definition |
  |---|---|
  | `earned_salary` | GEN-§6 |
  | `retro_pay` | The `retro_pay` input, or 0 |
  | `taxable_allowances` | Taxable part of allowances (GEN-§7) |
  | `non_taxable_allowances` | Non-taxable part of allowances (GEN-§7) |
  | `gross_pay` | `earned_salary` + `retro_pay` + `taxable_allowances` + `non_taxable_allowances` |
  | `employee_social_insurance` | Jurisdiction rules |
  | `employee_pension` | Jurisdiction rules |
  | `income_tax` | Jurisdiction rules |
  | `net_pay` | GEN-§10.3 |
  | `employer_social_insurance` | Jurisdiction rules (reported, not deducted) |

- **GEN-§10.2 Rounded inputs to lines.** `gross_pay` is the sum of the four already-rounded lines that make it up.
- **GEN-§10.3 Net pay.** `net_pay` = `gross_pay` − `employee_social_insurance` − `employee_pension` − `income_tax`, using the rounded lines.

### GEN-§11 Progressive tax brackets

- **GEN-§11.1 Marginal rates.** A bracket table lists bands with a lower bound, an upper bound (or none for the top band) and a rate. Tax on an amount is the sum, over the bands, of the rate times the part of the amount that falls inside that band. Bands are half-open: the part of the amount above the lower bound and up to the upper bound.
- **GEN-§11.2 No negative tax.** A negative taxable amount is treated as zero.

---

## Part B: Jurisdictions

### VAL: Valdoria (local currency `VLD`, minor unit 0.01)

- **VAL-§1.1 Day count.** Proration (GEN-§6) uses **calendar days**.
- **VAL-§1.2 Required inputs.** `pay_period`, `monthly_salary`, `salary_currency`, `start_date`. **Unused inputs:** `tax_residency`, `ytd_contributory_earnings`.
- **VAL-§2.1 Social insurance ceiling (monthly).** The contribution base is the lesser of the period's contributory earnings and the **monthly** wage ceiling.
- **VAL-§2.2 Social insurance rates.** Employee contribution = employee rate × contribution base. Employer contribution = employer rate × contribution base.
- **VAL-§3.1 Pension.** Employee pension = pension rate × (earned salary + retro pay). There is no pension ceiling. Allowances are not pensionable.
- **VAL-§4.1 Taxable income.** Taxable income = earned salary + retro pay + taxable allowances − employee pension − **employee social insurance** − monthly personal allowance. In Valdoria, employee social insurance **is** deductible.
- **VAL-§4.2 Income tax.** Income tax = the monthly bracket table (GEN-§11) applied to taxable income.

| Valdoria table | 2025 | 2026 |
|---|---|---|
| Monthly personal allowance | 1,000.00 | 1,000.00 |
| Brackets (monthly taxable income) | 0–2,000: 10% · 2,000–5,000: 20% · 5,000–10,000: 30% · over 10,000: 40% | 0–2,000: 10% · 2,000–5,000: 20% · 5,000–10,000: 30% · over 10,000: 40% |
| Social insurance employee rate | 8% | 8% |
| Social insurance employer rate | 12% | 12% |
| Monthly social insurance ceiling | 5,500.00 | 6,000.00 |
| Employee pension rate | 5% | 5% |
| Monthly meal exemption | 120.00 | 150.00 |

### KES: Kestrel Isles (local currency `KSD`, minor unit 0.01)

- **KES-§1.1 Day count.** Proration (GEN-§6) uses **calendar days**.
- **KES-§1.2 Required inputs.** `pay_period`, `monthly_salary`, `salary_currency`, `start_date`, `tax_residency`, and `ytd_contributory_earnings`. **Exception:** when the pay period is January, `ytd_contributory_earnings` is **unused** — it is zero by definition, and any stated value is disregarded.
- **KES-§2.1 Social insurance ceiling (annual, cumulative).** The ceiling applies to the calendar year. The *remaining ceiling* = max(0, annual ceiling − `ytd_contributory_earnings`). The contribution base is the lesser of the period's contributory earnings and the remaining ceiling. Once the year's earnings reach the annual ceiling, no further contributions are due that year.
- **KES-§2.2 Social insurance rates.** Employee contribution = employee rate × contribution base. Employer contribution = employer rate × contribution base.
- **KES-§3.1 Pension.** Employee pension = pension rate × (earned salary + retro pay). No ceiling. Allowances are not pensionable.
- **KES-§4.1 Monthly taxable earnings.** Monthly taxable earnings (*M*) = earned salary + retro pay + taxable allowances − employee pension. In Kestrel Isles, employee social insurance is **not** deductible.
- **KES-§4.2 Residents: annualised tax.** For a `resident`: annual taxable income = 12 × *M* − annual personal allowance; annual tax = the **annual** bracket table (GEN-§11) applied to annual taxable income; income tax for the period = annual tax ÷ 12.
- **KES-§4.3 Non-residents: flat tax.** For a `non_resident`: income tax = the non-resident flat rate × *M*. No personal allowance applies and *M* is not annualised. A negative *M* is treated as zero.

| Kestrel Isles table | 2025 | 2026 |
|---|---|---|
| Annual personal allowance | 12,000.00 | 12,000.00 |
| Brackets (annual taxable income) | 0–24,000: 15% · 24,000–60,000: 25% · over 60,000: 35% | 0–24,000: 15% · 24,000–60,000: 25% · over 60,000: 35% |
| Non-resident flat rate | 25% | 25% |
| Social insurance employee rate | 6% | 6% |
| Social insurance employer rate | 9% | 9% |
| **Annual** social insurance ceiling | 66,000.00 | 72,000.00 |
| Employee pension rate | 4% | 4% |
| Monthly meal exemption | 100.00 | 100.00 |

### NRD: Nordmark (local currency `NMK`, minor unit **1**)

- **NRD-§1.1 Whole units.** Every payslip line is rounded half-up to a whole krone (GEN-§1.3); the accepted tolerance is 1 krone (GEN-§1.4).
- **NRD-§1.2 Day count.** Proration (GEN-§6) uses **working days**: Monday to Friday. Nordmark has no public holidays in this rule set.
- **NRD-§1.3 Required inputs.** `pay_period`, `monthly_salary`, `salary_currency`, `start_date`. **Unused inputs:** `tax_residency`, `ytd_contributory_earnings`.
- **NRD-§2.1 Social insurance ceiling (monthly).** The contribution base is the lesser of the period's contributory earnings and the **monthly** wage ceiling.
- **NRD-§2.2 Social insurance rates.** Employee contribution = employee rate × contribution base. Employer contribution = employer rate × contribution base.
- **NRD-§3.1 Pension.** Employee pension = pension rate × (earned salary + retro pay). No ceiling. Allowances are not pensionable.
- **NRD-§4.1 Taxable income.** Taxable income = earned salary + retro pay + taxable allowances − employee pension − monthly personal allowance. In Nordmark, employee social insurance is **not** deductible.
- **NRD-§4.2 Income tax.** Income tax = the monthly bracket table (GEN-§11) applied to taxable income.

| Nordmark table | 2025 | 2026 |
|---|---|---|
| Monthly personal allowance | 800 | 800 |
| Brackets (monthly taxable income) | 0–3,000: 12% · 3,000–7,000: 24% · over 7,000: 36% | 0–3,000: 12% · 3,000–7,000: 24% · over 7,000: 36% |
| Social insurance employee rate | 7% | 7% |
| Social insurance employer rate | 10% | 10% |
| Monthly social insurance ceiling | 4,800 | 5,000 |
| Employee pension rate | 3% | 3% |
| Monthly meal exemption | 80 | 80 |

### FX: Exchange rates

- **FX-§1.1 Rates.** Units of local currency per one unit of the salary currency, for the last calendar day of each month in 2025 and 2026. A pair or date not listed has no rate (GEN-§8.2).

| Pair | Rate (every month-end in 2025) | Rate (every month-end in 2026) |
|---|---|---|
| `USD → VLD` | 3.2000 | 3.4000 |
| `EUR → VLD` | 3.5000 | 3.6500 |
| `USD → KSD` | 1.2500 | 1.3000 |
| `EUR → KSD` | 1.3500 | 1.4000 |
| `USD → NMK` | 9.8000 | 10.2000 |
| `EUR → NMK` | 10.6000 | 11.0000 |

Only `USD` and `EUR` salaries are convertible. A salary in any other currency that is not the local currency (for example `GBP` or `JPY`) has no rate (GEN-§9.4).

---

## Part C: Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-17 | First pinned version. |
