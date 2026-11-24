"""HelpDesk Lite: a small local IT service desk ticketing web app.

Run with: python app.py  ->  http://127.0.0.1:5050
All database access goes through db.py; all SLA/workflow rules live in sla.py.
"""
from __future__ import annotations

import csv
import io
import os
import re
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for

from db import close_db, get_db, init_db
from sla import (
    AGENTS,
    CATEGORIES,
    LEVELS,
    PRIORITIES,
    PRIORITY_LABELS,
    SLA_HOURS,
    STATUSES,
    can_transition,
    compute_due,
    dashboard_stats,
    format_ist,
    from_db,
    sla_message,
    sla_state,
    ticket_number,
    to_db,
    utc_now,
)

BASE_DIR = Path(__file__).resolve().parent
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Whitelist for sorting. The raw query parameter is never put into SQL.
ORDER_BY = {
    "newest": "created_at DESC, id DESC",
    "due": "(resolved_at IS NOT NULL) ASC, due_at ASC, id ASC",
    "priority": "priority ASC, due_at ASC, id ASC",
}

CSV_HEADER = [
    "ticket_number", "title", "requester_name", "requester_email", "category",
    "priority", "status", "level", "assignee", "kb_reference", "created_at_utc",
    "due_at_utc", "resolved_at_utc", "sla_state",
]


def clean(value: str | None) -> str:
    """Normalise a submitted form field: missing -> empty string, trim whitespace."""
    return (value or "").strip()


def decorate_ticket(row, now) -> dict:
    """Add display-only fields to a ticket row. Does not touch the database."""
    t = dict(row)
    created = from_db(t["created_at"])
    due = from_db(t["due_at"])
    resolved = from_db(t["resolved_at"]) if t["resolved_at"] else None
    t["number"] = ticket_number(t["id"])
    t["sla_state"] = sla_state(created, due, resolved, now)
    t["sla_slug"] = t["sla_state"].lower().replace(" ", "-")
    t["sla_message"] = sla_message(created, due, resolved, now)
    t["status_slug"] = t["status"].lower().replace(" ", "-")
    t["priority_label"] = PRIORITY_LABELS[t["priority"]]
    return t


