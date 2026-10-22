
from flask import Flask, render_template, jsonify, request
from datetime import date, timedelta
from uuid import uuid4
import json

from database import (
    init_db,
    get_connection,
    get_all_loans,
    get_loan,
    save_loan,
    log_action,
    get_action_logs,
    save_hold,
    get_hold,
    get_all_holds,
)

app = Flask(__name__)
init_db()


# --------------------------------------------------
# SYNTHETIC CATALOGUE
# --------------------------------------------------

EDITIONS = [
    {
        "id": "B301",
        "title": "Database System Concepts",
        "edition": "7th edition",
        "author": "Abraham Silberschatz",
        "year": "2019",
        "isbn": "9780078022159",
    },
    {
        "id": "B302",
        "title": "Fundamentals of Database Systems",
        "edition": "7th edition",
        "author": "Ramez Elmasri",
        "year": "2016",
        "isbn": "9780133970777",
    },
    {
        "id": "B303",
        "title": "Database Systems",
        "edition": "6th edition",
        "author": "Thomas Connolly",
        "year": "2014",
        "isbn": "9780132943260",
    },
]


SCENARIOS = {
    "TC1": {
        "name": "Two books due tomorrow",
        "loan_ids": ["L101", "L102"],
    },
    "TC2": {
        "name": "Book reserved by another user",
        "loan_ids": ["L201"],
    },
    "TC3": {
        "name": "Three Database editions",
    },
    "TC4": {
        "name": "Renewal limit reached",
        "loan_ids": ["L401"],
    },
}


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def check_renewal(loan):
    if loan is None:
        return "needs_review", "Loan record not found"

    if loan["reserved"]:
        return "not_renewable", "Another user has reserved this book"

    if loan["renewals_used"] >= loan["max_renewals"]:
        return "not_renewable", "Renewal limit reached"

    return "eligible", "Synthetic eligibility checks passed"


def enriched_loan(loan):
    """Add the field names expected by the dashboard."""
    item = dict(loan)
    item["account_id"] = "DEMO001"
    item["renewal_limit"] = item.get("max_renewals", 3)
    return item


def find_log(action_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM action_logs WHERE action_id = ?",
            (action_id,),
        ).fetchone()

    return dict(row) if row else None


