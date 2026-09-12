"""主循环（冻结文件）。

不按名字 import 任何具体 agent 或具体工具：只依赖注入的 Agent 与工具注册表。
这是"可替换"的机械保证。

三条不变量：
- 工具抛出的异常永远变成 tool_result 事实，不炸掉 run。
- 自身异常记 error 事件，且 run_end 一定写出（崩溃后轨迹仍完整可读）。
- 失败分类先到者胜；连续计数跨 step 累计，故"连续"指中间没有成功。
"""

import traceback

from .. import clock, contract
from ..eval.runner import run_verification
from ..trace import prepare_stream
from .messages import Abort, ConversationState, Finish, ToolCalls

_STATUS_BY_CLASS = {
    "none": "completed",
    "verification_failed": "failed",
    "env_error": "error",
    "harness_error": "error",
}


def run_agent(*, agent, task, tools, tool_ctx, run_ctx, executor) -> str:
    config = run_ctx.config
    budgets = config.budgets
    trace = run_ctx.trace

    def elapsed_ms(t0: float) -> int:
        return clock.ms_since(t0)

    failure_class = None
    finished = False
    step = 0
    tool_call_count = 0
    started = clock.now()

    state = ConversationState(
        task_id=task.id,
        description=task.description,
        workspace=executor.visible_path(run_ctx.workspace),
    )
    state.append("user", task.description)

    trace.emit(
        "run_start",
        task_id=task.id,
        agent=agent.name,
        executor=executor.kind,
        config_hash=run_ctx.config_hash,
        harness_git_sha=run_ctx.harness_git_sha,
        python_version=run_ctx.python_version,
        schema_version=contract.SCHEMA_VERSION,
    )

    streak_sig, streak = None, 0
    denied_count = 0
    cwd_visible = executor.visible_path(run_ctx.workspace)

    try:
        while failure_class is None:
            if clock.now() - started > budgets.wall_timeout_s:
                failure_class = "timeout_wall"
                break
            if step >= budgets.max_steps:
                failure_class = "agent_loop_limit"
                break

            step += 1
            step_started = clock.now()
            action = agent.next_action(state)

            if isinstance(action, Finish):
                state.append("agent", action.summary)
                trace.emit("agent_message", step=step, role="agent", content=action.summary)
                finished = True
                break
            if isinstance(action, Abort):
                state.append("agent", action.reason)
                trace.emit("agent_message", step=step, role="agent",
                           content=f"[abort] {action.reason}")
                failure_class = "agent_gave_up"
                break
            if not isinstance(action, ToolCalls):
                raise TypeError(f"agent 返回了非法动作: {type(action).__name__}")

            for call in action.calls:
                tool_call_count += 1
                trace.emit("tool_call", step=step, call_id=call.call_id, tool=call.tool,
                           args=call.args, cwd=cwd_visible)
                outcome = tools.dispatch(tool_ctx, call)
                out_text, out_meta = prepare_stream(outcome.stdout, config.trace, run_ctx.blobs_dir)
                err_text, err_meta = prepare_stream(outcome.stderr, config.trace, run_ctx.blobs_dir)
                trace.emit("tool_result", step=step, call_id=call.call_id, tool=call.tool,
                           status=outcome.status, exit_code=outcome.exit_code,
                           duration_ms=outcome.duration_ms, reason=outcome.reason,
                           artifacts=list(outcome.artifacts),
                           stdout=out_text, stderr=err_text,
                           stdout_stream=out_meta, stderr_stream=err_meta)
                state.append("tool", {"tool": call.tool, "status": outcome.status,
                                      "exit_code": outcome.exit_code,
                                      "stdout": out_text, "stderr": err_text})

                if outcome.fatal_env:
                    failure_class = "env_error"
                    break
                if outcome.status == "denied":
                    denied_count += 1
                    streak_sig, streak = None, 0
                    if denied_count >= budgets.max_denied_calls:
                        failure_class = "policy_denied"
                        break
                elif outcome.status in ("error", "timeout"):
                    sig = outcome.reason or outcome.status
                    if sig == streak_sig:
                        streak += 1
                    else:
                        streak_sig, streak = sig, 1
                    if streak >= budgets.max_tool_error_streak:
                        failure_class = "tool_error_repeated"
                        break
                else:
                    streak_sig, streak = None, 0

            if failure_class:
                break
            if elapsed_ms(step_started) > budgets.step_timeout_s * 1000:
                failure_class = "timeout_step"
                break
            trace.emit("step_end", step=step, duration_ms=elapsed_ms(step_started))

    except KeyboardInterrupt:
        failure_class = "aborted_by_user"
    except Exception as exc:
        trace.emit("error", where="loop", exception_type=type(exc).__name__, message=str(exc),
                   traceback_tail=traceback.format_exc()[-2000:])
        failure_class = "harness_error"

    verify_result = None
    try:
        verify_result = run_verification(run_ctx, executor)
    except Exception as exc:
        trace.emit("error", where="verification", exception_type=type(exc).__name__,
                   message=str(exc), traceback_tail=traceback.format_exc()[-2000:])
        if failure_class is None and finished:
            failure_class = "harness_error"

    if failure_class is None:
        if not finished:
            failure_class = "harness_error"
        elif verify_result is None:
            failure_class = "harness_error"
        elif verify_result["status"] == "passed":
            failure_class = "none"
        elif verify_result["status"] in ("failed", "timeout"):
            failure_class = "verification_failed"
        else:
            failure_class = "env_error"

    totals = {
        "steps": step,
        "tool_calls": tool_call_count,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
    }
    trace.emit(
        "run_end",
        status=_STATUS_BY_CLASS.get(failure_class, "aborted"),
        failure_class=failure_class,
        steps=step,
        duration_ms=elapsed_ms(started),
        totals=totals,
        verification_status=(verify_result or {}).get("status"),
    )
    run_ctx.close()
    return failure_class
