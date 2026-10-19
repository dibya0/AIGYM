"""Payslip inputs (RULESET GEN-§2.1), possibly stated in several source documents (GEN-§2.3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SalaryChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    effective_date: date
    monthly_salary: Decimal


class Allowance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["meal", "transport", "housing"]
    amount: Decimal = Field(ge=0)


class SourceRecord(BaseModel):
    """What one source document (e.g. HR record, contract) states. ``None`` = not stated."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    monthly_salary: Decimal | None = None
    salary_currency: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    salary_change: SalaryChange | None = None
    allowances: tuple[Allowance, ...] | None = None
    retro_pay: Decimal | None = None
    tax_residency: Literal["resident", "non_resident"] | None = None
    ytd_contributory_earnings: Decimal | None = None


INPUT_FIELDS: tuple[str, ...] = tuple(SourceRecord.model_fields)
OPTIONAL_INPUTS: tuple[str, ...] = ("end_date", "salary_change", "allowances", "retro_pay")  # GEN-§2.2


class PayslipCase(BaseModel):
    """One payslip question: jurisdiction and period are fixed by the task; inputs come from sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    jurisdiction: Literal["VAL", "KES", "NRD"]
    pay_period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    sources: dict[str, SourceRecord]

    @property
    def year(self) -> int:
        return int(self.pay_period[:4])

    @property
    def month(self) -> int:
        return int(self.pay_period[5:])
