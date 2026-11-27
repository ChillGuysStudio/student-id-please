import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_sagas", ROOT / "scripts/check_sagas.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class CheckSagas(unittest.TestCase):
    def test_saga_groups_steps_by_saga_in_order(self):
        rows = [["a", "compensated", "hold-shift", "compensated", "1", "1"],
                ["a", "compensated", "award-shift", "compensated", "1", "1"],
                ["b", "running", "hold-shift", "done", "1", "0"],
                ["b", "running", "award-shift", "pending", "2", "0"]]
        with mock.patch.object(check, "sql", return_value=rows):
            sagas = check.saga("s")
        self.assertEqual([state for state, _ in sagas], ["compensated", "running"])
        self.assertEqual(sagas[1][1][1], ("award-shift", "pending", 2, 0))

    def test_state_reads_the_broker_session_and_ledger(self):
        def sql(name, statement):
            return {"session-db": [["ending"]], "player-db": [["shift", "3"]]}[name]

        with mock.patch.object(check, "saga", return_value=[["running", []]]), \
                mock.patch.object(check, "sql", side_effect=sql):
            self.assertEqual(check.state("s"), ("running", "ending", {"shift": 3}))

    def test_settled_waits_for_the_final_state(self):
        states = iter([("running", "ending", {}), ("completed", "ended", {"shift": 3})])
        with mock.patch.object(check, "state", side_effect=lambda sid: next(states)), \
                mock.patch.object(check.time, "sleep"):
            self.assertEqual(check.settled("s", "completed"), ("completed", "ended", {"shift": 3}))

    def test_a_failed_case_is_reported_and_the_rest_run(self):
        output = io.StringIO()
        cases = [("first", mock.Mock(side_effect=AssertionError("wrong"))), ("second", mock.Mock(return_value="fine"))]
        with mock.patch.object(check, "player_ready") as ready, contextlib.redirect_stdout(output):
            results = [check.case(title, run) for title, run in cases]
        self.assertEqual(results, [False, True])
        self.assertEqual(ready.call_count, 2)
        self.assertIn("FAIL  first: wrong", output.getvalue())
        self.assertIn("ok    second", output.getvalue())

    def test_main_runs_only_the_named_cases_and_fails_on_a_failure(self):
        with mock.patch.object(check, "case", side_effect=[True, False]) as case:
            with self.assertRaises(SystemExit) as stopped:
                check.main(["repeated-step", "normal"])
        self.assertEqual([call.args[0] for call in case.call_args_list], ["repeated step", "normal run"])
        self.assertEqual(stopped.exception.code, 1)

    def test_main_refuses_an_unknown_case(self):
        with self.assertRaises(SystemExit) as stopped:
            check.main(["everything"])
        self.assertIn("unknown case: everything", str(stopped.exception.code))


if __name__ == "__main__":
    unittest.main()
