"""文本报告。

报告**由 trace.jsonl 派生**，不读内存状态——因此报告与原始记录天然一致，
不可能出现"报告说成功、轨迹里有错"。
"""

import json
from pathlib import Path

from ..trace import read_trace


def _fmt_ms(value) -> str:
    return f"{value} ms" if isinstance(value, int) else "-"


def generate(run_dir: Path) -> Path:
    trace_path = run_dir / "trace.jsonl"
    records = read_trace(trace_path)
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    run_end = next((r for r in records if r["type"] == "run_end"), None)
    verifications = [r for r in records if r["type"] == "verification"]
    tool_results = [r for r in records if r["type"] == "tool_result"]

    lines = []
    lines.append(f"# Run {meta.get('run_id', run_dir.name)}")
    lines.append("")
    lines.append("> 本报告由 `trace.jsonl` 派生，未读取任何内存状态。")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 任务 | `{meta.get('task_id', '-')}` |")
    lines.append(f"| agent | `{meta.get('agent', '-')}` |")
    lines.append(f"| 执行器 | `{meta.get('executor', '-')}` |")
    lines.append(f"| 仓库变体 | `{meta.get('repo_variant', '-')}` |")
    lines.append(f"| schema 版本 | {meta.get('schema_version', '-')} |")
    lines.append(f"| 配置哈希 | `{meta.get('config_hash', '-')}` |")
    lines.append(f"| harness git sha | `{meta.get('harness_git_sha', '-')}` |")
    lines.append(f"| Python | {meta.get('python_version', '-')} |")
    if run_end:
        lines.append(f"| 最终状态 | **{run_end['status']}** |")
        lines.append(f"| failure_class | **`{run_end['failure_class']}`** |")
        lines.append(f"| 步数 | {run_end['steps']} |")
        lines.append(f"| 总耗时 | {_fmt_ms(run_end['duration_ms'])} |")
    lines.append("")

    lines.append("## 时间线")
    lines.append("")
    lines.append("| seq | 步 | 事件 | 工具 | 状态 | 退出码 | 耗时 |")
    lines.append("|---|---|---|---|---|---|---|")
    for rec in records:
        et = rec["type"]
        if et == "tool_result":
            lines.append(
                f"| {rec['seq']} | {rec.get('step', '-')} | tool_result | `{rec['tool']}` | "
                f"{rec['status']} | {rec['exit_code']} | {_fmt_ms(rec['duration_ms'])} |"
            )
        elif et == "step_end":
            lines.append(
                f"| {rec['seq']} | {rec.get('step', '-')} | step_end | - | - | - | "
                f"{_fmt_ms(rec['duration_ms'])} |"
            )
        elif et in ("run_start", "run_end", "error", "agent_message"):
            detail = rec.get("message") or rec.get("content") or ""
            detail = str(detail).replace("\n", " ")[:60]
            lines.append(
                f"| {rec['seq']} | {rec.get('step', '-')} | {et} | - | - | - | {detail} |"
            )
    lines.append("")

    if verifications:
        lines.append("## 验证结果")
        lines.append("")
        for rec in verifications:
            lines.append(f"- 命令：`{' '.join(rec['command'])}`（cwd `{rec.get('cwd', '-')}`）")
            lines.append(f"- 退出码：{rec['exit_code']}，判定：**{rec['status']}**，耗时 {_fmt_ms(rec['duration_ms'])}")
            parsed = rec.get("parsed") or {}
            lines.append(
                f"- 解析：用例总数 {parsed.get('tests_total')}，失败 {parsed.get('failures')}，"
                f"错误 {parsed.get('errors')}，通过 {parsed.get('passed')}"
            )
            lines.append(f"- 原始输出：`verification/verify.stdout.txt`、`verification/verify.stderr.txt`")
        lines.append("")

    lines.append("## 输出截断")
    lines.append("")
    truncated = []
    for rec in tool_results + verifications:
        for key in ("stdout_stream", "stderr_stream"):
            stream = rec.get(key)
            if isinstance(stream, dict) and stream.get("truncated"):
                truncated.append((rec["type"], rec.get("tool", rec.get("name", "-")), key, stream))
    if not truncated:
        lines.append("本次运行没有发生截断。")
    else:
        lines.append("| 事件 | 工具 | 流 | 原始字节 | 交付字节 | 省略字节 | blob |")
        lines.append("|---|---|---|---|---|---|---|")
        for et, tool, key, stream in truncated:
            lines.append(
                f"| {et} | `{tool}` | {key} | {stream['bytes_total']} | "
                f"{stream['bytes_delivered']} | {stream['elided_bytes']} | `{stream['blob_ref']}` |"
            )
    lines.append("")

    lines.append("## token 与成本")
    lines.append("")
    totals = (run_end or {}).get("totals") or {}
    if totals.get("input_tokens") is None:
        lines.append("阶段 1 无 LLM，token 与成本字段已在 schema 中占位，取值为 `null`。")
    else:
        lines.append(f"- 输入 token：{totals['input_tokens']}")
        lines.append(f"- 输出 token：{totals['output_tokens']}")
        lines.append(f"- 成本（估算）：{totals['cost_usd']}")
    lines.append(f"- 工具调用次数：{totals.get('tool_calls', '-')}")
    lines.append("")

    lines.append("## 产物")
    lines.append("")
    for name in ("meta.json", "trace.jsonl", "report.md"):
        lines.append(f"- `{name}`")
    lines.append("- `workspace/`（本 run 的目标仓库副本，agent 只改动这里）")
    lines.append("- `verification/`（验证命令的原始输出）")
    lines.append("- `blobs/`（超长输出的完整副本）")
    lines.append("")

    lines.append("## 复现本次运行")
    lines.append("")
    variant = meta.get("repo_variant")
    extra = f" --variant {variant}" if variant and variant != "repo" else ""
    lines.append("```")
    lines.append(
        f"python -m harness run --task {meta.get('task_id', '<task>')} "
        f"--agent {meta.get('agent', '<agent>')}{extra}"
    )
    lines.append("```")
    lines.append("")

    out = run_dir / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
