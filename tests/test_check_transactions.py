import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_transactions", ROOT / "scripts/check_transactions.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CheckTransactions(unittest.TestCase):
    def test_state_reads_both_databases_and_the_broker(self):
        rows = {
            ("session-db", "SELECT status"): [["ended"]],
            ("player-db", "SELECT count(*) FROM progression_ledger"): [["3"]],
            ("broker-db", "SELECT t.state"): [["aborted"], ["committed"]],
            ("session-db", "SELECT count(*) FROM pg_prepared_xacts"): [["0"]],
            ("player-db", "SELECT count(*) FROM pg_prepared_xacts"): [["1"]],
        }

        def sql(name, statement):
            return next(value for (db, start), value in rows.items() if db == name and statement.startswith(start))

        with mock.patch.object(check, "sql", side_effect=sql):
            self.assertEqual(check.state("s"), ("ended", 3, ["aborted", "committed"], 1))

    def test_settled_waits_for_the_latest_transaction(self):
        states = iter([("active", 0, ["preparing"], 2), ("ended", 3, ["aborted", "committed"], 0)])
        with mock.patch.object(check, "state", side_effect=lambda sid: next(states)), \
                mock.patch.object(check.time, "sleep"):
            self.assertEqual(check.settled("s", "committed"), ("ended", 3, ["aborted", "committed"], 0))

    def test_until_gives_up(self):
        with mock.patch.object(check.time, "sleep"), \
                mock.patch.object(check.time, "monotonic", side_effect=[0, 0, 2, 2]):
            with self.assertRaises(RuntimeError):
                check.until("nothing", lambda: None, 1)

    def test_a_failed_case_is_reported_and_the_rest_run(self):
        output = io.StringIO()
        cases = [("first", mock.Mock(side_effect=AssertionError("wrong"))), ("second", mock.Mock(return_value="fine"))]
        with mock.patch.object(check, "player_ready") as ready, contextlib.redirect_stdout(output):
            results = [check.case(title, run) for title, run in cases]
        self.assertEqual(results, [False, True])
        self.assertEqual(ready.call_count, 2)
        self.assertIn("FAIL  first: wrong", output.getvalue())
        self.assertIn("ok    second: fine", output.getvalue())

    def test_main_fails_when_any_case_fails(self):
        with mock.patch.object(check, "case", side_effect=[True, False, True, True, True]):
            with self.assertRaises(SystemExit) as stopped:
                check.main([])
        self.assertEqual(stopped.exception.code, 1)

    def test_main_runs_only_the_named_cases(self):
        with mock.patch.object(check, "case", return_value=True) as case:
            with self.assertRaises(SystemExit) as stopped:
                check.main(["repeat", "commit"])
        self.assertEqual([call.args[0] for call in case.call_args_list], ["repeated end", "normal commit"])
        self.assertEqual(stopped.exception.code, 0)

    def test_main_refuses_an_unknown_case(self):
        with self.assertRaises(SystemExit) as stopped:
            check.main(["everything"])
        self.assertIn("unknown case: everything", str(stopped.exception.code))


if __name__ == "__main__":
    unittest.main()
