"""Check the pure helpers of the verification suite without Docker, rich, or a running stack."""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_suite import util, window  # noqa: E402
from verify_suite.model import Case, CaseResult, LogLine, Mutation, Step, Suite, SuiteResult  # noqa: E402
from verify_suite.report import build_report, render_markdown  # noqa: E402
from verify_suite.suites import all_suites  # noqa: E402

UUID = "61c8a612-381d-49e6-a34f-38da4e03f832"


class EnvTests(unittest.TestCase):
    def test_parse_env_drops_comments_and_quotes(self):
        text = "# note\nA=1\nB='two words'\nC=\"x\"\n\nD=a=b\n"
        self.assertEqual(util.parse_env(text), {"A": "1", "B": "two words", "C": "x", "D": "a=b"})

    def test_set_env_value_adds_replaces_and_removes(self):
        text = "A=1\nSESSION_REPLICAS=2\nB=3"
        self.assertEqual(util.set_env_value(text, "SESSION_REPLICAS", "3"), "A=1\nSESSION_REPLICAS=3\nB=3")
        self.assertEqual(util.set_env_value(text, "SESSION_REPLICAS", None), "A=1\nB=3")
        self.assertEqual(util.set_env_value(text, "NEW", "x"), "A=1\nSESSION_REPLICAS=2\nB=3\nNEW=x\n")

    def test_set_env_value_round_trip_restores_the_original(self):
        text = "A=1\n# keep\nB='q'\n"
        raised = util.set_env_value(text, "SESSION_REPLICAS", "3")
        self.assertEqual(util.set_env_value(raised, "SESSION_REPLICAS", None), text)


class RedactorTests(unittest.TestCase):
    def test_known_secret_jwt_and_token_fields_disappear(self):
        redactor = util.Redactor(["s3cret-value"])
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl"
        text = redactor.scrub(f"login s3cret-value {jwt} control_token=abc123 ok")
        self.assertNotIn("s3cret-value", text)
        self.assertNotIn("eyJ", text)
        self.assertNotIn("abc123", text)
        self.assertIn("ok", text)

    def test_webhook_url_is_hidden(self):
        text = util.Redactor().scrub("send https://discord.com/api/webhooks/1/abc now")
        self.assertNotIn("webhooks/1", text)

    def test_secret_values_picks_credential_keys_only(self):
        found = util.secret_values({"OPERATOR_CONTROL_TOKEN": "tok-123456", "GATEWAY_PORT": "8080", "DB_PASSWORD": "pw-123456"})
        self.assertEqual(sorted(found), ["pw-123456", "tok-123456"])


class IdentifierTests(unittest.TestCase):
    def test_idempotency_keys_are_stable_and_distinct(self):
        self.assertEqual(util.idem_key("vf-1", "a"), util.idem_key("vf-1", "a"))
        self.assertNotEqual(util.idem_key("vf-1", "a"), util.idem_key("vf-1", "b"))
        self.assertNotEqual(util.idem_key("vf-1", "a"), util.idem_key("vf-2", "a"))

    def test_run_id_format(self):
        now = datetime.datetime(2026, 10, 29, 18, 5, 9, tzinfo=datetime.timezone.utc)
        self.assertEqual(util.new_run_id(now, "abcdef"), "vf-261029180509-abcd")

    def test_host_and_service_names_round_trip(self):
        self.assertEqual(util.host_to_service("session-slot-1"), "session")
        self.assertEqual(util.host_to_service("session-slot-2"), "session-slot-2")
        self.assertEqual(util.host_to_service("discovery-slot-1"), "discovery")
        self.assertEqual(util.service_to_host("session"), "session-slot-1")
        self.assertEqual(util.service_to_host("session-slot-3"), "session-slot-3")
        self.assertEqual(util.replica_of("session-slot-3"), "3")
        self.assertEqual(util.replica_of("session"), "1")
        self.assertEqual(util.base_service("session-slot-3"), "session")

    def test_durations(self):
        self.assertEqual(util.fmt_duration(0.25), "250 ms")
        self.assertEqual(util.fmt_duration(4.26), "4.3 s")
        self.assertEqual(util.fmt_duration(125), "2 min 05 s")


