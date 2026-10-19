# Rule-set fidelity audit

Brief p.10: hand-check at least 10 generated tasks against the rule-set text and report the divergence rate.

**Method.** For each task, work out the payslip **by hand from `ruleset/v1.0/RULESET.md` only** (no code), write the hand values in Part 1, then compare with the reference implementation in Part 2. A divergence is any line differing by more than one minor unit (GEN-§1.4), or a different refuse/compute decision or reason code. Where they differ, the rule set is right and the code has a bug (brief p.9), unless the rule set itself is ambiguous, in which case the rule set is clarified and its version bumped.

## Part 1: hand derivation

*Filled 2026-10-19 by Claude from `RULESET.md` only, before Part 2 was opened. Arithmetic and weekday counts were done with a calculator (a per-task script written from the clauses, not the reference code). Note: the worksheet lists inputs already normalised (annual ÷ 12, MM/DD dates, number formats); the raw prompts were checked for tasks 5, 6 and 7 (`annual_salary` 43200.00 / 79200.00, `05/04/2026` under MM/DD/YYYY).*

### 1. `gen-2000005-twin`: VAL 2026-05  (tags: twin, proration_start, allowances, multi_source, ceiling_binds)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"11380","salary_currency":"VLD","start_date":"2026-05-07"}
payroll_note: {"allowances":[{"type":"meal","amount":"220"},{"type":"housing","amount":"320"}]}
contract: {"monthly_salary":"11380","salary_currency":"VLD","start_date":"2026-05-07"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 9177.42 | GEN-§6.2/VAL-§1.1: 11380 × 25/31 (7–31 May) |
| taxable_allowances | 390.00 | GEN-§7.2: meal 220 − 150 exemption (2026) = 70; GEN-§7.3 housing 320; non-taxable 150 |
| employee_social_insurance | 480.00 | GEN-§5.1: 9177.42 + 390 = 9567.42 > ceiling 6000 (VAL-§2.1, 2026) → 8% × 6000 |
| employee_pension | 458.87 | VAL-§3.1: 5% × 9177.419… |
| income_tax | 1588.56 | VAL-§4.1: 9177.419 + 390 − 458.871 − 480 − 1000 = 7628.548; GEN-§11: 200 + 600 + 30% × 2628.548 |
| net_pay | 7189.99 | GEN-§10.3: gross 9717.42 − 480.00 − 458.87 − 1588.56 |

### 2. `gen-2000000`: KES 2025-02  (tags: fx, mid_period_change, allowances, annual_ceiling, multi_source, irrelevant_context, ceiling_slack)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"6840","salary_currency":"USD","start_date":"2022-05-20","salary_change":{"effective_date":"2025-02-09","monthly_salary":"7540"},"tax_residency":"resident","ytd_contributory_earnings":"7280"}
payroll_note: {"allowances":[{"type":"meal","amount":"50"},{"type":"housing","amount":"120"}]}
contract: {"monthly_salary":"6840","salary_currency":"USD","start_date":"2022-05-20"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 9175.00 | GEN-§8.1: ×1.25 (USD→KSD 2025) → 8550 / 9425; GEN-§6.3: 8550 × 8/28 + 9425 × 20/28 (change from 9 Feb) |
| taxable_allowances | 120.00 | GEN-§7.2: meal 50 ≤ exemption 100 (non-taxable 50); housing 120 taxable |
| employee_social_insurance | 557.70 | KES-§2.1: remaining ceiling 66000 − 7280 = 58720 > 9295 → 6% × 9295 |
| employee_pension | 367.00 | KES-§3.1: 4% × 9175 |
| income_tax | 2074.80 | KES-§4.1: M = 9175 + 120 − 367 = 8928; KES-§4.2: 12M − 12000 = 95136 → 3600 + 9000 + 35% × 35136 = 24897.60 ÷ 12 |
| net_pay | 6345.50 | gross 9345.00 − 557.70 − 367.00 − 2074.80 |

### 3. `gen-2000007`: NRD 2025-02  (tags: proration_start, mid_period_change, retro, allowances, irrelevant_context, ceiling_binds)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"12350","salary_currency":"NMK","start_date":"2025-02-06","salary_change":{"effective_date":"2025-02-10","monthly_salary":"13870"},"allowances":[{"type":"transport","amount":"100"},{"type":"transport","amount":"60"}],"retro_pay":"1340","tax_residency":"resident"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 11638 | NRD-§1.2: Feb 2025 has 20 working days; 6–7 Feb = 2 at 12350, 10–28 Feb = 15 at 13870 → 1235 + 10402.5 = 11637.5 → half-up 11638 |
| taxable_allowances | 0 | transport 100 + 60 non-taxable (GEN-§7.1, §7.4); non-taxable 160 |
| employee_social_insurance | 336 | contributory 11637.5 + 1340 = 12977.5 > 4800 (NRD-§2.1, 2025) → 7% × 4800 |
| employee_pension | 389 | NRD-§3.1: 3% × (11637.5 + 1340) = 389.325 |
| income_tax | 3044 | NRD-§4.1: 12977.5 − 389.325 − 800 = 11788.175 → 360 + 960 + 36% × 4788.175 = 3043.74 |
| net_pay | 9369 | gross 11638 + 1340 + 160 = 13138 − 336 − 389 − 3044 |

### 4. `gen-2000002`: NRD 2026-07  (tags: fx, mid_period_change, multi_source, irrelevant_context, ceiling_slack)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"370","salary_currency":"EUR","start_date":"2024-08-05","salary_change":{"effective_date":"2026-07-07","monthly_salary":"430"},"tax_residency":"resident"}
contract: {"monthly_salary":"370","salary_currency":"EUR","start_date":"2024-08-05"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 4615 | ×11.0 (EUR→NMK 2026) → 4070 / 4730; July 2026: 23 working days, 1–6 Jul = 4 old, 7–31 Jul = 19 new → 4614.78 |
| taxable_allowances | 0 | no allowances |
| employee_social_insurance | 323 | 4614.78 < 5000 (NRD 2026) → 7% × 4614.78 = 323.03 |
| employee_pension | 138 | 3% × 4614.78 = 138.44 |
| income_tax | 522 | 4614.78 − 138.44 − 800 = 3676.34 → 360 + 24% × 676.34 = 522.32 |
| net_pay | 3632 | 4615 − 323 − 138 − 522 |

### 5. `gen-2000009`: VAL 2026-02  (tags: proration_end, retro, allowances, multi_source, annual_salary_stated, ceiling_slack)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"3600","salary_currency":"VLD","start_date":"2024-01-01","end_date":"2026-02-17","tax_residency":"resident"}
payroll_note: {"allowances":[{"type":"transport","amount":"160"},{"type":"transport","amount":"140"}],"retro_pay":"1490"}
contract: {"monthly_salary":"3600","salary_currency":"VLD","start_date":"2024-01-01"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 2185.71 | GEN-§2.6: 43200 ÷ 12 = 3600; GEN-§6.2: × 17/28 (end 17 Feb 2026) |
| taxable_allowances | 0.00 | transport 160 + 140 non-taxable; non-taxable 300 |
| employee_social_insurance | 294.06 | contributory 2185.714 + 1490 = 3675.714 < 6000 → 8% |
| employee_pension | 183.79 | VAL-§3.1: 5% × (2185.714 + 1490) |
| income_tax | 239.57 | 3675.714 − 183.786 − 294.057 − 1000 = 2197.871 → 200 + 20% × 197.871 |
| net_pay | 3258.29 | gross 2185.71 + 1490.00 + 300.00 = 3975.71 − 294.06 − 183.79 − 239.57 |

### 6. `gen-2000015`: NRD 2026-05  (tags: fx, proration_start, format:mdy/comma_dot, ceiling_binds)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"990","salary_currency":"EUR","start_date":"2026-05-04","tax_residency":"non_resident"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 10371 | GEN-§2.4: 05/04/2026 MM/DD = 4 May; ×11.0 → 10890; May 2026: 21 working days, 20 employed → 10371.43 |
| taxable_allowances | 0 | none |
| employee_social_insurance | 350 | 10371.43 > 5000 → 7% × 5000 |
| employee_pension | 311 | 3% × 10371.43 = 311.14 |
| income_tax | 2134 | non_resident is unused in NRD (NRD-§1.3); 10371.43 − 311.14 − 800 = 9260.29 → 360 + 960 + 36% × 2260.29 = 2133.70 |
| net_pay | 7576 | 10371 − 350 − 311 − 2134 |

### 7. `gen-2000003`: KES 2025-01  (tags: fx, proration_start, allowances, irrelevant_context, annual_salary_stated, ceiling_slack)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"6600","salary_currency":"USD","start_date":"2025-01-23","allowances":[{"type":"transport","amount":"90"},{"type":"transport","amount":"100"}],"tax_residency":"resident"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 2395.16 | GEN-§2.6: 79200 ÷ 12 = 6600 USD × 1.25 = 8250; × 9/31 (23–31 Jan) |
| taxable_allowances | 0.00 | transport 90 + 100 non-taxable; non-taxable 190 |
| employee_social_insurance | 143.71 | KES-§1.2: January → ytd unused (= 0); 2395.16 < 66000 → 6% |
| employee_pension | 95.81 | 4% × 2395.161 |
| income_tax | 194.90 | M = 2299.355; 12M − 12000 = 15592.26 → 15% = 2338.84 ÷ 12 |
| net_pay | 2150.74 | gross 2585.16 − 143.71 − 95.81 − 194.90 |

### 8. `gen-2000011`: NRD 2025-07  (tags: proration_end, allowances, irrelevant_context, ceiling_slack)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"2040","salary_currency":"NMK","start_date":"2022-04-03","end_date":"2025-07-16","allowances":[{"type":"meal","amount":"40"},{"type":"meal","amount":"100"}]}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| earned_salary | 1064 | July 2025: 23 working days, 1–16 Jul = 12 → 2040 × 12/23 = 1064.35 |
| taxable_allowances | 60 | meal 40 + 100 = 140 (GEN-§7.4) − 80 exemption = 60 taxable; non-taxable 80 |
| employee_social_insurance | 79 | 1064.35 + 60 = 1124.35 < 4800 → 7% = 78.70 |
| employee_pension | 32 | 3% × 1064.35 = 31.93 |
| income_tax | 35 | 1064.35 + 60 − 31.93 − 800 = 292.42 → 12% = 35.09 |
| net_pay | 1058 | gross 1064 + 60 + 80 = 1204 − 79 − 32 − 35 |

### 9. `gen-2000005-trap`: VAL 2026-05  (tags: trap, conflicting_records, conflict:monthly_salary, proration_start, allowances, multi_source)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"11380","salary_currency":"VLD","start_date":"2026-05-07"}
payroll_note: {"allowances":[{"type":"meal","amount":"220"},{"type":"housing","amount":"320"}]}
contract: {"monthly_salary":"12120","salary_currency":"VLD","start_date":"2026-05-07"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| decision / reason code | refuse: CONFLICTING_RECORDS | GEN-§9.2: monthly_salary (required) is 11380 in the HR record and 12120 in the contract; GEN-§9.5: a 2026 VAL table exists and VLD is local, so no earlier reason applies |

### 10. `gen-2000004-trap`: KES 2026-06  (tags: trap, missing_input, missing:ytd_contributory_earnings, retro, annual_ceiling)

Inputs as the documents state them:

```json
hr_record: {"monthly_salary":"2730","salary_currency":"KSD","start_date":"2023-07-15","retro_pay":"940","tax_residency":"resident"}
```

| Line | Hand value (from prose) | Working (clauses) |
|---|---|---|
| decision / reason code | refuse: MISSING_INPUT | GEN-§9.1, KES-§1.2: ytd_contributory_earnings is required in June and absent from every source; a 2026 KES table exists and KSD is local (§9.5) |

## Part 2: reference implementation (compare only after Part 1)

1. `gen-2000005-twin`: earned_salary=9177.42, taxable_allowances=390.00, employee_social_insurance=480.00, employee_pension=458.87, income_tax=1588.56, net_pay=7189.99
2. `gen-2000000`: earned_salary=9175.00, taxable_allowances=120.00, employee_social_insurance=557.70, employee_pension=367.00, income_tax=2074.80, net_pay=6345.50
3. `gen-2000007`: earned_salary=11638, taxable_allowances=0, employee_social_insurance=336, employee_pension=389, income_tax=3044, net_pay=9369
4. `gen-2000002`: earned_salary=4615, taxable_allowances=0, employee_social_insurance=323, employee_pension=138, income_tax=522, net_pay=3632
5. `gen-2000009`: earned_salary=2185.71, taxable_allowances=0.00, employee_social_insurance=294.06, employee_pension=183.79, income_tax=239.57, net_pay=3258.29
6. `gen-2000015`: earned_salary=10371, taxable_allowances=0, employee_social_insurance=350, employee_pension=311, income_tax=2134, net_pay=7576
7. `gen-2000003`: earned_salary=2395.16, taxable_allowances=0.00, employee_social_insurance=143.71, employee_pension=95.81, income_tax=194.90, net_pay=2150.74
8. `gen-2000011`: earned_salary=1064, taxable_allowances=60, employee_social_insurance=79, employee_pension=32, income_tax=35, net_pay=1058
9. `gen-2000005-trap`: refuse `CONFLICTING_RECORDS` (GEN-§9.2), inputs ['monthly_salary']
10. `gen-2000004-trap`: refuse `MISSING_INPUT` (GEN-§9.1), inputs ['ytd_contributory_earnings']

## Result

| Tasks checked | Lines/decisions compared | Divergences | Divergence rate |
|---|---|---|---|
| 10 (8 payslips, 2 traps) | 50 (48 payslip lines + 2 refuse decisions with reason code and named input) | **0** | **0 / 50 = 0 %** (95 % CI upper bound ≈ 6 % by the rule of three) |

Findings and fixes:
- **No divergence.** Every hand value matches the reference to the exact minor unit, not merely within the GEN-§1.4 tolerance. Both trap decisions also match: reason code, clause and the named input.
- **Rules the sample exercised:**
  - calendar-day and working-day proration, including a period starting on a weekend (task 3) and a half-krone rounding boundary (11637.5 → 11638, task 3);
  - salary change mid-period (tasks 2–4) and FX conversion with the 2025 vs 2026 rates (tasks 2, 4, 6, 7);
  - the monthly ceiling binding (tasks 1, 3, 6) and the Kestrel annual ceiling with year-to-date earnings (task 2);
  - the January YTD exception (task 7) and an input that is unused in its jurisdiction (task 6: `non_resident` in Nordmark);
  - meal exemption split, transport, housing and several allowances of one type (tasks 1, 2, 3, 5, 7, 8);
  - retro pay in the pension and contribution bases (tasks 3, 5) and the annual-salary and MM/DD formats (tasks 5, 6, 7);
  - VAL's deductible social insurance vs NRD/KES's non-deductible one (tasks 1, 5 vs 3, 4, 2);
  - conflicting and missing required input (traps 9, 10).
- **Not exercised by this sample**, so it says nothing about them:
  - Kestrel non-resident flat tax;
  - the annual ceiling fully exhausted by YTD earnings;
  - a salary change effective before or after the period;
  - `NO_APPLICABLE_TABLE` and `UNSUPPORTED_CURRENCY` traps;
  - reason precedence when two reasons apply.

  These are covered by the per-clause unit and property tests (`tests/test_reference.py`, `tests/test_reference_properties.py`) and the hand-checked seed set (`tasks/seed_v1.jsonl`), but not by this audit.
- **Limits of this audit:**
  1. The same author (Claude) wrote `RULESET.md`, the reference and this hand check, so a misreading shared by all three would not show up. The user's own review of the working above (USER_ACTIONS §C) is the independent check.
  2. A sample of 10 bounds the divergence rate only loosely: 0/50 lines, but the tasks are not independent draws of every rule.
  3. The worksheet shows inputs already normalised. The raw prompts were checked for the three tasks where normalisation applies.

