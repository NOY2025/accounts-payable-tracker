"""Business logic for the accounts payable tracker."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import models
from . import storage

MONEY_QUANTIZE = Decimal("0.01")
BUCKET_NAMES = ("current", "1-30", "31-60", "61-90", "91+")


class AccountsPayableError(RuntimeError):
    """Base class for domain-specific errors."""


class NotFoundError(AccountsPayableError):
    """Raised when a requested entity does not exist."""


def _normalize_amount(value: Decimal | float | int | str) -> Decimal:
    """Convert an arbitrary numeric input to a two-decimal :class:`Decimal`."""

    if isinstance(value, Decimal):
        amount = value
    else:
        amount = Decimal(str(value))
    return amount.quantize(MONEY_QUANTIZE, rounding=ROUND_HALF_UP)


def _amount_to_cents(value: Decimal | float | int | str) -> int:
    """Convert a decimal currency value to its integer representation in cents."""

    amount = _normalize_amount(value)
    cents = int(amount * 100)
    return cents


def _cents_to_amount(value: int) -> Decimal:
    """Convert stored integer cents back to a :class:`Decimal`."""

    decimal_value = Decimal(value) / Decimal(100)
    return decimal_value.quantize(MONEY_QUANTIZE)


def _parse_date(value: date | datetime | str) -> date:
    """Convert a date-like value into a :class:`datetime.date` instance."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Initialise the database and return an open connection."""

    storage.initialize_database(db_path)
    return storage.get_connection(db_path)


def add_vendor(db_path: Optional[Path], name: str, contact_info: Optional[str] = None) -> models.Vendor:
    """Create a new vendor and return the resulting record."""

    name = (name or "").strip()
    if not name:
        raise ValueError("Vendor name is required.")

    try:
        with _connect(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO vendors (name, contact_info) VALUES (?, ?)", (name, contact_info)
            )
            vendor_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise AccountsPayableError(f"Vendor '{name}' already exists.") from exc

    return models.Vendor(id=vendor_id, name=name, contact_info=contact_info)


def list_vendors(db_path: Optional[Path]) -> List[models.Vendor]:
    """Return all vendors ordered alphabetically."""

    with _connect(db_path) as conn:
        rows = list(storage.iter_rows(conn.execute("SELECT id, name, contact_info FROM vendors ORDER BY name")))

    return [models.Vendor(id=row["id"], name=row["name"], contact_info=row["contact_info"]) for row in rows]


def get_vendor(db_path: Optional[Path], vendor_id: int) -> models.Vendor:
    """Fetch a vendor by identifier."""

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, contact_info FROM vendors WHERE id = ?", (vendor_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Vendor {vendor_id} was not found.")
    return models.Vendor(id=row["id"], name=row["name"], contact_info=row["contact_info"])


def _invoice_status(amount_cents: int, total_paid_cents: int, due_date: date, as_of: date) -> str:
    balance_cents = amount_cents - total_paid_cents
    if balance_cents <= 0:
        return "paid"
    if due_date < as_of:
        return "overdue"
    if total_paid_cents > 0:
        return "partial"
    return "pending"


def _row_to_invoice(row: sqlite3.Row, total_paid_cents: int, as_of: date) -> models.Invoice:
    amount_cents = int(row["amount_cents"])
    invoice_date = _parse_date(row["invoice_date"])
    due_date = _parse_date(row["due_date"])
    balance_cents = max(amount_cents - total_paid_cents, 0)
    return models.Invoice(
        id=row["id"],
        vendor_id=row["vendor_id"],
        vendor_name=row["vendor_name"],
        invoice_number=row["invoice_number"],
        description=row["description"],
        amount=_cents_to_amount(amount_cents),
        invoice_date=invoice_date,
        due_date=due_date,
        total_paid=_cents_to_amount(total_paid_cents),
        balance_due=_cents_to_amount(balance_cents),
        status=_invoice_status(amount_cents, total_paid_cents, due_date, as_of),
    )


