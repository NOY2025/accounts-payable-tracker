# Accounts Payable Tracker

A lightweight accounts payable tracking system implemented in Python. It stores
vendor, invoice, and payment information in a local SQLite database and offers a
command line interface for day-to-day tasks as well as Python APIs for
integration or scripting.

## Features

- Manage vendor records with optional contact information.
- Capture invoices with invoice/due dates, descriptions, and support for cents-accurate amounts.
- Record payments while preventing overpayments and automatically tracking
  balances.
- Generate outstanding balance summaries and aging reports with standard buckets
  (current, 1-30, 31-60, 61-90, 91+ days past due).
- SQLite-backed storage with schema initialised on first use.
- Test-covered business logic that can be reused directly from Python.

## Requirements

- Python 3.10+
- No third-party dependencies are required for the core application. Tests use
  `pytest`.

## Getting Started

1. (Optional) Create and activate a virtual environment.
2. Clone the repository and change into the project directory.
3. Run the CLI via `python -m accounts_payable.cli`.

On first run a SQLite database file named `accounts_payable.db` will be created
in the current working directory. Use the `--db-path` option to specify an
alternative location.

## Command Line Usage

```
python -m accounts_payable.cli [--db-path PATH] <command> [options]
```

### Vendor Management

Add a vendor:

```
python -m accounts_payable.cli vendor add "Acme Supplies" --contact "ap@acme.test"
```

List vendors:

```
python -m accounts_payable.cli vendor list
```

### Invoices

Create an invoice:

```
python -m accounts_payable.cli invoice add 1 INV-2024-001 1200.50 2024-06-30 \
    --invoice-date 2024-06-01 --description "Quarterly consulting"
```

List invoices (with optional status filtering):

```
python -m accounts_payable.cli invoice list --status overdue
```

View invoice details including payments:

```
python -m accounts_payable.cli invoice detail 1
```

### Payments

Record a payment:

```
python -m accounts_payable.cli payment record 1 600.00 --date 2024-06-15
```

### Reporting

Outstanding summary by vendor:

```
python -m accounts_payable.cli report outstanding
```

Aging report with bucket totals:

```
python -m accounts_payable.cli report aging --as-of 2024-06-30
```

## Python API

All operations are available programmatically from
`accounts_payable.services`. For example:

```python
from datetime import date
from accounts_payable import services

DB_PATH = "accounts_payable.db"
vendor = services.add_vendor(DB_PATH, "Acme")
invoice = services.add_invoice(DB_PATH, vendor.id, "INV-1", amount="250.00", due_date=date(2024, 7, 15))
services.record_payment(DB_PATH, invoice.id, "125.00")
summary = services.get_outstanding_summary(DB_PATH)
```

See the tests in `tests/test_services.py` for more detailed usage examples.

## Running Tests

Install development dependencies (only `pytest` is required) and run:

```
pip install pytest
pytest
```

The test suite uses a temporary database file and does not touch the default
production database.

## Database Schema

The database consists of three tables:

- `vendors`: vendor master data with a unique `name`.
- `invoices`: invoices linked to vendors, storing integer cent amounts for exact
  calculations.
- `payments`: payments linked to invoices, also stored in integer cents.

Foreign keys enforce referential integrity and cascading deletes.
