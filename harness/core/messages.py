"""与任何 LLM SDK 无关的中立消息类型。

Agent 接口只暴露"状态进、动作出"这一对，因此假 agent 与真 LLM agent
可以共用同一个主循环。
"""

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    call_id: str
    tool: str
    args: dict


@dataclass
class ToolOutcome:
    status: str                 # contract.TOOL_RESULT_STATUSES
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    artifacts: list = field(default_factory=list)
    reason: str = ""            # 归一化错误签名，用于连续失败计数
    fatal_env: bool = False     # 执行环境本身不可用 → 终止为 env_error


@dataclass
class ToolCalls:
    calls: list


@dataclass
class Finish:
    summary: str = ""


@dataclass
class Abort:
    reason: str


@dataclass
class ConversationState:
    task_id: str
    description: str
    workspace: str
    messages: list = field(default_factory=list)

    def append(self, role: str, content) -> None:
        self.messages.append({"role": role, "content": content})
