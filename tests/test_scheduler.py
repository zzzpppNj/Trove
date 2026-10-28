import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import negotiation_due_scheduler as scheduler  # noqa: E402


class SchedulerGroupingTest(unittest.TestCase):
    def test_groups_records_by_their_own_thread(self):
        records = [
            {"id": "a", "thread_id": "t1"},
            {"id": "b", "thread_id": "t2"},
            {"id": "c", "thread_id": "t1"},
        ]
        grouped = scheduler.group_by_thread(records, "fallback")
        self.assertEqual(sorted(item["id"] for item in grouped["t1"]), ["a", "c"])
        self.assertEqual([item["id"] for item in grouped["t2"]], ["b"])

    def test_falls_back_when_record_has_no_thread(self):
        records = [
            {"id": "a", "thread_id": ""},
            {"id": "b", "thread_id": "t2"},
        ]
        grouped = scheduler.group_by_thread(records, "fallback")
        self.assertEqual(grouped["fallback"], [records[0]])
        self.assertEqual(grouped["t2"], [records[1]])


if __name__ == "__main__":
    unittest.main()
