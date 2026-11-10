import json
import os
import sqlite3
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import reducer
import snapshot


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
        self.assertEqual(failed["f"]["outcome_attempts"], 6)
        self.assertEqual({row["task_id"]: row for row in snapshot.load_snapshot(self.path).categories["failed"]["rows"]}["f"]["label"], "crashed ×6 · 11 attempts")
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
        for name in ("running", "done", "failed", "blocked"):
            category = r["task_filters"]["categories"][name]
            self.assertEqual(category["count"], len(category["rows"]), name)
            self.assertEqual(category["total"], category["count"] + category["omitted"], name)
        self.assertEqual(r["task_filters"]["categories"]["done"]["count"], 1)
        self.assertEqual(r["task_filters"]["categories"]["failed"]["count"], 1)
        self.assertEqual(r["task_kpi"]["tasks_done"], r["task_filters"]["categories"]["done"]["total"])
        self.assertTrue(r["tasks"][0]["id"])

    def test_cap_and_count_identity(self):
        c = sqlite3.connect(self.path)
        for i in range(25):
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (f"r{i:02}", "running", "p", "running", None, None, i, None, 1, i, 0))
        c.commit(); c.close()
        result = reducer.reduce_task_filters(path=self.path)
        cat = result["task_filters"]["categories"]["running"]
        self.assertEqual((cat["count"], cat["total"], cat["omitted"]), (20, 26, 6))
        self.assertEqual(cat["count"], len(cat["rows"]))
        self.assertEqual(len({x["task_id"] for x in cat["rows"]}), 20)
        # The legacy KPI remains the uncapped population, not the tile count.
        self.assertEqual(result["task_kpi"]["tasks_running"], 26)
        self.assertEqual(result["task_filters"]["categories"]["failed"]["count"], len(result["failures"]))

    def test_all_failure_outcomes_and_empty_reasons(self):
        c = sqlite3.connect(self.path)
        outcomes = ("crashed", "gave_up", "timed_out", "failed", "rate_limited")
        for i, outcome in enumerate(outcomes):
            task_id = f"outcome-{i}"
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (task_id, task_id, None, "ready", None, None, 1, i, None, None, 0))
            c.execute("INSERT INTO task_runs VALUES(?,?,?,?,?,?,?,?)", (30+i, task_id, "p", outcome, None if i == 0 else "" if i == 1 else "reason", 1, 2, None))
        c.commit(); c.close()
        result = reducer.reduce_task_filters(path=self.path)
        failed = {row["task_id"]: row for row in result["task_filters"]["categories"]["failed"]["rows"]}
        self.assertEqual({failed[f"outcome-{i}"]["outcome"] for i in range(5)}, set(outcomes))
        self.assertEqual(failed["outcome-0"]["error"], None)
        self.assertEqual(failed["outcome-1"]["error"], "")
        self.assertEqual(failed["outcome-0"]["attempts"], 1)
        self.assertEqual(result["failures"], result["task_filters"]["categories"]["failed"]["rows"])
        self.assertEqual(result["failures_omitted"], result["task_filters"]["categories"]["failed"]["omitted"])

    def test_blocked_kinds_reasons_and_stale_kind(self):
        c = sqlite3.connect(self.path)
        kinds = ("needs_input", "dependency", "capability", "transient")
        for i, kind in enumerate(kinds):
            task_id = f"blocked-{kind}"
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (task_id, task_id, "p", "blocked", kind, None, 1, i, None, None, 0))
            c.execute("INSERT INTO task_events VALUES(?,?,?,?,?)", (50+i, task_id, "blocked", json.dumps({"reason": f"reason-{kind}"}), i))
        c.commit(); c.close()
        blocked = {row["task_id"]: row for row in reducer.reduce_task_filters(path=self.path)["task_filters"]["categories"]["blocked"]["rows"]}
        for kind in kinds:
            self.assertEqual(blocked[f"blocked-{kind}"]["blocked_kind"], kind)
            self.assertEqual(blocked[f"blocked-{kind}"]["block_reason"], f"reason-{kind}")
        self.assertNotIn("s", blocked)  # stale block_kind on ready status

    def test_empty_database_is_available_and_schema_mismatch_is_not(self):
        empty = os.path.join(self.tmp.name, "empty.db")
        c = sqlite3.connect(empty)
        c.executescript("CREATE TABLE tasks(id TEXT,title TEXT,assignee TEXT,status TEXT,block_kind TEXT,current_step_key TEXT,started_at INTEGER,completed_at INTEGER,priority INTEGER,created_at INTEGER,consecutive_failures INTEGER); CREATE TABLE task_links(parent_id TEXT,child_id TEXT); CREATE TABLE task_runs(id INTEGER,task_id TEXT,profile TEXT,outcome TEXT,error TEXT,started_at INTEGER,ended_at INTEGER,summary TEXT); CREATE TABLE task_events(id INTEGER,task_id TEXT,kind TEXT,payload TEXT,created_at INTEGER);")
        c.close()
        r = reducer.reduce_task_filters(path=empty)
        self.assertTrue(r["task_filters"]["available"])
        self.assertEqual([r["task_filters"]["categories"][k]["count"] for k in ("running", "done", "failed", "blocked")], [0, 0, 0, 0])
        bad = os.path.join(self.tmp.name, "schema.db")
        sqlite3.connect(bad).close()
        unavailable = reducer.reduce_task_filters(path=bad)
        self.assertFalse(unavailable["task_filters"]["available"])
        self.assertEqual(unavailable["task_filters"]["error"], "board unavailable: schema_mismatch")
        self.assertIsNone(unavailable["task_filters"]["categories"]["running"]["total"])


if __name__ == "__main__":
    unittest.main()