class LogTests(unittest.TestCase):
    def test_docker_stamp_is_split(self):
        stamp, text = util.split_docker_line("2026-10-29T18:12:17.124500000Z hello world")
        self.assertEqual(text, "hello world")
        self.assertEqual((stamp.hour, stamp.minute, stamp.second, stamp.microsecond), (18, 12, 17, 124500))
        self.assertEqual(util.split_docker_line("no stamp here"), (None, "no stamp here"))

    def test_access_line_becomes_request_and_status(self):
        raw = f'2026-10-29 18:12:17,124 INFO uvicorn.access 172.19.0.2:54306 - "GET /api/v1/sessions/{UUID} HTTP/1.1" 200'
        self.assertEqual(util.shorten(raw), "GET /api/v1/sessions/61c8a612 200")

    def test_request_marker_loses_its_run_prefix(self):
        raw = '2026-10-29 18:12:17,124 INFO uvicorn.access 172.19.0.2:54306 - "GET /api/v1/players/me?vf=vf-261029182553-9c72-rr-player-0 HTTP/1.1" 200'
        self.assertEqual(util.shorten(raw), "GET /api/v1/players/me?vf=rr-player-0 200")

    def test_event_line_keeps_the_useful_fields(self):
        raw = (f"2026/10/29 14:59:28 alert event=ready service_name=discord-dms instance_id={UUID} "
               "event_id=c46ef9e9 utilization=0.00 reason=ready")
        short = util.shorten(raw)
        self.assertTrue(short.startswith("alert event=ready service_name=discord-dms"))
        self.assertNotIn(UUID, short)

    def test_websocket_line_hides_the_ticket(self):
        raw = f'2026-10-29 18:31:50,191 INFO uvicorn.error 172.19.0.1:47392 - "WebSocket /api/v1/sessions/{UUID}/ws?ticket=abc" [accepted]'
        self.assertEqual(util.shorten(raw), "WebSocket /api/v1/sessions/61c8a612/ws [accepted]")

    def test_plain_text_line_is_kept(self):
        self.assertEqual(util.shorten("2026-10-29 18:31:50,193 INFO uvicorn.error connection open"), "uvicorn.error connection open")

    def test_long_lines_are_cut(self):
        self.assertLessEqual(len(util.shorten("x" * 400, 100)), 100)

    def test_served_by_maps_markers_to_replicas(self):
        lines = [LogLine("session", "2", "t", "GET /api/v1/sessions/x?vf=vf-1-rr-0 200"),
                 LogLine("session", "1", "t", "GET /api/v1/sessions/x?vf=vf-1-rr-1 200"),
                 LogLine("session", "1", "t", "GET /api/v1/sessions/x?vf=vf-9-rr-1 200"),
                 LogLine("session", "1", "t", "GET /internal/v1/status 200")]
        self.assertEqual(util.served_by(lines, "vf-1"), {"vf-1-rr-0": "session#2", "vf-1-rr-1": "session#1"})

    def test_served_by_reads_the_raw_line_when_the_shown_text_is_short(self):
        line = LogLine("player", "1", "t", "GET /api/v1/players/me?vf=rr-0 200", raw='GET /api/v1/players/me?vf=vf-1-rr-0 HTTP/1.1" 200')
        self.assertEqual(util.served_by([line], "vf-1"), {"vf-1-rr-0": "player#1"})

    def test_alternation_and_balance(self):
        self.assertTrue(util.alternates(["a", "b", "a", "b"]))
        self.assertFalse(util.alternates(["a", "a", "b", "b"]))
        self.assertFalse(util.alternates(["a", "a"]))
        self.assertTrue(util.balanced(["a", "b"] * 6, 2))
        self.assertFalse(util.balanced(["a"] * 7 + ["b"] * 5, 2))
        self.assertFalse(util.balanced(["a"] * 12, 2))


def sample_results():
    ok = Step("status 200", seconds=0.2, logs=[LogLine("session", "2", "18:00:00.001", "GET /x 200")], notes=["live"])
    bad = Step("wrong token", ok=False, seconds=0.1, detail="returned 200 with token=hunter22")
    passed = CaseResult("status", "auth", "Authenticated status", "passed", 1.5, [ok])
    failed = CaseResult("status", "logs", "Log volume", "failed", 2.0, [bad], error="boom")
    skipped = CaseResult("scaling", "up-down", "Scale", "skipped", 0.0)
    return [SuiteResult("status", "3", "Status and logs", [passed, failed]), SuiteResult("scaling", "5", "Scaling", [skipped])]


class ReportTests(unittest.TestCase):
    def test_suite_status_rolls_up_cases(self):
        status, scaling = sample_results()
        self.assertEqual(status.status, "failed")
        self.assertEqual(scaling.status, "skipped")
        self.assertAlmostEqual(status.seconds, 3.5)

    def test_report_redacts_and_summarises(self):
        report = build_report("vf-1", "start", "end", {"project": "p", "gateway": "g", "ready": "17 of 17"}, sample_results(),
                              redact=util.Redactor(["hunter22"]).scrub)
        self.assertEqual(report["result"], "failed")
        self.assertNotIn("hunter22", str(report))
        self.assertEqual([s["status"] for s in report["suites"]], ["failed", "skipped"])

    def test_markdown_has_the_summary_table_and_steps(self):
        report = build_report("vf-1", "start", "end", {"project": "p", "gateway": "g", "ready": "17 of 17"}, sample_results())
        text = render_markdown(report)
        self.assertIn("| status | 3 | FAIL | 3.5 s |", text)
        self.assertIn("| scaling | 5 | skipped | 0 ms |", text)
        self.assertIn("- pass status 200 (200 ms).", text)
        self.assertIn("`session` replica 2: `GET /x 200`", text)
        self.assertNotIn("\u2014", text)

    def test_passing_run_reports_passed(self):
        passed = SuiteResult("status", "3", "S", [CaseResult("status", "a", "A", "passed", 1.0)])
        self.assertEqual(build_report("v", "s", "e", {}, [passed])["result"], "passed")


