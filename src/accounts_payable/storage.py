"""SQLite storage helpers for the accounts payable tracker."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

DATABASE_FILENAME = "accounts_payable.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return a sqlite connection with sensible defaults."""

    if db_path is None:
        db_path = Path(DATABASE_FILENAME)
    else:
        db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database(db_path: Optional[Path] = None) -> None:
    """Ensure the database contains the necessary tables."""

    with get_connection(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                contact_info TEXT
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id INTEGER NOT NULL,
                invoice_number TEXT NOT NULL,
                description TEXT,
                amount_cents INTEGER NOT NULL,
                invoice_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                UNIQUE(vendor_id, invoice_number),
                FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                amount_cents INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
            );
            """
        )


def iter_rows(cursor: sqlite3.Cursor) -> Iterable[sqlite3.Row]:
    """Yield rows from a cursor and ensure it is closed afterwards."""

    try:
        for row in cursor:
            yield row
    finally:
        cursor.close()
