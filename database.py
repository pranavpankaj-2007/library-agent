
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "library.db"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn



import sqlite3
from pathlib import Path

# Database location: E:\LibraryAgent\data\library.db
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "library.db"


def get_connection():
    """Create a connection to the SQLite database."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create the required tables and insert sample loans if needed."""
    with get_connection() as conn:

        # Existing loans table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS loans (
                loan_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                due_date TEXT NOT NULL,
                renewals_used INTEGER NOT NULL,
                max_renewals INTEGER NOT NULL,
                reserved INTEGER NOT NULL,
                renewal_period_days INTEGER NOT NULL
            )
        """)

        # Existing action history table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                action_id TEXT PRIMARY KEY,
                test_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # New simulated book holds table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS holds (
                hold_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                title TEXT NOT NULL,
                author TEXT,
                edition TEXT,
                isbn TEXT,
                status TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
                queue_position INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Insert sample loans only if the loans table is empty
        count = conn.execute(
            "SELECT COUNT(*) FROM loans"
        ).fetchone()[0]

        if count == 0:
            conn.executemany("""
                INSERT INTO loans (
                    loan_id,
                    title,
                    due_date,
                    renewals_used,
                    max_renewals,
                    reserved,
                    renewal_period_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    "L101", "Database System Concepts",
                    "2026-10-21", 0, 3, 0, 14
                ),
                (
                    "L102", "Operating Systems",
                    "2026-10-21", 1, 3, 0, 14
                ),
                (
                    "L201", "Computer Networks",
                    "2026-10-21", 0, 3, 1, 14
                ),
                (
                    "L401", "Data Structures",
                    "2026-10-21", 3, 3, 0, 14
                ),
            ])


def get_all_loans():
    """Return all sample loans as dictionaries."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM loans ORDER BY loan_id
        """).fetchall()

    return [dict(row) for row in rows]


def get_loan(loan_id):
    """Return one loan using its loan ID."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM loans WHERE loan_id = ?
        """, (loan_id,)).fetchone()

    return dict(row) if row else None


def save_loan(loan):
    """Update the due date and renewal count for a loan."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE loans
            SET due_date = ?, renewals_used = ?
            WHERE loan_id = ?
        """, (
            loan["due_date"],
            loan["renewals_used"],
            loan["loan_id"]
        ))


def log_action(action_id, test_id, action_type, status, details):
    """Save an action to the audit log."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO action_logs (
                action_id,
                test_id,
                action_type,
                status,
                details
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            action_id,
            test_id,
            action_type,
            status,
            details
        ))


def get_action_logs():
    """Return action logs, newest first."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM action_logs
            ORDER BY created_at DESC
        """).fetchall()

    return [dict(row) for row in rows]


def save_hold(hold):
    """Insert a simulated hold or update an existing hold."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO holds (
                hold_id,
                account_id,
                title,
                author,
                edition,
                isbn,
                status,
                queue_position
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(hold_id) DO UPDATE SET
                status = excluded.status,
                queue_position = excluded.queue_position
        """, (
            hold["hold_id"],
            hold["account_id"],
            hold["title"],
            hold.get("author"),
            hold.get("edition"),
            hold.get("isbn"),
            hold.get("status", "PENDING_APPROVAL"),
            hold.get("queue_position")
        ))


def get_hold(hold_id):
    """Retrieve one hold by its ID."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM holds WHERE hold_id = ?
        """, (hold_id,)).fetchone()

    return dict(row) if row else None


def get_all_holds(account_id=None):
    """Return all holds, optionally filtered by account."""
    with get_connection() as conn:
        if account_id:
            rows = conn.execute("""
                SELECT * FROM holds
                WHERE account_id = ?
                ORDER BY created_at DESC
            """, (account_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM holds
                ORDER BY created_at DESC
            """).fetchall()

    return [dict(row) for row in rows]


if __name__ == "__main__":
    init_db()

    print("Database initialized:", DB_PATH)
    print("Total loans:", len(get_all_loans()))
    print("Total holds:", len(get_all_holds()))