class RegistryTests(unittest.TestCase):
    def test_suites_are_well_formed(self):
        suites = all_suites()
        self.assertEqual(len({s.id for s in suites}), len(suites))
        for suite in suites:
            self.assertTrue(suite.cases, suite.id)
            self.assertEqual(len({c.id for c in suite.cases}), len(suite.cases), suite.id)
            for case in suite.cases:
                if case.mutation:
                    self.assertTrue(case.mutation.faults and case.mutation.restores, case.id)

    def test_suite_names_carry_no_lab_numbers(self):
        for suite in all_suites():
            text = " ".join([suite.id, suite.title, suite.description] + [c.id + c.title for c in suite.cases]).lower()
            self.assertNotRegex(text, r"\blab[- ]?\d")


class WindowTests(unittest.TestCase):
    def line(self, second, fraction="", sep="."):
        return f"2026-10-29 18:00:{second:02d}{sep + fraction if fraction else ''} INFO dependency_failure destination_instance_id=x"

    def test_stamp_reads_python_go_and_java_lines(self):
        base = datetime.datetime(2026, 10, 29, 18, 0, 5, tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(window.stamp("2026-10-29 18:00:05,250 INFO x"), base + 0.25)
        self.assertEqual(window.stamp("2026/10/29 18:00:05 WARN x"), base)
        self.assertEqual(window.stamp("2026-10-29T18:00:05.500Z  INFO 1 --- x"), base + 0.5)
        self.assertEqual(window.resolution("2026-10-29 18:00:05,250 INFO x"), 0.05)
        self.assertEqual(window.resolution("2026/10/29 18:00:05 WARN x"), 1.0)
        with self.assertRaises(ValueError):
            window.stamp("no stamp")

    def test_trip_waits_for_three_failures_inside_the_window(self):
        self.assertEqual(window.expected_trip([0.0, 1.0, 2.0], 7.0), 2.0)
        self.assertIsNone(window.expected_trip([0.0, 4.0, 8.0], 7.0))
        self.assertEqual(window.expected_trip([0.0, 4.0, 8.0, 9.0], 7.0), 9.0)
        self.assertIsNone(window.expected_trip([0.0, 1.0], 7.0))

    def test_window_includes_its_start(self):
        # docs/contracts/resilience.md: failures at 0, 2 and 7 s trip a 7 s window, and 0, 2 and 7.001 s do not.
        self.assertEqual(window.expected_trip([0.0, 2.0, 7.0], 7.0), 7.0)
        self.assertIsNone(window.expected_trip([0.0, 2.0, 7.001], 7.0))

    def test_trip_must_follow_the_filling_failure(self):
        self.assertTrue(window.trip_matches(None, None))
        self.assertFalse(window.trip_matches(3.0, None))
        self.assertFalse(window.trip_matches(None, 2.0))
        self.assertTrue(window.trip_matches(2.4, 2.0))
        self.assertFalse(window.trip_matches(3.5, 2.0))
        self.assertFalse(window.trip_matches(1.5, 2.0))
        self.assertTrue(window.trip_matches(1.5, 2.0, tolerance_before=1.0))

    def test_timeline_removes_a_backward_wall_clock_step(self):
        clock = window.ClockTrack(start=False)
        clock.segs = [[100.0, 110.0, 1000.0], [120.0, 130.0, 998.2]]  # wall = monotonic + offset, stepped back 1.8 s
        self.assertEqual(clock.steps(), [-1.8])
        fmt = lambda wall: datetime.datetime.fromtimestamp(wall, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3] + " INFO x"
        # Wall stamps 1109.900 and 1118.700 are 8.8 s apart, but 10.6 s really passed.
        times = clock.timeline([fmt(1109.9), fmt(1118.7)])
        self.assertAlmostEqual(times[0], 109.9, places=2)
        self.assertAlmostEqual(times[1], 120.5, places=2)

    def test_sample_starts_a_new_segment_only_on_a_step(self):
        clock = window.ClockTrack(start=False)
        clock.segs = [[100.0, 100.0, 1000.0]]
        clock.sample(1100.1, 100.1)
        self.assertEqual(len(clock.segs), 1)
        clock.sample(1100.2 - 1.8 + 0.0, 100.2)
        self.assertEqual(len(clock.segs), 2)

if __name__ == "__main__":
    unittest.main()
