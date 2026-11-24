import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sla  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 11, 24, 10, 0, 0, tzinfo=UTC)


class TestTimeHelpers(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(sla.to_db(T0), "2026-11-24 10:00:00")
        self.assertEqual(sla.from_db("2026-11-24 10:00:00"), T0)

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            sla.to_db(datetime(2026, 11, 24, 10, 0, 0))

    def test_format_ist(self):
        self.assertEqual(sla.format_ist(T0), "24 Nov 2026, 15:30")

    def test_ticket_number(self):
        self.assertEqual(sla.ticket_number(7), "INC-0007")
        self.assertEqual(sla.ticket_number(12345), "INC-12345")


class TestWorkflow(unittest.TestCase):
    def test_agents(self):
        self.assertEqual(set(sla.AGENTS.values()), {"L1", "L2"})

    def test_transitions(self):
        self.assertTrue(sla.can_transition("New", "In Progress"))
        self.assertTrue(sla.can_transition("New", "Resolved"))
        self.assertTrue(sla.can_transition("Escalated", "In Progress"))
        self.assertTrue(sla.can_transition("Resolved", "In Progress"))
        self.assertFalse(sla.can_transition("Resolved", "Escalated"))
        self.assertFalse(sla.can_transition("In Progress", "New"))
        self.assertFalse(sla.can_transition("Nonsense", "New"))


class TestSla(unittest.TestCase):
    def test_due_times(self):
        self.assertEqual(sla.compute_due(T0, "P1"), T0 + timedelta(hours=1))
        self.assertEqual(sla.compute_due(T0, "P2"), T0 + timedelta(hours=4))
        self.assertEqual(sla.compute_due(T0, "P3"), T0 + timedelta(hours=8))
        self.assertEqual(sla.compute_due(T0, "P4"), T0 + timedelta(hours=24))
        with self.assertRaises(ValueError):
            sla.compute_due(T0, "P9")

    def test_states_open_ticket(self):
        due = sla.compute_due(T0, "P3")  # 8h window, at risk when <= 2h left
        self.assertEqual(sla.sla_state(T0, due, None, T0 + timedelta(hours=1)), "On Track")
        self.assertEqual(sla.sla_state(T0, due, None, T0 + timedelta(hours=6)), "At Risk")  # exactly 2h left
        self.assertEqual(sla.sla_state(T0, due, None, T0 + timedelta(hours=7)), "At Risk")
        self.assertEqual(sla.sla_state(T0, due, None, due), "At Risk")  # exactly due is not yet breached
        self.assertEqual(sla.sla_state(T0, due, None, due + timedelta(seconds=1)), "Breached")

    def test_states_resolved_ticket(self):
        due = sla.compute_due(T0, "P2")
        self.assertEqual(sla.sla_state(T0, due, T0 + timedelta(hours=3), T0 + timedelta(days=9)), "Met")
        self.assertEqual(sla.sla_state(T0, due, due, T0 + timedelta(days=9)), "Met")
        self.assertEqual(sla.sla_state(T0, due, due + timedelta(minutes=1), T0 + timedelta(days=9)), "Missed")

    def test_format_duration(self):
        self.assertEqual(sla.format_duration(0), "<1m")
        self.assertEqual(sla.format_duration(59), "<1m")
        self.assertEqual(sla.format_duration(60), "1m")
        self.assertEqual(sla.format_duration(3725), "1h 2m")
        self.assertEqual(sla.format_duration(-3725), "1h 2m")
        self.assertEqual(sla.format_duration(90000), "1d 1h")

    def test_messages(self):
        due = sla.compute_due(T0, "P2")
        self.assertEqual(sla.sla_message(T0, due, None, T0 + timedelta(hours=1)), "3h 0m left")
        self.assertEqual(sla.sla_message(T0, due, None, due + timedelta(minutes=40)), "Overdue by 40m")
        self.assertEqual(sla.sla_message(T0, due, T0 + timedelta(hours=3), T0 + timedelta(days=1)),
                         "Resolved with 1h 0m to spare")
        self.assertEqual(sla.sla_message(T0, due, due + timedelta(minutes=5), T0 + timedelta(days=1)),
                         "Resolved 5m after the due time")


def make_row(category, priority, status, created, resolved=None):
    return {
        "category": category,
        "priority": priority,
        "status": status,
        "created_at": sla.to_db(created),
        "due_at": sla.to_db(sla.compute_due(created, priority)),
        "resolved_at": sla.to_db(resolved) if resolved else None,
    }


class TestDashboardStats(unittest.TestCase):
    def test_empty(self):
        stats = sla.dashboard_stats([], T0)
        self.assertEqual(stats["total"], 0)
        self.assertIsNone(stats["sla_compliance_pct"])
        self.assertIsNone(stats["avg_resolution_hours"])
        self.assertEqual(stats["by_status"], {"New": 0, "In Progress": 0, "Escalated": 0, "Resolved": 0})
        self.assertEqual(stats["by_category"], [])

    def test_mixed(self):
        now = T0 + timedelta(hours=10)
        rows = [
            make_row("Network", "P2", "Resolved", T0, T0 + timedelta(hours=3)),       # met, 3h
            make_row("Network", "P1", "Resolved", T0, T0 + timedelta(hours=2)),       # missed, 2h
            make_row("Printer", "P3", "In Progress", T0 + timedelta(hours=5)),        # 3h left of 8h -> On Track
            make_row("Email", "P4", "New", T0 - timedelta(hours=30)),                 # overdue -> breached
            make_row("Email", "P3", "Escalated", T0 + timedelta(hours=2)),            # due exactly 'now' -> 0h left -> At Risk
        ]
        stats = sla.dashboard_stats(rows, now)
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["by_status"], {"New": 1, "In Progress": 1, "Escalated": 1, "Resolved": 2})
        self.assertEqual(stats["resolved_count"], 2)
        self.assertEqual(stats["sla_compliance_pct"], 50.0)
        self.assertEqual(stats["avg_resolution_hours"], 2.5)
        self.assertEqual(stats["breached_open"], 1)
        self.assertEqual(stats["at_risk_open"], 1)
        self.assertEqual(stats["open_by_priority"], {"P1": 0, "P2": 0, "P3": 2, "P4": 1})
        self.assertEqual(stats["by_category"], [("Email", 2), ("Network", 2), ("Printer", 1)])


if __name__ == "__main__":
    unittest.main()
