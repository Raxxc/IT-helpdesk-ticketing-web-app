# Interview Guide: HelpDesk Lite -> Digital Workplace Services (Service Desk)

Read this after you have run the app once. It is your "should know about this project" map.
Everything here describes the code in this folder. Only say things you actually understand;
this is a **demo project**, not a production system used by real clients.

---

## 1. Why this project fits the job description

| JD line | Where it appears in the project |
| --- | --- |
| "First point of contact for end-users reporting IT issues" | `/tickets/new` form: requester name/email, category, title, description -> creates a New ticket |
| "Log, track and resolve tickets accurately and within defined SLAs" | `tickets` table, status workflow, `due_at`, `sla_state`, dashboard metrics |
| "Troubleshoot hardware and software issues to minimise downtime" | Categories (Hardware, Software, Network, Account/Access, Email, Printer, Other) and resolution notes |
| "Collaborate with internal IT teams to escalate complex scenarios" | L1 -> L2 escalation with a **mandatory reason** and optional L2 assignee |
| "Build and maintain knowledge base articles for faster resolution" | `kb_reference` field on resolved tickets + `ticket_events` audit trail |
| "Client-focused mindset, diverse cultures" | Clear requester fields, plain-language UI, IST display, respectful written notes |
| "Strong verbal and written communication" | Resolution notes, escalation reasons, timeline entries, flash confirmations |
| "Willingness to work in shifts from the office" | Not a technical feature — be ready to answer this directly and honestly |

---

## 2. Tech stack map (what talks to what)

| Layer | Technology | Files | Job | Interview hook |
| --- | --- | --- | --- | --- |
| UI | HTML forms + Jinja2 templates + one CSS file | `templates/`, `static/style.css` | Server-rendered pages; user submits forms, sees tables and badges | "No JavaScript on purpose: offline, no build step, simple to reason about" |
| Web framework | Flask 3.x | `app.py` | Routing, request parsing, validation, flash messages, redirects, error handling | Application factory `create_app(test_config)` |
| Business rules | Pure Python | `sla.py` | SLA maths, allowed status transitions, dashboard statistics | No Flask/DB imports -> easy to unit test with fixed times |
| Data access | `sqlite3` | `db.py`, `schema.sql` | One connection per request, foreign keys ON, tables + indexes | `flask.g` + `teardown_appcontext(close_db)` |
| Data | SQLite file `helpdesk.db` | created at runtime | `tickets` + `ticket_events` tables | `?` placeholders, `ON DELETE CASCADE`, indexes |
| Demo data | Python CLI (`argparse`, `random`) | `seed.py` | 24 deterministic tickets (`Random(42)`) | `--reset` wipes and recreates data |
| Tests | `unittest` | `tests/test_sla.py`, `tests/test_app.py` | 29 tests: 13 pure-logic + 16 integration | Temporary DB per test; real DB untouched |
| Config | Environment variables | `app.py` | `SECRET_KEY`, `HELPDESK_DB` | Tests inject config; no hard-coded paths |

### Request flow (the answer to "how do the pieces communicate?")

```
Browser (HTML form / link)
      |
      v
Flask route in app.py  ---- reads request.form / request.args
      |
      +--> validation (app.py) ---------- rejects with 400 (new ticket) or flash + 303 (actions)
      |
      +--> db.get_db() ------------------ SQLite connection stored on flask.g for this request
      |         |
      |         v
      |    schema.sql tables: tickets (current state), ticket_events (audit trail)
      |
      +--> sla.py functions ------------- SLA state, due time, dashboard stats
      |
      v
Jinja2 template -> HTML response -> browser
```

**Write flow for an action** (status change, assign, escalate, note):

```
POST /tickets/<id>/status
  -> load ticket (404 if missing)
  -> validate actor, new status, note, KB reference
  -> UPDATE tickets ...            (one transaction)
  -> INSERT ticket_events ...      (same transaction)
  -> conn.commit()                 (all or nothing)
  -> flash("...", "success")
  -> 303 redirect to ticket detail  (Post/Redirect/Get)
```