def _fetch_invoice(conn: sqlite3.Connection, invoice_id: int, as_of: date) -> models.Invoice:
    row = conn.execute(
        """
        SELECT invoices.*, vendors.name AS vendor_name
        FROM invoices
        JOIN vendors ON vendors.id = invoices.vendor_id
        WHERE invoices.id = ?
        """,
        (invoice_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Invoice {invoice_id} was not found.")
    total_paid_cents = int(
        conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchone()[0]
    )
    return _row_to_invoice(row, total_paid_cents, as_of)


def add_invoice(
    db_path: Optional[Path],
    vendor_id: int,
    invoice_number: str,
    amount: Decimal | float | int | str,
    due_date: date | datetime | str,
    *,
    invoice_date: Optional[date | datetime | str] = None,
    description: Optional[str] = None,
) -> models.Invoice:
    """Create a new invoice and return the resulting record."""

    amount_cents = _amount_to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("Invoice amount must be greater than zero.")

    invoice_number = (invoice_number or "").strip()
    if not invoice_number:
        raise ValueError("Invoice number is required.")

    invoice_date_obj = _parse_date(invoice_date or date.today())
    due_date_obj = _parse_date(due_date)
    if due_date_obj < invoice_date_obj:
        raise ValueError("Due date cannot be earlier than the invoice date.")

    with _connect(db_path) as conn:
        vendor = conn.execute("SELECT id FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} was not found.")
        try:
            cursor = conn.execute(
                """
                INSERT INTO invoices (
                    vendor_id, invoice_number, description, amount_cents, invoice_date, due_date
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    vendor_id,
                    invoice_number,
                    description,
                    amount_cents,
                    invoice_date_obj.isoformat(),
                    due_date_obj.isoformat(),
                ),
            )
            invoice_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise AccountsPayableError(
                "An invoice with that number already exists for the selected vendor."
            ) from exc

    return get_invoice(db_path, invoice_id)


def list_invoices(
    db_path: Optional[Path],
    *,
    vendor_id: Optional[int] = None,
    status: Optional[str] = None,
    overdue_only: bool = False,
    as_of: Optional[date] = None,
) -> List[models.Invoice]:
    """Return invoices optionally filtered by vendor or status."""

    status_filter = status.lower() if status else None
    if status_filter and status_filter not in {"pending", "partial", "overdue", "paid"}:
        raise ValueError("Status filter must be one of: pending, partial, overdue, paid.")

    as_of_date = as_of or date.today()
    query = [
        "SELECT invoices.*, vendors.name AS vendor_name,",
        "       COALESCE(SUM(payments.amount_cents), 0) AS total_paid_cents",
        "FROM invoices",
        "JOIN vendors ON vendors.id = invoices.vendor_id",
        "LEFT JOIN payments ON payments.invoice_id = invoices.id",
    ]
    params: List[object] = []
    if vendor_id is not None:
        query.append("WHERE invoices.vendor_id = ?")
        params.append(vendor_id)
    query.append("GROUP BY invoices.id ORDER BY invoices.due_date")
    sql = "\n".join(query)

    invoices: List[models.Invoice] = []
    with _connect(db_path) as conn:
        for row in storage.iter_rows(conn.execute(sql, params)):
            total_paid_cents = int(row["total_paid_cents"] or 0)
            invoice = _row_to_invoice(row, total_paid_cents, as_of_date)
            if status_filter and invoice.status != status_filter:
                continue
            if overdue_only and invoice.status != "overdue":
                continue
            invoices.append(invoice)
    return invoices


def get_invoice(db_path: Optional[Path], invoice_id: int, *, as_of: Optional[date] = None) -> models.Invoice:
    """Fetch a single invoice by identifier."""

    as_of_date = as_of or date.today()
    with _connect(db_path) as conn:
        return _fetch_invoice(conn, invoice_id, as_of_date)


def list_payments(db_path: Optional[Path], invoice_id: int) -> List[models.Payment]:
    """Return all payments recorded against an invoice."""

    with _connect(db_path) as conn:
        rows = list(
            storage.iter_rows(
                conn.execute(
                    "SELECT id, invoice_id, amount_cents, payment_date FROM payments WHERE invoice_id = ? ORDER BY payment_date",
                    (invoice_id,),
                )
            )
        )
    return [
        models.Payment(
            id=row["id"],
            invoice_id=row["invoice_id"],
            amount=_cents_to_amount(int(row["amount_cents"])),
            payment_date=_parse_date(row["payment_date"]),
        )
        for row in rows
    ]


def record_payment(
    db_path: Optional[Path],
    invoice_id: int,
    amount: Decimal | float | int | str,
    *,
    payment_date: Optional[date | datetime | str] = None,
) -> models.Payment:
    """Record a payment against an invoice and return the stored record."""

    amount_cents = _amount_to_cents(amount)
    if amount_cents <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    payment_date_obj = _parse_date(payment_date or date.today())

    with _connect(db_path) as conn:
        invoice_row = conn.execute(
            "SELECT amount_cents FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if invoice_row is None:
            raise NotFoundError(f"Invoice {invoice_id} was not found.")
        total_paid_cents = int(
            conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()[0]
        )
        remaining_cents = int(invoice_row["amount_cents"]) - total_paid_cents
        if remaining_cents <= 0:
            raise AccountsPayableError("Invoice is already fully paid.")
        if amount_cents > remaining_cents:
            raise AccountsPayableError("Payment exceeds outstanding balance.")

        cursor = conn.execute(
            "INSERT INTO payments (invoice_id, amount_cents, payment_date) VALUES (?, ?, ?)",
            (invoice_id, amount_cents, payment_date_obj.isoformat()),
        )
        payment_id = cursor.lastrowid

    return models.Payment(
        id=payment_id,
        invoice_id=invoice_id,
        amount=_cents_to_amount(amount_cents),
        payment_date=payment_date_obj,
    )


def get_invoice_with_payments(
    db_path: Optional[Path], invoice_id: int, *, as_of: Optional[date] = None
) -> Tuple[models.Invoice, List[models.Payment]]:
    """Return an invoice paired with its payments."""

    as_of_date = as_of or date.today()
    with _connect(db_path) as conn:
        invoice = _fetch_invoice(conn, invoice_id, as_of_date)
        payment_rows = list(
            storage.iter_rows(
                conn.execute(
                    "SELECT id, amount_cents, payment_date FROM payments WHERE invoice_id = ? ORDER BY payment_date",
                    (invoice_id,),
                )
            )
        )
    payments = [
        models.Payment(
            id=row["id"],
            invoice_id=invoice_id,
            amount=_cents_to_amount(int(row["amount_cents"])),
            payment_date=_parse_date(row["payment_date"]),
        )
        for row in payment_rows
    ]
    return invoice, payments


def get_outstanding_summary(
    db_path: Optional[Path],
    *,
    vendor_id: Optional[int] = None,
    as_of: Optional[date] = None,
) -> Dict[str, object]:
    """Return summary statistics for outstanding invoices."""

    invoices = list_invoices(db_path, vendor_id=vendor_id, as_of=as_of)
    outstanding_invoices = [inv for inv in invoices if inv.balance_due > Decimal("0.00")]
    total_outstanding = sum((inv.balance_due for inv in outstanding_invoices), Decimal("0.00"))
    by_vendor: Dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for invoice in outstanding_invoices:
        by_vendor[invoice.vendor_name] += invoice.balance_due
    return {
        "count": len(outstanding_invoices),
        "total_outstanding": total_outstanding.quantize(MONEY_QUANTIZE),
        "by_vendor": {vendor: amount.quantize(MONEY_QUANTIZE) for vendor, amount in sorted(by_vendor.items())},
    }


def get_aging_report(
    db_path: Optional[Path],
    *,
    as_of: Optional[date] = None,
) -> models.AgingReport:
    """Generate an aging report for all outstanding invoices."""

    as_of_date = as_of or date.today()
    invoices = list_invoices(db_path, as_of=as_of_date)

    entries: List[models.AgingEntry] = []
    totals: Dict[str, Decimal] = {name: Decimal("0.00") for name in BUCKET_NAMES}

    for invoice in invoices:
        if invoice.balance_due <= Decimal("0.00"):
            continue
        days_overdue = (as_of_date - invoice.due_date).days
        if days_overdue <= 0:
            bucket = "current"
        elif days_overdue <= 30:
            bucket = "1-30"
        elif days_overdue <= 60:
            bucket = "31-60"
        elif days_overdue <= 90:
            bucket = "61-90"
        else:
            bucket = "91+"
        totals[bucket] += invoice.balance_due
        entries.append(
            models.AgingEntry(
                invoice_id=invoice.id,
                vendor_name=invoice.vendor_name,
                invoice_number=invoice.invoice_number,
                due_date=invoice.due_date,
                balance_due=invoice.balance_due,
                days_overdue=days_overdue,
                bucket=bucket,
            )
        )

    for bucket in totals:
        totals[bucket] = totals[bucket].quantize(MONEY_QUANTIZE)

    return models.AgingReport(as_of=as_of_date, entries=entries, totals=totals)


def format_currency(value: Decimal) -> str:
    """Return a human-friendly currency string."""

    return f"${value.quantize(MONEY_QUANTIZE):,.2f}"


def vendor_exists(db_path: Optional[Path], vendor_id: int) -> bool:
    """Return ``True`` when the vendor exists."""

    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    return row is not None


def invoice_exists(db_path: Optional[Path], invoice_id: int) -> bool:
    """Return ``True`` when the invoice exists."""

    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    return row is not None
