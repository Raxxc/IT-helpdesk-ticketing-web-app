PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS tickets (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    requester_name TEXT NOT NULL,
    requester_email TEXT NOT NULL,
    category       TEXT NOT NULL CHECK (category IN ('Hardware','Software','Network','Account/Access','Email','Printer','Other')),
    priority       TEXT NOT NULL CHECK (priority IN ('P1','P2','P3','P4')),
    status         TEXT NOT NULL DEFAULT 'New' CHECK (status IN ('New','In Progress','Escalated','Resolved')),
    level          TEXT NOT NULL DEFAULT 'L1' CHECK (level IN ('L1','L2')),
    assignee       TEXT,
    kb_reference   TEXT,
    created_at     TEXT NOT NULL,
    due_at         TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE TABLE IF NOT EXISTS ticket_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id  INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('created','status_change','assignment','escalation','note')),
    actor      TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tickets_status   ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
CREATE INDEX IF NOT EXISTS idx_events_ticket    ON ticket_events(ticket_id);
