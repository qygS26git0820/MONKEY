"""成本/用量预算的两端：配置期的拒绝，运行期的终止。

上半（ConfigCostCapTest）测启动前：设了成本上限就必须能算成本，否则拒绝
启动，不建 run 目录。下半（BudgetStopTest）测运行中：agent 记的用量越过
上限时，主循环以 cost_budget_exceeded 终止，且验证照跑（schema R3）。

预算检查点由 loop.py 提供，本文件的 agent 与 loop.py 无继承关系——它只
需要能在 next_action 里往 run_ctx.usage 记一笔。attach 就是拿到那个账本
的入口。
"""

import unittest

from harness import paths
from harness.config import ConfigError, load_config
from harness.core.messages import Finish
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support

# 最小合法配置。字段值取自 configs/default.toml，好让"只有上限不同"这个
# 对照成立——被拒绝的原因只可能是上限，不是别的字段写错。
CONFIG_TEMPLATE = """\
[executor]
kind = "local"

[budgets]
max_steps = 8
wall_timeout_s = 60.0
step_timeout_s = 30.0
per_tool_timeout_s = 10.0
verify_timeout_s = 30.0
max_tool_error_streak = 3
max_denied_calls = 2
{extra_budget}

[trace]
truncate_threshold_bytes = 8192
head_chars = 3000
tail_chars = 3000
{llm_section}
"""


class ConfigCostCapTest(unittest.TestCase):
    """设了 max_cost_usd 却没有可信单价 → 拒绝启动。"""

    def setUp(self):
        self.scratch = self.enterContext(support.scratch_dir("cfg"))
        self._original = paths.CONFIGS_DIR
        paths.CONFIGS_DIR = self.scratch
        self.addCleanup(setattr, paths, "CONFIGS_DIR", self._original)

    def _write_and_load(self, *, model=None, max_cost_usd=None,
                        max_total_tokens=None):
        extra = ""
        if max_cost_usd is not None:
            extra += f"max_cost_usd = {max_cost_usd}\n"
        if max_total_tokens is not None:
            extra += f"max_total_tokens = {max_total_tokens}\n"
        llm = "" if model is None else f'\n[llm]\nmodel = "{model}"\n'
        text = CONFIG_TEMPLATE.format(extra_budget=extra.rstrip("\n"), llm_section=llm)
        (self.scratch / "probe.toml").write_text(text, encoding="utf-8")
        return load_config("probe")

    def test_cap_without_a_model_is_refused(self):
        with self.assertRaises(ConfigError) as caught:
            self._write_and_load(max_cost_usd=1.0)
        self.assertIn("model", str(caught.exception))

    def test_cap_with_an_unpriced_model_is_refused(self):
        # pricing.PRICES 目前为空，任何模型名都查不到单价。
        with self.assertRaises(ConfigError) as caught:
            self._write_and_load(model="no-such-model", max_cost_usd=1.0)
        self.assertIn("no-such-model", str(caught.exception))

    def test_cap_with_a_priced_model_loads(self):
        from harness.llm import pricing

        pricing.PRICES["test-model"] = (1.0, 2.0, "test fixture", "2026-09-13")
        self.addCleanup(pricing.PRICES.pop, "test-model", None)

        config = self._write_and_load(model="test-model", max_cost_usd=1.0)
        self.assertEqual(1.0, config.budgets.max_cost_usd)
        self.assertEqual("test-model", config.llm_model)

    def test_unpriced_model_without_a_cost_cap_loads(self):
        # 没有上限时，成本未知是可接受的：跑得起来，只是拿不到成本数字。
        config = self._write_and_load(model="no-such-model")
        self.assertIsNone(config.budgets.max_cost_usd)
        self.assertEqual("no-such-model", config.llm_model)

    def test_token_cap_alone_needs_no_price(self):
        # token 上限只数 token，不需要单价。
        config = self._write_and_load(max_total_tokens=1000)
        self.assertEqual(1000, config.budgets.max_total_tokens)
        self.assertIsNone(config.llm_model)


class SpendingAgent:
    """第一笔就记一笔用量，然后 Finish。

    记完就 Finish 是有意的：主循环的预算检查排在动作分派**之前**，所以
    "记了一笔超支的量、同时给出 Finish"必须止于 cost_budget_exceeded。
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

    def test_cost_cap_trips_on_a_single_overspend(self):
        failure_class, records = self._run({"cost_usd": 0.9}, max_cost_usd=0.5)
        self.assertEqual("cost_budget_exceeded", failure_class)

        end = records[-1]
        self.assertEqual("run_end", end["type"])
        self.assertEqual("cost_budget_exceeded", end["failure_class"])
        # cost_budget_exceeded 不在 _STATUS_BY_CLASS 里，落到默认值 aborted。
        self.assertEqual("aborted", end["status"])
        self.assertEqual(0.9, end["totals"]["cost_usd"])
        self.assertEqual([], validate_records(records))

    def test_verification_still_runs_after_a_budget_stop(self):
        # schema R3：无论因何终止，只要工作区在就照跑验证。
        _, records = self._run({"cost_usd": 0.9}, max_cost_usd=0.5)
        verifications = [r for r in records if r["type"] == "verification"]
        self.assertEqual(1, len(verifications))
        # 这个 agent 没改任何文件，toy-001 的仓库仍是坏的。
        self.assertEqual("failed", verifications[0]["status"])

    def test_spending_exactly_at_the_cap_does_not_trip(self):
        # 严格大于：花到上限不算超支。故这里正常收尾，落在验证失败上。
        failure_class, records = self._run({"cost_usd": 0.5}, max_cost_usd=0.5)
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(0.5, records[-1]["totals"]["cost_usd"])

    def test_token_cap_trips_on_input_plus_output(self):
        failure_class, records = self._run(
            {"input_tokens": 60, "output_tokens": 50}, max_total_tokens=100)
        self.assertEqual("cost_budget_exceeded", failure_class)
        self.assertEqual(60, records[-1]["totals"]["input_tokens"])
        self.assertEqual(50, records[-1]["totals"]["output_tokens"])

    def test_no_cap_records_the_usage_but_never_trips(self):
        # 对照组：同样的记账、不同的配置。证明终止来自上限而非记账本身。
        failure_class, records = self._run({"cost_usd": 999.0})
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(999.0, records[-1]["totals"]["cost_usd"])

    def test_unknown_cost_is_recorded_as_none_and_cannot_trip(self):
        # 已知残差：只报了一部分量时，那个量是未知的（None），而未知不能
        # 触发终止——我们无法证明它超了。
        failure_class, records = self._run({"input_tokens": 10}, max_cost_usd=0.5)
        self.assertEqual("verification_failed", failure_class)
        self.assertEqual(10, records[-1]["totals"]["input_tokens"])
        self.assertIsNone(records[-1]["totals"]["cost_usd"])
