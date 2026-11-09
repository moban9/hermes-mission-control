import json
import os
import sqlite3
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import reducer


class TaskFilterProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "board.db")
        c = sqlite3.connect(self.path)
        c.executescript("""
          CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,assignee TEXT,status TEXT,block_kind TEXT,current_step_key TEXT,started_at INTEGER,completed_at INTEGER,priority INTEGER,created_at INTEGER,consecutive_failures INTEGER);
          CREATE TABLE task_links(parent_id TEXT,child_id TEXT);
          CREATE TABLE task_runs(id INTEGER PRIMARY KEY,task_id TEXT,profile TEXT,outcome TEXT,error TEXT,started_at INTEGER,ended_at INTEGER,summary TEXT);
          CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id TEXT,kind TEXT,payload TEXT,created_at INTEGER);
        """)
        tasks = [
            ("f", "failed", "p", "blocked", "capability", None, 1, None, 1, 1, 0),
            ("d", "recovered", "p", "done", None, None, 1, 4, 1, 2, 0),
            ("o", "open retry", "p", "running", None, None, 1, None, 1, 3, 0),
            ("a", "archived", "p", "archived", "transient", None, 1, None, 1, 4, 0),
            ("s", "stale kind", "p", "ready", "dependency", None, 1, None, 1, 5, 0),
        ]
        c.executemany("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", tasks)
        runs = [(i, "f", "p", "crashed" if i in {1, 3, 5, 7, 9, 11} else "completed", 'diagnostic:v1 last_tool=browser_click approval_state=denied tool_call_id=call-<x> source=approval' if i == 11 else None, i, i, "") for i in range(1, 12)]
        runs += [(12, "d", "p", "crashed", "old", 1, 2, ""), (13, "d", "p", "completed", None, 2, 4, "")]
        runs += [(14, "o", "p", "crashed", "old failure", 1, 2, ""), (15, "o", "p", None, None, 3, None, "")]
        runs += [(16, "a", "p", "failed", "archived", 1, 2, "")]
        c.executemany("INSERT INTO task_runs VALUES(?,?,?,?,?,?,?,?)", runs)
        c.execute("INSERT INTO task_events VALUES(1,'f','blocked',?,20)", (json.dumps({"reason": "needs protocol correction"}),))
        c.commit(); c.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_latest_run_semantics_and_reason(self):
        r = reducer.reduce_task_filters(now=30, path=self.path)
        filters = r["task_filters"]
        self.assertTrue(filters["available"])
        self.assertEqual(set(filters), {"version", "available", "error", "generated_at", "scope", "limit", "categories", "success_rate_pct"})
        cats = filters["categories"]
        failed = {x["task_id"]: x for x in cats["failed"]["rows"]}
        self.assertEqual(set(failed["f"]), {"task_id", "title", "assignee", "profile", "task_status", "latest_run_id", "outcome", "attempts", "outcome_attempts", "ended_at", "started_at", "completed_at", "timestamp", "error", "blocked_kind", "block_reason", "current_step"})
        self.assertEqual(failed["f"]["attempts"], 11)
        self.assertEqual(failed["f"]["outcome_attempts"], 6)
        self.assertEqual(failed["f"]["error"], "diagnostic:v1 last_tool=browser_click approval_state=denied tool_call_id=call-<x> source=approval")
        self.assertNotIn("d", failed)
        self.assertNotIn("o", failed)
        self.assertNotIn("a", failed)
        self.assertEqual(cats["blocked"]["rows"][0]["block_reason"], "needs protocol correction")
        self.assertNotIn("s", {x["task_id"] for x in cats["blocked"]["rows"]})
        self.assertEqual(r["failures"], cats["failed"]["rows"])

    def test_read_only_and_unavailable_are_not_empty(self):
        r = reducer.reduce_task_filters(path=self.path)
        with self.assertRaises(sqlite3.OperationalError):
            c = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
            c.execute("INSERT INTO tasks VALUES('x','x','p','done',NULL,NULL,1,1)")
        unavailable = reducer.reduce_task_filters(path=self.path + ".missing")
        unavailable_filters = unavailable["task_filters"]
        self.assertFalse(unavailable_filters["available"])
        self.assertIsNone(unavailable_filters["categories"]["failed"]["count"])
        self.assertEqual(unavailable["failures"], [])
        self.assertIsNotNone(unavailable["failures_error"])
        self.assertEqual(r["task_filters"]["categories"]["failed"]["count"], len(r["failures"]))
        self.assertIsNone(unavailable["task_kpi"]["tasks_running"])

    def test_snapshot_includes_tasks_and_full_kpis_from_same_projection(self):
        r = reducer.reduce_task_filters(path=self.path)
        self.assertEqual({x["id"] for x in r["tasks"]}, {"f", "d", "o", "a", "s"})
        self.assertEqual(r["task_kpi"]["tasks_running"], 1)
        self.assertEqual(r["task_kpi"]["tasks_done"], 1)
        self.assertEqual(r["task_kpi"]["tasks_blocked"], 1)
        self.assertEqual(r["task_kpi"]["tasks_failed"], 1)
        self.assertEqual(r["task_kpi"]["tasks_total"], 5)
        self.assertEqual(r["task_kpi"]["success_rate"], 50.0)
        self.assertTrue(r["tasks"][0]["id"])

    def test_cap_and_count_identity(self):
        c = sqlite3.connect(self.path)
        for i in range(25):
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (f"r{i:02}", "running", "p", "running", None, None, i, None, 1, i, 0))
        c.commit(); c.close()
        cat = reducer.reduce_task_filters(path=self.path)["task_filters"]["categories"]["running"]
        self.assertEqual((cat["count"], cat["total"], cat["omitted"]), (20, 26, 6))
        self.assertEqual(cat["count"], len(cat["rows"]))
        self.assertEqual(len({x["task_id"] for x in cat["rows"]}), 20)


if __name__ == "__main__":
    unittest.main()
