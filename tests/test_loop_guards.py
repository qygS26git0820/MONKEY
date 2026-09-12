"""主循环的每个终止守卫。

这里的 agent 全部定义在测试文件里，不继承 harness.agent 的任何东西——
主循环只调用 agent.next_action(state)，既不 import 具体 agent 也不做
isinstance 检查。这些用例能跑通，本身就是"agent 可替换"的证明。

超时类守卫把时钟压到亚秒级：默认配置的 30s/60s 不适合放进测试。
"""

import time
import unittest

from harness.core.messages import Abort, Finish, ToolCall, ToolCalls
from harness.tasks.loader import load_task

from . import support


class ForeignAgent:
    """与 harness 无继承关系的鸭子类型 agent。"""

    def __init__(self, name, actions):
        self.name = name
        self._actions = list(actions)
        self._i = 0

    def next_action(self, state):
        if self._i >= len(self._actions):
            return Finish("脚本耗尽")
        action = self._actions[self._i]
        self._i += 1
        return action(state) if callable(action) else action


def read(path):
    return ToolCalls([ToolCall("c", "read_file", {"path": path})])


def write(path, content):
    return ToolCalls([ToolCall("c", "write_file", {"path": path, "content": content})])


def run_binary(command):
    return ToolCalls([ToolCall("c", "run_command", {"command": command})])


class LoopGuardTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.task = load_task("toy-001")

    def _classify(self, agent, **overrides):
        config = support.make_config(**overrides) if overrides else None
        failure_class, _ = support.run_scenario(agent, self.task, config=config)
        return failure_class

    def test_agent_loop_limit_when_agent_never_finishes(self):
        agent = ForeignAgent("never_finishes", [read("calc.py")] * 50)
        self.assertEqual("agent_loop_limit", self._classify(agent, max_steps=5))

    def test_agent_gave_up_when_agent_aborts(self):
        agent = ForeignAgent("gives_up", [Abort("定位不到")])
        self.assertEqual("agent_gave_up", self._classify(agent))

    def test_tool_error_repeated_on_same_failure_signature(self):
        agent = ForeignAgent("bad_reads", [read("no_such_file.py")] * 10)
        self.assertEqual("tool_error_repeated",
                         self._classify(agent, max_tool_error_streak=3,
                                        max_denied_calls=1, max_steps=20))

    def test_policy_denied_after_repeated_escapes(self):
        agent = ForeignAgent("escapes", [write("../escape.txt", "x")] * 10)
        self.assertEqual("policy_denied",
                         self._classify(agent, max_denied_calls=2,
                                        max_tool_error_streak=3, max_steps=20))

    def test_env_error_when_launcher_is_missing(self):
        agent = ForeignAgent("bad_launcher",
                             [run_binary(["definitely-not-a-real-binary-xyz"])])
        self.assertEqual("env_error", self._classify(agent))

    def test_harness_error_when_agent_returns_illegal_action(self):
        agent = ForeignAgent("illegal", ["not-an-action"])
        self.assertEqual("harness_error", self._classify(agent))

    def test_aborted_by_user_on_keyboard_interrupt(self):
        def interrupt(state):
            raise KeyboardInterrupt()

        agent = ForeignAgent("interrupted", [interrupt])
        self.assertEqual("aborted_by_user", self._classify(agent))

    def test_timeout_step_when_a_single_step_overruns(self):
        def slow_read(state):
            time.sleep(0.2)
            return read("calc.py")

        agent = ForeignAgent("slow_step", [slow_read])
        self.assertEqual("timeout_step",
                         self._classify(agent, step_timeout_s=0.05, wall_timeout_s=5.0))

    def test_timeout_wall_when_steps_accumulate_past_the_budget(self):
        # 单步 0.15s 不触发 step 守卫（0.25s），但三步累计越过 0.40s 的墙。
        def slow_read(state):
            time.sleep(0.15)
            return read("calc.py")

        agent = ForeignAgent("slow_wall", [slow_read] * 50)
        self.assertEqual("timeout_wall",
                         self._classify(agent, step_timeout_s=0.25, wall_timeout_s=0.40,
                                        max_steps=50, max_tool_error_streak=3,
                                        max_denied_calls=2))


class TraceAlwaysClosedTest(unittest.TestCase):
    """无论怎么结束，run_end 都必须落盘——崩溃后轨迹仍可读。"""

    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.task = load_task("toy-001")

    def test_every_ending_writes_run_end(self):
        from harness.trace import read_trace

        cases = {
            "loop_limit": (ForeignAgent("a", [read("calc.py")] * 20), {"max_steps": 3}),
            "gave_up": (ForeignAgent("b", [Abort("停")]), {}),
            "harness_error": (ForeignAgent("c", [42]), {}),
            "aborted": (ForeignAgent("d", [lambda s: (_ for _ in ()).throw(KeyboardInterrupt())]), {}),
        }
        for label, (agent, overrides) in cases.items():
            with self.subTest(case=label):
                config = support.make_config(**overrides) if overrides else None
                failure_class, run_dir = support.run_scenario(agent, self.task, config=config)
                records = read_trace(run_dir / "trace.jsonl")
                self.assertEqual("run_end", records[-1]["type"])
                self.assertEqual(failure_class, records[-1]["failure_class"])
