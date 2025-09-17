"""Data models for the accounts payable tracker."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Vendor:
    """Represents a vendor."""

    id: int
    name: str
    contact_info: Optional[str] = None


@dataclass(frozen=True)
class Payment:
    """Represents a payment recorded against an invoice."""

    id: int
    invoice_id: int
    amount: Decimal
    payment_date: date


@dataclass(frozen=True)
class Invoice:
    """Summary of an invoice including computed financial fields."""

    id: int
    vendor_id: int
    vendor_name: str
    invoice_number: str
    amount: Decimal
    description: Optional[str]
    invoice_date: date
    due_date: date
    total_paid: Decimal
    balance_due: Decimal
    status: str


@dataclass(frozen=True)
class AgingEntry:
    """Entry within an aging report describing a single outstanding invoice."""

    invoice_id: int
    vendor_name: str
    invoice_number: str
    due_date: date
    balance_due: Decimal
    days_overdue: int
    bucket: str


@dataclass(frozen=True)
class AgingReport:
    """Report summarising the aging of unpaid invoices."""

    as_of: date
    entries: List[AgingEntry]
    totals: Dict[str, Decimal]


def group_entries_by_bucket(entries: Iterable[AgingEntry]) -> Dict[str, List[AgingEntry]]:
    """Group aging report entries by their bucket name."""

    grouped: Dict[str, List[AgingEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.bucket, []).append(entry)
    return grouped
