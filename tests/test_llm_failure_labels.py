"""三个 LLM 失败标签的**产生点**，以及非法标签的降级分支。

标签在 contract.py 里"声明了"不等于"会产生"——trace-schema.md 记录 1 里
为 `cost_budget_exceeded` 专门写过这件事（它从"声明了但没有产生点"变成有
产生点才算数）。本文件让假 agent 抛 ModelFailure，证明主循环真的把它们落进
run_end，而不是让它们停在常数表里。

真 LLM 客户端属于后续工作。这里先测主循环侧，是为了让标签的产生点先于
客户端定稿：否则网关上线后的第一批轨迹就带着无法分类的失败，而这批轨迹
正是最需要分类的那一批。
"""

import unittest

from harness import contract
from harness.core.errors import ModelFailure
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support


class FailingAgent:
    """第一次动作就抛 ModelFailure。"""

    name = "llm-failing"

    def __init__(self, failure_class, detail="网关返回了无法解析的响应"):
        self._failure_class = failure_class
        self._detail = detail

    def next_action(self, state):
        raise ModelFailure(self._failure_class, self._detail)


class LabelProducedTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.task = load_task("toy-001")

    def _run(self, failure_class, detail=None):
        agent = (FailingAgent(failure_class) if detail is None
                 else FailingAgent(failure_class, detail))
        _, run_dir = support.run_scenario(agent, self.task)
        records = read_trace(run_dir / "trace.jsonl")
        return records

    def test_each_label_reaches_run_end(self):
        for label in contract.LLM_FAILURE_CLASSES:
            with self.subTest(label=label):
                records = self._run(label)
                end = records[-1]

                self.assertEqual("run_end", end["type"])
                self.assertEqual(label, end["failure_class"])
                self.assertEqual("error", end["status"],
                                 "LLM 失败不是被中止（aborted），是出错（error）")
                self.assertEqual([], validate_records(records))

    def test_the_error_event_carries_the_label_and_the_llm_origin(self):
        records = self._run("llm_transport_error", detail="connect timeout")

        errors = [r for r in records if r["type"] == "error"]
        self.assertEqual(1, len(errors))
        self.assertEqual("llm", errors[0]["where"])
        self.assertEqual("llm_transport_error", errors[0]["failure_class"])
        self.assertEqual("ModelFailure", errors[0]["exception_type"])
        self.assertIn("connect timeout", errors[0]["message"])

    def test_the_label_wins_over_the_verification_verdict(self):
        # 这个 agent 什么都没改，验证必然失败。若 run_end 落在
        # verification_failed，说明 LLM 失败被后续的验证判定覆盖了——
        # "为什么 run 结束"就答错了。
        records = self._run("llm_api_rejected")

        self.assertEqual("llm_api_rejected", records[-1]["failure_class"])
        verifications = [r for r in records if r["type"] == "verification"]
        self.assertEqual(1, len(verifications), "R3：验证仍要照跑")
        self.assertEqual("failed", verifications[0]["status"])

    def test_an_unknown_label_degrades_to_harness_error(self):
        # 抛出方给了一个我们不认识的标签：不能把它原样落盘（那会让轨迹里
        # 出现未声明的 failure_class，validate_records 都拦不住它），
        # 退回 harness_error——"分类失败"本身就是我们这边的问题。
        records = self._run("gateway_melted")

        self.assertEqual("harness_error", records[-1]["failure_class"])
        self.assertEqual("harness_error",
                         [r for r in records if r["type"] == "error"][0]["failure_class"])
        self.assertEqual([], validate_records(records))


class LabelDeclarationTest(unittest.TestCase):
    """三标签与冻结常数的关系。"""

    def test_labels_are_declared_and_ranked_where_documented(self):
        order = contract.FAILURE_DECISION_ORDER
        env_error = order.index("env_error")

        for label in contract.LLM_FAILURE_CLASSES:
            with self.subTest(label=label):
                self.assertIn(label, contract.FAILURE_CLASSES)
                self.assertIn(label, order)
                # 紧跟在 env_error 之后：与"执行环境不可用"同属外部原因，
                # 而不是我们代码的 bug。这正是把三者从 harness_error 里
                # 分出来的理由。
                self.assertGreater(order.index(label), env_error)
                self.assertLess(order.index(label), order.index("cost_budget_exceeded"))
                self.assertLess(order.index(label), order.index("none"))

    def test_the_three_labels_are_the_documented_ones(self):
        # 名字本身是冻结语义：改名 = 历史轨迹里的标签失去定义。
        self.assertEqual(
            ("llm_transport_error", "llm_api_rejected", "llm_response_invalid"),
            contract.LLM_FAILURE_CLASSES,
        )

    def test_llm_labels_are_not_silently_widened(self):
        # LLM_FAILURE_CLASSES 是"主循环认识哪些标签"的判据。它若比三个多，
        # 就等于主循环开始接受未在文档里定义过的分类。
        self.assertEqual(3, len(contract.LLM_FAILURE_CLASSES))
        self.assertEqual(len(set(contract.LLM_FAILURE_CLASSES)),
                         len(contract.LLM_FAILURE_CLASSES))
