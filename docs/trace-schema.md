# Trace Schema 与失败分类契约

- 状态：**待你评审**。评审通过后进入"冻结"状态，此后只增不改、不删不改名
- 适用范围：阶段 1 起生效；阶段 2 只填值、不改结构
- 上游：`docs/stage1-design.md` §6

---

## 第一部分：失败分类（failure_class）

### 1.1 关键区分：两个正交的维度

必须先分清两组东西，否则标签会退化成大杂烩：

| 维度 | 位置 | 语义 | 取值 |
|---|---|---|---|
| **为什么结束** | `run_end.failure_class` | 这次运行的**终止原因**，每次 run **恰好一个** | 本文件定义的标签 |
| **过程中发生了什么** | `tool_result.status` | 单次调用的**事实**，一次 run 里可出现多次 | `ok / error / timeout / denied` |

由此推出三条判定规则：

- **R1**：`failure_class` 描述"为什么结束"，**不描述过程中是否出过错**。agent 中途踩了工具错误但换了策略最终修好 → 标签是 `none`，过程中的错误留在对应的 `tool_result` 里。这是本套标签能被用来做失败模式分析的前提。
- **R2**：单次工具调用超时、单次策略拒绝都是**可恢复**的，只写 `tool_result.status`，**不**产生终止标签。只有累积到阈值才终止。
- **R3**：无论因何终止，只要工作区存在，**仍然照跑验证**并记录结果。因此会出现"`failure_class=agent_loop_limit` 且 `verification.status=passed`"这种组合——"步数耗尽但其实修好了"是有价值的观察数据，不该被丢掉。

### 1.2 判定过程（互斥性由构造保证）

标签 = **实际终止这次运行的那个原因**。主循环是顺序的，终止条件在时间上天然有序，**先到者胜**，因此每次 run 精确命中一个，不存在多标签并存。判定顺序如下：

1. 进程被外部中断（SIGINT / 外部终止）→ `aborted_by_user`
2. 我们自身代码抛未捕获异常或不变式被破坏 → `harness_error`
3. 执行环境不可用（执行器起不来、工作区建不出、仓库缺失）→ `env_error`
4. 累计 token/成本超预算 → `cost_budget_exceeded`
5. 整个 run 墙上时钟超 `wall_timeout` → `timeout_wall`
6. 单个 step 累计耗时超 `step_timeout` → `timeout_step`
7. 同一工具同一错误签名**连续**失败达到 `max_tool_error_streak` → `tool_error_repeated`
8. 被策略层拒绝的调用累计达到 `max_denied_calls` → `policy_denied`
9. agent 返回 `Abort` → `agent_gave_up`
10. 步数达到 `max_steps` → `agent_loop_limit`
11. agent 返回 `Finish` → 进入验证：
    - 验证通过 → `none`
    - 验证命令**成功启动**但 exit≠0 或解析出失败用例 → `verification_failed`
    - 验证命令**无法启动** → `env_error`
    - 验证结果无法解析 / 任务未定义验证 → `harness_error`

**配置不变量**（启动时校验，不满足则拒绝启动并明确报错，不创建 run 目录）：
`max_denied_calls < max_tool_error_streak < max_steps`，且 `step_timeout < wall_timeout`。
这些不变量保证"外层预算不会遮蔽内层更具体的原因"。即便有人配错，规则"先到者胜"仍能给出唯一确定的标签。

### 1.3 标签定义表

| # | 标签 | 触发条件（唯一） | 最容易混淆的边界 |
|---|---|---|---|
| 1 | `none` | 由 `Finish` 正常结束，且验证通过 | 过程中有过工具错误不算失败（见 R1） |
| 2 | `agent_loop_limit` | 步数达 `max_steps` 且 agent 未给出 `Finish`/`Abort` | 若连续错误已达阈值则先命中 #7 |
| 3 | `agent_gave_up` | agent 返回 `Abort(reason)` | agent 口头说"做不到"但仍 `Finish` → 不走此标签，走验证判定 |
| 4 | `tool_error_repeated` | 同工具 + 同错误签名（错误类型 + 归一化首行）**连续**失败 ≥ `max_tool_error_streak` | 工具必须**真的执行过**；被策略拒绝的不算（归 #8）；偶发一次且已换策略的不算 |
| 5 | `verification_failed` | 验证命令**启动成功**，但 exit≠0 或解析出失败用例 | 与 #3 的区别：#3 根本没跑起来。这是最易混的一对 |
| 6 | `timeout_wall` | 整个 run 墙上时钟超 `wall_timeout` | 单次**工具**超时可恢复，不产生标签（见 R2） |
| 7 | `timeout_step` | 单个 step 累计耗时（agent 决策 + 该步全部工具调用）超 `step_timeout` | 阶段 2 起 step 含 LLM 调用延迟，故该标签涵盖"模型挂住"与"工具挂住" |
| 8 | `policy_denied` | 被命令策略层拒绝的调用累计 ≥ `max_denied_calls` | 被拒绝的调用**不计入**工具错误，与 #4 不混算；单次拒绝可恢复 |
| 9 | `env_error` | 环境本身不可用：执行器无法启动（Docker 守护进程未运行、容器创建失败）、工作区无法建立、任务仓库缺失、验证命令无法启动 | 与 #10 的区别：不是我们代码的 bug；与 #5 的区别：命令根本没跑起来 |
| 10 | `harness_error` | 我们自身代码异常或不变式被破坏：未捕获异常、trace 写入失败、schema 校验失败、任务定义非法、验证结果无法解析 | 工具未注册**不算**：记 `tool_result(status=error, reason=unknown_tool)` 并计入 #4 |
| 11 | `aborted_by_user` | **【建议新增】** 进程收到外部中断（SIGINT/Ctrl-C、外部 kill） | 原 10 个的**遗漏项**：此前只能勉强归入 #10，会把"用户打断"误导成"我们的代码有 bug" |
| 12 | `cost_budget_exceeded` | **【建议新增】** 累计 token/成本超预算 | 原 10 个的**第二处遗漏**：阶段 2 必然需要花费上限，且成本是你的一等观察目标，用 #6 代偿语义错误 |

