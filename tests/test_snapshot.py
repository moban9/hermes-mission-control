import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
import snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "board.db")
        with sqlite3.connect(self.path) as con:
            con.executescript("""
                CREATE TABLE tasks(id TEXT, title TEXT, assignee TEXT, status TEXT, block_kind TEXT, current_step_key TEXT, priority INTEGER, created_at REAL, started_at REAL, completed_at REAL, consecutive_failures INTEGER);
                CREATE TABLE task_links(parent_id TEXT, child_id TEXT);
                CREATE TABLE task_runs(id INTEGER, task_id TEXT, profile TEXT, outcome TEXT, error TEXT, started_at REAL, ended_at REAL, summary TEXT, step_key TEXT);
                CREATE TABLE task_events(id INTEGER, task_id TEXT, kind TEXT, payload TEXT, created_at REAL);
                INSERT INTO tasks VALUES ('t1','Example','cask','running',NULL,NULL,0,1,2,NULL,0);
                INSERT INTO task_runs VALUES (1,'t1','cask',NULL,NULL,2,NULL,NULL,NULL);
                INSERT INTO task_events VALUES (1,'t1','created','{}',1);
                INSERT INTO task_links VALUES ('p','t1');
            """)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_available_empty_and_alias_fields(self):
        result = snapshot.load_snapshot(self.path)
        self.assertTrue(result.available)
        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(len(result.runs), 1)
        self.assertEqual(result.aliases["failures"], result.categories["failed"]["rows"])
        self.assertEqual(result.legacy_kpis["tasks_running"], 1)
        empty = os.path.join(self.tmp.name, "empty.db")
        with sqlite3.connect(empty) as con:
            con.executescript("CREATE TABLE tasks(id TEXT,title TEXT,assignee TEXT,status TEXT,block_kind TEXT,current_step_key TEXT,priority INTEGER,created_at REAL,started_at REAL,completed_at REAL,consecutive_failures INTEGER); CREATE TABLE task_links(parent_id TEXT,child_id TEXT); CREATE TABLE task_runs(id INTEGER,task_id TEXT,profile TEXT,outcome TEXT,error TEXT,started_at REAL,ended_at REAL,summary TEXT,step_key TEXT); CREATE TABLE task_events(id INTEGER,task_id TEXT,kind TEXT,payload TEXT,created_at REAL);")
        result = snapshot.load_snapshot(empty)
        self.assertTrue(result.available)
        self.assertEqual(result.legacy_kpis["tasks_running"], 0)
        missing = snapshot.load_snapshot(empty + ".missing")
        self.assertFalse(missing.available)
        self.assertIsNone(missing.legacy_kpis["tasks_running"])
        self.assertEqual(missing.error, "board unavailable: read_error")

    def test_exact_category_semantics_and_fields(self):
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE tasks SET block_kind='stale' WHERE id='t1'")
            con.execute("UPDATE tasks SET status='blocked' WHERE id='t1'")
            con.execute("UPDATE task_runs SET outcome='crashed', error='latest diagnostic' WHERE id=1")
            con.execute("INSERT INTO task_runs VALUES (2,'t1','cask',NULL,NULL,3,NULL,NULL,NULL)")
            con.execute("INSERT INTO task_events VALUES (2,'t1','blocked','{\"reason\":\"event JSON\"}',4)")
        result = snapshot.load_snapshot(self.path)
        failed = result.categories['failed']
        blocked = result.categories['blocked']
        self.assertEqual((failed['count'], failed['total'], failed['omitted']), (0, 0, 0))
        self.assertEqual(blocked['rows'][0]['latest_outcome'], None)
        self.assertEqual(blocked['rows'][0]['attempts'], 2)
        self.assertEqual(blocked['rows'][0]['outcome_attempts'], 0)
        self.assertEqual(blocked['rows'][0]['label'], 'no outcome · 2 attempts')
        self.assertEqual(blocked['rows'][0]['reason'], 'no reason recorded')
        self.assertEqual(blocked['rows'][0]['blocked_reason'], {'reason': 'event JSON'})
        self.assertEqual(blocked['rows'][0]['blocked_kind'], 'stale')
        self.assertEqual(result.legacy_kpis['tasks_failed'], 0)

    def test_category_cap_does_not_cap_totals(self):
        with sqlite3.connect(self.path) as con:
            con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                (f'r{i}', f'Run {i}', 'cask', 'running', None, None, 0, i, i, None, 0)
                for i in range(25)
            ])
        result = snapshot.load_snapshot(self.path)
        category = result.categories['running']
        self.assertEqual((category['count'], category['total'], category['omitted']), (20, 26, 6))
        self.assertEqual(result.legacy_kpis['tasks_running'], 26)

    def test_connection_enforces_read_only(self):
        with snapshot.open_snapshot(self.path) as con:
            with self.assertRaises(sqlite3.OperationalError):
                con.execute("DELETE FROM tasks")


if __name__ == "__main__":
    unittest.main()
