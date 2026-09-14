"""向后兼容：阶段 1 落盘的轨迹，在之后任何阶段都必须仍然合法。

这是"冻结清单 diff 为空"这条验收条件的运行时对应物——
即使有人手滑改了 contract.py，sample 轨迹也会立刻被这条测试拦住。
"""

import json
import unittest
from pathlib import Path

from harness import contract
from harness.config import load_config
from harness.trace import read_trace, validate_records

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLE_TRACE = FIXTURES / "phase1-sample-trace.jsonl"
SAMPLE_META = FIXTURES / "phase1-sample-meta.json"

PROMISED_EVENT_TYPES = (
    "run_start", "tool_call", "tool_result", "step_end", "agent_message",
    "verification", "run_end",
)


class Phase1SampleTraceTest(unittest.TestCase):
    def setUp(self):
        self.records = read_trace(SAMPLE_TRACE)

    def test_sample_trace_is_still_valid(self):
        self.assertEqual([], validate_records(self.records))

    def test_sample_trace_covers_the_promised_event_types(self):
        present = {rec["type"] for rec in self.records}
        for event_type in PROMISED_EVENT_TYPES:
            with self.subTest(event=event_type):
                self.assertIn(event_type, present)

    def test_sample_trace_schema_version_is_current(self):
        for rec in self.records:
            self.assertEqual(contract.SCHEMA_VERSION, rec["schema_version"])

    def test_sample_meta_matches_schema_version(self):
        meta = json.loads(SAMPLE_META.read_text(encoding="utf-8"))
        self.assertEqual(contract.SCHEMA_VERSION, meta["schema_version"])
        self.assertEqual(self.records[0]["run_id"], meta["run_id"])


class Phase1ConfigHashTest(unittest.TestCase):
    """阶段 1 配置的哈希必须不变。

    config_hash 是整份配置字典的哈希，所以"给预算加两个可选字段"这类改动
    只要没碰 TOML 文件，哈希就不该动；一旦动了，那批轨迹的配置归属就断了。
    这条测试是"不碰 default.toml"这条纪律的运行时对应物。
    """

    def test_default_config_hash_still_matches_the_phase1_sample(self):
        meta = json.loads(SAMPLE_META.read_text(encoding="utf-8"))
        self.assertEqual(meta["config_hash"], load_config("default").config_hash())
