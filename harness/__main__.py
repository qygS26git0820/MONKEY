"""CLI 入口。

    python -m harness run --task toy-001 --agent scripted_ok
    python -m harness replay --run <run_id>
    python -m harness validate-trace --trace <path>
"""

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

from . import paths
from .agent.scripted import AGENT_NAMES, ScriptedAgent
from .config import ConfigError, load_config
from .core.loop import run_agent
from .env.factory import make_executor
from .llm.agent import LLM_AGENT_NAME, LlmAgent
from .llm.client import (DEFAULT_BASE_URL, DEFAULT_MAX_OUTPUT_TOKENS,
                         LlmClient)
from .report import text_report
from .runctx import RunContext
from .tasks.loader import TaskError, load_task
from .tools.context import ToolContext
from .tools.registry import ToolRegistry
from .trace import ContractViolation, read_trace, validate_records

AGENT_CHOICES = list(AGENT_NAMES) + [LLM_AGENT_NAME]


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(paths.PROJECT_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=10, shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _resolve_run_dir(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_dir():
        return paths.ensure_within(candidate)
    return paths.ensure_within(paths.RUNS_DIR / value)


def _build_agent(args, config):
    """假 agent 与真 agent 在这里分岔。两者的差别只是"动作从哪来"。"""
    if args.agent == LLM_AGENT_NAME:
        client = LlmClient(
            model=config.llm_model,
            base_url=config.llm_base_url or DEFAULT_BASE_URL,
            max_output_tokens=config.llm_max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return LlmAgent(client)
    return ScriptedAgent(args.agent)


def cmd_run(args) -> int:
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    try:
        task = load_task(args.task)
    except TaskError as exc:
        print(f"任务错误: {exc}", file=sys.stderr)
        return 2

    if args.agent == LLM_AGENT_NAME and not config.llm_model:
        # 选了真 agent 却没配模型。与"配了模型却没凭据"同一条理由：此刻拒绝
        # 不产生任何产物；等到建完 run 目录、第一次请求才炸，就是用一次失败的
        # 实验换一个本可以启动前报出的错误。
        print(f"配置错误: --agent {LLM_AGENT_NAME} 需要配置 {args.config!r} 里的 "
              f"[llm].model；该配置未提供", file=sys.stderr)
        return 2

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"{stamp}-{task.id}-{args.agent}"

    try:
        run_ctx = RunContext(
            run_id=run_id,
            config=config,
            task=task,
            agent_name=args.agent,
            harness_git_sha=_git_sha(),
            executor_kind=config.executor_kind,
            repo_variant=args.variant,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"无法创建运行目录: {exc}", file=sys.stderr)
        return 2

    executor = make_executor(config, run_ctx.run_dir, run_ctx.workspace)
    tools = ToolRegistry()
    tool_ctx = ToolContext(
        workspace=run_ctx.workspace,
        executor=executor,
        config=config,
        task=task,
        verification_dir=run_ctx.verification_dir,
    )
    agent = _build_agent(args, config)
    if isinstance(agent, LlmAgent):
        # 轨迹写入端与累计账本由 RunContext 内部创建，agent 拿不到，必须由
        # 外部注入——与 tests/support.py::run_scenario(attach=...) 同一条路径。
        agent.attach(run_ctx)

    try:
        failure_class = run_agent(
            agent=agent, task=task, tools=tools, tool_ctx=tool_ctx,
            run_ctx=run_ctx, executor=executor,
        )
    except Exception as exc:
        run_ctx.close()
        print(f"harness 异常: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    report_path = text_report.generate(run_ctx.run_dir)
    print(f"run_dir      : {run_ctx.run_dir}")
    print(f"failure_class: {failure_class}")
    print(f"report       : {report_path}")
    return 0 if failure_class in ("none",) else 1


def cmd_replay(args) -> int:
    run_dir = _resolve_run_dir(args.run)
    records = read_trace(run_dir / "trace.jsonl")
    for rec in records:
        et = rec["type"]
        prefix = f"[{rec['seq']:>3}] {rec.get('ts_mono', 0):>8.3f}s"
        step = f" step={rec['step']}" if "step" in rec else ""
        if et == "tool_call":
            print(f"{prefix}{step} CALL  {rec['tool']} {rec['args']} (cwd={rec['cwd']})")
        elif et == "tool_result":
            print(f"{prefix}{step} RESULT {rec['tool']} status={rec['status']} "
                  f"exit={rec['exit_code']} {rec['duration_ms']}ms")
            if rec["stdout"].strip():
                print(_indent(rec["stdout"][:600]))
            if rec["stderr"].strip():
                print(_indent(rec["stderr"][:600]))
            for key in ("stdout_stream", "stderr_stream"):
                stream = rec[key]
                if stream["truncated"]:
                    print(f"           [{key} 截断] 原始 {stream['bytes_total']} B → "
                          f"交付 {stream['bytes_delivered']} B，完整内容 {stream['blob_ref']}")
        elif et == "llm_request":
            usage_note = f"params={rec['params']}" if rec.get("params") else ""
            print(f"{prefix}{step} LLM→  {rec['model']} "
                  f"messages={len(rec.get('messages') or [])} "
                  f"tools={len(rec.get('tools') or [])} {usage_note}")
        elif et == "llm_response":
            usage = rec.get("usage") or {}
            print(f"{prefix}{step} LLM←  {rec['model']} stop={rec['stop_reason']} "
                  f"{rec['latency_ms']}ms in={usage.get('input_tokens')} "
                  f"out={usage.get('output_tokens')}")
            if rec.get("content"):
                print(_indent(rec["content"][:600]))
            for call in rec.get("tool_calls") or []:
                print(f"{prefix}{step}        ↳ {call['name']} {call['arguments']}")
        elif et == "verification":
            print(f"{prefix} VERIFY status={rec['status']} exit={rec['exit_code']} "
                  f"parsed={rec['parsed']}")
        elif et == "agent_message":
            print(f"{prefix}{step} AGENT {rec['content'][:200]}")
        elif et == "error":
            print(f"{prefix} ERROR {rec['where']}: {rec['exception_type']}: {rec['message']}")
        elif et == "run_end":
            print(f"{prefix} END   status={rec['status']} failure_class={rec['failure_class']} "
                  f"steps={rec['steps']} totals={rec['totals']}")
        else:
            print(f"{prefix}{step} {et}")
    return 0


def _indent(text: str) -> str:
    return "\n".join("           | " + line for line in text.rstrip().splitlines())


def cmd_validate_trace(args) -> int:
    path = Path(args.trace)
    if not path.is_absolute():
        path = paths.ensure_within(paths.PROJECT_ROOT / path)
    if path.is_dir():
        path = path / "trace.jsonl"
    if not path.is_file():
        print(f"找不到轨迹文件: {path}", file=sys.stderr)
        return 2
    try:
        records = read_trace(path)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"无法读取轨迹 {path}: {exc}", file=sys.stderr)
        return 2
    problems = validate_records(records)
    if problems:
        print(f"轨迹不合法，共 {len(problems)} 个问题:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"轨迹合法: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="SWE Agent 行为观察 Harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="跑一个任务")
    p_run.add_argument("--task", required=True)
    p_run.add_argument("--agent", required=True, choices=AGENT_CHOICES)
    p_run.add_argument("--config", default="default")
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--variant", default=None,
                       help="覆盖使用的仓库副本目录名（负向对照用，例如 repo_faulty）")
    p_run.set_defaults(func=cmd_run)

    p_replay = sub.add_parser("replay", help="把轨迹回放到终端")
    p_replay.add_argument("--run", required=True, help="run_id 或运行目录路径")
    p_replay.set_defaults(func=cmd_replay)

    p_val = sub.add_parser("validate-trace", help="校验轨迹是否符合契约")
    p_val.add_argument("--trace", required=True)
    p_val.set_defaults(func=cmd_validate_trace)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ContractViolation as exc:
        print(f"契约违反: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
