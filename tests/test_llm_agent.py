"""接线批次（提交 2）的离线验证：用假客户端替换传输层，跑**完整主循环**。

不花一分钱、不碰网络：真端点长什么样由冒烟探针回答，这里不假装。

盯住三件事：
- 动作翻译：tool_calls → `ToolCalls`，纯文本 → `Finish`，空响应 → `Abort`。
- 轨迹：`llm_request` / `llm_response` 写进去了、字段齐、`step` 与主循环对齐。
- 工具结果回填：下一轮请求里带上了 `role="tool"` 与正确的 `tool_call_id`。
"""

import copy
import os
import unittest
from contextlib import contextmanager
from unittest import mock

from harness.agent.scripted import FIXED_CALC, AGENT_NAMES
from harness.core.errors import ModelFailure
from harness.llm import credentials, prompt
from harness.llm.agent import LLM_AGENT_NAME, LlmAgent
from harness.llm.client import SHIPPED_TIMEOUTS, LlmReply
from harness.config import load_config
from harness.__main__ import build_parser
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support

IN_TOKENS = 100
OUT_TOKENS = 20


@contextmanager
def _key_present():
    with mock.patch.dict(os.environ, {credentials.API_KEY_ENV: "probe-sentinel-key"}):
        yield


def _reply(*, content=None, tool_calls=(), stop_reason="stop"):
    return LlmReply(
        model="fake-model", content=content, tool_calls=list(tool_calls),
        stop_reason=stop_reason, input_tokens=IN_TOKENS, output_tokens=OUT_TOKENS,
        latency_ms=1, request_json_bytes=2,
    )


def _call(name, args, call_id):
    return {"id": call_id, "name": name, "arguments": args}


def _success_script() -> list:
    """读 → 改 → 验证 → 收尾。跑完应当 failure_class == "none"。"""
    return [
        _reply(tool_calls=[_call("read_file", {"path": "calc.py"}, "c1")],
               stop_reason="tool_calls"),
        _reply(tool_calls=[_call("write_file",
                                 {"path": "calc.py", "content": FIXED_CALC}, "c2")],
               stop_reason="tool_calls"),
        _reply(tool_calls=[_call("run_verify", {}, "c3")], stop_reason="tool_calls"),
        _reply(content="已修复并通过验证"),
    ]


class FakeClient:
    """离线替身：不发请求，按脚本返回 `LlmReply`，或者把脚本里的异常抛出去。"""

    model = "fake-model"
    max_output_tokens = 2048

    def __init__(self, script):
        self._script = list(script)
        self.calls = []          # 每次收到的 (messages, tools) 深拷贝，供断言

    def complete(self, *, messages, tools=None):
        # 深拷贝：agent 复用并就地改自己的 _wire，不拷的话断言看到的是"最后一次"。
        self.calls.append({"messages": copy.deepcopy(messages), "tools": tools})
        if not self._script:
            raise AssertionError("假客户端脚本用完了——模型被多问了一次？")
        step = self._script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


class LlmAgentRunTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def _run(self, script, task_id="toy-001"):
        client = FakeClient(script)
        failure_class, run_dir = support.run_scenario(
            LlmAgent(client), load_task(task_id),
            attach=lambda ctx, agent: agent.attach(ctx))
        return client, failure_class, run_dir

    def _records(self, run_dir):
        return read_trace(run_dir / "trace.jsonl")

    # --- 端到端 ---------------------------------------------------------

    def test_a_full_offline_run_completes_with_a_valid_trace(self):
        _, failure_class, run_dir = self._run(_success_script())

        self.assertEqual("none", failure_class)
        records = self._records(run_dir)
        self.assertEqual([], validate_records(records))
        self.assertEqual(4, sum(1 for r in records if r["type"] == "llm_request"))
        self.assertEqual(4, sum(1 for r in records if r["type"] == "llm_response"))

    def test_the_self_counted_step_matches_the_loop_step(self):
        # 审计 §7.1 的耦合：agent 自己数 step，主循环也数，两者必须对齐。
        # 一旦将来在一个 step 内重试（多发一次请求），这条会先红。
        _, _, run_dir = self._run(_success_script())
        records = self._records(run_dir)

        llm_steps = sorted({r["step"] for r in records
                            if r["type"] == "llm_response"})
        loop_steps = sorted({r["step"] for r in records if r["type"] == "tool_call"})

        self.assertEqual([1, 2, 3], loop_steps, "主循环的 step 形状变了")
        self.assertEqual([1, 2, 3, 4], llm_steps, "自计数不连续或与主循环错位")
        self.assertTrue(set(loop_steps) <= set(llm_steps),
                        "主循环记的 step 里有一个没有对应的 llm_response")

    def test_usage_is_accumulated_into_the_run_totals(self):
        _, _, run_dir = self._run(_success_script())
        end = next(r for r in self._records(run_dir) if r["type"] == "run_end")

        self.assertEqual(4 * IN_TOKENS, end["totals"]["input_tokens"])
        self.assertEqual(4 * OUT_TOKENS, end["totals"]["output_tokens"])
        self.assertEqual(4, end["totals"]["steps"])
        self.assertEqual(3, end["totals"]["tool_calls"])

    # --- 请求内容 -------------------------------------------------------

    def test_the_first_request_carries_the_system_prompt_the_task_and_the_tools(self):
        client, _, _ = self._run(_success_script())
        first = client.calls[0]

        self.assertEqual("system", first["messages"][0]["role"])
        self.assertIn("run_verify", first["messages"][0]["content"])
        self.assertEqual("user", first["messages"][1]["role"])
        self.assertEqual(load_task("toy-001").description,
                         first["messages"][1]["content"])
        self.assertEqual(len(prompt.TOOL_SCHEMAS), len(first["tools"]))

    def test_the_next_request_carries_the_tool_result_with_its_call_id(self):
        client, _, _ = self._run(_success_script())
        messages = client.calls[1]["messages"]

        assistant, tool_message = messages[-2], messages[-1]
        self.assertEqual("assistant", assistant["role"])
        self.assertEqual("c1", assistant["tool_calls"][0]["id"])
        self.assertEqual("tool", tool_message["role"])
        self.assertEqual("c1", tool_message["tool_call_id"])
        self.assertIn("status=ok", tool_message["content"])
        # 读到的是工作区里那个坏实现，证明工具输出真的回流到了模型。
        self.assertIn("return a - b", tool_message["content"])

    def test_arguments_round_trip_as_a_json_string_on_the_wire(self):
        client, _, _ = self._run(_success_script())
        # 第二次请求里最后一条 assistant 消息的 arguments 必须是 JSON 字符串
        assistant = client.calls[1]["messages"][-2]
        arguments = assistant["tool_calls"][0]["function"]["arguments"]
        self.assertIsInstance(arguments, str)
        self.assertIn("calc.py", arguments)

    # --- 失败路径 -------------------------------------------------------

    def test_a_transport_failure_lands_as_llm_transport_error(self):
        script = [ModelFailure("llm_transport_error", detail="总时限 90s 超时")]
        _, failure_class, run_dir = self._run(script)

        self.assertEqual("llm_transport_error", failure_class)
        records = self._records(run_dir)
        end = next(r for r in records if r["type"] == "run_end")
        self.assertEqual("error", end["status"])
        errors = [r for r in records if r["type"] == "error"]
        self.assertEqual(["llm"], [e["where"] for e in errors])
        # 请求已记、响应缺席——"挂住"在轨迹里就是这个形状（审计 §5.2 的信号）。
        kinds = [r["type"] for r in records]
        self.assertIn("llm_request", kinds)
        self.assertNotIn("llm_response", kinds)

    def test_a_length_truncated_reply_aborts_and_leaves_the_reason_in_the_trace(self):
        _, failure_class, run_dir = self._run(
            [_reply(content="我开始分析了，但是…", stop_reason="length")])

        self.assertEqual("agent_gave_up", failure_class)
        records = self._records(run_dir)
        response = next(r for r in records if r["type"] == "llm_response")
        self.assertEqual("length", response["stop_reason"])
        message = next(r for r in records if r["type"] == "agent_message")
        self.assertIn("截断", message["content"])

    def test_an_empty_reply_aborts(self):
        _, failure_class, _ = self._run([_reply(content=None)])
        self.assertEqual("agent_gave_up", failure_class)

    def test_an_unbound_agent_is_our_bug_not_a_gateway_error(self):
        # 没 attach 就发请求 = 产生一段没人记录的观测。要炸，且是我们的错。
        failure_class, _ = support.run_scenario(
            LlmAgent(FakeClient([_reply(content="x")])), load_task("toy-001"))
        self.assertEqual("harness_error", failure_class)


class LlmAgentNamingTest(unittest.TestCase):
    """裁定 2：真 agent 的名字不混进阶段 1 的假 agent 清单。"""

    def test_the_name_is_not_in_the_scripted_list(self):
        self.assertNotIn(LLM_AGENT_NAME, AGENT_NAMES)

    def test_the_cli_accepts_the_name(self):
        args = build_parser().parse_args(
            ["run", "--task", "toy-001", "--agent", "llm", "--config", "llm"])
        self.assertEqual(LLM_AGENT_NAME, args.agent)

    def test_the_agent_reports_the_name(self):
        self.assertEqual(LLM_AGENT_NAME, LlmAgent(FakeClient([])).name)


class LlmCliRefusalTest(unittest.TestCase):
    """选了真 agent 却没配模型：启动前拒绝，不留任何产物。"""

    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def test_agent_llm_without_an_llm_model_is_refused_before_any_artifacts(self):
        import io
        from contextlib import redirect_stderr
        from harness import paths
        from harness.__main__ import main

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(["run", "--task", "toy-001", "--agent", LLM_AGENT_NAME,
                         "--config", "default"])

        self.assertEqual(2, code)
        self.assertIn("[llm]", stderr.getvalue())
        self.assertEqual([], sorted(p.name for p in paths.RUNS_DIR.iterdir()),
                         "拒绝启动却在 runs/ 里留下了目录")


class ShippedLlmConfigTest(unittest.TestCase):
    """configs/llm.toml 与客户端超时之间的顺序不变量（记录 6 §6.3）。"""

    def setUp(self):
        self.enterContext(_key_present())

    def test_the_client_deadline_is_below_the_step_timeout(self):
        config = load_config("llm")
        # 慢而未挂的调用要先被客户端判成更具体的 llm_transport_error，
        # 而不是泛化的 timeout_step。
        self.assertLess(SHIPPED_TIMEOUTS.total_s, config.budgets.step_timeout_s)

    def test_the_smoke_run_is_not_budget_capped(self):
        self.assertIsNone(load_config("llm").budgets.max_total_tokens)

    def test_the_config_names_a_model_and_an_endpoint(self):
        config = load_config("llm")
        self.assertTrue(config.llm_model)
        self.assertTrue(config.llm_base_url)

    def test_the_phase1_config_is_still_untouched(self):
        # 真 LLM 配置是新文件，default.toml 一个字没动。
        self.assertIsNone(load_config("default").llm_model)
