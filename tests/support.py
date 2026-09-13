"""测试辅助。

两个刻意的选择：
- 运行目录被重定向到 tmp/。runs/ 只放真实实验，观察语料不能被测试掺入。
- 配置直接构造而非读 toml，好让守卫类测试把超时压到亚秒级。
  make_config 不做不变量校验（load_config 才做），调用方负责给出自洽的数值。
"""

import shutil
import uuid
from contextlib import contextmanager

from harness import paths
from harness.config import Budgets, Config, TraceOptions
from harness.core.loop import run_agent
from harness.env.factory import make_executor
from harness.runctx import RunContext
from harness.tools.context import ToolContext
from harness.tools.registry import ToolRegistry


@contextmanager
def scratch_dir(prefix="scratch"):
    paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
    target = paths.TMP_DIR / f"{prefix}-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    try:
        yield target
    finally:
        shutil.rmtree(target, ignore_errors=True)


@contextmanager
def isolated_runs_dir():
    """把 paths.RUNS_DIR 临时指向 tmp/ 下的目录，结束后恢复。"""
    with scratch_dir("test-runs") as scratch:
        original = paths.RUNS_DIR
        paths.RUNS_DIR = scratch
        try:
            yield scratch
        finally:
            paths.RUNS_DIR = original


def make_config(*, max_steps=8, wall_timeout_s=60.0, step_timeout_s=30.0,
                per_tool_timeout_s=10.0, verify_timeout_s=30.0,
                max_tool_error_streak=3, max_denied_calls=2,
                truncate_threshold_bytes=8192, head_chars=3000, tail_chars=3000,
                executor_kind="local", docker_image=None) -> Config:
    return Config(
        executor_kind=executor_kind,
        budgets=Budgets(
            max_steps=max_steps,
            wall_timeout_s=wall_timeout_s,
            step_timeout_s=step_timeout_s,
            per_tool_timeout_s=per_tool_timeout_s,
            verify_timeout_s=verify_timeout_s,
            max_tool_error_streak=max_tool_error_streak,
            max_denied_calls=max_denied_calls,
        ),
        trace=TraceOptions(
            truncate_threshold_bytes=truncate_threshold_bytes,
            head_chars=head_chars,
            tail_chars=tail_chars,
        ),
        raw={},
        docker_image=docker_image,
    )


def run_scenario(agent, task, *, config=None, variant=None):
    """跑完整主循环，返回 (failure_class, run_dir)。

    后端由 config.executor_kind 决定，与 __main__.cmd_run 走同一个
    make_executor：测试跑的后端与线上跑的后端不是两份实现。
    """
    config = config or make_config()
    run_ctx = RunContext(
        run_id=f"t-{uuid.uuid4().hex[:10]}",
        config=config,
        task=task,
        agent_name=agent.name,
        harness_git_sha=None,
        executor_kind=config.executor_kind,
        repo_variant=variant,
    )
    executor = make_executor(config, run_ctx.run_dir, run_ctx.workspace)
    tool_ctx = ToolContext(
        workspace=run_ctx.workspace,
        executor=executor,
        config=config,
        task=task,
        verification_dir=run_ctx.verification_dir,
    )
    failure_class = run_agent(
        agent=agent, task=task, tools=ToolRegistry(),
        tool_ctx=tool_ctx, run_ctx=run_ctx, executor=executor,
    )
    return failure_class, run_ctx.run_dir
