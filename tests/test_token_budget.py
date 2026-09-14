"""token 预算的运行期终止：agent 记的用量越过上限时，主循环以
token_budget_exceeded 终止，且验证照跑（schema R3）。

预算检查点由 loop.py 提供，本文件的 agent 与 loop.py 无继承关系——它只
需要能在 next_action 里往 run_ctx.usage 记一笔。attach 就是拿到那个账本
的入口。
"""

import unittest

from harness.core.messages import Finish
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support


class SpendingAgent:
    """第一笔就记一笔用量，然后 Finish。

    记完就 Finish 是有意的：主循环的预算检查排在动作分派**之前**，所以
    "记了一笔越限的量、同时给出 Finish"必须止于 token_budget_exceeded。
    若终局是正常收尾，说明检查点站错了位置。
    """

    name = "spending"

    def __init__(self, **usage):
        self._usage = usage
        self._ledger = None

    def bind(self, run_ctx):
        self._ledger = run_ctx.usage

    def next_action(self, state):
        self._ledger.record(**self._usage)
        return Finish("记一笔就收工")


class BudgetStopTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.task = load_task("toy-001")

    def _run(self, usage, **config_kwargs):
        agent = SpendingAgent(**usage)
        config = support.make_config(**config_kwargs)
        failure_class, run_dir = support.run_scenario(
            agent, self.task, config=config,
            attach=lambda ctx, a: a.bind(ctx),
        )
        records = read_trace(run_dir / "trace.jsonl")
        return failure_class, records

    def test_token_cap_trips_on_input_plus_output(self):
        failure_class, records = self._run(
            {"input_tokens": 60, "output_tokens": 50}, max_total_tokens=100)
        self.assertEqual("token_budget_exceeded", failure_class)

        end = records[-1]
        self.assertEqual("run_end", end["type"])
        self.assertEqual("token_budget_exceeded", end["failure_class"])
        # token_budget_exceeded 不在 _STATUS_BY_CLASS 里，落到默认值 aborted。
        self.assertEqual("aborted", end["status"])
        self.assertEqual(60, end["totals"]["input_tokens"])
        self.assertEqual(50, end["totals"]["output_tokens"])
        self.assertEqual([], validate_records(records))

    def test_verification_still_runs_after_a_budget_stop(self):
        # schema R3：无论因何终止，只要工作区在就照跑验证。
        _, records = self._run(
            {"input_tokens": 60, "output_tokens": 50}, max_total_tokens=100)
        verifications = [r for r in records if r["type"] == "verification"]
        self.assertEqual(1, len(verifications))
        # 这个 agent 没改任何文件，toy-001 的仓库仍是坏的。
        self.assertEqual("failed", verifications[0]["status"])

    def test_spending_exactly_at_the_cap_does_not_trip(self):
        # 严格大于：用满上限不算越限。故这里正常收尾，落在验证失败上。
        failure_class, records = self._run(
            {"input_tokens": 50, "output_tokens": 50}, max_total_tokens=100)
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(50, records[-1]["totals"]["input_tokens"])
        self.assertEqual(50, records[-1]["totals"]["output_tokens"])

    def test_no_cap_records_the_usage_but_never_trips(self):
        # 对照组：同样的记账、不同的配置。证明终止来自上限而非记账本身。
        failure_class, records = self._run({"input_tokens": 60, "output_tokens": 50})
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(60, records[-1]["totals"]["input_tokens"])

    def test_unknown_usage_is_recorded_as_none_and_cannot_trip(self):
        # 已知残差：只报了一部分量时，那个量是未知的（None），而未知不能
        # 触发终止——我们无法证明它超了。
        failure_class, records = self._run(
            {"input_tokens": 10**6}, max_total_tokens=100)
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(10**6, records[-1]["totals"]["input_tokens"])
        self.assertIsNone(records[-1]["totals"]["output_tokens"])
