# 证据：批次 2 / 提交 1 —— LLM 传输层与 A2

- 日期：2026-09-14
- 范围：**只**含传输层。`harness/llm/client.py`（含 A2 三层超时）、
  `requirements.txt`、`credentials.api_key()`、`llm/__init__` 文档串、
  `tests/test_llm_client_timeouts.py`、`trace-schema.md` 记录 6。
- 接线（`prompt.py` / `agent.py` / `configs/llm.toml` / CLI）是**提交 2**，
  本目录不覆盖。
- 本批**0 冻结改动**：`contract.py` / `core/loop.py` / `agent/base.py` /
  `tools/base.py` / `env/base.py` 一个字未动。

## 本目录文件

| 文件 | 是什么 |
|---|---|
| `01-a2-socket-tests.txt` | `tests/test_llm_client_timeouts.py -v` 的完整输出（16 项） |
| `02-installed-packages.txt` | 装完 httpx 后的 `pip list` 实况（版本号的权威来源） |
| `03-a2-mutation-probe.txt` | A2 变异探针：证明第 3 层承重、且关连接能解阻塞 worker |
| `04-credentials-and-init-diff.txt` | `credentials.py` / `__init__.py` 的 diff |
| `05-git-status.txt` | 提交前的 `git status --short` |

## A2 是怎么被证明的

三层，各有一条承重用例，全部走**真实回环 socket**（`httpx.MockTransport` 绕过
httpcore，测不到 socket 层，故刻意不用）：

| 层 | 承重用例 | 判据 |
|---|---|---|
| 1/2 逐阶段超时 + socket | `test_silence_mid_body_trips_the_read_timeout` | detail 含"读取超时"，且 elapsed < 总时限 |
| 3 总时限（滴流） | `test_a_body_dribble_trips_the_total_deadline` | detail 含"总时限"，且 elapsed ≥ read 窗口 |
| 3 总时限（**头之前**滴流，A2 陷阱） | `test_a_header_dribble_that_never_finishes_trips_the_total_deadline` | 同上 |
| 反向对照 | `test_a_well_behaved_server_completes` | 正常服务器必须成功 |

反向对照不是装饰：没有它，"所有请求都超时"也会显得全绿。

`03-a2-mutation-probe.txt` 里的两条**变异证据**（不靠断言自证）：

1. 把总时限放到 30s，header-dribble 在 2.5s 内**不返回** ⇒ 是第 3 层在救，
   不是 `read` 顺手救的（`read` 只有 0.3s，根本没触发）。
2. 总时限触发后，`llm-post` worker 线程**泄漏 0 个**（基线 0 → 1.5s 后 0）
   ⇒ `client.close()` 确实解阻塞了被阻塞在 recv 上的 worker，每次超时不留线程。

## 验收命令（都是离线的，零成本）

```bash
# ① 本批的承重测试（期望 16 项通过）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest \
    tests.test_llm_client_timeouts -v

# ② 全套（提交 2 完成后由你跑；当前 121 项通过、skipped=6）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover

# ③ 冻结清单 diff 为空（本批 0 冻结改动）
git diff --numstat HEAD -- harness/contract.py harness/core/loop.py \
    harness/agent/base.py harness/tools/base.py harness/env/base.py
```

## 未覆盖 / 明确的边界

- **真实端点未触碰**。本批不发任何真实请求，故"端点细节（是否要 `/v1` 前缀、
  鉴权头格式、tool-call 风格）"仍是未知的未知（审计 §9 第 3/4 项），留给冒烟探针。
- **`api_key()` 的返回值没有落盘路径**：它只在 `client.complete()` 里出现一次，
  直接拼进请求头。`tests/test_llm_client_timeouts.py` 用**假哨兵值**断言它出现在
  请求头里——断言的是我们自己的代码，不触碰真实凭据。
- **重试、流式**：本批都不做。不重试是因为重试会让一次 `next_action` 对应多条
  `llm_request`，而 agent 侧的 `step` 是自计数的（见记录 6 / 提交 2）。
