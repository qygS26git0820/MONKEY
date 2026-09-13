"""无污染自证。

对应设计文档 §3-D6 与 §4.4：跑完任务后，`harness/ configs/ tasks/` 的文件哈希
清单必须与运行前逐条一致。

它保护的是"产物不污染代码"这个不变量。最要紧的一条是 tasks/：
`tasks/<id>/repo/` 是任务模板，运行时只应被**复制**进 runs/<id>/workspace/，
绝不能被就地改动——否则第一个 run 会把题目改坏，之后所有 run 都在做一道
已经被人做过的题，而对照实验的前提就此失效。

`__pycache__` 不计：它由解释器按需生成，与 agent 行为无关。
"""

import hashlib
import unittest

from harness import paths
from harness.agent.scripted import ScriptedAgent
from harness.tasks.loader import load_task

from . import support

WATCHED = ("harness", "configs", "tasks")

# 覆盖会改动工作区的三类 agent，以及一个多文件任务。
SCENARIOS = (
    ("toy-001", "scripted_ok", None),
    ("toy-001", "scripted_bad_edit", None),
    ("toy-001", "scripted_denied", None),
    ("toy-002", "scripted_ok", None),
)


def hash_manifest() -> dict:
    manifest = {}
    for top in WATCHED:
        for path in sorted((paths.PROJECT_ROOT / top).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            key = path.relative_to(paths.PROJECT_ROOT).as_posix()
            manifest[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


class NoPollutionTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def test_running_tasks_leaves_source_and_templates_untouched(self):
        before = hash_manifest()
        self.assertGreater(len(before), 0, "哈希清单为空，这条测试就没在保护任何东西")

        for task_id, agent_name, variant in SCENARIOS:
            with self.subTest(task=task_id, agent=agent_name, variant=variant or "repo"):
                support.run_scenario(
                    ScriptedAgent(agent_name), load_task(task_id), variant=variant)

        after = hash_manifest()

        self.assertEqual(sorted(before), sorted(after), "有文件被新增或删除")
        changed = sorted(k for k in before if before[k] != after.get(k))
        self.assertEqual([], changed, f"这些文件在运行后被改动: {changed}")

    def test_task_templates_survive_a_correct_fix(self):
        # 单独把最要紧的那条挑出来直说：答案是写进副本的，不是写进题目的。
        target = "tasks/toy-001/repo/calc.py"
        before = hash_manifest()[target]
        support.run_scenario(ScriptedAgent("scripted_ok"), load_task("toy-001"))
        self.assertEqual(before, hash_manifest()[target],
                         "agent 的修复被写回了任务模板；下一次 run 将跑在已被改过的题上")
