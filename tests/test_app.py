"""Integration tests for HelpDesk Lite. Uses a temporary SQLite file, never helpdesk.db."""
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import seed  # noqa: E402
from app import create_app  # noqa: E402

CSV_HEADER_LINE = (
    "ticket_number,title,requester_name,requester_email,category,priority,status,level,"
    "assignee,kb_reference,created_at_utc,due_at_utc,resolved_at_utc,sla_state"
)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path})
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_ticket(self, **overrides):
        data = {
            "requester_name": "Test User",
            "requester_email": "test@example.com",
            "category": "Network",
            "priority": "P3",
            "title": "Wi-Fi down",
            "description": "No connection",
        }
        data.update(overrides)
        return self.client.post("/tickets/new", data=data)

    def action(self, ticket_id, name, **data):
        return self.client.post(
            f"/tickets/{ticket_id}/{name}", data=data, follow_redirects=True
        )

    def ticket_row(self, ticket_id=1):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        finally:
            conn.close()

    def count(self, table="tickets"):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def test_01_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"ok")

    def test_02_empty_dashboard(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)
        self.assertIn(b"No tickets yet", response.data)

    def test_03_create_valid_ticket(self):
        response = self.make_ticket()
        self.assertIn(response.status_code, (302, 303))
        row = self.ticket_row()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "New")
        self.assertEqual(row["level"], "L1")
        self.assertIn(b"INC-0001", self.client.get("/tickets/1").data)

    def test_04_invalid_priority_rejected(self):
        response = self.make_ticket(priority="P9")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.count(), 0)

    def test_05_empty_title_rejected(self):
        response = self.make_ticket(title="")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Title is required.", response.data)
        self.assertEqual(self.count(), 0)

    def test_06_resolve_without_note_rejected(self):
        self.make_ticket()
        response = self.action(1, "status", actor="Aarav Mehta", new_status="Resolved", note="")
        self.assertIn(b"A resolution note is required", response.data)
        self.assertEqual(self.ticket_row()["status"], "New")

    def test_07_new_to_in_progress(self):
        self.make_ticket()
        self.action(1, "status", actor="Aarav Mehta", new_status="In Progress", note="Looking into it")
        row = self.ticket_row()
        self.assertEqual(row["status"], "In Progress")
        self.assertEqual(row["assignee"], "Aarav Mehta")
        self.assertEqual(row["level"], "L1")

    def test_08_resolve_with_note_and_kb(self):
        self.make_ticket()
        note = "Cleared the DNS cache and reconnected."
        self.action(1, "status", actor="Priya Nair", new_status="Resolved", note=note,
                    kb_reference="KB-001")
        row = self.ticket_row()
        self.assertEqual(row["status"], "Resolved")
        self.assertIsNotNone(row["resolved_at"])
        self.assertEqual(row["kb_reference"], "KB-001")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            events = conn.execute(
                "SELECT * FROM ticket_events WHERE ticket_id = 1 AND event_type = 'status_change'"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(len(events), 1)
        self.assertIn(note, events[0]["note"])

    def test_09_reopen_resolved_ticket(self):
        self.make_ticket()
        self.action(1, "status", actor="Priya Nair", new_status="Resolved", note="Fixed")
        self.assertIsNotNone(self.ticket_row()["resolved_at"])
        self.action(1, "status", actor="Priya Nair", new_status="In Progress", note="Reopened")
        row = self.ticket_row()
        self.assertEqual(row["status"], "In Progress")
        self.assertIsNone(row["resolved_at"])

    def test_10_escalation_requires_reason(self):
        self.make_ticket()
        response = self.action(1, "escalate", actor="Aarav Mehta", reason="", l2_assignee="")
        self.assertIn(b"An escalation reason is required", response.data)
        self.assertEqual(self.ticket_row()["status"], "New")

        self.action(1, "escalate", actor="Aarav Mehta",
                    reason="Needs network team to check switch port", l2_assignee="Rohan Iyer")
        row = self.ticket_row()
        self.assertEqual(row["status"], "Escalated")
        self.assertEqual(row["level"], "L2")
        self.assertEqual(row["assignee"], "Rohan Iyer")

    def test_11_resolved_cannot_be_escalated(self):
        self.make_ticket()
        self.action(1, "status", actor="Priya Nair", new_status="Resolved", note="Fixed")
        response = self.action(1, "escalate", actor="Aarav Mehta", reason="Second look", l2_assignee="")
        self.assertIn(b"That status change is not allowed", response.data)
        self.assertEqual(self.ticket_row()["status"], "Resolved")

    def test_12_assignment_rules(self):
        self.make_ticket()
        self.action(1, "assign", actor="Aarav Mehta", assignee="Sneha Kulkarni")
        row = self.ticket_row()
        self.assertEqual(row["assignee"], "Sneha Kulkarni")
        self.assertEqual(row["level"], "L2")

        self.action(1, "status", actor="Sneha Kulkarni", new_status="Resolved", note="Done")
        response = self.action(1, "assign", actor="Aarav Mehta", assignee="Priya Nair")
        self.assertIn(b"This ticket is resolved", response.data)
        self.assertEqual(self.ticket_row()["assignee"], "Sneha Kulkarni")

    def test_13_filters_and_search(self):
        self.make_ticket()
        self.make_ticket(title="Printer offline", description="Paper jam")
        self.action(1, "status", actor="Aarav Mehta", new_status="Resolved", note="Fixed")

        resolved = self.client.get("/tickets?status=Resolved")
        self.assertEqual(resolved.status_code, 200)
        self.assertIn(b"Wi-Fi down", resolved.data)
        self.assertNotIn(b"Printer offline", resolved.data)

        found = self.client.get("/tickets?q=Wi-Fi")
        self.assertEqual(found.status_code, 200)
        self.assertIn(b"Wi-Fi down", found.data)
        self.assertNotIn(b"Printer offline", found.data)

    def test_14_csv_export(self):
        self.make_ticket()
        response = self.client.get("/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertEqual(response.data.decode("utf-8").splitlines()[0], CSV_HEADER_LINE)

    def test_15_seeded_data_renders(self):
        seed.seed(self.db_path, reset=True)
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"SLA compliance", dashboard.data)
        self.assertEqual(self.client.get("/tickets").status_code, 200)

    def test_16_missing_ticket_is_404(self):
        self.assertEqual(self.client.get("/tickets/999").status_code, 404)


if __name__ == "__main__":
    unittest.main()
