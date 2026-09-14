"""A4：配了模型却没有凭据时，在建 run 目录之前拒绝启动。

关键不是"报了个错"，而是**没有产生任何产物**：run 目录、轨迹、工作区副本
都不该存在。晚一步失败意味着用一次失败的实验换一个本可以在启动前报出的
错误——而失败的实验会污染 runs/ 里的观察语料。

凭据本身从不进入本测试的断言：只断言"在不在"导致的行为差异。变量名从
`credentials.API_KEY_ENV` 取，不在这里重复字面量。
"""

import io
import os
import unittest
from contextlib import contextmanager, redirect_stderr
from unittest import mock

from harness import paths
from harness.__main__ import main
from harness.config import ConfigError, load_config
from harness.llm import credentials

from . import support

CONFIG_WITH_MODEL = """\
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

[trace]
truncate_threshold_bytes = 8192
head_chars = 3000
tail_chars = 3000

[llm]
model = "test-model"
"""

CONFIG_WITHOUT_MODEL = CONFIG_WITH_MODEL.split("\n[llm]")[0]

CONFIG_WITHOUT_LLM_SECTION = CONFIG_WITHOUT_MODEL


@contextmanager
def key_absent():
    """让凭据不存在——即便测试者的 shell 里真的设了一个。"""
    with mock.patch.dict(os.environ):
        os.environ.pop(credentials.API_KEY_ENV, None)
        yield


@contextmanager
def key_present():
    """让凭据存在。值只用于判断"在不在"，不会被任何地方读走。"""
    with mock.patch.dict(os.environ, {credentials.API_KEY_ENV: "present-for-test"}):
        yield


class ConfigKeyCheckTest(unittest.TestCase):
    def setUp(self):
        self.scratch = self.enterContext(support.scratch_dir("cfg"))
        self._original = paths.CONFIGS_DIR
        paths.CONFIGS_DIR = self.scratch
        self.addCleanup(setattr, paths, "CONFIGS_DIR", self._original)

    def _write(self, text, name="probe"):
        (self.scratch / f"{name}.toml").write_text(text, encoding="utf-8")
        return name

    def test_a_model_without_a_key_is_refused(self):
        name = self._write(CONFIG_WITH_MODEL)
        with key_absent(), self.assertRaises(ConfigError) as caught:
            load_config(name)
        self.assertIn(credentials.API_KEY_ENV, str(caught.exception))

    def test_a_model_with_a_key_loads(self):
        name = self._write(CONFIG_WITH_MODEL)
        with key_present():
            config = load_config(name)
        self.assertEqual("test-model", config.llm_model)

    def test_no_llm_section_needs_no_key(self):
        # 阶段 1 的配置就是这个形状：没有大脑，自然不需要凭据。
        name = self._write(CONFIG_WITHOUT_LLM_SECTION, name="nollm")
        with key_absent():
            config = load_config(name)
        self.assertIsNone(config.llm_model)

    def test_an_llm_section_without_a_model_needs_no_key(self):
        # 只写了 [llm] 但没写 model：不会发请求，凭据无从谈起。
        name = self._write(CONFIG_WITHOUT_MODEL, name="nomodel")
        with key_absent():
            config = load_config(name)
        self.assertIsNone(config.llm_model)


class StartupRefusalTest(unittest.TestCase):
    """端到端：拒绝启动时不留任何产物。"""

    def setUp(self):
        self.enterContext(support.isolated_runs_dir())
        self.scratch = self.enterContext(support.scratch_dir("cfg"))
        self._original = paths.CONFIGS_DIR
        paths.CONFIGS_DIR = self.scratch
        self.addCleanup(setattr, paths, "CONFIGS_DIR", self._original)
        (self.scratch / "probe.toml").write_text(CONFIG_WITH_MODEL, encoding="utf-8")

    def _run(self, argv) -> tuple[int, str, list]:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(argv)
        return code, stderr.getvalue(), sorted(p.name for p in paths.RUNS_DIR.iterdir())

    def test_missing_key_exits_two_and_leaves_no_run_directory(self):
        argv = ["run", "--task", "toy-001", "--agent", "scripted_ok", "--config", "probe"]
        with key_absent():
            code, err, run_dirs = self._run(argv)

        self.assertEqual(2, code)
        self.assertIn(credentials.API_KEY_ENV, err)
        self.assertEqual([], run_dirs, "拒绝启动却在 runs/ 里留下了目录")

    def test_with_a_key_the_same_command_does_create_a_run(self):
        # 反空转：同样的命令、只差凭据在不在。没有这一条，"拒绝"可能只是
        # 别的地方在报错。
        argv = ["run", "--task", "toy-001", "--agent", "scripted_ok", "--config", "probe"]
        with key_present():
            code, err, run_dirs = self._run(argv)

        self.assertEqual(0, code, err)
        self.assertEqual(1, len(run_dirs))
