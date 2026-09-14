"""把 LLM 接进主循环：状态 → 提示词 → 一次请求 → 动作。

两件事在这里收口，都是冻结接口留下的缝：

1. **step 自计数**。`contract.py` 要求 `llm_request` / `llm_response` 带 `step`，
   而 `ConversationState` 里没有 step，`loop.py` 也不负责发这两个事件（它冻结）。
   因为**本批不重试**，一个 `next_action` 恰好发一次请求，故 agent 自数的第 n 次
   调用恒等于主循环的 `step = n`。这条耦合不写在任何接口里（审计 §7.1），故由
   `tests/test_llm_agent.py` 钉住——一旦将来加重试，那条测试会先红。

2. **工具结果回填**。`loop.py` 把每次工具结果 `append("tool", {...})` 进
   `state.messages`，但不记录它回答的是哪个 tool_call；而协议的 `role="tool"`
   消息**必须**带 `tool_call_id`。故 agent 记住自己上一次发出的 tool_call id 顺序，
   在下一轮按序配对。

agent 不构造 `httpx`、也不解析 JSON：那是 `client.py` 的活。这里只做
"状态 ↔ wire 消息 ↔ 动作"的翻译。
"""

import json

from ..agent.base import Agent
from ..core.messages import Abort, Finish, ToolCall, ToolCalls
from . import prompt

LLM_AGENT_NAME = "llm"


class LlmAgent(Agent):
    def __init__(self, client):
        self.name = LLM_AGENT_NAME
        self._client = client
        self._trace = None
        self._usage = None
        self._wire = None          # wire 格式的会话历史，agent 自己维护
        self._consumed = 0         # 已翻译进 _wire 的 state.messages 条数
        self._step = 0             # 自计数，恒等于主循环的 step
        self._pending_ids = []     # 上一次发出的 tool_call id，按序

    def attach(self, run_ctx) -> None:
        """注入 `RunContext` 里的轨迹写入端与累计账本。

        与 `tests/support.py::run_scenario(attach=...)` 是同一条注入路径：这两个
        对象由 RunContext 内部创建，agent 拿不到，必须由外部交进来。
        """
        self._trace = run_ctx.trace
        self._usage = run_ctx.usage

    def next_action(self, state):
        if self._trace is None or self._usage is None:
            # 没有轨迹就发请求，等于产生一段没人记录的观测。宁可炸。
            raise RuntimeError("LlmAgent 未注入 run_ctx（attach 未被调用）")

        self._step += 1
        if self._wire is None:
            self._wire = prompt.build_messages(state)
            self._consumed = len(state.messages)
        self._absorb_new_messages(state)

        # 先记请求、再发请求：若请求挂住或失败，轨迹里留下"有一次请求、没有响应"
        # ——这正是审计 §5.2 描述的"模型挂住"的信号。
        self._trace.emit(
            "llm_request",
            step=self._step,
            model=self._client.model,
            messages=self._wire,
            tools=list(prompt.TOOL_SCHEMAS),
            params={
                "max_tokens": self._client.max_output_tokens,
                "stream": False,
                "tool_choice": "auto",
            },
        )

        reply = self._client.complete(messages=self._wire, tools=list(prompt.TOOL_SCHEMAS))

        # 账本先于事件：即便后面的解析出错，已经花掉的 token 也已入账。
        self._usage.record(input_tokens=reply.input_tokens,
                           output_tokens=reply.output_tokens)
        self._trace.emit(
            "llm_response",
            step=self._step,
            model=reply.model,
            content=reply.content,
            tool_calls=reply.tool_calls,
            stop_reason=reply.stop_reason,
            usage={"input_tokens": reply.input_tokens,
                   "output_tokens": reply.output_tokens},
            latency_ms=reply.latency_ms,
        )

        self._wire.append(_assistant_wire_message(reply))
        # 记住本次发出的 tool_call id 顺序，供下一轮把工具结果配对回填。
        self._pending_ids = [call["id"] for call in reply.tool_calls]
        return _to_action(reply)

    def _absorb_new_messages(self, state) -> None:
        """把 loop 新 append 进 state 的消息翻译成 wire 消息。"""
        new = state.messages[self._consumed:]
        self._consumed = len(state.messages)
        for entry in new:
            role, payload = entry.get("role"), entry.get("content")
            if role == "tool":
                # 协议要求 role="tool" 必须带 tool_call_id，而 state 里没有——
                # 按发出顺序配对（loop 也是按同样顺序 append 的）。
                call_id = (self._pending_ids.pop(0) if self._pending_ids
                           else f"orphan_{len(self._wire)}")
                self._wire.append({"role": "tool", "tool_call_id": call_id,
                                   "content": prompt.tool_result_text(payload)})
            elif role == "agent":
                self._wire.append({"role": "assistant", "content": str(payload)})
            else:
                self._wire.append({"role": "user", "content": str(payload)})


def _assistant_wire_message(reply) -> dict:
    message = {"role": "assistant", "content": reply.content}
    if reply.tool_calls:
        # 协议里 arguments 是 JSON **字符串**；client 已经把它解析成 dict 供我们
        # 使用，回填历史时要再序列化回去。
        message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in reply.tool_calls
        ]
    return message


def _to_action(reply):
    if reply.tool_calls:
        return ToolCalls([
            ToolCall(call_id=call["id"], tool=call["name"], args=call["arguments"])
            for call in reply.tool_calls
        ])
    if reply.content:
        if reply.stop_reason == "length":
            # 被 max_tokens 截断：内容不完整，不能当成"修好了"。Agent 接口只能
            # 表达 agent_gave_up（冻结），但真因留在了 llm_response.stop_reason
            # 里——审计 §5.4 指出的正是这条信号。
            return Abort(f"响应被 max_tokens 截断，内容不完整：{reply.content[:200]}")
        return Finish(reply.content)
    return Abort("模型既没有调用工具，也没有给出文本")
