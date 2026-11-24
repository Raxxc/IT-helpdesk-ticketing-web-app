"""Create demo data. Usage:  python seed.py          (only if the database is empty)
                            python seed.py --reset  (wipe tickets and re-create demo data)
Does not need Flask. Uses a fixed random seed so every run produces the same shape of data."""
from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import sla

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "helpdesk.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

TEMPLATES = [
    ("Cannot connect to office Wi-Fi", "Laptop shows 'No internet' on the corporate Wi-Fi since this morning.", "Network", "P3"),
    ("Outlook stuck on 'Trying to connect'", "Outlook has been disconnected for an hour and no email is arriving.", "Email", "P3"),
    ("Password expired, cannot log in", "User sees 'password has expired' and cannot sign in to the laptop.", "Account/Access", "P3"),
    ("Account locked after password change", "Account keeps locking a few minutes after the password was changed.", "Account/Access", "P2"),
    ("Printer on 3rd floor shows offline", "Nobody on the floor can print. The printer shows as offline.", "Printer", "P3"),
    ("Laptop very slow after Windows update", "Laptop takes ten minutes to start and apps are slow to open.", "Hardware", "P4"),
    ("VPN disconnects every few minutes", "Remote user is dropped from the VPN repeatedly while working from home.", "Network", "P2"),
    ("Cannot open shared finance folder", "Access denied when opening the finance team shared folder.", "Account/Access", "P2"),
    ("Teams microphone not detected", "Microphone is not detected in Teams meetings, other apps are fine.", "Software", "P3"),
    ("Request to install Adobe Reader", "User needs a PDF reader installed on the laptop.", "Software", "P4"),
    ("Monitor flickering on docking station", "External monitor flickers when connected through the docking station.", "Hardware", "P4"),
    ("Entire floor has no network access", "All users on the second floor report no network or Wi-Fi.", "Network", "P1"),
    ("Excel crashes when opening large file", "Excel closes unexpectedly when opening the monthly report workbook.", "Software", "P3"),
    ("Mailbox full, cannot send email", "Outlook says the mailbox is full and sending is blocked.", "Email", "P3"),
    ("Keyboard keys not working on laptop", "Several keys on the laptop keyboard do not respond.", "Hardware", "P4"),
    ("New joiner needs laptop setup", "New employee starts on Monday and needs a configured laptop.", "Hardware", "P3"),
]

REQUESTERS = [
    ("Neha Sharma", "neha.sharma@example.com"),
    ("Vikram Desai", "vikram.desai@example.com"),
    ("Ananya Joshi", "ananya.joshi@example.com"),
    ("Rahul Verma", "rahul.verma@example.com"),
    ("Pooja Patil", "pooja.patil@example.com"),
    ("Imran Shaikh", "imran.shaikh@example.com"),
    ("Kavya Menon", "kavya.menon@example.com"),
    ("Sandeep Rao", "sandeep.rao@example.com"),
]


def _insert_event(conn, ticket_id, event_type, actor, note, when):
    conn.execute(
        "INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, event_type, actor, note, sla.to_db(when)),
    )


def seed(db_path, count: int = 24, reset: bool = False, now: datetime | None = None) -> int:
    """Insert `count` demo tickets. Returns how many were inserted (0 if skipped)."""
    now = now or sla.utc_now()
    rng = random.Random(42)
    l1 = [name for name, level in sla.AGENTS.items() if level == "L1"]
    l2 = [name for name, level in sla.AGENTS.items() if level == "L2"]

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        existing = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        if existing and not reset:
            print(f"Database already has {existing} tickets. Use --reset to replace them.")
            return 0
        if reset:
            conn.execute("DELETE FROM ticket_events")
            conn.execute("DELETE FROM tickets")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('tickets', 'ticket_events')")

        for i in range(count):
            title, description, category, priority = TEMPLATES[i % len(TEMPLATES)]
            name, email = REQUESTERS[rng.randrange(len(REQUESTERS))]
            roll = rng.random()
            sla_minutes = sla.SLA_HOURS[priority] * 60

            status, level, assignee, resolved_at, kb_reference = "New", "L1", None, None, None
            if roll < 0.40:
                status = "Resolved"
                age_minutes = rng.randint(60, 7 * 24 * 60)
            else:
                # open tickets are mostly recent, so only a few are past their SLA
                age_minutes = rng.randint(15, int(sla_minutes * 1.15))
                if roll < 0.65:
                    status = "In Progress"
                elif roll < 0.80:
                    status = "Escalated"
                    level = "L2"
            created = now - timedelta(minutes=age_minutes)
            due = sla.compute_due(created, priority)

            if status == "Resolved":
                res_minutes = max(5, min(rng.randint(10, int(sla_minutes * 1.25)), age_minutes - 5))
                resolved_at = created + timedelta(minutes=res_minutes)
                assignee = rng.choice(l1)
                if rng.random() < 0.5:
                    kb_reference = f"KB-{rng.randint(1, 12):03d}"
            elif status == "In Progress":
                assignee = rng.choice(l1)
            elif status == "Escalated":
                assignee = rng.choice(l2) if rng.random() < 0.6 else None

            cur = conn.execute(
                """INSERT INTO tickets (title, description, requester_name, requester_email, category, priority,
                                         status, level, assignee, kb_reference, created_at, due_at, resolved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, description, name, email, category, priority, status, level, assignee, kb_reference,
                 sla.to_db(created), sla.to_db(due), sla.to_db(resolved_at) if resolved_at else None),
            )
            ticket_id = cur.lastrowid
            _insert_event(conn, ticket_id, "created", name, "Ticket created", created)
            if status != "New" and assignee:
                _insert_event(conn, ticket_id, "assignment", assignee, f"Assigned to {assignee} ({sla.AGENTS[assignee]})",
                              created + timedelta(minutes=3))
            if status == "Escalated":
                _insert_event(conn, ticket_id, "escalation", l1[0], "Escalated to L2: needs deeper investigation",
                              created + timedelta(minutes=10))
            if status == "Resolved":
                _insert_event(conn, ticket_id, "status_change", assignee, "In Progress -> Resolved: issue fixed at L1",
                              resolved_at)
        conn.commit()
        return count
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the HelpDesk Lite database with demo tickets.")
    parser.add_argument("--reset", action="store_true", help="delete existing tickets first")
    parser.add_argument("--count", type=int, default=24, help="number of tickets to create (default 24)")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="path to the SQLite file")
    args = parser.parse_args()
    inserted = seed(args.db, count=args.count, reset=args.reset)
    if inserted:
        print(f"Seeded {inserted} demo tickets into {args.db}")


if __name__ == "__main__":
    main()