Why 303? After a POST, redirecting with GET stops the user from re-submitting the form when they refresh
and keeps the browser's Back/Reload button safe.

---

## 3. "Should know about this project" checklist

Tick these off; each one is a likely follow-up question.

### Ticket workflow
- [ ] Statuses: **New, In Progress, Escalated, Resolved**.
- [ ] Allowed transitions: New -> In Progress / Escalated / Resolved; In Progress -> Escalated / Resolved;
      Escalated -> In Progress / Resolved; Resolved -> In Progress (re-open only).
- [ ] Re-opening sets `resolved_at = NULL`; resolving stores the UTC time and requires a resolution note.
- [ ] Assignment sets `level` from `AGENTS` (Aarav/Priya = L1; Rohan/Sneha = L2). A resolved ticket cannot be reassigned.
- [ ] Escalation requires a reason; it sets status `Escalated`, level `L2`, and optionally assigns an L2 agent.
- [ ] Every change also appends a `ticket_events` row (`created`, `status_change`, `assignment`, `escalation`, `note`).

### SLA logic (the heart of the project)
- [ ] Due time = created time + SLA hours: **P1 1h, P2 4h, P3 8h, P4 24h** (calendar hours).
- [ ] Five states: `Met` (resolved on/before due), `Missed` (resolved after due), `Breached` (open and past due),
      `At Risk` (open, <= 25% of the window left), `On Track` (open, > 25% left).
- [ ] At exactly the due time: still open -> `At Risk`, resolved -> `Met`. One second later while open -> `Breached`.
- [ ] SLA math lives in `sla.py` and receives `now` as an argument. This makes tests deterministic —
      no relying on the real clock, no `datetime.utcnow()`.

### Data and security
- [ ] `sla.utc_now()` gives timezone-aware UTC; DB stores `YYYY-MM-DD HH:MM:SS` UTC strings; the `ist` filter displays IST.
- [ ] All user values in SQL go through `?` placeholders. Sorting uses a whitelist dictionary, never raw input.
- [ ] Search escapes `\`, `%` and `_` so wildcard characters in user input are treated literally.
- [ ] Jinja auto-escapes values; `|safe` is forbidden (it would allow stored XSS).
- [ ] CSV export prefixes `'` to cells starting with `=`, `+`, `-`, `@` to block spreadsheet formula injection.
- [ ] `PRAGMA foreign_keys = ON` and `ON DELETE CASCADE` keep the event table consistent with tickets.
- [ ] Indexes on status, priority and ticket_id make common filters fast.

### Architecture and testing
- [ ] App factory means tests can inject `{"TESTING": True, "DATABASE": temp_path}`.
- [ ] `close_db` is registered with `teardown_appcontext`, so connections are closed even on errors.
- [ ] `tests/test_sla.py` = unit tests (pure functions); `tests/test_app.py` = integration tests (Flask test client).
- [ ] 29 tests pass with `python -m unittest discover -s tests -v`.
- [ ] Known limitations: no login, no CSRF protection, single user, calendar hours not business hours,
      no email notifications, no attachments, no real KB table.

---

## 4. Likely questions and how to answer them

### Q: "Walk me through your project in 60 seconds."
> "HelpDesk Lite is a local ticketing app I built with Flask and SQLite to model a Service Desk workflow.
> An agent logs an incident with requester details, category and priority; the app calculates an SLA due time
> and shows whether the ticket is On Track, At Risk or Breached. Tickets move through New, In Progress,
> Escalated and Resolved, and every action writes an audit event. Escalation to L2 requires a reason, and
> resolved tickets can carry a resolution note and KB reference. A dashboard shows SLA compliance and average
> resolution time. I kept the SLA rules in a separate pure module so they could be unit tested, and wrote 29 tests."

