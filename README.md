# HelpDesk Lite

HelpDesk Lite is a small, local IT servcie desk ticketing web app. It lets a support agent log incidents, track them against SLA deadlines, escalate them from L1 to L2, record resolution notes and KB references, and see dashboard metrics — the day-to-day workflow of a Service Desk, in one offline Flask app.

## Features

- Log tickets with requester, category, priority (P1-P4), title and description.
- Track status (New, In Progress, Escalated, Resolved), support level (L1/L2) and assignee.
- SLA due times with five visible states: On Track, At Risk, Breached, Met, Missed.
- Mandatory reason for L1 -> L2 escalation; optional assignment to a named L2 agent.
- Resolution notes and an optional KB article reference on resolved tickets.
- A timestamped timeline of events on every ticket.
- Dashboard: status counts, open tickets by priority, tickets by category, SLA compliance %, average resolution time, and a "Needs attention" list of breached open tickets.
- Filter/search by status, priority, category and free text; sort by newest, due time or priority.
- CSV export with a formula-injection guard on text cells.
- Health check endpoint (`/healthz`) and 16 automated tests.

## How the SLA works

SLA clocks use **calendar hours**, starting when the ticket is created. Due time = created time + the hours below.

| Priority | Meaning | SLA |
| --- | --- | --- |
| P1 | Critical | 1 h |
| P2 | High | 4 h |
| P3 | Medium | 8 h |
| P4 | Low | 24 h |

The five states (logic lives in `sla.py`, function `sla_state`):

| State | How it is decided |
| --- | --- |
| Met | Ticket is resolved at or before its due time. |
| Missed | Ticket is resolved after its due time. |
| Breached | Ticket is still open and the current time is past the due time. |
| At Risk | Ticket is still open and 25% or less of the total SLA time remains (exactly at the due time still counts as At Risk). |
| On Track | Ticket is still open and more than 25% of the SLA time remains. |

All times are stored in UTC in SQLite and displayed in IST (`format_ist`, UTC+05:30).

## How to run

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python seed.py --reset
python app.py
```

Then open <http://127.0.0.1:5050>. Port 5050 is used instead of 5000 because recent macOS versions use 5000 for AirPlay.

To start empty instead of with demo data, skip `python seed.py --reset`.

## How to run tests

```bash
python -m unittest discover -s tests -v
```

Tests create their own temporary database, so they never change `helpdesk.db`.

## Project structure

```
HelpOut! - Test/
  app.py                  Flask app factory, routes, validation, CSV export
  sla.py                  Pure SLA/workflow/statistics functions (no Flask, no DB)
  db.py                   SQLite connection per request, schema initialisation
  schema.sql              tickets and ticket_events tables plus indexes
  seed.py                 Deterministic demo data generator
  requirements.txt        Only dependency: Flask
  static/style.css        Single stylesheet, system fonts, no CDN
  templates/              Six Jinja2 templates
  tests/test_sla.py       Unit tests for pure SLA logic
  tests/test_app.py       Integration tests using Flask's test client
```

Request flow: browser -> Flask route in `app.py` -> `db.py` connection -> SQLite file -> decorated rows -> Jinja template -> HTML response. Every state change writes the ticket row and its `ticket_events` row in one transaction.

## Design decisions

- **SQLite** needs no server or setup; it is a good fit for a single-user demo and keeps the project fully offline.
- **SLA logic lives in a pure module** (`sla.py`) with no Flask or database imports, so it can be unit tested with fixed datetimes and reused by both routes and the dashboard. Deterministic tests make SLA behaviour easy to prove.
- **SQL uses `?` placeholders** and whitelists for sort/filter values; user text is never concatenated into SQL. Templates rely on Jinja auto-escaping, and CSV export escapes spreadsheet formulas.
- **Application factory** (`create_app`) allows tests to inject a temporary database configuration.

## Limitations

- No login or authentication — single-user demo only.
- SLA uses calendar hours, not business hours or holidays.
- No email notifications or automatic escalation jobs.
- No attachments, multi-user concurrency controls or real knowledge-base backend.

## Ideas for next steps

- Add authentication and role-based access (L1 vs L2).
- Add business-hours-aware SLA calendars and reminder notifications.
- Add a real KB table and link articles to ticket categories.
- Add pagination and drag-and-drop triage board.
