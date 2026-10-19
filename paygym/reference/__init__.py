"""Reference implementation of the rule set: the gym's verifier (brief Phase 02/04)."""

from paygym.reference.calculator import LINES, Payslip, Undetermined, bracket_tax, compute_payslip, resolve_inputs
from paygym.reference.inputs import Allowance, PayslipCase, SalaryChange, SourceRecord
from paygym.reference.trace import Trace, TraceStep, cites

__all__ = [
    "LINES",
    "Allowance",
    "Payslip",
    "PayslipCase",
    "SalaryChange",
    "SourceRecord",
    "Trace",
    "TraceStep",
    "Undetermined",
    "bracket_tax",
    "cites",
    "compute_payslip",
    "resolve_inputs",
]
