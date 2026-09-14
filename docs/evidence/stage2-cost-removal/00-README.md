# 第三次冻结基线移动：删除成本面 + 标签改名（2026-09-14）

## 你裁定的三条

1. **选 B**：第三次移动冻结基线，把成本面删干净（而不是留一套休眠骨架）。
2. **保留 `max_total_tokens` 与 `max_steps`**；砍掉 `max_cost_cny`、峰谷判定、
   缓存命中率（后两者从未实现，无代码可删）。
3. **`cost_budget_exceeded` 改名 `token_budget_exceeded`**，与 B 合并成同一次移动。

外加一处你单独裁决的语义：`run_end.totals` **保留** `input_tokens`/`output_tokens`，
只删 `cost` 与 `pricing_currency`。

## 改了什么

| 文件 | 改动 | 冻结？ |
| --- | --- | --- |
| `harness/contract.py` | 标签改名（`FAILURE_CLASSES` + `FAILURE_DECISION_ORDER` 各一处） | **是** |
| `harness/core/loop.py` | 两处 producer 改名；`totals` 删 `cost`/`pricing_currency`；旁注 | **是** |
| `harness/core/usage.py` | 删 `cost`（属性/参数/分支）；保留 input/output | 否 |
| `harness/config.py` | 删 `max_cost_cny` 字段、成本上限不变量整块、`price_for` import | 否 |
| `harness/runctx.py` | 删 `pricing_currency` 及其对 `pricing.CURRENCY` 的引用 | 否 |
| `harness/llm/__init__.py` | 文档串（不再有 `pricing.py`） | 否 |
| `harness/report/text_report.py` | 删成本行；章节名 `token 与成本` → `token` | 否 |
| `harness/llm/pricing.py` | **整文件删除** | 否 |
| `tests/fixtures/contract_snapshot.json` | 同步改名 | 否 |
| `tests/support.py` | `make_config` 去掉 `max_cost_cny` | 否 |
| `tests/test_usage_ledger.py` | 删 7 条 cost 用例 | 否 |
| `tests/test_cost_budget.py` → `tests/test_token_budget.py` | 删 `ConfigCostCapTest`；`BudgetStopTest` 转 token | 否 |
| `tests/test_llm_failure_labels.py` | 标签名引用 | 否 |
| `docs/trace-schema.md` | §1.2 #4、§1.3 #12、§1.4 标签名；新增记录 5 | — |

## 机械差别（必须记在最前面）

前两次基线移动的判据是"`contract.py` 形如 `N 0`（**0 删除行**）"。本次
`contract.py` **第一次出现删除行**（`2 2`）——旧标签名被删。这是"只增不改"在
标签名这一处的**有意让路**，理由见 `trace-schema.md` 记录 5 §5.1。该判据在本次作废。

可行性依据：**没有任何已归档轨迹带 `cost_budget_exceeded`**（唯一产生点是测试；
`tests/fixtures/phase1-sample-trace.jsonl` 的 `run_end` 是 `none`），故改名不使任何
历史产物失效。

## 刻意没做什么

| 没碰的东西 | 理由 |
| --- | --- |
| `test/fixtures/phase1-sample-trace.jsonl` | 阶段 1 的冻结样本，逐字节不动（记录 3 已声明） |
| `docs/stage1-design.md` / `stage1-retrospective.md` | 历史文档，改写等于伪造历史 |
| `docs/evidence/stage2-cost-budget/`、`stage2-baseline-move/` | 历史证据，同上 |
| 记录 1/2/3/4 | 追加式台账，不重写；反转由记录 5 承载 |
| LLM 客户端 / httpx | 不属本次范围，留到客户端批次 |

以上记入 `docs/known-residues.md`。

## 独立验证

| 证据 | 命令 | 结论 |
| --- | --- | --- |
| `01-full-suite.txt` | `.venv/Scripts/python.exe -m unittest discover -t . -v` | 105 项通过（本次前 112 项；−7 = 删掉的成本测试） |
| `02-removed-names-grep.txt` | `grep -rn --include=*.py "<已删名字>" harness/` | 无输出，无悬挂引用 |
| `03-freeze-diff.txt` | `git diff --numstat dee4e57 -- <五个冻结文件>` | `contract.py 2 2`、`loop.py 5 7`；后三个文件不出现；含完整 diff |
| `04-token-budget-stop.txt` | `.venv/Scripts/python.exe tmp/probe-token-stop.py` | 越限 → `token_budget_exceeded`/`aborted`；用满不触发；只报一半不触发 |

−7 的去向：`ConfigCostCapTest`（5 条）+ `BudgetStopTest` 的文件合并（6 → 5 条）+
`test_usage_ledger.py` 的 cost 用例（7 → 6 条）。等号边界覆盖未丢：
`test_token_budget.py::test_spending_exactly_at_the_cap_does_not_trip` 与
`test_usage_ledger.py::test_token_exactly_at_cap_does_not_exceed`。

**一条命令的更正**：`python -m unittest discover -s tests`（缺 `-t .`）会把 `tests/`
当顶层目录导入，破坏这些测试的相对 `import`。正确形式是 `discover` 或
`discover -s tests -t .`，须在仓库根运行。
