from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from accounts_payable import services


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "ap.db"


def test_add_vendor_and_prevent_duplicates(db_path):
    vendor = services.add_vendor(db_path, "Acme", contact_info="acme@example.com")
    assert vendor.id == 1
    assert vendor.name == "Acme"

    vendors = services.list_vendors(db_path)
    assert vendors == [vendor]

    with pytest.raises(services.AccountsPayableError):
        services.add_vendor(db_path, "Acme")


def test_invoice_lifecycle(db_path):
    vendor = services.add_vendor(db_path, "Globex")
    base_date = date.today()
    invoice = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="INV-001",
        amount="150.50",
        invoice_date=base_date,
        due_date=base_date + timedelta(days=30),
    )

    invoice_initial = services.get_invoice(db_path, invoice.id, as_of=base_date)
    assert invoice_initial.status == "pending"
    assert invoice_initial.balance_due == Decimal("150.50")

    payment_one = services.record_payment(
        db_path,
        invoice.id,
        "50.50",
        payment_date=base_date + timedelta(days=5),
    )
    assert payment_one.amount == Decimal("50.50")

    invoice_after_payment = services.get_invoice(
        db_path, invoice.id, as_of=base_date + timedelta(days=6)
    )
    assert invoice_after_payment.status == "partial"
    assert invoice_after_payment.balance_due == Decimal("100.00")

    with pytest.raises(services.AccountsPayableError):
        services.record_payment(
            db_path, invoice.id, "150.00", payment_date=base_date + timedelta(days=7)
        )

    invoice_overdue = services.get_invoice(
        db_path, invoice.id, as_of=base_date + timedelta(days=40)
    )
    assert invoice_overdue.status == "overdue"

    summary = services.get_outstanding_summary(
        db_path, as_of=base_date + timedelta(days=6)
    )
    assert summary["count"] == 1
    assert summary["total_outstanding"] == Decimal("100.00")
    assert summary["by_vendor"] == {vendor.name: Decimal("100.00")}

    payment_two = services.record_payment(
        db_path,
        invoice.id,
        "100.00",
        payment_date=base_date + timedelta(days=20),
    )
    assert payment_two.amount == Decimal("100.00")

    invoice_paid = services.get_invoice(
        db_path, invoice.id, as_of=base_date + timedelta(days=21)
    )
    assert invoice_paid.status == "paid"
    assert invoice_paid.balance_due == Decimal("0.00")

    summary_after = services.get_outstanding_summary(
        db_path, as_of=base_date + timedelta(days=21)
    )
    assert summary_after["count"] == 0
    assert summary_after["total_outstanding"] == Decimal("0.00")

    payments = services.list_payments(db_path, invoice.id)
    assert [payment.amount for payment in payments] == [Decimal("50.50"), Decimal("100.00")]

    paid_invoices = services.list_invoices(db_path, status="paid")
    assert len(paid_invoices) == 1
    assert paid_invoices[0].invoice_number == "INV-001"


def test_aging_report(db_path):
    vendor = services.add_vendor(db_path, "Soylent")
    as_of = date(2024, 6, 1)

    current_invoice = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="CUR-01",
        amount="100.00",
        invoice_date=as_of - timedelta(days=10),
        due_date=as_of + timedelta(days=10),
    )

    bucket_30 = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="AGE-15",
        amount="200.00",
        invoice_date=as_of - timedelta(days=45),
        due_date=as_of - timedelta(days=15),
    )

    bucket_60 = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="AGE-45",
        amount="300.00",
        invoice_date=as_of - timedelta(days=80),
        due_date=as_of - timedelta(days=45),
    )

    bucket_90 = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="AGE-75",
        amount="400.00",
        invoice_date=as_of - timedelta(days=110),
        due_date=as_of - timedelta(days=75),
    )

    bucket_120 = services.add_invoice(
        db_path,
        vendor_id=vendor.id,
        invoice_number="AGE-120",
        amount="500.00",
        invoice_date=as_of - timedelta(days=150),
        due_date=as_of - timedelta(days=120),
    )

    services.record_payment(db_path, bucket_60.id, "100.00", payment_date=as_of - timedelta(days=30))
    services.record_payment(db_path, bucket_90.id, "250.00", payment_date=as_of - timedelta(days=20))

    report = services.get_aging_report(db_path, as_of=as_of)

    assert report.totals["current"] == Decimal("100.00")
    assert report.totals["1-30"] == Decimal("200.00")
    assert report.totals["31-60"] == Decimal("200.00")
    assert report.totals["61-90"] == Decimal("150.00")
    assert report.totals["91+"] == Decimal("500.00")

    assert {entry.invoice_id for entry in report.entries} == {
        current_invoice.id,
        bucket_30.id,
        bucket_60.id,
        bucket_90.id,
        bucket_120.id,
    }

    overdue_invoices = services.list_invoices(db_path, overdue_only=True, as_of=as_of)
    assert {invoice.invoice_number for invoice in overdue_invoices} == {
        "AGE-15",
        "AGE-45",
        "AGE-75",
        "AGE-120",
    }
