# 证据：批次 2 / 提交 2 —— 接线（prompt / agent / llm.toml / CLI）

- 日期：2026-09-14
- 前置：提交 1（传输层 + A2），证据在 `docs/evidence/stage2-llm-client/`。
- 范围：`harness/llm/prompt.py`、`harness/llm/agent.py`、`configs/llm.toml`、
  `harness/config.py`（两个带默认值的新字段）、`harness/__main__.py`（`--agent llm`
  与 replay 的 LLM 分支）、`tests/test_llm_agent.py`、`tests/test_llm_tool_schemas.py`。
- 本批**0 冻结改动**：五个冻结文件一个字未动。
- **全程离线、零成本**：本目录没有任何一次真实 LLM 调用。真端点由冒烟探针负责。

## 本目录文件

| 文件 | 是什么 |
|---|---|
| `01-agent-tests.txt` | `tests.test_llm_agent` + `tests.test_llm_tool_schemas` 的完整输出（25 项） |
| `02-full-suite.txt` | `python -m unittest discover` 的全套输出（146 项，skipped=6） |
| `03-offline-run-replay.txt` | 用假客户端产出一个 run，再 `validate-trace` + `replay` |

## 接线被证明到什么程度

用一个**假客户端**替换传输层、跑**真实主循环**（`tests/support.py::run_scenario`，
与线上同一条注入路径 `attach`），因此 `loop.py` 的工具派发、截断、轨迹、
验证、失败分类全都真的执行了。被证明的：

- **动作翻译**：`tool_calls` → `ToolCalls`；纯文本 + `stop=stop` → `Finish`；
  空响应 → `Abort`；`stop=length` → `Abort` 且 `llm_response.stop_reason` 留着真因。
- **工具结果回填**：下一轮请求里带上 `role="tool"` 与正确的 `tool_call_id`
  （`03-offline-run-replay.txt` 里 `messages` 数 2→4→6→8，即历史在增长）。
- **step 对齐**：agent 自计数与主循环 `step` 相等（R-006 的机械钉子）。
- **失败落点**：客户端抛 `ModelFailure("llm_transport_error")` → 标签
  `llm_transport_error`、`run_end.status=error`、轨迹里"有请求、无响应"。
- **schema 漂移**：注册工具与 schema 名字集合必须相等。

`03` 里那次 run 的 `messages` 全文、`tools` 全文、`usage`、`latency_ms` 都在轨迹里，
可直接复核"模型看到了什么"。

## 一个我自己写错、被测试抓住的 bug

`LlmAgent` 第一版把"记住本次发出的 tool_call id"漏掉了——`_to_action` 是模块级
函数，改不到 `self._pending_ids`，于是每个工具结果都回填成合成的 `orphan_<n>` id。
`test_the_next_request_carries_the_tool_result_with_its_call_id` 当场报
`'c1' != 'orphan_3'`。修法是在 `next_action` 里显式记录 id 顺序。
**这条断言不是装饰**：没有它，模型会收到一串对不上号的工具结果，而所有测试照绿。

## 验收命令（离线、零成本）

```bash
# ① 全套（期望 146 项通过、skipped=6）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover

# ② 接线与 schema 漂移（期望 25 项通过）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest \
    tests.test_llm_agent tests.test_llm_tool_schemas -v

# ③ 轨迹合法 + 回放（期望"轨迹合法"，且 replay 打出 LLM→ / LLM← 行）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace --trace <run_dir>
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay --run <run_dir>
```

## 未覆盖 / 明确交给冒烟

- **真实端点**：模型名 `deepseek-chat`、`base_url`、是否需要 `/v1` 前缀、鉴权头格式、
  model 到底回原生 `tool_calls` 还是文本 JSON——**全部未知**，由探针第一次真实触碰时
  回答（审计 §9 第 3/4 项）。
- **重试、流式**：本批都不做。不重试是 R-006 的前提。
- **提示词质量**：系统提示词是否够好是接上大脑之后的**实验**议题（审计"未覆盖"节），
  不是本批的验证目标。
