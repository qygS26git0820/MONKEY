"""契约冻结。

这条测试的存在只为一件事：contract.py 一旦改动，必须同步快照，否则失败。
"只增不改"是阶段 2 验收（冻结清单 git diff 为空）的机械依据。
"""

import json
import unittest
from pathlib import Path

from harness import contract

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "contract_snapshot.json"


def _live() -> dict:
    return {
        "SCHEMA_VERSION": contract.SCHEMA_VERSION,
        "COMMON_FIELDS": list(contract.COMMON_FIELDS),
        "EVENT_TYPES": list(contract.EVENT_TYPES),
        "FAILURE_CLASSES": list(contract.FAILURE_CLASSES),
        "FAILURE_DECISION_ORDER": list(contract.FAILURE_DECISION_ORDER),
        "TOOL_RESULT_STATUSES": list(contract.TOOL_RESULT_STATUSES),
        "TRUNCATION_STRATEGIES": list(contract.TRUNCATION_STRATEGIES),
        "STREAM_FIELDS": list(contract.STREAM_FIELDS),
        "REQUIRED_FIELDS": {k: list(v) for k, v in contract.REQUIRED_FIELDS.items()},
        "RUN_END_STATUSES": list(contract.RUN_END_STATUSES),
    }


class FrozenSnapshotTest(unittest.TestCase):
    def test_snapshot_matches_live_contract(self):
        frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(frozen, _live(),
                         "contract.py 变了但 tests/fixtures/contract_snapshot.json 没变。"
                         "若是有意变更，请同步快照并在 docs/trace-schema.md 登记。")


class ContractShapeTest(unittest.TestCase):
    def test_schema_version_is_1(self):
        self.assertEqual(1, contract.SCHEMA_VERSION)

    def test_failure_classes_are_12_and_unique(self):
        self.assertEqual(12, len(contract.FAILURE_CLASSES))
        self.assertEqual(len(contract.FAILURE_CLASSES), len(set(contract.FAILURE_CLASSES)))

    def test_decision_order_is_a_permutation_of_failure_classes(self):
        self.assertEqual(set(contract.FAILURE_CLASSES),
                         set(contract.FAILURE_DECISION_ORDER))
        # "none" 必须排在最后：它是"其余原因都不成立"的兜底，先到者胜才有意义。
        self.assertEqual("none", contract.FAILURE_DECISION_ORDER[-1])

    def test_event_types_unique_and_have_required_fields(self):
        self.assertEqual(len(contract.EVENT_TYPES), len(set(contract.EVENT_TYPES)))
        self.assertEqual(set(contract.EVENT_TYPES), set(contract.REQUIRED_FIELDS))

    def test_common_fields_are_declared_on_run_start(self):
        # 公共字段由 validate_records 统一检查；run_start 额外显式声明 schema_version。
        self.assertIn("schema_version", contract.REQUIRED_FIELDS["run_start"])
