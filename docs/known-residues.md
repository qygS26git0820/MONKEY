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

## R-006 `step` 是 agent 自计数的，靠"不重试"维持与主循环对齐

- **是什么**：`contract.py` 要求 `llm_request`/`llm_response` 带 `step`，但
  `ConversationState` 里没有 step，`loop.py` 也不发这两个事件（冻结）。`LlmAgent`
  因此自数调用次数。对齐成立的前提是**一次 `next_action` 恰好发一次请求**。
- **为什么不处理**：正确的修法是让 `loop.py` 发这两个事件（把 step 交给它），那要
  移冻结基线；而当前"不重试"的取舍使自计数恰好等价，代价是这条隐含契约不写在任何
  接口里（审计 §7.1）。
- **影响**：一旦将来引入重试（一个 step 内多次请求），自计数会与主循环 `step` 错位，
  且 `validate_records` 不检查 step 合理性、发现不了。**缓解**：`tests/test_llm_agent.py::
  test_the_self_counted_step_matches_the_loop_step` 钉住等号关系，加重试时该测试先红。
- **出处**：`harness/llm/agent.py`、`tests/test_llm_agent.py`。

## R-007 工具 schema 与系统提示词的措辞是未版本化的实验条件

- **是什么**：模型看到什么（工具描述、系统提示词的用词）本身就是观测的一部分，
  但这些文本只随代码走，`config_hash` 覆盖不到——换一版措辞不会改变配置归属。
- **为什么不处理**：审计 §7.3 建议的"把观测侧描述显式版本化"尚未做。当前只有一个
  版本，还没有需要区分的情形。
- **影响**：跨版本对比轨迹时，无法从 `config_hash` 看出"提示词改过"。缓解：这些文本
  在 `harness/llm/prompt.py` 里，`git log` 可查；`trace.jsonl` 的每条 `llm_request`
  都带当时的 `messages`/`tools` 全文，故**逐条可复核**。

## R-008 成功收尾的那一步被预算检查丢弃时，轨迹缺少分类事件

- **是什么**：`loop.py:88` 的用量检查排在动作分类（`loop.py:92`）之前，中间只隔了
  `step += 1` 与 `agent.next_action()`。若第 N 步取回的动作是 `Finish`，而该次响应
  使累计用量越过 `max_total_tokens`，循环会在**识别出这是 `Finish` 之前** `break`。
  后果三条同时出现：该 run 的 `agent_message` 计数为 0（正常应有 1）、该步没有
  `step_end`（`steps=13` 而 `step_end=12`）、`run_end.status = aborted`，而
  `verification_status` 可以同时是 `passed`。该步的文本**没有丢**——它逐字存在于
  `llm_response` 事件的 `content` 字段（`llm_response` 不走 `prepare_stream`，只有工具
  输出才截断）；丢的是"这段文本是一次 Finish"这个**分类事件**。
- **为什么不处理**：修它必须改 `loop.py` 的检查顺序（冻结文件），代价是第 4 次基线
  移动。裁定（2026-09-17）："那是第 4 次基线移动，不值得"，上限职责交给
  `max_steps=20`。检查排在动作分类之前本身是有理由的（`loop.py:86` 的注释：不等到下
  一轮开头，否则被观测到的越限会多出整整一步），代价是这条副作用。
- **影响**：任何按 `agent_message` 或 `run_end.status` 判断"agent 是否给出了收尾陈述"
  的下游分析，在这个情形下会漏读或误读。`chaos-001` 的第 1 次实跑就落在这一格。
- **出处**：`harness/core/loop.py:73/88/92/149`；`docs/chaos-retrospective.md` §1.3 偏离 2；
  证据 `docs/evidence/chaos-001/01-run1-token-budget-exceeded.trace.jsonl`（`seq 81`）。

## R-009 `chaos-001` 的判据对 `workload` 只做子串匹配

- **是什么**：`tasks/chaos-001/task.json` 的判据原为
  `'nginx' not in str(d['workload']).lower()`——只要 `workload` 里含 `nginx` 即通过。
  于是把根因归到**别的**恰好名字含 nginx 的对象也能过：`nginx-svc`（Service）、
  `nginx-6559559688-ggv7d`（Pod 名）、`endpoints/nginx`。判据**通过 ≠ 诊断正确**。
- **为什么不处理**（原文）→ **【已处理：2026-09-17，随本条登记同批提交】**：裁定为
  "登记，并同时修判据"。修改后的规则：先把 `workload` 做 alnum 归一，剥掉前缀与后缀
  的 `default`/`deployment`/`deploy` 令牌，余下必须**恰好等于** `nginx`。这接受
  `nginx`、`deployment/nginx`、`default/nginx`、`Deployment nginx`、`nginx Deployment`
  等自然写法，拒绝指向 Service / Pod / Endpoints 的答案。真值表从 10 例扩到 17 例
  （新增 `11-指向Service`、`12-指向Pod名`、`13-指向Endpoints` 三条反例与 4 条正例），
  全部符合预期；两次已归档的实跑诊断（均为 `workload: "nginx"`）**仍 `exit 0`**，
  故本次收紧不使任何历史证据失效。
- **影响**：`chaos-001` 的判据现在能区分"指向工作负载"与"指向别的含 nginx 的对象"。
  仍未覆盖的：若有人把 `workload` 写成一段散文（例如 `"nginx 三副本"`），会被判失败
  而不是被解析；判据要的是标识符不是句子。`task.json` 的 `description` **未改**
  （改它等于改实验条件），因此收紧后的规则必须只依赖 `description` 已有的措辞
  （"直接受影响的工作负载"）就能满足——已按实测的自然写法逐条核对。
- **出处**：`tasks/chaos-001/task.json` 的 `verify.command`；正反控制探针
  `tmp/probe-verify-predicate.py`（不入库）；`docs/chaos-retrospective.md` §3.3。

