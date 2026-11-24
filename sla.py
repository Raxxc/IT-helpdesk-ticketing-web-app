"""Pure helper functions for SLA maths, ticket workflow rules and dashboard statistics.

Rules for this module:
- No Flask imports, no database access, no reading of the system clock except utc_now().
- Every function that needs "the current time" receives it as an argument named `now`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
IST = timezone(timedelta(hours=5, minutes=30), "IST")

PRIORITIES = ("P1", "P2", "P3", "P4")
PRIORITY_LABELS = {"P1": "Critical", "P2": "High", "P3": "Medium", "P4": "Low"}
SLA_HOURS = {"P1": 1, "P2": 4, "P3": 8, "P4": 24}
AT_RISK_FRACTION = 0.25  # "At Risk" when 25% or less of the total SLA time is left

STATUSES = ("New", "In Progress", "Escalated", "Resolved")
CATEGORIES = ("Hardware", "Software", "Network", "Account/Access", "Email", "Printer", "Other")
LEVELS = ("L1", "L2")

# Demo support team. Maps agent name -> support level.
AGENTS = {
    "Aarav Mehta": "L1",
    "Priya Nair": "L1",
    "Rohan Iyer": "L2",
    "Sneha Kulkarni": "L2",
}

ALLOWED_TRANSITIONS = {
    "New": ("In Progress", "Escalated", "Resolved"),
    "In Progress": ("Escalated", "Resolved"),
    "Escalated": ("In Progress", "Resolved"),
    "Resolved": ("In Progress",),  # re-open
}


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_db(dt: datetime) -> str:
    """Aware datetime -> 'YYYY-MM-DD HH:MM:SS' (UTC) for storing in SQLite."""
    if dt.tzinfo is None:
        raise ValueError("naive datetimes are not allowed")
    return dt.astimezone(timezone.utc).strftime(DB_TIME_FORMAT)


def from_db(text: str) -> datetime:
    """'YYYY-MM-DD HH:MM:SS' (UTC) -> aware UTC datetime."""
    return datetime.strptime(text, DB_TIME_FORMAT).replace(tzinfo=timezone.utc)


def format_ist(dt: datetime) -> str:
    """Aware datetime -> '24 Nov 2026, 14:05' in Indian Standard Time."""
    return dt.astimezone(IST).strftime("%d %b %Y, %H:%M")


def ticket_number(ticket_id: int) -> str:
    return f"INC-{int(ticket_id):04d}"


def can_transition(current: str, new: str) -> bool:
    return new in ALLOWED_TRANSITIONS.get(current, ())


def compute_due(created: datetime, priority: str) -> datetime:
    if priority not in SLA_HOURS:
        raise ValueError(f"unknown priority: {priority!r}")
    return created + timedelta(hours=SLA_HOURS[priority])


def sla_state(created: datetime, due: datetime, resolved_at: datetime | None, now: datetime) -> str:
    """Returns one of: 'Met', 'Missed', 'Breached', 'At Risk', 'On Track'."""
    if resolved_at is not None:
        return "Met" if resolved_at <= due else "Missed"
    if now > due:
        return "Breached"
    total = (due - created).total_seconds()
    remaining = (due - now).total_seconds()
    if remaining <= AT_RISK_FRACTION * total:
        return "At Risk"
    return "On Track"


def format_duration(seconds: float) -> str:
    """3725 -> '1h 2m', 59 -> '<1m', 90000 -> '1d 1h'. Sign is ignored."""
    seconds = int(abs(seconds))
    if seconds < 60:
        return "<1m"
    minutes = seconds // 60
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def sla_message(created: datetime, due: datetime, resolved_at: datetime | None, now: datetime) -> str:
    state = sla_state(created, due, resolved_at, now)
    if state == "Met":
        return f"Resolved with {format_duration((due - resolved_at).total_seconds())} to spare"
    if state == "Missed":
        return f"Resolved {format_duration((resolved_at - due).total_seconds())} after the due time"
    if state == "Breached":
        return f"Overdue by {format_duration((now - due).total_seconds())}"
    return f"{format_duration((due - now).total_seconds())} left"


def dashboard_stats(rows, now: datetime) -> dict:
    """rows: iterable of mappings (dict or sqlite3.Row) with keys
    category, priority, status, created_at, due_at, resolved_at (DB-format strings or None)."""
    by_status = {s: 0 for s in STATUSES}
    open_by_priority = {p: 0 for p in PRIORITIES}
    category_counts: dict[str, int] = {}
    breached_open = 0
    at_risk_open = 0
    resolved_count = 0
    met_count = 0
    resolution_seconds = 0.0
    total = 0

    for row in rows:
        total += 1
        status = row["status"]
        by_status[status] += 1
        category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1

        created = from_db(row["created_at"])
        due = from_db(row["due_at"])
        resolved = from_db(row["resolved_at"]) if row["resolved_at"] else None
        state = sla_state(created, due, resolved, now)

        if resolved is None:
            open_by_priority[row["priority"]] += 1
            if state == "Breached":
                breached_open += 1
            elif state == "At Risk":
                at_risk_open += 1
        else:
            resolved_count += 1
            resolution_seconds += (resolved - created).total_seconds()
            if state == "Met":
                met_count += 1

    compliance = round(100.0 * met_count / resolved_count, 1) if resolved_count else None
    avg_hours = round(resolution_seconds / resolved_count / 3600.0, 1) if resolved_count else None
    by_category = sorted(category_counts.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "total": total,
        "by_status": by_status,
        "open_by_priority": open_by_priority,
        "by_category": by_category,
        "breached_open": breached_open,
        "at_risk_open": at_risk_open,
        "resolved_count": resolved_count,
        "sla_compliance_pct": compliance,
        "avg_resolution_hours": avg_hours,
    }