def save_log_status(action_id, status, details):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE action_logs
            SET status = ?, details = ?
            WHERE action_id = ?
            """,
            (status, json.dumps(details), action_id),
        )


def create_pending_renewal(test_id, eligible_loans, account_id="DEMO001"):
    """Save a renewal proposal without changing any loan."""
    action_id = str(uuid4())

    proposal = {
        "loan_ids": [item["loan_id"] for item in eligible_loans],
        "proposed_due_dates": {
            item["loan_id"]: item["proposed_due_date"]
            for item in eligible_loans
        },
        "account_id": account_id,
    }

    log_action(
        action_id,
        test_id,
        "SIMULATED_RENEWAL",
        "PENDING_APPROVAL",
        json.dumps(proposal),
    )

    return action_id


def create_pending_hold(book, account_id="DEMO001"):
    """Save a reservation proposal; do not place the hold before approval."""
    action_id = str(uuid4())
    proposal = {
        "account_id": account_id,
        "book": book,
        "hold_id": str(uuid4()),
    }
    log_action(
        action_id,
        "NL_HOLD_REQUEST",
        "SIMULATED_HOLD",
        "PENDING_APPROVAL",
        json.dumps(proposal),
    )
    return action_id


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "mode": "Synthetic demo mode",
        "live_opac_configured": False,
        "message": "Flask backend connected. Live OPAC is not configured.",
    })


# --------------------------------------------------
# SAMPLE LOANS
# --------------------------------------------------

@app.route("/api/loans")
def loans():
    return jsonify({
        "source": "SQLite synthetic demo data",
        "mode": (
            "Demo mode · Synthetic data · "
            "No real library actions executed."
        ),
        "loans": [
            enriched_loan(loan)
            for loan in get_all_loans()
        ],
    })


@app.route("/api/holds")
def holds():
    account_id = request.args.get("account_id", "").strip() or None
    return jsonify({
        "source": "SQLite synthetic demo data",
        "holds": get_all_holds(account_id),
        "real_library_action": False,
    })


# --------------------------------------------------
# CATALOGUE SEARCH
# --------------------------------------------------

@app.route("/api/catalog")
def catalog():
    query = request.args.get("q", "").strip().casefold()

    matches = [
        book for book in EDITIONS
        if query in book["title"].casefold()
        or query in book["author"].casefold()
    ] if query else []

    return jsonify({
        "mock_results": matches,
        "live_opac": {
            "status": "not_configured",
            "message": (
                "Live OPAC is not connected. "
                "Results shown are synthetic sample editions."
            ),
            "results": [],
            "source_url": None,
        },
    })


# --------------------------------------------------
# NATURAL-LANGUAGE REQUEST PREVIEW
# --------------------------------------------------

@app.route("/api/preview", methods=["POST"])
def preview():
    body = request.get_json(silent=True) or {}

    message = str(body.get("message", "")).strip()
    account_id = str(body.get("account_id", "DEMO001")).strip()

    if not message:
        return jsonify({
            "error": "Please enter a library request."
        }), 400

    text = message.casefold()
    proposed_actions = []
    action_id = None

    # Renewal request
    if any(word in text for word in ("renew", "extend")):
        all_loans = get_all_loans()

        # Prefer an explicitly named book.
        matches = [
            loan for loan in all_loans
            if loan["title"].casefold() in text
        ]

        # Otherwise, find sample loans due today or tomorrow.
        if not matches:
            tomorrow = (
                date.today() + timedelta(days=1)
            ).isoformat()

            matches = [
                loan for loan in all_loans
                if loan["due_date"] <= tomorrow
            ]

        eligible_loans = []

        for loan in matches:
            status, reason = check_renewal(loan)

            item = {
                "loan_id": loan["loan_id"],
                "title": loan["title"],
                "action": "renew",
                "status": status,
                "reason": reason,
            }

            if status == "eligible":
                proposed_date = (
                    date.fromisoformat(loan["due_date"])
                    + timedelta(
                        days=loan["renewal_period_days"]
                    )
                ).isoformat()

                item["proposed_due_date"] = proposed_date
                eligible_loans.append(item)

            proposed_actions.append(item)

        if eligible_loans:
            action_id = create_pending_renewal(
                "NL_REQUEST",
                eligible_loans,
                account_id,
            )

            message_text = (
                "Review the proposed renewal and approve "
                "only if the details are correct."
            )
        elif proposed_actions:
            message_text = (
                "No eligible renewals were found. "
                "Review the reasons shown below."
            )
        else:
            message_text = (
                "No matching sample loans were found. "
                "Please specify a book title."
            )

    # Reservation request
    elif any(word in text for word in ("reserve", "reservation", "hold")):
        # Match the catalogue title/author/ISBN mentioned by the user.
        matched_books = [
            book for book in EDITIONS
            if book["title"].casefold() in text
            or book["author"].casefold() in text
            or book["isbn"] in text
            or book["id"].casefold() in text
        ]

        # Generic "Database" requests match multiple editions. Ask first.
        if not matched_books:
            broad_matches = [
                book for book in EDITIONS
                if any(term in book["title"].casefold() for term in text.split())
                and any(term in text.split() for term in ("database", "systems", "system"))
            ]
            matched_books = broad_matches

        if len(matched_books) == 1:
            book = matched_books[0]
            action_id = create_pending_hold(book, account_id)
            proposed_actions.append({
                "title": book["title"],
                "author": book["author"],
                "edition": book["edition"],
                "isbn": book["isbn"],
                "action": "reserve",
                "status": "pending_approval",
                "reason": "Exact synthetic catalogue edition matched.",
            })
            message_text = (
                "Review the reservation details and approve to place "
                "the simulated hold."
            )
        elif len(matched_books) > 1:
            proposed_actions.extend([
                {
                    "title": book["title"],
                    "author": book["author"],
                    "edition": book["edition"],
                    "isbn": book["isbn"],
                    "action": "reserve",
                    "status": "needs_clarification",
                    "reason": "Choose this exact edition before reserving.",
                }
                for book in matched_books
            ])
            message_text = (
                "Several editions match. Search the catalogue and enter "
                "the exact book title or ISBN before approving."
            )
        else:
            proposed_actions.append({
                "title": message,
                "action": "reserve",
                "status": "not_found",
                "reason": "No matching synthetic catalogue edition found.",
            })
            message_text = (
                "No matching sample edition was found. Search the catalogue "
                "and enter its exact title."
            )

    # Unrecognised request
    else:
        proposed_actions.append({
            "title": "Library request",
            "action": "review",
            "status": "needs_clarification",
            "reason": (
                "Specify whether you want to renew or reserve a book."
            ),
        })

        message_text = (
            "I need more information to prepare this request."
        )

    return jsonify({
        "request_id": str(uuid4()),
        "message": message_text,
        "proposed_actions": proposed_actions,
        "action_id": action_id,
        "approval_required": bool(action_id),
        "executed": False,
        "source": "SQLite synthetic demo data",
    })


# --------------------------------------------------
# HACKATHON TEST CASES
# --------------------------------------------------

@app.route("/api/tests")
def list_tests():
    return jsonify([
        {"id": key, "name": value["name"]}
        for key, value in SCENARIOS.items()
    ])


@app.route("/api/plan/<test_id>", methods=["POST"])
def create_plan(test_id):
    scenario = SCENARIOS.get(test_id)

    if scenario is None:
        return jsonify({"error": "Unknown test case"}), 404

    # Multiple matching editions: ask the user to choose.
    if test_id == "TC3":
        return jsonify({
            "test_id": test_id,
            "message": (
                "Three matching editions found. "
                "Select the required edition."
            ),
            "editions": EDITIONS,
        })

    actions = []

    for loan_id in scenario["loan_ids"]:
        loan = get_loan(loan_id)

        if loan is None:
            actions.append({
                "loan_id": loan_id,
                "title": loan_id,
                "due_date": "Unknown",
                "status": "needs_review",
                "reason": "Loan record not found in SQLite.",
            })
            continue

        status, reason = check_renewal(loan)

        item = {
            "loan_id": loan["loan_id"],
            "title": loan["title"],
            "due_date": loan["due_date"],
            "status": status,
            "reason": reason,
        }

        if status == "eligible":
            item["proposed_due_date"] = (
                date.fromisoformat(loan["due_date"])
                + timedelta(
                    days=loan["renewal_period_days"]
                )
            ).isoformat()

        if test_id == "TC4":
            overdue_days = max(
                (
                    date.today()
                    - date.fromisoformat(loan["due_date"])
                ).days,
                0,
            )

            item["fine_estimate"] = overdue_days * 5
            item["fine_note"] = (
                "Illustrative estimate at ₹5/day only. "
                "Verify the actual library fine policy."
            )

        actions.append(item)

    eligible = [
        item for item in actions
        if item["status"] == "eligible"
    ]

    action_id = None

    if eligible:
        action_id = create_pending_renewal(
            test_id,
            eligible,
        )

    return jsonify({
        "test_id": test_id,
        "message": (
            "Review the proposed renewals and approve to continue."
            if eligible
            else "No eligible renewals. No action was executed."
        ),
        "actions": actions,
        "action_id": action_id,
        "approval_required": bool(action_id),
        "source": "SQLite synthetic records",
    })


# --------------------------------------------------
# HUMAN APPROVAL AND SIMULATED VERIFICATION
# --------------------------------------------------

@app.route("/api/approve", methods=["POST"])
def approve():
    body = request.get_json(silent=True) or {}
    action_id = body.get("action_id")

    if not action_id:
        return jsonify({"error": "Missing action ID"}), 400

    action = find_log(action_id)

    if not action:
        return jsonify({"error": "Action not found"}), 404

    proposal = json.loads(action["details"])

    # If this reservation action was already handled, return the existing
    # hold when one exists instead of failing with a misleading 409.
    if action["status"] != "PENDING_APPROVAL":
        if action["action_type"] == "SIMULATED_HOLD":
            book = proposal.get("book") or {}
            account_id = proposal.get("account_id", "DEMO001")
            existing = [
                hold for hold in get_all_holds(account_id)
                if hold.get("isbn") == book.get("isbn")
                and hold.get("status") == "PLACED"
            ]
            if existing:
                hold = existing[0]
                result = {
                    "hold_id": hold.get("hold_id"),
                    "account_id": hold.get("account_id"),
                    "title": hold.get("title"),
                    "author": hold.get("author"),
                    "edition": hold.get("edition"),
                    "isbn": hold.get("isbn"),
                    "status": hold.get("status"),
                    "queue_position": hold.get("queue_position"),
                    "verification": "verified_in_sqlite_simulator",
                }
                return jsonify({
                    "status": "simulated_success",
                    "message": "This reservation already exists and was verified. No duplicate was created.",
                    "results": [result],
                    "real_library_action": False,
                }), 200
        return jsonify({
            "error": "This action is no longer pending approval.",
            "status": action["status"],
        }), 409

    # Reservation approval path
    if action["action_type"] == "SIMULATED_HOLD":
        book = proposal.get("book")
        account_id = proposal.get("account_id", "DEMO001")
        hold_id = proposal.get("hold_id")

        if not book or not hold_id:
            save_log_status(
                action_id,
                "VERIFICATION_FAILED",
                {"reason": "Reservation details are incomplete."},
            )
            return jsonify({"error": "Reservation details are incomplete."}), 400

        # Recheck for a duplicate active hold for this account and edition.
        existing = [
            hold for hold in get_all_holds(account_id)
            if hold.get("isbn") == book.get("isbn")
            and hold.get("status") == "PLACED"
        ]
        if existing:
            existing_hold = existing[0]
            result = {
                "hold_id": existing_hold.get("hold_id"),
                "account_id": existing_hold.get("account_id"),
                "title": existing_hold.get("title"),
                "author": existing_hold.get("author"),
                "edition": existing_hold.get("edition"),
                "isbn": existing_hold.get("isbn"),
                "status": existing_hold.get("status"),
                "queue_position": existing_hold.get("queue_position"),
                "verification": "verified_in_sqlite_simulator",
            }
            save_log_status(
                action_id,
                "SIMULATED_VERIFIED",
                {
                    "message": "Reservation already existed; no duplicate created.",
                    "results": [result],
                },
            )
            return jsonify({
                "status": "simulated_success",
                "message": "This reservation was already placed. The existing hold was verified; no duplicate was created.",
                "results": [result],
                "real_library_action": False,
            }), 200

        active_holds = [
            hold for hold in get_all_holds()
            if hold.get("isbn") == book.get("isbn")
            and hold.get("status") == "PLACED"
        ]
        queue_position = len(active_holds) + 1

        hold_record = {
            "hold_id": hold_id,
            "account_id": account_id,
            "title": book["title"],
            "author": book.get("author"),
            "edition": book.get("edition"),
            "isbn": book.get("isbn"),
            "status": "PLACED",
            "queue_position": queue_position,
        }
        save_hold(hold_record)

        observed = get_hold(hold_id)
        verified = (
            observed is not None
            and observed.get("account_id") == account_id
            and observed.get("isbn") == book.get("isbn")
            and observed.get("status") == "PLACED"
        )
        result = {
            "hold_id": hold_id,
            "account_id": account_id,
            "title": book["title"],
            "author": book.get("author"),
            "edition": book.get("edition"),
            "isbn": book.get("isbn"),
            "status": observed.get("status") if observed else None,
            "queue_position": observed.get("queue_position") if observed else None,
            "verification": (
                "verified_in_sqlite_simulator" if verified
                else "verification_failed"
            ),
        }
        save_log_status(
            action_id,
            "SIMULATED_VERIFIED" if verified else "VERIFICATION_FAILED",
            {"results": [result]},
        )
        return jsonify({
            "status": "simulated_success" if verified else "verification_failed",
            "message": (
                "Simulated hold saved and re-read from SQLite."
                if verified else "The saved hold could not be verified."
            ),
            "results": [result],
            "real_library_action": False,
        }), (200 if verified else 500)

    loan_ids = proposal.get("loan_ids", [])
    proposed_dates = proposal.get("proposed_due_dates", {})

    # Validate all records before changing any of them.
    for loan_id in loan_ids:
        loan = get_loan(loan_id)
        status, reason = check_renewal(loan)

        if status != "eligible":
            save_log_status(
                action_id,
                "REJECTED_RECHECK",
                {
                    "loan_id": loan_id,
                    "reason": reason,
                },
            )

            return jsonify({
                "error": (
                    "Eligibility changed. "
                    "No renewal was performed."
                ),
                "reason": reason,
            }), 409

    verified_results = []

    for loan_id in loan_ids:
        loan = get_loan(loan_id)
        proposed_date = proposed_dates.get(loan_id)

        if not proposed_date:
            save_log_status(
                action_id,
                "VERIFICATION_FAILED",
                {"reason": "Proposed due date missing."},
            )

            return jsonify({
                "error": "Proposed due date is missing."
            }), 400

        loan["due_date"] = proposed_date
        loan["renewals_used"] += 1
        save_loan(loan)

        # Read the record again to verify the simulated update.
        observed = get_loan(loan_id)
        verified = (
            observed is not None
            and observed["due_date"] == proposed_date
        )

        verified_results.append({
            "loan_id": loan_id,
            "title": observed["title"] if observed else loan_id,
            "new_due_date": (
                observed["due_date"] if observed else None
            ),
            "verification": (
                "verified_in_sqlite_simulator"
                if verified else "verification_failed"
            ),
        })

    all_verified = bool(verified_results) and all(
        item["verification"] == "verified_in_sqlite_simulator"
        for item in verified_results
    )

    save_log_status(
        action_id,
        "SIMULATED_VERIFIED" if all_verified
        else "VERIFICATION_FAILED",
        {"results": verified_results},
    )

    return jsonify({
        "status": (
            "simulated_success"
            if all_verified
            else "verification_failed"
        ),
        "message": (
            "Synthetic SQLite records updated and re-read."
            if all_verified
            else "One or more records failed verification."
        ),
        "results": verified_results,
        "real_library_action": False,
    })


# --------------------------------------------------
# AUDIT LOG
# --------------------------------------------------

@app.route("/api/logs")
def logs():
    return jsonify(get_action_logs())


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)
