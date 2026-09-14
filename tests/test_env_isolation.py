"""A1：被观测的进程看不到宿主的 MONKEY_* 变量。

要证明的不是"过滤器写了"，而是"agent 主动去读也读不到"。因此本文件的
正例都让子进程自己枚举环境，而不是从外部断言 env 字典长什么样——前者是
被观测对象的视角，后者是观测者的视角，两者不是一回事。

三个方向都要有对照，否则测试可能是空转的：
- MONKEY_* 不可见（要防的事）
- 其它变量仍然可见（证明环境不是被整个清空）
- 显式传入的 MONKEY_* 可见（证明过滤只针对"继承"，不针对"有意传递"）
"""

import json
import os
import sys
import unittest
from unittest import mock

from harness.core.messages import Finish, ToolCall, ToolCalls
from harness.env.local import HIDDEN_ENV_PREFIX, LocalExecutor
from harness.tasks.loader import load_task

from . import support

CANARY = "MONKEY_TEST_CANARY"
PLAIN = "PLAIN_TEST_CANARY"
CANARY_VALUE = "sk-this-must-never-be-observable"

# 子进程自己枚举 MONKEY_* 前缀的变量，把结果以 JSON 打到 stdout。
DUMP_MONKEY_ENV = (
    "import json, os; "
    "print(json.dumps({k: v for k, v in os.environ.items() "
    "if k.startswith('MONKEY_')}, sort_keys=True))"
)


def _env(**values):
    """临时写入环境变量，退出时精确还原（含"原本不存在"的情形）。"""
    return mock.patch.dict(os.environ, values)


class ChildEnvTest(unittest.TestCase):
    def setUp(self):
        self.root = self.enterContext(support.scratch_dir("env"))
        self.executor = LocalExecutor(self.root)
        self.enterContext(_env(**{CANARY: CANARY_VALUE, PLAIN: "visible-on-purpose"}))

    def _run(self, code, env=None) -> str:
        result = self.executor.run(
            [sys.executable, "-c", code], self.root, 30.0, env=env)
        self.assertEqual(0, result.exit_code, f"子进程未正常退出: {result.stderr}")
        return result.stdout.strip()

    def test_a_child_that_enumerates_the_environment_finds_no_monkey_vars(self):
        self.assertEqual("{}", self._run(DUMP_MONKEY_ENV))

    def test_the_environment_is_not_merely_emptied(self):
        # 正向对照：过滤的是前缀，不是全部。没有这一条，"环境被整体清空"
        # 这种更粗暴的实现也会让上一条通过。
        out = self._run(f"import os; print(os.environ.get({PLAIN!r}, 'MISSING'))")
        self.assertEqual("visible-on-purpose", out)

    def test_explicitly_passed_env_reaches_the_child(self):
        # 显式传递是调用方有意为之，不受前缀过滤约束。
        explicit = f"{HIDDEN_ENV_PREFIX}EXPLICIT"
        out = self._run(DUMP_MONKEY_ENV, env={explicit: "yes"})
        self.assertEqual(json.dumps({explicit: "yes"}, sort_keys=True), out)


class EnvDumpAgent:
    """第一次动作让工具去打印那个凭据，第二次收工。"""

    name = "env-dump"

    def __init__(self):
        self._step = 0

    def next_action(self, state):
        self._step += 1
        if self._step > 1:
            return Finish("环境已探测完毕")
        code = (
            "import os; "
            f"print('CANARY=' + os.environ.get({CANARY!r}, 'MISSING'))"
        )
        return ToolCalls([ToolCall("c1", "run_command",
                                   {"command": [sys.executable, "-c", code]})])


class TraceLeakTest(unittest.TestCase):
    """端到端：一个主动去读环境的 agent，也读不到凭据。"""

    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.enterContext(_env(**{CANARY: CANARY_VALUE}))

    def test_the_canary_never_reaches_the_trace(self):
        _, run_dir = support.run_scenario(EnvDumpAgent(), load_task("toy-001"))
        trace_text = (run_dir / "trace.jsonl").read_text(encoding="utf-8")

        self.assertNotIn(CANARY_VALUE, trace_text)
        # 反空转：命令确实执行了、确实读了环境，只是读到的不是那个值。
        self.assertIn("CANARY=MISSING", trace_text)
