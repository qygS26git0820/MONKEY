"""累计账本与预算判定。

这是纯单元测试，不经主循环：账本的全部行为就是"把若干笔报告并成一个
唯一的数，并回答它是否越过上限"。把它单独测透，主循环那边的集成测试
才能只关心"检查点在不在对的位置"。
"""

import unittest

from harness.core.usage import UsageLedger

from . import support


def budgets(**kwargs):
    return support.make_config(**kwargs).budgets


class AccumulationTest(unittest.TestCase):
    def test_fresh_ledger_reports_unknown(self):
        ledger = UsageLedger()
        self.assertIsNone(ledger.input_tokens)
        self.assertIsNone(ledger.output_tokens)
        self.assertIsNone(ledger.cost_usd)

    def test_known_values_accumulate(self):
        ledger = UsageLedger()
        ledger.record(input_tokens=100, output_tokens=20, cost_usd=0.01)
        ledger.record(input_tokens=50, output_tokens=5, cost_usd=0.005)
        self.assertEqual(150, ledger.input_tokens)
        self.assertEqual(25, ledger.output_tokens)
        self.assertAlmostEqual(0.015, ledger.cost_usd)

    def test_fields_are_independent(self):
        ledger = UsageLedger()
        ledger.record(cost_usd=0.02)
        self.assertEqual(0.02, ledger.cost_usd)
        self.assertIsNone(ledger.input_tokens)

    def test_a_missing_field_makes_that_field_unknown(self):
        ledger = UsageLedger()
        ledger.record(input_tokens=100, output_tokens=20, cost_usd=0.01)
        # 第二笔没报成本：真实总成本已经无法得知。
        ledger.record(input_tokens=50, output_tokens=5)
        self.assertEqual(150, ledger.input_tokens)
        self.assertIsNone(ledger.cost_usd)

    def test_unknown_is_sticky_because_a_later_value_cannot_recover_it(self):
        ledger = UsageLedger()
        ledger.record(cost_usd=None)
        ledger.record(cost_usd=0.01)
        # 若这里给出 0.01，第一笔的真实花费就被静默吞掉了。
        self.assertIsNone(ledger.cost_usd)

    def test_first_value_after_no_records_is_kept(self):
        # 与上一条对立：完全没有记录过 ≠ 记录过一笔缺失。
        ledger = UsageLedger()
        ledger.record(cost_usd=0.01)
        self.assertEqual(0.01, ledger.cost_usd)

    def test_record_is_keyword_only(self):
        ledger = UsageLedger()
        with self.assertRaises(TypeError):
            ledger.record(100)


class ExceededTest(unittest.TestCase):
    def test_no_caps_never_exceeds(self):
        ledger = UsageLedger()
        ledger.record(input_tokens=10**9, output_tokens=10**9, cost_usd=999.0)
        self.assertFalse(ledger.exceeded(budgets()))

    def test_unknown_never_exceeds_even_with_a_cap(self):
        ledger = UsageLedger()
        self.assertFalse(ledger.exceeded(budgets(max_cost_usd=0.5)))

    def test_cost_over_cap_exceeds(self):
        ledger = UsageLedger()
        ledger.record(cost_usd=0.51)
        self.assertTrue(ledger.exceeded(budgets(max_cost_usd=0.5)))

    def test_cost_exactly_at_cap_does_not_exceed(self):
        ledger = UsageLedger()
        ledger.record(cost_usd=0.5)
        self.assertFalse(ledger.exceeded(budgets(max_cost_usd=0.5)))

    def test_token_cap_counts_input_plus_output(self):
        ledger = UsageLedger()
        ledger.record(input_tokens=60, output_tokens=50)
        self.assertTrue(ledger.exceeded(budgets(max_total_tokens=100)))

    def test_token_cap_not_tripped_by_either_side_alone(self):
        ledger = UsageLedger()
        ledger.record(input_tokens=60, output_tokens=30)
        self.assertFalse(ledger.exceeded(budgets(max_total_tokens=100)))

    def test_token_cap_is_unknown_when_only_one_side_is_reported(self):
        # 只报了输入、没报输出时，总和未知，不得凭它终止。
        ledger = UsageLedger()
        ledger.record(input_tokens=10**6)
        self.assertFalse(ledger.exceeded(budgets(max_total_tokens=100)))
