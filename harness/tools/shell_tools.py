"""命令执行工具与验证工具。命令一律以参数列表给出，绝不走 shell。"""

import sys

from .. import clock
from ..core.messages import ToolOutcome
from .base import Tool
from .policy import PathPolicyError, resolve_in_workspace


class RunCommand(Tool):
    name = "run_command"

    def execute(self, ctx, args) -> ToolOutcome:
        started = clock.now()
        command = args.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
            return ToolOutcome("error", None, stderr="command 必须是非空字符串列表",
                               reason="bad_args", duration_ms=_ms(started))
        try:
            cwd = resolve_in_workspace(ctx.workspace, args.get("cwd", "."))
        except PathPolicyError as exc:
            return ToolOutcome("denied", None, stderr=str(exc), reason="path_outside_workspace")
        timeout = float(args.get("timeout_s", ctx.config.budgets.per_tool_timeout_s))

        result = ctx.executor.run(command, cwd, timeout)
        if result.launcher_error:
            return ToolOutcome("error", None, stderr=result.launcher_error,
                               reason="launcher_error", fatal_env=True,
                               duration_ms=result.duration_ms)
        status = "timeout" if result.timed_out else ("ok" if result.exit_code == 0 else "error")
        reason = "" if status == "ok" else ("tool_timeout" if status == "timeout" else "nonzero_exit")
        return ToolOutcome(status, result.exit_code, stdout=result.stdout, stderr=result.stderr,
                           reason=reason, duration_ms=result.duration_ms)


class RunVerify(Tool):
    """执行任务定义的验证命令。agent 无法选择用哪条命令证明自己对了。"""

    name = "run_verify"

    def execute(self, ctx, args) -> ToolOutcome:
        spec = ctx.task.verify
        command = [_substitute(a) for a in spec["command"]]
        try:
            cwd = resolve_in_workspace(ctx.workspace, spec.get("cwd", "."))
        except PathPolicyError as exc:
            return ToolOutcome("denied", None, stderr=str(exc), reason="path_outside_workspace")

        result = ctx.executor.run(command, cwd, ctx.config.budgets.verify_timeout_s)
        if result.launcher_error:
            return ToolOutcome("error", None, stderr=result.launcher_error,
                               reason="launcher_error", fatal_env=True,
                               duration_ms=result.duration_ms)
        status = "timeout" if result.timed_out else ("ok" if result.exit_code == 0 else "error")
        reason = "" if status == "ok" else ("tool_timeout" if status == "timeout" else "tests_failed")
        return ToolOutcome(status, result.exit_code, stdout=result.stdout, stderr=result.stderr,
                           reason=reason, duration_ms=result.duration_ms)


def _substitute(token: str) -> str:
    if token == "{python}":
        return sys.executable
    if token == "{workspace}":
        return "."
    return token


def _ms(started: float) -> int:
    return clock.ms_since(started)