def create_app(test_config: dict | None = None) -> Flask:
    """Application factory: builds a fresh Flask app, safe to call in tests."""
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("HELPDESK_DB", str(BASE_DIR / "helpdesk.db")),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

    @app.context_processor
    def inject_globals():
        return {
            "PRIORITIES": PRIORITIES,
            "PRIORITY_LABELS": PRIORITY_LABELS,
            "STATUSES": STATUSES,
            "CATEGORIES": CATEGORIES,
            "LEVELS": LEVELS,
            "AGENTS": AGENTS,
            "SLA_HOURS": SLA_HOURS,
            "ticket_number": ticket_number,
        }

    @app.template_filter("ist")
    def ist(value):
        if not value:
            return "-"
        return format_ist(from_db(value)) + " IST"

    @app.errorhandler(404)
    def not_found(error):
        return render_template("404.html"), 404

    def load_ticket(ticket_id: int):
        row = get_db().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            abort(404)
        return row

    def redirect_with_flash(ticket_id: int, message: str, success: bool):
        flash(message, "success" if success else "error")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id), code=303)

    @app.route("/")
    def index():
        return redirect(url_for("dashboard"), code=303)

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/dashboard")
    def dashboard():
        now = utc_now()
        conn = get_db()
        rows = conn.execute(
            "SELECT category, priority, status, created_at, due_at, resolved_at FROM tickets"
        ).fetchall()
        stats = dashboard_stats(rows, now)

        open_rows = conn.execute(
            "SELECT * FROM tickets WHERE status != 'Resolved' ORDER BY due_at ASC"
        ).fetchall()
        attention = []
        for row in open_rows:
            ticket = decorate_ticket(row, now)
            if ticket["sla_state"] == "Breached":
                attention.append(ticket)
            if len(attention) == 5:
                break

        max_category_count = max((count for _, count in stats["by_category"]), default=1) or 1
        return render_template(
            "dashboard.html",
            stats=stats,
            attention=attention,
            max_category_count=max_category_count,
            now_ist=format_ist(now) + " IST",
        )

    @app.route("/tickets")
    def ticket_list():
        now = utc_now()
        raw_status = request.args.get("status", "")
        raw_priority = request.args.get("priority", "")
        raw_category = request.args.get("category", "")
        q = request.args.get("q", "")[:100]
        raw_sort = request.args.get("sort", "newest")

        status = raw_status if raw_status in STATUSES else ""
        priority = raw_priority if raw_priority in PRIORITIES else ""
        category = raw_category if raw_category in CATEGORIES else ""
        sort = raw_sort if raw_sort in ORDER_BY else "newest"

        clauses = []
        params = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        if category:
            clauses.append("category = ?")
            params.append(category)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = "%" + escaped + "%"
            clauses.append(
                "(title LIKE ? ESCAPE '\\' OR requester_name LIKE ? ESCAPE '\\' "
                "OR description LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = "SELECT * FROM tickets" + where + " ORDER BY " + ORDER_BY[sort] + " LIMIT 200"
        rows = get_db().execute(sql, params).fetchall()

        return render_template(
            "tickets.html",
            tickets=[decorate_ticket(row, now) for row in rows],
            filters={"status": status, "priority": priority, "category": category, "q": q, "sort": sort},
            result_count=len(rows),
        )

    @app.route("/tickets/new", methods=["GET", "POST"])
    def ticket_new():
        if request.method == "GET":
            return render_template("ticket_new.html", form={"priority": "P3"}, errors={})

        form = {
            "requester_name": clean(request.form.get("requester_name")),
            "requester_email": clean(request.form.get("requester_email")),
            "category": clean(request.form.get("category")),
            "priority": clean(request.form.get("priority")),
            "title": clean(request.form.get("title")),
            "description": clean(request.form.get("description")),
        }
        errors = {}
        if not form["requester_name"]:
            errors["requester_name"] = "Name is required."
        elif len(form["requester_name"]) > 80:
            errors["requester_name"] = "Name must be 80 characters or fewer."
        if len(form["requester_email"]) > 120 or not EMAIL_RE.match(form["requester_email"]):
            errors["requester_email"] = "A valid email address is required."
        if form["category"] not in CATEGORIES:
            errors["category"] = "Choose a category."
        if form["priority"] not in PRIORITIES:
            errors["priority"] = "Choose a priority."
        if not form["title"]:
            errors["title"] = "Title is required."
        elif len(form["title"]) > 120:
            errors["title"] = "Title must be 120 characters or fewer."
        if not form["description"]:
            errors["description"] = "Description is required."
        elif len(form["description"]) > 2000:
            errors["description"] = "Description must be 2000 characters or fewer."

        if errors:
            return render_template("ticket_new.html", form=form, errors=errors), 400

        now = utc_now()
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO tickets (title, description, requester_name, requester_email, category,
                                    priority, status, level, assignee, kb_reference,
                                    created_at, due_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, 'New', 'L1', NULL, NULL, ?, ?, NULL)""",
            (
                form["title"], form["description"], form["requester_name"], form["requester_email"],
                form["category"], form["priority"], to_db(now),
                to_db(compute_due(now, form["priority"])),
            ),
        )
        ticket_id = cur.lastrowid
        conn.execute(
            """INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
               VALUES (?, 'created', ?, 'Ticket created', ?)""",
            (ticket_id, form["requester_name"], to_db(now)),
        )
        conn.commit()
        flash(f"Ticket {ticket_number(ticket_id)} created.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id), code=303)

    @app.route("/tickets/<int:ticket_id>")
    def ticket_detail(ticket_id):
        now = utc_now()
        ticket = decorate_ticket(load_ticket(ticket_id), now)
        events = [dict(event) for event in get_db().execute(
            "SELECT * FROM ticket_events WHERE ticket_id = ? ORDER BY id ASC", (ticket_id,)
        ).fetchall()]
        allowed_next = [s for s in ("In Progress", "Resolved") if can_transition(ticket["status"], s)]
        can_escalate = can_transition(ticket["status"], "Escalated")
        l2_agents = [name for name, level in AGENTS.items() if level == "L2"]
        return render_template(
            "ticket_detail.html",
            ticket=ticket,
            events=events,
            allowed_next=allowed_next,
            can_escalate=can_escalate,
            l2_agents=l2_agents,
        )

    @app.route("/tickets/<int:ticket_id>/status", methods=["POST"])
    def ticket_status(ticket_id):
        now = utc_now()
        ticket = load_ticket(ticket_id)
        actor = clean(request.form.get("actor"))
        new_status = clean(request.form.get("new_status"))
        note = clean(request.form.get("note"))
        kb_reference = clean(request.form.get("kb_reference"))

        message = None
        if actor not in AGENTS:
            message = "Choose a valid agent."
        elif new_status not in ("In Progress", "Resolved") or not can_transition(ticket["status"], new_status):
            message = "That status change is not allowed."
        elif new_status == "Resolved" and not note:
            message = "A resolution note is required to resolve a ticket."
        elif len(note) > 1000:
            message = "Note must be 1000 characters or fewer."
        elif len(kb_reference) > 200:
            message = "KB reference must be 200 characters or fewer."

        if message:
            return redirect_with_flash(ticket_id, message, False)

        new_assignee = ticket["assignee"] or actor
        new_level = ticket["level"] if ticket["assignee"] else AGENTS[actor]
        conn = get_db()
        if new_status == "In Progress":
            conn.execute(
                "UPDATE tickets SET status = ?, resolved_at = NULL, assignee = ?, level = ? WHERE id = ?",
                (new_status, new_assignee, new_level, ticket_id),
            )
        else:
            conn.execute(
                """UPDATE tickets SET status = ?, resolved_at = ?, assignee = ?, level = ?,
                                      kb_reference = ? WHERE id = ?""",
                (new_status, to_db(now), new_assignee, new_level,
                 kb_reference or ticket["kb_reference"], ticket_id),
            )
        event_note = f"{ticket['status']} -> {new_status}" + (f": {note}" if note else "")
        conn.execute(
            """INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
               VALUES (?, 'status_change', ?, ?, ?)""",
            (ticket_id, actor, event_note, to_db(now)),
        )
        conn.commit()
        return redirect_with_flash(ticket_id, f"Ticket {ticket_number(ticket_id)} moved to {new_status}.", True)

    @app.route("/tickets/<int:ticket_id>/assign", methods=["POST"])
    def ticket_assign(ticket_id):
        ticket = load_ticket(ticket_id)
        actor = clean(request.form.get("actor"))
        assignee = clean(request.form.get("assignee"))

        if actor not in AGENTS or assignee not in AGENTS:
            return redirect_with_flash(ticket_id, "Choose a valid agent.", False)
        if ticket["status"] == "Resolved":
            return redirect_with_flash(ticket_id, "This ticket is resolved. Re-open it before assigning.", False)

        conn = get_db()
        conn.execute(
            "UPDATE tickets SET assignee = ?, level = ? WHERE id = ?",
            (assignee, AGENTS[assignee], ticket_id),
        )
        conn.execute(
            """INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
               VALUES (?, 'assignment', ?, ?, ?)""",
            (ticket_id, actor, f"Assigned to {assignee} ({AGENTS[assignee]})", to_db(utc_now())),
        )
        conn.commit()
        return redirect_with_flash(ticket_id, f"Ticket {ticket_number(ticket_id)} assigned to {assignee}.", True)

    @app.route("/tickets/<int:ticket_id>/escalate", methods=["POST"])
    def ticket_escalate(ticket_id):
        ticket = load_ticket(ticket_id)
        actor = clean(request.form.get("actor"))
        reason = clean(request.form.get("reason"))
        l2_assignee = clean(request.form.get("l2_assignee"))

        message = None
        if actor not in AGENTS:
            message = "Choose a valid agent."
        elif not can_transition(ticket["status"], "Escalated"):
            message = "That status change is not allowed."
        elif not reason:
            message = "An escalation reason is required."
        elif len(reason) > 1000:
            message = "Note must be 1000 characters or fewer."
        elif l2_assignee and (l2_assignee not in AGENTS or AGENTS[l2_assignee] != "L2"):
            message = "Choose a valid agent."

        if message:
            return redirect_with_flash(ticket_id, message, False)

        conn = get_db()
        conn.execute(
            "UPDATE tickets SET status = 'Escalated', level = 'L2', assignee = ? WHERE id = ?",
            (l2_assignee or None, ticket_id),
        )
        note = reason + (f" (assigned to {l2_assignee})" if l2_assignee else " (L2 queue)")
        conn.execute(
            """INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
               VALUES (?, 'escalation', ?, ?, ?)""",
            (ticket_id, actor, note, to_db(utc_now())),
        )
        conn.commit()
        return redirect_with_flash(ticket_id, f"Ticket {ticket_number(ticket_id)} escalated to L2.", True)

    @app.route("/tickets/<int:ticket_id>/note", methods=["POST"])
    def ticket_note(ticket_id):
        load_ticket(ticket_id)
        actor = clean(request.form.get("actor"))
        note = clean(request.form.get("note"))

        if actor not in AGENTS:
            return redirect_with_flash(ticket_id, "Choose a valid agent.", False)
        if not note:
            return redirect_with_flash(ticket_id, "A note is required.", False)
        if len(note) > 1000:
            return redirect_with_flash(ticket_id, "Note must be 1000 characters or fewer.", False)

        conn = get_db()
        conn.execute(
            """INSERT INTO ticket_events (ticket_id, event_type, actor, note, created_at)
               VALUES (?, 'note', ?, ?, ?)""",
            (ticket_id, actor, note, to_db(utc_now())),
        )
        conn.commit()
        return redirect_with_flash(ticket_id, "Note added.", True)

    @app.route("/export.csv")
    def export_csv():
        now = utc_now()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(CSV_HEADER)
        for row in get_db().execute("SELECT * FROM tickets ORDER BY id").fetchall():
            state = sla_state(from_db(row["created_at"]), from_db(row["due_at"]),
                              from_db(row["resolved_at"]) if row["resolved_at"] else None, now)
            values = [
                ticket_number(row["id"]), row["title"], row["requester_name"], row["requester_email"],
                row["category"], row["priority"], row["status"], row["level"], row["assignee"],
                row["kb_reference"], row["created_at"], row["due_at"], row["resolved_at"], state,
            ]
            safe = []
            for value in values:
                text = "" if value is None else str(value)
                if text.startswith(("=", "+", "-", "@")):
                    text = "'" + text
                safe.append(text)
            writer.writerow(safe)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=helpdesk_tickets.csv"},
        )

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5050, debug=False)
