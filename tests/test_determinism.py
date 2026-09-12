"""确定性：同任务同 agent 重跑，去掉时间戳后的轨迹应一致。

两类真实抖动，都在规范化里被抹掉：

1. 验证子进程自报的 unittest 运行时长（"Ran 2 tests in 0.000s"）及由它派生的 sha。
2. 失败用例的回溯里带着工作区的绝对路径——而工作区路径里含 run_id。
   见 test_failure_output_embeds_run_path：这不是测试的局限，是被观测的现实。
   阶段 2/3 换容器后端后，同一段输出会变成 /workspace/...，agent 看到的
   自身失败信息会随后端而变。这条留作跨后端可比性的已知混杂项。

除这两类外，字段要求严格相等——否则"对照实验"这个前提就不成立。
"""

import json
import re
import unittest

from harness.agent.scripted import ScriptedAgent
from harness.tasks.loader import load_task
from harness.trace import read_trace

from . import support

VOLATILE = ("ts_mono", "ts_wall", "duration_ms", "run_id")
_RAN = re.compile(r"Ran (\d+) tests? in [0-9.]+s")


def _scrub_text(text, run_dir):
    text = _RAN.sub(r"Ran \1 tests in <elapsed>", text)
    return text.replace(str(run_dir), "<run_dir>")


def _scrub_stream(meta):
    return {k: v for k, v in meta.items() if not k.startswith("sha256_")}


def _project(records, run_dir):
    """把轨迹投影成可比较的形状，只抹掉真实抖动，不抹掉结构。

    run_id 出现在两个地方：run_id 字段本身，以及失败回溯里的绝对路径。
    后者要在 JSON 文本层替换——结构化字段里它是子串，看不见。
    """
    escaped = json.dumps(str(run_dir))[1:-1]
    out = []
    for rec in records:
        item = json.loads(json.dumps(rec, ensure_ascii=False, sort_keys=True)
                          .replace(escaped, "<run_dir>"))
        item = {k: v for k, v in item.items() if k not in VOLATILE}
        for key in ("stdout", "stderr"):
            if key in item:
                item[key] = _scrub_text(item[key], run_dir)
        for key in ("stdout_stream", "stderr_stream"):
            if key in item:
                item[key] = _scrub_stream(item[key])
        out.append(item)
    return out


class DeterminismTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.task = load_task("toy-001")

    def _two_runs(self, agent_name):
        first_class, first_dir = support.run_scenario(ScriptedAgent(agent_name), self.task)
        second_class, second_dir = support.run_scenario(ScriptedAgent(agent_name), self.task)
        return (
            first_class, _project(read_trace(first_dir / "trace.jsonl"), first_dir),
            second_class, _project(read_trace(second_dir / "trace.jsonl"), second_dir),
        )

    def test_passing_run_is_reproducible(self):
        first_class, first, second_class, second = self._two_runs("scripted_ok")
        self.assertEqual("none", first_class)
        self.assertEqual(first_class, second_class)
        self.assertEqual(first, second)

    def test_failing_run_is_reproducible(self):
        first_class, first, second_class, second = self._two_runs("scripted_bad_edit")
        self.assertEqual("verification_failed", first_class)
        self.assertEqual(first_class, second_class)
        self.assertEqual(first, second)

    def test_failure_output_embeds_run_path(self):
        # 把这条现象钉成断言，而不是假装它不存在：失败回溯里是宿主绝对路径。
        # 阶段 2/3 换成容器后端时，这里会变成容器内路径，届时必须重新评估。
        _, run_dir = support.run_scenario(ScriptedAgent("scripted_bad_edit"), self.task)
        verify_output = "".join(
            rec["stderr"] for rec in read_trace(run_dir / "trace.jsonl")
            if rec["type"] == "tool_result" and rec["tool"] == "run_verify"
        )
        self.assertIn(str(run_dir / "workspace"), verify_output)

    def test_trace_records_workspace_relative_paths(self):
        # executor.visible_path 的存在意义：轨迹里记的是 agent 视角的路径，
        # 不把宿主机的绝对布局焊进语料。
        _, run_dir = support.run_scenario(ScriptedAgent("scripted_ok"), self.task)
        calls = [r for r in read_trace(run_dir / "trace.jsonl") if r["type"] == "tool_call"]
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual("workspace", call["cwd"])
