# 成本/用量预算的落地（B 步，2026-09-13）

## B 做了什么

四件事，都在非冻结文件里：

1. **写入侧** `harness/core/usage.py` 的 `UsageLedger.record()`——agent 侧每次模型
   响应后记一笔。keyword-only：input/output 写反不会有任何报错，只会静静算错成本。
2. **判定** 同文件 `exceeded(budgets)`——累计用量是否越过上限。严格大于；未知不触发。
3. **预算配置项** `harness/config.py` 的 `Budgets.max_cost_usd` / `max_total_tokens`
   （可选，默认 `None`）与 `Config.llm_model`（读 `[llm].model`）。
4. **缺单价拒绝启动** 同文件——配了 `max_cost_usd` 却没有模型名、或模型查不到单价，
   抛 `ConfigError` 拒绝启动，**不创建 run 目录**。这是"上限必须可执行"的落点。

## B 刻意没有做什么

| 没碰的东西 | 理由 |
| --- | --- |
| `harness/core/loop.py` | 检查点已在基线移动（`b6f983f`）时定稿。再碰就是第二次移动基线 |
| `configs/default.toml` / `configs/docker.toml` | 加新字段会改 `config_hash`，阶段 1 那批轨迹的配置归属就断了 |
| `harness/contract.py` | 无新增事件类型、无新增必需字段，契约常量不动 |
| `harness/llm/pricing.py` 的 `PRICES` | **故意留空**：端点与模型名未定，价格必须由你提供，我不臆造 |

`PRICES` 为空不是缺口，是结构保证：`load_config` 在"有上限、无价格"时拒绝启动，
所以空表不可能悄悄放行一个不受约束的 run。

## 独立验证

| 证据 | 命令 | 结论 |
| --- | --- | --- |
| `01-full-suite.txt` | `python -m unittest discover -s tests -t .` | 93 项通过（B 之前 67 项） |
| `02-traces-unchanged.txt` | `tmp/cmp-traces.py mv-local b2-local [harness_git_sha]` | 8 组对照 104 条事件，逐字段零差异 |
| `03-freeze-diff.txt` | `git diff b6f983f --stat` 与冻结文件 `git diff` | 5 个冻结文件 diff 为空；`default.toml` 哈希不变 |
| `04-cost-cap.txt` | `tmp/probe-cost-cap.py` + `tmp/probe-budget-stop.py` | 拒绝启动时不建目录；运行中越限以 `cost_budget_exceeded` 终止，验证照跑 |

新增 26 项测试：`tests/test_usage_ledger.py`（14，账本与判定的纯单元）、
`tests/test_cost_budget.py`（11，配置期拒绝 5 + 运行期终止 6）、
`tests/test_backcompat.py` 的 `Phase1ConfigHashTest`（1，钉住阶段 1 配置哈希）。

`02` 的两遍比较沿用 `tests/test_determinism.py` 的归一化口径。第一遍**如实列出**
唯一差异 `run_start.harness_git_sha`（`4e824e0` → `b6f983f`，两批抓取时 HEAD 不同），
第二遍才抹掉它。理由见 `docs/evidence/stage2-docker/00-README.md` 第 1 条：
该字段记的是 HEAD 而非工作树内容，所以它随提交顺序变，与 B 的行为无关。

行尾**不统一**（`01`–`04` 是 mixed，因为中间经过 Python 的 stdout 管道，与
`stage2-docker/05` 同因）。`.gitattributes` 的 `-text` 保证捕获到什么字节就存什么
字节，不替它们做行尾转换。此处照实说明，避免重复"未经核对的结论"那一类错误。

## 已知残差（登记，不修）

1. **未知不能触发终止。** 累计量是 `None`（没有记录，或某笔记录缺失污染）时
   `exceeded()` 短路为假。代价：这个量上的超支会漏判。取舍是"无法证明它超了就不
   凭它终止"，而不是拿一个偏小的部分和去判断。产生源头在客户端是否回报 `usage`，
   归 item 3。
2. **循环顶部的成本检查目前不可达。** 主循环在"动作返回后"也查一次，而只有 agent
   会写账本，所以任何一次越限都会在那里先被拦下；下一轮开头的检查因而永不单独触发。
   它保留的意义是声明判定顺序（`trace-schema.md` §1.2 把 `cost_budget_exceeded`
   排第 4、`timeout_wall` 排第 5），若将来有工具侧写账本，它就会生效。
3. **`cost_budget_exceeded` 的 `run_end.status` 是 `aborted`。** 它不在 `loop.py`
   的 `_STATUS_BY_CLASS` 里，落到默认值。区分靠 `failure_class`。改它要动冻结文件，
   不值得为它再移一次基线。
4. **`text_report.py` 的 null 分支措辞会过时。** 现在 `input_tokens is None` 时打印
   "阶段 1 无 LLM……取值为 `null`"。阶段 2 的 run 若只是**没回报** usage，也会走这一
   分支，于是措辞变成一句假话。归 item 3/4（那时才有真 LLM run）。
5. **`max_total_tokens` 的"总量"= 输入 + 输出。** 任一侧未知则总量未知，不判定。
