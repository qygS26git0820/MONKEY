# 证据：阶段 2 —— 装大脑 + 首次真实冒烟

- 日期：2026-09-15
- 前置：提交 1（传输层，`6c8d01a`）、提交 2（接线，`801b86a`）。
- 本目录是**第一次真实 LLM 流量**的留档。之前的证据全是离线的：假客户端
  替身、真实回环 socket、`httpx.MockTransport` 的教训。这里第一次不是替身。

`runs/` 被 `.gitignore` 覆盖（第 4 行），所以把冒烟产物复制进来：

| 文件 | 是什么 |
|---|---|
| `01-smoke-trace.jsonl` | 本次 run 的完整轨迹（23 条记录，逐字节复制） |
| `02-smoke-report.md` | 由轨迹派生的文本报告（逐字节复制） |

原 run 目录：`runs/20260915-052422-toy-001-llm/`（含 `workspace/`、`verification/`、
`blobs/`、`meta.json`，未入库）。harness git sha `801b86a`，Python 3.12.13。

## 一、先导：单调用探针（2026-09-14）

真实冒烟前先发**恰好一次**请求（`tmp/probe-one-call.py`，临时文件不入库），
回答接线批次刻意留白的几件事。实测：

| 问题 | 答案 |
|---|---|
| `base_url` 要不要 `/v1` 前缀 | **不要**，`https://api.deepseek.com` 直接用 |
| 鉴权头格式 | `Authorization: Bearer <key>`，接受 |
| 模型回原生 `tool_calls` 还是正文 JSON | **原生 `tool_calls`**，`stop_reason="tool_calls"` |
| 模型名 | 请求 `deepseek-chat`（别名）时端点**回显** `deepseek-flash` |

最后一条促成了 `configs/llm.toml` 的改名：名字以**回显**为准，否则轨迹里的
`llm_request.model` 会和实际跑的模型对不上——观测目标里"模型看到了什么"就掺了假。

## 二、全量任务的结果

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness run \
    --task toy-001 --agent llm --config llm
```

| 项 | 值 |
|---|---|
| failure_class | **`none`**（`run_end.status = completed`，进程退出码 0） |
| 步数 | 4 |
| `llm_request` / `llm_response` | **4 / 4**（一一对应，无"有请求、无响应"） |
| 工具调用 | 4 次 |
| tokens | in 4214 / out 208 |
| model 请求 vs 回显 | 两边都是 `deepseek-flash` |
| 验证 | `passed`，3/3 通过，errors=0 failures=0 |
| 总耗时 | 4137 ms |

模型实际动作序列（**这是观测目标本身**，不只是"跑通了"）：

```
step=1  read_file calc.py              ← 同一轮里并发两个读
step=1  read_file tests/test_calc.py
step=2  write_file calc.py             a - b  →  a + b
step=3  run_verify                     → passed 3/3
step=4  纯文本收尾 → Finish
```

`messages` 数 `2→5→7→9`：第一轮一次发**两个** tool_call，之后每轮 +2。历史在长、
`role="tool"` 回填正确、`stop_reason` 为 `tool_calls ×3 + stop ×1`——接线批次用
假客户端写的每条断言，在真实流量上逐条复现了。

花费：in 4214 / out 208 ≈ **0.006 元**（探针 0.0012 元作锚点外推，跑前预测
~0.006 元，命中）。上限由 `max_steps=20` 兜住，本次只用了 4 次。

## 三、这份证据证明什么、不证明什么

**证明**：

- 端到端真的能跑：真端点 → 真模型 → 原生工具调用 → 工具派发 → 验证通过 → 轨迹合法。
- 修复是**真**的、由外部证据背书：`workspace/calc.py` 最终为 `return a + b`，
  且任务自带的验证命令（**绕过 harness** 直接跑）报 `OK`。不是 `agent_message`
  自己说"修好了"（那是被冻结契约明确拒绝的伪证据）。
- 观测面完整：每条 `llm_request` 都带着当时的完整 `messages` 与 `tools`，
  所以"模型看到了什么"可从轨迹离线复核，不必重跑。

**不证明**：

- **n = 1**。一次成功不是"agent 能力"，只是"这条路能走通"。真正的能力问题
  需要多任务、多变体、多次重复，那是后续实验的事。
- 提示词质量、工具 schema 措辞是否够好，仍未评估（R-007）。
- 挂住/超时路径在真实端点上也**没被触发**——它由离线回环 socket 证明
  （`docs/evidence/stage2-llm-client/`）。真实网关是否与回环行为一致，未知。

## 四、独立复核命令（离线、零成本）

```bash
# ① 轨迹合法（本目录里是 01-smoke-trace.jsonl，不是默认名 trace.jsonl，
#    所以要指到文件本身，不能指目录）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/stage2-llm-smoke/01-smoke-trace.jsonl

# ② 回放到终端（期望 LLM→ / LLM← 各 4 行，END failure_class=none steps=4）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay \
    --run runs/20260915-052422-toy-001-llm

# ③ 不信 agent 自述，独立重跑任务自带的验证命令（期望 Ran 3 tests / OK）
cd "runs/20260915-052422-toy-001-llm/workspace" && \
  PYTHONIOENCODING=utf-8 "../../../.venv/Scripts/python.exe" \
  -m unittest discover -s tests -t . -v
```

第 ③ 条是关键：它绕过 harness 直接对 agent 留下的工作区跑验证，所以"修好了"
由外部证据背书。

## 五、未覆盖 / 交给后续

- 真实端点上的**慢调用与挂住**：未触发。客户端三层超时的真实行为待观察。
- 真端点上的 **401 / 402 / 429 / 5xx**：未触发。标签映射只在离线 socket 上验过。
- **重试与流式**：本批都不做。不重试是 R-006 的前提。
- **多步长任务的成本**：本批 `max_total_tokens` 留空，单任务小到不必设限。
