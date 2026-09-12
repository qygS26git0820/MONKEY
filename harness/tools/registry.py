"""工具注册与分发。

主循环按名字查表分发，不 import 任何具体工具——这是"工具可替换"的机械保证。
工具抛出的一切异常都在这里被转成 status=error 的事实，绝不让一次工具失败
炸掉整个 run。
"""

from .. import clock
from ..core.messages import ToolOutcome
from .base import Tool
from .fs_tools import ReadFile, WriteFile
from .shell_tools import RunCommand, RunVerify


class ToolRegistry:
    def __init__(self, tools=None):
        self._tools = {}
        for tool in tools if tools is not None else default_tools():
            self.register(tool)

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list:
        return sorted(self._tools)

    def dispatch(self, ctx, call) -> ToolOutcome:
        tool = self._tools.get(call.tool)
        if tool is None:
            return ToolOutcome("error", None, stderr=f"未注册的工具: {call.tool}",
                               reason="unknown_tool")
        started = clock.now()
        try:
            outcome = tool.execute(ctx, call.args)
        except Exception as exc:
            return ToolOutcome("error", None, stderr=f"{type(exc).__name__}: {exc}",
                               reason=f"tool_exception:{type(exc).__name__}",
                               duration_ms=clock.ms_since(started))
        if not isinstance(outcome, ToolOutcome):
            return ToolOutcome("error", None, stderr="工具返回了非法结果",
                               reason="bad_tool_return")
        return outcome


def default_tools() -> list:
    return [ReadFile(), WriteFile(), RunCommand(), RunVerify()]