### 1.4 关于我发现的这两处遗漏

你要求确认"互斥、无遗漏"。互斥性由 §1.2 的顺序判定保证；**无遗漏这一条我没能做到——原 10 个标签有两处缺口**：

- **#11 外部中断**：这是任何交互式实验都会遇到的最常见终止原因之一，且塞进 `harness_error` 会污染"我们代码有 bug"这一信号。
- **#12 成本预算**：阶段 2 引入 LLM 后这是刚需，且与你的"token/成本是一等观察目标"直接相关。

两处现在补上代价为零（尚未写任何代码），冻结之后再补就必须迁移历史数据——这正是我在设计文档里用来说服你"token 字段从第一天就在"的同一个理由，所以我对自己的标签集用同一标准。是否接受由你定；若你否决，我会把这两类情况显式记录为"归入 #10 并附加 `sub_reason` 字段"的降级方案。

---

## 第二部分：输出截断（schema 修订）

### 2.1 修订内容

`tool_result` 与 `verification` 的**每条输出流**（`stdout`、`stderr` 各自独立）都要带下列字段：

| 字段 | 含义 |
|---|---|
| `bytes_total` | **截断前的原始字节数** |
| `bytes_delivered` | **截断后交付给 agent 的字节数** |
| `elided_bytes` | `bytes_total - bytes_delivered`（被省略的字节数） |
| `truncated` | 布尔 |
| `strategy` | `none` 或 `head_tail` |
| `head_bytes` / `tail_bytes` | `head_tail` 策略下两段各自保留的字节数 |
| `marker_text` | 插入的省略标记**原文**，用于事后精确重建 |
| `sha256_full` | 完整内容哈希 |
| `sha256_delivered` | 交付内容哈希 |
| `blob_ref` | 完整内容在 `blobs/<sha256>.blob` 的引用 |

你要求的"截断前原始长度"与"截断后长度"即 `bytes_total` 与 `bytes_delivered`；额外给出的 `elided_bytes` 让"被切掉多少"可以直接聚合，不必做减法。

### 2.2 一处会影响观测正确性的策略选择：head + tail

截断策略定为**保留头部 + 保留尾部**，而不是只留头部。理由是具体的：**测试失败信息通常出现在输出的末尾**。若只截头部，会把 agent 最需要的那段信号切掉，于是我们观察到的就变成"agent 被我们的截断方式搞糊涂了"，而不是"agent 如何解决问题"——观测工具本身成了干扰变量。

`marker_text` 落盘的目的也在于此：事后要能**精确重建** agent 当时看到的每一个字节，才能把 agent 的行为归因到正确的输入上。

### 2.3 可验证性质（会写成测试）

- `reconstruct(blob_ref, head_bytes, tail_bytes, marker_text)` 的结果与 `sha256_delivered` 一致；
- 该重建结果与当时**实际喂给 agent 的文本**逐字节一致。

有了这条，你就能证明"轨迹足以还原 agent 当时的输入"，而不是只能相信它。

---

## 第三部分：冻结声明（评审通过后生效）

冻结内容：
- 本文件 §1.3 的标签集合与语义
- §1.2 的判定顺序与配置不变量
- §2.1 的字段名与 §2.2 的策略语义
- JSONL 事件名（`run_start / agent_message / llm_request / llm_response / tool_call / tool_result / step_end / verification / error / run_end`）

冻结后允许：**新增**事件类型、**新增**字段、**新增**标签。
冻结后禁止：改字段名、改字段语义、改标签语义、删除、改判定顺序。