### Q: "How does a ticket move from creation to resolution?"
> "The new-ticket form validates name, email, category, priority, title and description. On success we insert a
> ticket with status New, level L1 and a due time computed from priority, plus a `created` event. An agent then
> moves it to In Progress, optionally assigns it, or escalates it with a reason. Resolving requires a note and
> stores `resolved_at`. In the same database transaction we insert a `status_change` event, commit, flash a
> confirmation and redirect to the ticket detail page."

### Q: "What is SLA and how did you implement it?"
> "A service-level agreement is the promised time to resolve an issue by priority. Here P1 gets 1 hour, P2 4,
> P3 8 and P4 24. I store created and due times in UTC, then a pure function compares them with the current time
> and returns one of five states: On Track, At Risk when 25% or less time remains, Breached when overdue and open,
> Met when resolved in time, Missed when resolved late. The dashboard uses the same function so numbers and badges
> can never disagree."

### Q: "Why require a reason for escalation?"
> "Because escalation is a hand-off to another team. A mandatory reason forces the L1 agent to summarise what was
> tried and what is still wrong, which helps L2 start faster, creates an audit trail, and builds reusable knowledge.
> That maps directly to the JD's 'collaborate with internal IT teams' and 'knowledge base' responsibilities."

### Q: "How do you keep the data consistent?"
> "Each action updates the ticket and inserts its event in one transaction, then calls commit once. If validation
> fails, nothing is written. Foreign keys are enabled, and events cascade when a ticket is deleted."

### Q: "What did you do to prevent SQL injection / XSS?"
> "User values are never concatenated into SQL; every value uses `?` placeholders. Sort order comes from a fixed
> whitelist. Jinja auto-escapes output and I never use `|safe`. Search input escapes `%`, `_` and backslash so
> wildcards are literal. CSV export also guards against formula injection."

### Q: "Why Flask and SQLite? Why no JavaScript?"
> "Flask is small and lets me keep the whole app in a few readable files; SQLite needs no server, which keeps the
> project offline and portable. Server-rendered HTML forms are enough for this workflow, so there is no build step,
> no CDN and no dependency on a browser running extra code."

### Q: "How did you test it?"
> "Two levels. `test_sla.py` unit-tests pure functions with fixed datetimes, including edge cases like exactly at
> the due time. `test_app.py` uses Flask's test client against a temporary SQLite file and covers creation,
> validation, workflow rules, filters, CSV export, seeded data and 404s. The real database is never touched."

### Q: "How does this project relate to a Service Desk job?"
> "It mirrors the daily loop: receive an issue, log it correctly, prioritise it, work the SLA, escalate with context,
> resolve with a documented fix, and record KB references so the next agent resolves it faster. It also shows I can
> communicate technical information clearly in writing, which matters when supporting users across cultures."

### Q: "What would you improve next?"
> "Add authentication and roles, business-hours-aware SLAs, reminder notifications before At Risk, a real KB table,
> pagination, and CSRF protection. In a real Service Desk I would also integrate with the ticketing platform and
> reporting dashboards."

### Q: "Why are you OK with shifts / office work?"
> "I understand support is time-critical and coverage matters, especially for P1 incidents. I'm willing to work in
> shifts from the office, and the project reflects that mindset: SLA clocks are explicit and the dashboard surfaces
> breached tickets immediately so nothing is missed during a handover."

---

## 5. STAR story bank (use only what is true for you)

### Story 1: "Built a service-desk workflow tool from scratch"
**Use for:** initiative, problem-solving, technical skill, understanding of the role.
- **S:** "I wanted to demonstrate Service Desk skills practically, not just list them on a resume."
- **T:** "I set out to build a local ticketing app covering logging, SLA tracking, escalation and knowledge capture."
- **A:** "I separated SLA rules into a pure module, designed two SQLite tables with an audit-trail event table, added
  validation and transaction-based updates, and wrote both unit and integration tests."
