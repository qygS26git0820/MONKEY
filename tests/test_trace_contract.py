"""轨迹契约的写入端与校验端。

校验端用"合法样本 + 单点注入"的方式测：样本是真实产出的轨迹，
每个用例只破坏一个字段，断言恰好被这一个问题抓到。
这样既证明校验器能发现问题，也证明它不会无中生有。
"""

import unittest
from pathlib import Path

from harness.trace import (
    ContractViolation,
    TraceWriter,
    read_trace,
    validate_records,
)

from . import support

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "phase1-sample-trace.jsonl"


def _find(records, event_type):
    for rec in records:
        if rec["type"] == event_type:
            return rec
    raise AssertionError(f"样本轨迹里没有 {event_type}")


class ValidateRecordsTest(unittest.TestCase):
    def setUp(self):
        self.records = read_trace(FIXTURE)

    def test_reference_sample_is_valid(self):
        self.assertEqual([], validate_records(self.records))

    def test_seq_gap_is_detected(self):
        self.records[3]["seq"] += 1
        problems = validate_records(self.records)
        self.assertTrue(any("seq" in p for p in problems), problems)

    def test_unknown_event_type_is_detected(self):
        self.records[1]["type"] = "telemetry"
        problems = validate_records(self.records)
        self.assertTrue(any("telemetry" in p for p in problems), problems)

    def test_missing_common_field_is_detected(self):
        del self.records[1]["run_id"]
        problems = validate_records(self.records)
        self.assertTrue(any("run_id" in p for p in problems), problems)

    def test_missing_required_field_is_detected(self):
        del _find(self.records, "step_end")["duration_ms"]
        problems = validate_records(self.records)
        self.assertTrue(any("duration_ms" in p for p in problems), problems)

    def test_illegal_tool_result_status_is_detected(self):
        _find(self.records, "tool_result")["status"] = "sort-of-ok"
        problems = validate_records(self.records)
        self.assertTrue(any("sort-of-ok" in p for p in problems), problems)

    def test_missing_stream_field_is_detected(self):
        del _find(self.records, "tool_result")["stdout_stream"]["blob_ref"]
        problems = validate_records(self.records)
        self.assertTrue(any("blob_ref" in p for p in problems), problems)

    def test_illegal_truncation_strategy_is_detected(self):
        _find(self.records, "tool_result")["stderr_stream"]["strategy"] = "middle"
        problems = validate_records(self.records)
        self.assertTrue(any("middle" in p for p in problems), problems)

    def test_illegal_failure_class_is_detected(self):
        _find(self.records, "run_end")["failure_class"] = "vibes_were_off"
        problems = validate_records(self.records)
        self.assertTrue(any("vibes_were_off" in p for p in problems), problems)

    def test_illegal_run_end_status_is_detected(self):
        _find(self.records, "run_end")["status"] = "mostly_done"
        problems = validate_records(self.records)
        self.assertTrue(any("mostly_done" in p for p in problems), problems)


class TraceWriterGuardTest(unittest.TestCase):
    def setUp(self):
        self.scratch = self.enterContext(support.scratch_dir("tw"))
        self.writer = TraceWriter(self.scratch / "trace.jsonl", "run-x")

    def tearDown(self):
        self.writer.close()

    def test_undeclared_event_type_is_refused(self):
        with self.assertRaises(ContractViolation):
            self.writer.emit("vibes")

    def test_missing_required_field_is_refused(self):
        # step_end 需要 duration_ms，这里只给 step。
        with self.assertRaises(ContractViolation):
            self.writer.emit("step_end", step=1)

    def test_refused_event_does_not_advance_seq(self):
        with self.assertRaises(ContractViolation):
            self.writer.emit("vibes")
        self.assertEqual(0, self.writer.seq)

    def test_valid_emission_round_trips_and_validates(self):
        self.writer.emit(
            "run_start", task_id="t", agent="a", executor="local", config_hash="h",
            harness_git_sha=None, python_version="3.12.13", schema_version=1,
        )
        self.writer.close()

        records = read_trace(self.scratch / "trace.jsonl")
        self.assertEqual(1, len(records))
        self.assertEqual("run_start", records[0]["type"])
        self.assertEqual([], validate_records(records))


class ReadTraceTest(unittest.TestCase):
    def setUp(self):
        self.scratch = self.enterContext(support.scratch_dir("rt"))

    def test_malformed_json_line_raises_contract_violation(self):
        path = self.scratch / "broken.jsonl"
        path.write_text('{"type": "run_start"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(ContractViolation):
            read_trace(path)

    def test_blank_lines_are_skipped(self):
        path = self.scratch / "blank.jsonl"
        path.write_text("\n\n", encoding="utf-8")
        self.assertEqual([], read_trace(path))
