"""八个脚本化对照的端到端矩阵。

这是阶段 1 最核心的一条断言：每个对照组都必须命中设计好的那一个标签。
失败分类的互斥性不靠人工检查，靠八个同时为真的等式。
"""

import unittest

from harness.agent.scripted import ScriptedAgent
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support

CONTROLS = (
    ("toy-001", "scripted_ok", None, "none"),
    ("toy-002", "scripted_ok", None, "none"),
    ("toy-001", "scripted_bad_edit", None, "verification_failed"),
    ("toy-001", "scripted_ok", "repo_faulty", "verification_failed"),
    ("toy-001", "scripted_tool_error", None, "tool_error_repeated"),
    ("toy-001", "scripted_denied", None, "policy_denied"),
    ("toy-001", "scripted_gave_up", None, "agent_gave_up"),
    ("toy-001", "scripted_loop_limit", None, "agent_loop_limit"),
)


class ScriptedControlMatrixTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def test_every_control_hits_its_designed_label(self):
        for task_id, agent_name, variant, expected in CONTROLS:
            with self.subTest(task=task_id, agent=agent_name, variant=variant or "repo"):
                task = load_task(task_id)
                failure_class, run_dir = support.run_scenario(
                    ScriptedAgent(agent_name), task, variant=variant)
                self.assertEqual(expected, failure_class)

                # 分类对了还不够：轨迹本身也必须先合契约。
                self.assertEqual([], validate_records(read_trace(run_dir / "trace.jsonl")))