- **R:** "The app runs offline with 29 passing tests and a dashboard showing SLA compliance and resolution time."
- **Short version:** "I built a Flask ticketing app that models the full Service Desk loop, with 29 automated tests
  and SLA rules separated from the web layer so they can be tested independently."

### Story 2: "Handling ambiguous requirements"
**Use for:** problem-solving, attention to detail.
- **S:** "The specification did not define every edge case, for example what happens exactly at the SLA deadline."
- **T:** "I needed consistent behaviour that would also be easy to explain to an interviewer or a support agent."
- **A:** "I made explicit rules: exactly at the due time an open ticket is At Risk and a resolved ticket is Met;
  one second later while open it is Breached. I encoded those rules as unit tests."
- **R:** "The behaviour is deterministic and documented, and the dashboard cannot disagree with the ticket badge."

### Story 3 (template — fill with a REAL incident you have handled)
**Use for:** "Tell me about a difficult user / incident."
- **S:** "A user reported [issue] and was [frustrated/urgent] because [business impact]."
- **T:** "As the first point of contact, I had to [acknowledge, gather information, restore service]."
- **A:** "I listened, confirmed impact, asked structured questions (what changed, since when, who else affected),
  checked [system], documented each step, and escalated to [team] with a clear summary when needed."
- **R:** "Service was restored in [time], the user was updated, and I recorded the fix as a KB note for reuse."

**Do not invent workplace experience.** If you have none, say: "My hands-on practice has been through this project;
here is how I would apply that structure in a real ticket."

---

## 6. "Tell me about yourself" script (tailored)

> "I'm a beginner developer with a strong interest in IT support and service delivery. I recently built HelpDesk Lite,
> a Flask and SQLite ticketing app that models the Service Desk workflow: logging tickets, SLA deadlines, L1-to-L2
> escalation with a reason, resolution notes and KB references, and a dashboard for compliance. I wrote 29 automated
> tests and deliberately kept the SLA logic separate from the web layer so it is easy to verify. What attracts me to
> the Digital Workplace Services role is the combination of troubleshooting, clear communication with users, and
> disciplined tracking of issues. I'm comfortable working in shifts from the office and I want to grow in a team
> where service quality is measured."

---

## 7. Questions to ask the interviewer

1. "What does a typical shift look like, and how are tickets handed over between shifts?"
2. "Which ticketing platform does the team use, and how is the escalation matrix defined?"
3. "How are SLA targets set for P1-P4 incidents, and which metric matters most to the team?"
4. "Who owns the knowledge base, and how are KB articles reviewed for accuracy?"
5. "What does success look like in the first 30 to 60 days for a new Service Desk analyst?"

---

## 8. Resume bullets you can adapt (truthful for this project)

- Built a Flask + SQLite ticketing app modelling the Service Desk lifecycle: ticket logging, L1/L2 assignment,
  SLA tracking, escalation with mandatory justification, and resolution with KB references.
- Implemented a 5-state SLA engine (On Track, At Risk, Breached, Met, Missed) with UTC storage and IST display,
  plus a dashboard reporting SLA compliance and average resolution time.
- Hardened data handling with parameterized SQL, input validation, whitelisted sorting and CSV formula-injection
  protection; wrote 29 unit and integration tests using temporary databases.

**Avoid:** claiming real clients, production traffic, or enterprise integrations. Say "demo project".

---

## 9. Red flags to avoid in the interview

- Blaming users or calling an issue "simple" — show a client-focused mindset.
- Claiming you used ServiceNow/ITSM tools you have not used; say this project is your hands-on analogue.
- Not knowing your own numbers: P1=1h, P2=4h, P3=8h, P4=24h, 25% At Risk threshold, 29 tests, port 5050.
- Saying "I don't know" with no follow-up — say what you would check or how you would find out.
- Complaining about shifts; the JD explicitly expects shift work from the office.
