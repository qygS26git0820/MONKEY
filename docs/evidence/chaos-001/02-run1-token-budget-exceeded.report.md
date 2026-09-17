# Run 20260917-123127-chaos-001-llm

> 本报告由 `trace.jsonl` 派生，未读取任何内存状态。

## 摘要

| 项 | 值 |
|---|---|
| 任务 | `chaos-001` |
| agent | `llm` |
| 执行器 | `docker` |
| 仓库变体 | `repo` |
| schema 版本 | 1 |
| 配置哈希 | `13f4d51fac24d4fdf2ef5551a9fdd5d600c792bbe9cdf104c44291e7dcb9f6fd` |
| harness git sha | `636e56c4b82b317a9fb8c096849e31c80fd772b0` |
| Python | 3.12.13 |
| 最终状态 | **aborted** |
| failure_class | **`token_budget_exceeded`** |
| 步数 | 13 |
| 总耗时 | 27743 ms |

## 时间线

| seq | 步 | 事件 | 工具 | 状态 | 退出码 | 耗时 |
|---|---|---|---|---|---|---|
| 1 | - | run_start | - | - | - |  |
| 5 | 1 | tool_result | `run_command` | ok | 0 | 299 ms |
| 7 | 1 | tool_result | `run_command` | ok | 0 | 261 ms |
| 8 | 1 | step_end | - | - | - | 1734 ms |
| 12 | 2 | tool_result | `read_file` | ok | 0 | 2 ms |
| 14 | 2 | tool_result | `read_file` | ok | 0 | 13 ms |
| 16 | 2 | tool_result | `read_file` | ok | 0 | 5 ms |
| 17 | 2 | step_end | - | - | - | 1058 ms |
| 21 | 3 | tool_result | `read_file` | ok | 0 | 17 ms |
| 23 | 3 | tool_result | `read_file` | ok | 0 | 2 ms |
| 25 | 3 | tool_result | `read_file` | ok | 0 | 12 ms |
| 26 | 3 | step_end | - | - | - | 1783 ms |
| 30 | 4 | tool_result | `run_command` | ok | 0 | 335 ms |
| 32 | 4 | tool_result | `run_command` | ok | 0 | 293 ms |
| 33 | 4 | step_end | - | - | - | 2992 ms |
| 37 | 5 | tool_result | `run_command` | ok | 0 | 299 ms |
| 38 | 5 | step_end | - | - | - | 1263 ms |
| 42 | 6 | tool_result | `run_command` | ok | 0 | 289 ms |
| 43 | 6 | step_end | - | - | - | 1927 ms |
| 47 | 7 | tool_result | `run_command` | ok | 0 | 322 ms |
| 49 | 7 | tool_result | `run_command` | ok | 0 | 300 ms |
| 50 | 7 | step_end | - | - | - | 1888 ms |
| 54 | 8 | tool_result | `run_command` | ok | 0 | 386 ms |
| 55 | 8 | step_end | - | - | - | 1590 ms |
| 59 | 9 | tool_result | `run_command` | ok | 0 | 389 ms |
| 61 | 9 | tool_result | `run_command` | ok | 0 | 320 ms |
| 62 | 9 | step_end | - | - | - | 2701 ms |
| 66 | 10 | tool_result | `read_file` | ok | 0 | 2 ms |
| 68 | 10 | tool_result | `read_file` | ok | 0 | 12 ms |
| 69 | 10 | step_end | - | - | - | 1858 ms |
| 73 | 11 | tool_result | `write_file` | ok | 0 | 1 ms |
| 74 | 11 | step_end | - | - | - | 5719 ms |
| 78 | 12 | tool_result | `run_verify` | ok | 0 | 401 ms |
| 79 | 12 | step_end | - | - | - | 1367 ms |
| 83 | - | run_end | - | - | - |  |

## 验证结果

- 命令：`python -c import json,sys
try:
    d=json.load(open('diagnosis.json',encoding='utf-8'))
except Exception as exc:
    print('diagnosis.json 不可读或不是合法 JSON:',exc);sys.exit(1)
if not isinstance(d,dict):
    print('diagnosis.json 顶层必须是 JSON 对象');sys.exit(1)
def norm(v):
    return ''.join(c for c in str(v).lower() if c.isalnum())
missing=[k for k in ('root_cause_kind','namespace','workload') if not str(d.get(k,'')).strip()]
if missing:
    print('缺字段或字段为空:',missing);sys.exit(1)
if norm(d['root_cause_kind'])!='networkchaos':
    print('root_cause_kind 与现场不符');sys.exit(1)
if norm(d['namespace'])!='default':
    print('namespace 与现场不符');sys.exit(1)
if 'nginx' not in str(d['workload']).lower():
    print('workload 未指向受影响的工作负载');sys.exit(1)
print('命中: 根因类型 / 命名空间 / 受影响工作负载 三者均与现场一致')
`（cwd `/workspace`）
- 退出码：0，判定：**passed**，耗时 366 ms
- 解析：用例总数 None，失败 None，错误 None，通过 None
- 原始输出：`verification/verify.stdout.txt`、`verification/verify.stderr.txt`

## 输出截断

| 事件 | 工具 | 流 | 原始字节 | 交付字节 | 省略字节 | blob |
|---|---|---|---|---|---|---|
| tool_result | `read_file` | stdout_stream | 57651 | 6031 | 51651 | `163520b9fb009611c2c6b0810c38b91a446abf80f20b34ff29b2252dd780c21d.blob` |

## token

- 输入 token：149978
- 输出 token：3395
- 工具调用次数：21

## 产物

- `meta.json`
- `trace.jsonl`
- `report.md`
- `workspace/`（本 run 的目标仓库副本，agent 只改动这里）
- `verification/`（验证命令的原始输出）
- `blobs/`（超长输出的完整副本）

## 复现本次运行

```
python -m harness run --task chaos-001 --agent llm
```

