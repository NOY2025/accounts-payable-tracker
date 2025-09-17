"""Command line interface for the accounts payable tracker."""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional

from . import models, services
from .storage import DATABASE_FILENAME


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid date format: {value}. Use YYYY-MM-DD.") from exc


def _print_vendors(vendors: Iterable[models.Vendor]) -> None:
    vendors = list(vendors)
    if not vendors:
        print("No vendors found.")
        return
    for vendor in vendors:
        if vendor.contact_info:
            print(f"[{vendor.id}] {vendor.name} - {vendor.contact_info}")
        else:
            print(f"[{vendor.id}] {vendor.name}")


def _format_invoice_row(invoice: models.Invoice) -> str:
    return (
        f"{invoice.id:>4}  "
        f"{invoice.vendor_name:<20.20}  "
        f"{invoice.invoice_number:<15.15}  "
        f"{invoice.due_date.isoformat():<12}  "
        f"{services.format_currency(invoice.amount):>12}  "
        f"{services.format_currency(invoice.total_paid):>12}  "
        f"{services.format_currency(invoice.balance_due):>12}  "
        f"{invoice.status:<8}"
    )


def _print_invoices(invoices: Iterable[models.Invoice]) -> None:
    invoices = list(invoices)
    if not invoices:
        print("No invoices found.")
        return
    header = (
        f"{'ID':>4}  {'Vendor':<20}  {'Invoice #':<15}  {'Due Date':<12}  "
        f"{'Amount':>12}  {'Paid':>12}  {'Balance':>12}  {'Status':<8}"
    )
    print(header)
    print("-" * len(header))
    for invoice in invoices:
        print(_format_invoice_row(invoice))


def _print_payments(payments: Iterable[models.Payment]) -> None:
    payments = list(payments)
    if not payments:
        print("No payments recorded.")
        return
    for payment in payments:
        print(
            f"[{payment.payment_date.isoformat()}] "
            f"{services.format_currency(payment.amount)}"
        )


def _print_outstanding_summary(summary: dict) -> None:
    print(f"Outstanding invoices: {summary['count']}")
    print(f"Total outstanding: {services.format_currency(summary['total_outstanding'])}")
    if not summary["by_vendor"]:
        return
    print("By vendor:")
    for vendor, amount in summary["by_vendor"].items():
        print(f"  {vendor}: {services.format_currency(amount)}")


def _print_aging_report(report: models.AgingReport) -> None:
    print(f"Aging report as of {report.as_of.isoformat()}")
    print("Bucket totals:")
    for bucket in services.BUCKET_NAMES:
        print(f"  {bucket:>6}: {services.format_currency(report.totals[bucket])}")
    if not report.entries:
        print("No outstanding invoices.")
        return
    print("\nOutstanding invoices:")
    header = (
        f"{'ID':>4}  {'Vendor':<20}  {'Invoice #':<15}  {'Due Date':<12}  "
        f"{'Days':>5}  {'Bucket':<6}  {'Balance':>12}"
    )
    print(header)
    print("-" * len(header))
    for entry in report.entries:
        print(
            f"{entry.invoice_id:>4}  "
            f"{entry.vendor_name:<20.20}  "
            f"{entry.invoice_number:<15.15}  "
            f"{entry.due_date.isoformat():<12}  "
            f"{entry.days_overdue:>5}  "
            f"{entry.bucket:<6}  "
            f"{services.format_currency(entry.balance_due):>12}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Accounts Payable Tracker")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(DATABASE_FILENAME),
        help="Path to the SQLite database file (default: accounts_payable.db).",
    )

    subparsers = parser.add_subparsers(dest="command")

    vendor_parser = subparsers.add_parser("vendor", help="Manage vendors")
    vendor_sub = vendor_parser.add_subparsers(dest="vendor_command")

    vendor_add = vendor_sub.add_parser("add", help="Add a new vendor")
    vendor_add.add_argument("name", help="Vendor name")
    vendor_add.add_argument("--contact", dest="contact_info", help="Optional contact information")
    vendor_add.set_defaults(func=handle_vendor_add)

    vendor_list = vendor_sub.add_parser("list", help="List vendors")
    vendor_list.set_defaults(func=handle_vendor_list)

    invoice_parser = subparsers.add_parser("invoice", help="Manage invoices")
    invoice_sub = invoice_parser.add_subparsers(dest="invoice_command")

    invoice_add = invoice_sub.add_parser("add", help="Add a new invoice")
    invoice_add.add_argument("vendor_id", type=int, help="Vendor identifier")
    invoice_add.add_argument("invoice_number", help="Invoice number")
    invoice_add.add_argument("amount", type=str, help="Invoice amount")
    invoice_add.add_argument("due_date", type=_parse_iso_date, help="Due date (YYYY-MM-DD)")
    invoice_add.add_argument("--invoice-date", type=_parse_iso_date, help="Invoice date (YYYY-MM-DD)")
    invoice_add.add_argument("--description", help="Optional description")
    invoice_add.set_defaults(func=handle_invoice_add)

    invoice_list = invoice_sub.add_parser("list", help="List invoices")
    invoice_list.add_argument("--vendor-id", type=int, help="Filter by vendor id")
    invoice_list.add_argument(
        "--status",
        choices=["pending", "partial", "overdue", "paid"],
        help="Filter by invoice status",
    )
    invoice_list.add_argument("--overdue", action="store_true", help="Only show overdue invoices")
    invoice_list.set_defaults(func=handle_invoice_list)

    invoice_detail = invoice_sub.add_parser("detail", help="Show invoice detail including payments")
    invoice_detail.add_argument("invoice_id", type=int, help="Invoice identifier")
    invoice_detail.set_defaults(func=handle_invoice_detail)

    payment_parser = subparsers.add_parser("payment", help="Record payments")
    payment_sub = payment_parser.add_subparsers(dest="payment_command")

    payment_record = payment_sub.add_parser("record", help="Record a payment against an invoice")
    payment_record.add_argument("invoice_id", type=int, help="Invoice identifier")
    payment_record.add_argument("amount", type=str, help="Payment amount")
    payment_record.add_argument("--date", dest="payment_date", type=_parse_iso_date, help="Payment date")
    payment_record.set_defaults(func=handle_payment_record)

    report_parser = subparsers.add_parser("report", help="Generate reports")
    report_sub = report_parser.add_subparsers(dest="report_command")

    report_outstanding = report_sub.add_parser("outstanding", help="Summary of outstanding invoices")
    report_outstanding.add_argument("--vendor-id", type=int, help="Filter by vendor id")
    report_outstanding.set_defaults(func=handle_report_outstanding)

    report_aging = report_sub.add_parser("aging", help="Generate an aging report")
    report_aging.add_argument("--as-of", type=_parse_iso_date, help="Report as of date (YYYY-MM-DD)")
    report_aging.set_defaults(func=handle_report_aging)

    return parser


