# 已知残差台账

**用途**：记录"发现了但不处理"的事项，避免它们要么被静默忽略、要么被顺手改掉。
本文件不承诺修复，只承诺**不遗忘**。每条给出：是什么、为什么不处理、影响面。

**维护约定**：只增不改不删。处理掉了就在原条目标注 `【已处理：<提交/日期>】`，
不抹掉原记录——否则台账本身会腐烂。

---

## R-001 `run_end.totals` 里 token 未知量无法触发终止

- **是什么**：`UsageLedger` 的 input/output 只要有一笔记录缺失，该量就变为"未知"
  （`None`，且是粘的）。`exceeded()` 对未知量直接短路为假，故**未知量上的越限会漏判**。
- **为什么不处理**：这是刻意的设计取舍——"无法证明它超了，就不凭它终止"。凭一个
  未知量终止会制造假阳性，比漏判更坏。改掉它需要区分"未知"与"已知偏小"两类 None，
  属于重新设计账本，超出当前范围。
- **影响**：只报部分用量的 agent，可能绕过 `max_total_tokens`。当前唯一写入方是
  测试假 agent 与后续 LLM 客户端；真客户端把 prompt+completion 的 usage 一并上报时
  不会触发此残差。
- **出处**：`harness/core/usage.py::exceeded`。

## R-002 历史文档与证据仍命名已删除的成本面

- **是什么**：以下文件仍写着成本上限 / `cost_usd` / `cost_budget_exceeded` /
  `cost_usd_estimate` 等，与记录 5 之后的现实不一致：
  - `docs/stage1-design.md`（`cost_budget_exceeded`、`cost_usd_estimate` 等）
  - `docs/stage1-retrospective.md`（`cost_budget_exceeded`）
  - `docs/evidence/stage2-cost-budget/`（整目录，描述的是已删的成本不变量与证据）
  - `docs/evidence/stage2-baseline-move/`（其 diff 节选含 `cost_budget_exceeded`）
  - `docs/pre-llm-audit.md`（已提交于 `a35948e`；§1.1、§8.6 等整段在谈成本）
- **为什么不处理**：这些是**历史产物**。它们在其所记录的时间点是准确的；改写它们
  等于伪造历史，正是记录 5 "不重写记录 1/2/3/4" 的同一条理由。权威现状以
  `docs/trace-schema.md`（记录 5）为准。
- **影响**：读者若只看旧文档会以为 MONKEY 仍算成本。缓解：`trace-schema.md` 记录 5
  是唯一入口，旧文档不声明自己是现状。
- **可能的处理**（未采纳）：在旧文档顶部加一行"本文所述成本面已于 2026-09-14 移除，
  见 trace-schema 记录 5"的横幅。留待需要时再做。

## R-003 `phase1-sample-trace.jsonl` 的 totals 键名与现行 schema 不同

- **是什么**：`tests/fixtures/phase1-sample-trace.jsonl` 的 `run_end.totals` 含
  `cost_usd` 键（值 `null`），而现行 schema 已无此键（记录 3 改名为 `cost`，
  记录 5 直接删除）。
- **为什么不处理**：它是阶段 1 的**冻结样本**，逐字节不动是刻意的（记录 3 明文声明）。
  `validate_records` 不校验 `totals` 子键，故旧键不影响合法性。
- **影响**：任何按 totals 子键做聚合的分析代码，需对 `cost_usd`/`cost`/无 `cost`
  三代形状都容错。当前无此类代码。

## R-004 审计 §8.6 针对的旧测试文件已删除

- **是什么**：`docs/pre-llm-audit.md:409` §8.6 讨论 `tests/test_cost_budget.py` 的
  "恰好等于上限"用例。该文件已在记录 5 里删除、内容迁到 `tests/test_token_budget.py`。
- **为什么不处理**：同上，审计是历史产物。所涉的边界覆盖**未被丢弃**：等号边界现在由
  `tests/test_token_budget.py::test_spending_exactly_at_the_cap_does_not_trip` 与
  `tests/test_usage_ledger.py::test_token_exactly_at_cap_does_not_exceed` 覆盖。
- **影响**：无；仅作指针，防止有人照着 §8.6 去找一个不存在的文件。

## R-005 部分标签在 §1.3 表里仍标着"【建议新增】"

- **是什么**：`#11 aborted_by_user`、`#12 token_budget_exceeded` 等标签的"触发条件"
  列仍带"**【建议新增】**"前缀，但它们早已被采纳并冻结。
- **为什么不处理**：该前缀是引入时的历史标记，改动它属于冻结文档正文的无意义噪音，
  且会稀释 diff 的可读性。
- **影响**：纯观感，无语义影响。