def handle_vendor_add(args: argparse.Namespace) -> int:
    vendor = services.add_vendor(args.db_path, args.name, contact_info=args.contact_info)
    print(f"Created vendor {vendor.name} (id={vendor.id}).")
    return 0


def handle_vendor_list(args: argparse.Namespace) -> int:
    vendors = services.list_vendors(args.db_path)
    _print_vendors(vendors)
    return 0


def handle_invoice_add(args: argparse.Namespace) -> int:
    invoice = services.add_invoice(
        args.db_path,
        vendor_id=args.vendor_id,
        invoice_number=args.invoice_number,
        amount=args.amount,
        due_date=args.due_date,
        invoice_date=args.invoice_date,
        description=args.description,
    )
    print(
        "Created invoice"
        f" {invoice.invoice_number} for vendor {invoice.vendor_name}"
        f" (id={invoice.id}) with balance {services.format_currency(invoice.balance_due)}."
    )
    return 0


def handle_invoice_list(args: argparse.Namespace) -> int:
    invoices = services.list_invoices(
        args.db_path,
        vendor_id=args.vendor_id,
        status=args.status,
        overdue_only=args.overdue,
    )
    _print_invoices(invoices)
    return 0


def handle_invoice_detail(args: argparse.Namespace) -> int:
    invoice, payments = services.get_invoice_with_payments(args.db_path, args.invoice_id)
    print(
        f"Invoice {invoice.invoice_number} ({invoice.id}) for {invoice.vendor_name}\n"
        f"Amount: {services.format_currency(invoice.amount)}\n"
        f"Paid: {services.format_currency(invoice.total_paid)}\n"
        f"Balance: {services.format_currency(invoice.balance_due)}\n"
        f"Due date: {invoice.due_date.isoformat()}\n"
        f"Status: {invoice.status}"
    )
    _print_payments(payments)
    return 0


def handle_payment_record(args: argparse.Namespace) -> int:
    payment = services.record_payment(
        args.db_path,
        invoice_id=args.invoice_id,
        amount=args.amount,
        payment_date=args.payment_date,
    )
    print(
        f"Recorded payment {services.format_currency(payment.amount)} for invoice {payment.invoice_id}"
        f" on {payment.payment_date.isoformat()}."
    )
    return 0


def handle_report_outstanding(args: argparse.Namespace) -> int:
    summary = services.get_outstanding_summary(args.db_path, vendor_id=args.vendor_id)
    _print_outstanding_summary(summary)
    return 0


def handle_report_aging(args: argparse.Namespace) -> int:
    report = services.get_aging_report(args.db_path, as_of=args.as_of)
    _print_aging_report(report)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except (ValueError, services.AccountsPayableError, services.NotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
