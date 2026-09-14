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
    - 紧接其后（阶段 2 新增，不改变上面各条编号）：模型调用失败 → `llm_transport_error`（连不上）/ `llm_api_rejected`（网关拒绝）/ `llm_response_invalid`（响应不合协议）
4. 累计 token 超预算 → `token_budget_exceeded`
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
| 12 | `token_budget_exceeded` | **【建议新增】** 累计 token 超预算 | 原 10 个的**第二处遗漏**：阶段 2 必然需要预算上限，且用量是你的一等观察目标，用 #6 代偿语义错误 |
| 13 | `llm_transport_error` | 模型请求没能完成一次"传输"：DNS 解析失败、TCP/TLS 连不上、连接或读取超时、连接被重置 | 与 #10 的区别：请求根本没到达网关，不是我们拼错了请求；与 #5 的区别：没有任何响应可比对 |
| 14 | `llm_api_rejected` | 网关**明确**拒绝了请求：带错误体的 4xx/5xx（鉴权失败、余额不足、限流、模型名不存在） | 与 #13 的区别：拿到了明确的拒绝理由，可据此改配置；与 #15 的区别：拒绝是网关给的，不是我们解析出来的 |
| 15 | `llm_response_invalid` | 网关返回成功状态，但响应不合协议：非 JSON、缺必需字段、结构与约定不符 | 与 #14 的区别：HTTP 层面成功；与 #10 的区别：不是我们代码抛的异常，是外部数据不合约定 |

### 1.4 关于我发现的这两处遗漏

你要求确认"互斥、无遗漏"。互斥性由 §1.2 的顺序判定保证；**无遗漏这一条我没能做到——原 10 个标签有两处缺口**：

- **#11 外部中断**：这是任何交互式实验都会遇到的最常见终止原因之一，且塞进 `harness_error` 会污染"我们代码有 bug"这一信号。
- **#12 预算上限**：阶段 2 引入 LLM 后这是刚需，且与你的"token 是一等观察目标"直接相关。（该标签引入时名为 `cost_budget_exceeded`，记录 5 里改名为 `token_budget_exceeded`。）

两处现在补上代价为零（尚未写任何代码），冻结之后再补就必须迁移历史数据——这正是我在设计文档里用来说服你"token 字段从第一天就在"的同一个理由，所以我对自己的标签集用同一标准。是否接受由你定；若你否决，我会把这两类情况显式记录为"归入 #10 并附加 `sub_reason` 字段"的降级方案。

---

## 第二部分：输出截断（schema 修订）

### 2.1 修订内容

`tool_result` 与 `verification` 的**每条输出流**（`stdout`、`stderr` 各自独立）都要带下列字段：

| 字段 | 含义 |
|---|---|
| `bytes_total` | **截断前的原始字节数** |
| `bytes_delivered` | **截断后交付给 agent 的字节数** |
| `elided_bytes` | `bytes_total - head_bytes - tail_bytes`（被省略的字节数） |
| `truncated` | 布尔 |
| `strategy` | `none` 或 `head_tail` |
| `head_bytes` / `tail_bytes` | `head_tail` 策略下两段各自保留的字节数 |
| `marker_text` | 插入的省略标记**原文**，用于事后精确重建 |
| `sha256_full` | 完整内容哈希 |
| `sha256_delivered` | 交付内容哈希 |
| `blob_ref` | 完整内容在 `blobs/<sha256>.blob` 的引用 |

你要求的"截断前原始长度"与"截断后长度"即 `bytes_total` 与 `bytes_delivered`；额外给出的 `elided_bytes` 让"被切掉多少"可以直接聚合，不必做减法。

注意 `bytes_delivered` 与 `elided_bytes` **不互补**：交付文本是 `head_text + marker_text + tail_text`，所以
`bytes_delivered` **包含** `marker_text` 自身的字节数，而 `elided_bytes` **不含**标记——标记是观测工具加的开销，
不是"被省略的内容"。两者的关系是
`bytes_total - bytes_delivered == elided_bytes - len(marker_text.encode("utf-8"))`。
（本式原先写作 `elided_bytes = bytes_total - bytes_delivered`，与实现相差一个标记的长度；2026-09-14 修正，见变更记录 4。）

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

---

## 变更记录

### 记录 1：冻结基线移动（2026-09-13）

**基线从 `3342dcf` 移到主题为** `阶段 2：移动冻结基线（loop.py 的 token/成本读写接口定稿）` **的提交**
（SHA 用 `git log --format=%H -1 --grep="移动冻结基线"` 解析——本节无法引用自己的 SHA，故留命令）。

动的是 `harness/core/loop.py`，但**本文件的冻结内容一条没改**，所以只登记、不改条款：

- **§1.3 #12 `cost_budget_exceeded` 从"声明了但没有产生点"变成有产生点。** 判定顺序不变：仍排第 4，在 `env_error` 之后、`timeout_wall` 之前。`loop.py` 里成本检查排在墙上时钟检查**之前**，就是为了不违反已声明的这个顺序。
- **§2.1 的字段名与 §2.2 的策略语义不变。** 给 `llm_request`/`llm_response` 追加 `usage`/`latency_ms`/`stop_reason`/`cost_usd_estimate` 属于"新增字段"，本条规则本就允许，**无需改 `REQUIRED_FIELDS`**——`trace.py` 的 `emit` 只校验必需字段存在、不拒绝未知字段。这一条是本文件在阶段 2 不需要移动基线的唯一理由，故写在这里备查。
- **事件名不变。** `llm_request`/`llm_response` 自阶段 1 起就在事件名清单里，阶段 2 只是第一次真正往它们里写值。
- **`run_end.totals` 的三个字段名不变**（`input_tokens`/`output_tokens`/`cost_usd`）。阶段 1 填 `None` 的占位设计在这里兑现：阶段 2 只需开始填值，不需要改 schema、不需要重写已有轨迹的分析代码。

事后核对命令：`git diff 3342dcf -- harness/contract.py` 应无输出——本次移动没有碰契约常量。

### 记录 2：成本上限的启动前拒绝（2026-09-13）

**基线与记录 1 相同**（主题含 `移动冻结基线` 的提交），本次**没有再移基线**。
改动全在非冻结文件：`harness/core/usage.py`（写侧 `record()` 与判定 `exceeded()`）、
`harness/config.py`（可选预算字段与拒绝逻辑）、`harness/llm/pricing.py`（新增）。

登记一条可能被读作动条款的改动，交你裁决：

- **§1.2 声明了两条配置不变量（`max_denied_calls < max_tool_error_streak < max_steps`、
  `step_timeout_s < wall_timeout_s`），本次新增了第三条同性质的规则**：`max_cost_usd`
  非 `None` 时，要求 `[llm].model` 存在且能在 `harness/llm/pricing.py` 查到单价，
  否则抛 `ConfigError`、拒绝启动、不创建 run 目录。它只在启动前生效，**不参与 run 内
  的判定**，故不影响"先到者胜"的顺序。我把它视为**新增**（冻结后允许新增），若你认为
  它属于改条款，请指出，我改。
- **判定顺序不变**，§1.3 的标签语义不变。`#12 cost_budget_exceeded` 现在有了真实的
  产生点（判定实现落地），这与记录 1 里"变成有产生点"那句一致。
- **新增的配置字段是可选、默认 `None`**，故 `configs/*.toml` 一字未改，
  `config_hash` 未变——阶段 1 那批轨迹的配置归属仍成立。
- **`run_end.status` 的映射表未动**：`cost_budget_exceeded` 仍落到 `aborted`（默认值）。
  语义上它是"被预算中止"，与用户打断共用 `status=aborted`，区分靠 `failure_class`。

事后核对命令：`git diff <基线> -- harness/contract.py` 应无输出；
`load_config("default").config_hash()` 仍应等于阶段 1 样本 `meta.json` 里的哈希。

### 记录 3：第二次冻结基线移动（2026-09-14）

**基线从 `b6f983f` 移到主题含** `第二次移动冻结基线` **的提交**
（SHA 用 `git log --format=%H -1 --grep="第二次移动冻结基线"` 解析——本节无法引用自己的
SHA，故留命令，与记录 1 同）。

前两次移动都只登记、没动条款。**这次动了**，因此下面每一条都写明属于"新增"还是"改"。

#### 3.1 新增三个标签（§1.2 判定顺序插入，§1.3 表格新增三行）

`llm_transport_error` / `llm_api_rejected` / `llm_response_invalid`，语义见 §1.3 #13–#15。

- **新增，不是改**：原 12 个标签一个没动、一个没删，§1.3 的既有行逐字未改；判定顺序
  只在 §1.2 第 3 条（`env_error`）**之后插入**这三项，其余各条的相对顺序逐项不变。
- **为什么单列**：把"DeepSeek 连不上"和"我们写错了"塞进同一条 `harness_error`，是网关类
  问题永远无法与我们自身 bug 区分开的根源——两者要采取的行动完全不同。
- **产生点**：`harness/core/errors.py::ModelFailure(failure_class, detail)`，由 agent 侧抛出；
  冻结的 `loop.py` 多一个 `except ModelFailure`。**用异常而不是给 `next_action` 增加返回
  类型**，是因为 Agent 接口本身在冻结清单里——加返回类型就是改接口。
- **降级分支**：`contract.LLM_FAILURE_CLASSES` 是"主循环认识哪些标签"的判据。抛出方给了
  不认识的标签时降级为 `harness_error`，绝不让未声明的 `failure_class` 进轨迹。
- **`run_end.status`**：三者都映射到 `error`（见 §1.3 与 `loop.py::_STATUS_BY_CLASS`）。
  它们是"出错了"，不是"被中止"。

#### 3.2 改：`run_end.totals.cost_usd` → `cost`，并新增 `pricing_currency`

**这是本次唯一的删除行，也是"移基线"唯一的硬理由。** §3 的冻结声明禁止改字段名，
只有移动基线能做。

- **理由**：单价是人民币（`llm/pricing.py::CURRENCY`），字段名却写着 `usd`。将来换一个
  以美元计费的网关，同一份轨迹里两个 `cost_usd` 就是两种货币，而分析代码无法区分。
- **`pricing_currency`（值 `"CNY"`）与 `cost` 相邻落盘**：一个没有单位的成本数字，事后
  无法判断能不能和别的批次相加。
- **币种单点提供**：`llm/pricing.py::CURRENCY` → `run_ctx.pricing_currency` → `loop.py` 写入
  `totals`。绕这一圈是为了让冻结的 `loop.py` **仍然不 import `harness.llm`**——主循环不绑定
  具体后端这条不变式不动。
- **`max_cost_usd` → `max_cost_cny`**（配置字段与 TOML 键，非冻结文件，零成本）。`configs/*.toml`
  里没有这个键，故 `config_hash` 未变，阶段 1 那批轨迹的配置归属仍成立。
- **旧轨迹仍然合法**：`validate_records` 从不检查 `totals` 的子键。
  `tests/fixtures/phase1-sample-trace.jsonl` **保持 `cost_usd` 原样**、逐字节未改，
  `test_backcompat` 照旧通过。

#### 3.3 登记：§1.2 的第四条配置不变量

与记录 2 的第三条同性质，按裁决并进本条：

- 配了 `[llm].model` 却读不到环境变量 `MONKEY_DEEPSEEK_KEY` 时，抛 `ConfigError`、拒绝启动、
  不创建 run 目录（`__main__` 返回 exit 2）。它**只在启动前生效，不参与 run 内判定**。
- 理由：晚一步失败意味着 run 目录、轨迹、agent 的第一次工具调用都已产生——等于用一次
  失败的实验，换一个本可以在启动前报出的错误。
- 凭据读取收在 `harness/llm/credentials.py`：该模块只回答"在不在"、**不返回值**，调用方
  因此没有机会把它写进轨迹。
- 该检查排在成本上限检查**之后**：否则"有上限但模型无单价"会先撞到这里，报出与根因无关的
  缺 key。

#### 3.4 追认：同批次的另一个提交（`5b8c445`）不改 schema，但改变了观测值

`5b8c445`（环境隔离、截断、缺 key 拒绝启动）不含 schema 改动，登记两点影响备查：

- **A3 修好了重叠区的交付量**：此前 head/tail 按字符切、不卡字节，多字节输出在"总字符数 ≤
  head+tail 而字节数 > 阈值"的区间里，交付文本可能比原文还长、`elided_bytes` 为负、agent
  读到 `[truncated -8193 bytes]` 这类乱码标记。**字段名与语义没变，值变了**——同一段超长
  多字节输出，修复前后交付给 agent 的字节数不同。这是修掉了一个观察错误，不是改了契约。
- **A1 让子进程看不到 `MONKEY_*`**：宿主侧的观测不再可能把自身的凭据带进 `trace.jsonl`。
- A4 即 3.3。

#### 3.5 登记两处偏差，交你裁决（我不改条款）

**(a) §2.1 里 `elided_bytes` 的公式与实现不符。**

条款写 `bytes_total - bytes_delivered`，实现是 `bytes_total - head_bytes - tail_bytes`。
两者相差 `marker_text` 自身的字节数：交付文本里**包含省略标记**，而标记不是"被省略的内容"。
该行文字描述（"被省略的字节数"）与实现一致，需要改的是那个公式。

这条偏差**先于本次改动就存在**（截断一向如此算），本次只改了重叠区的保留量。可选修法：
把公式改成 `bytes_total - head_bytes - tail_bytes`，并写明等式
`交付文本 = head_text + marker_text + tail_text`。

**→ 已裁决（2026-09-14）：按上述修法改公式、保留语义。执行与登记见记录 4。**

**(b) 旧轨迹在报告里的读取路径。**

`report/text_report.py` 读 `totals.get('cost')`，没有对 `cost_usd` 的兼容回退。若某份旧轨迹
**同时有 token 又只有 `cost_usd`**，成本行会打印 `None`。阶段 1 不存在这种轨迹（无 LLM 则
token 恒为 `null`，报告走"阶段 1 无 LLM"分支），故我没有加回退——那属于为不存在的场景加分支。
若你认为该覆盖，请指出。

**→ 已裁决（2026-09-14）：接受，不加回退。** 阶段 1 的轨迹里 `cost_usd` 恒为 `null`，
不存在"有 token 又只有 `cost_usd`"的场景；加回退属于为不存在的场景加分支。

事后核对命令：

```
OLD=b6f983f
git diff --numstat $OLD HEAD -- harness/contract.py harness/core/loop.py \
    harness/agent/base.py harness/tools/base.py harness/env/base.py
# 期望：contract.py 形如 "N  0"（0 删除）；loop.py 形如 "N  1"；其余三个文件不出现
git diff -U0 $OLD HEAD -- harness/core/loop.py | grep "^[+-]"   # 唯一的 "-" 行是 cost_usd -> cost
```

### 记录 4：§2.1 的 `elided_bytes` 公式修正（2026-09-14）

**基线与记录 3 相同**（主题含 `第二次移动冻结基线` 的提交），本次**没有再移基线**。
本次动的是 §2.1 的一行公式文本，故必须登记。

- **改**：§2.1 表格里 `elided_bytes` 的算式从 `bytes_total - bytes_delivered` 改为
  `bytes_total - head_bytes - tail_bytes`；并在表后写明两个等式——交付文本是
  `head_text + marker_text + tail_text`，故 `bytes_delivered` 含标记、`elided_bytes` 不含，
  两者不互补。
- **语义未变**：`elided_bytes` 一直是"被省略的字节数"，`head_bytes`/`tail_bytes` 一直是
  "两段各自保留的字节数"，`marker_text` 一直是"插入的省略标记原文"。改的是文档里写错的
  算式——它此前与实现相差一个标记的长度（先于记录 3 的改动就存在）。
- **字段名、字段语义、判定顺序、标签集合均未动**；`contract.py` 未改，冻结清单 diff 为空。
- 该偏差由记录 3 §3.5(a) 登记，裁决为"改公式、保留语义"；三处实现（`trace.py::prepare_stream`）
  与新公式一致，故**没有代码改动**，只有文档改动。
- 记录 3 §3.5(b) 的裁决为"接受，不加回退"，同样没有代码改动。

事后核对命令：`git diff eadd1a8 --stat` 应只列出 `docs/trace-schema.md`；
`git diff eadd1a8 -- harness/` 应无输出。

### 记录 5：第三次冻结基线移动——删除成本面 + 标签改名（2026-09-14）

**基线**：主题含 `第三次移动冻结基线` 的提交。本次**移动了冻结基线**（`contract.py`
与 `loop.py` 都被改），这是阶段 2 的第三次移动。

**这次移动与前两次有一个机械差别，必须记在最前面**：前两次的判据是"`contract.py`
形如 `N 0`（0 删除行）"。本次 `contract.py` **第一次出现删除行**——旧标签名被删。
"只增不改"在标签名这一处被**有意让路**一次，理由见 5.1。此判据在本次作废；若以后
再有人拿"冻结清单 0 删除行"当不变式，以本条为准。

#### 5.1 改：`cost_budget_exceeded` → `token_budget_exceeded`

- **位置**：§1.2 判定顺序第 4 条、§1.3 表格 #12（`contract.py` 的 `FAILURE_CLASSES`
  与 `FAILURE_DECISION_ORDER` 各一处；`tests/fixtures/contract_snapshot.json` 同步）。
- **理由**：成本上限被砍（见 5.2），该标签所指的上限只剩 token。名字必须跟着它所指的
  东西走——否则就是又一次"名字说的是成本、判的是 token"，与 D7 同类。
- **这是唯一一次对冻结标签名的删除。** 可行性依据：**没有任何已归档轨迹带此标签**。
  它的唯一产生点是测试（`tests/test_token_budget.py`）；`tests/fixtures/phase1-sample-trace.jsonl`
  的 `run_end` 是 `none`。故改名不使任何历史产物失效。
- 标签**数量未变**（仍 15 个），判定顺序中它的位置未变（仍排第 4）。

#### 5.2 删：成本面（你裁定砍掉的三项：成本上限、峰谷判定、缓存命中率）

后两项（峰谷、缓存命中率）从未实现，无代码可删。实际删掉的：

- `harness/llm/pricing.py` —— **整文件**（`CURRENCY`、`PRICES`、`price_for`）。
- `harness/core/usage.py` —— `cost` 属性、`record()` 的 `cost` 关键字参数、
  `exceeded()` 的成本分支。**保留** input/output token。
- `harness/config.py` —— `Budgets.max_cost_cny` 字段、成本上限不变量整块、`price_for`
  import。**记录 2 §3.3 登记的"第四条配置不变量"就此作废**，现存不变量回到三条
  （`max_denied_calls < max_tool_error_streak < max_steps`、`step_timeout < wall_timeout`、
  `head+tail <= threshold`），外加缺 `[llm].model` 凭据时的启动前拒绝。
- `harness/runctx.py` —— `pricing_currency` 属性及其对 `pricing.CURRENCY` 的引用。
- `harness/report/text_report.py` —— 成本行；章节名 `token 与成本` → `token`。

#### 5.3 改：`run_end.totals` 删 `cost` 与 `pricing_currency`，保留 token

- 新形状：`{steps, tool_calls, input_tokens, output_tokens}`。
- **保留 token 的理由**：`max_total_tokens` 保留 ⇒ token 仍必须计数；一条因 token
  越限而死（`token_budget_exceeded`）的轨迹必须能看到超了多少——有标签、没数量，
  正是要避免的"不可观测"。
- **字段读写的语义未变**：`totals` 只是少了两个键。旧轨迹里的 `cost`/`cost_usd`/
  `pricing_currency` 键照旧留在文件里，`validate_records` 不校验 `totals` 子键，故旧
  轨迹仍合法、`text_report.py` 的 `.get()` 读取不受影响。

#### 5.4 保留未动

- **防线不变**：不重试（客户端批次）、单次请求超时（客户端批次）、`max_steps`、
  `max_total_tokens`。本次没有削弱任何一条。
- `run_end.status` 的映射表未动：`token_budget_exceeded` 仍落到默认值 `aborted`。
- `contract.py` 的 `LLM_FAILURE_CLASSES`、三个 LLM 标签、`REQUIRED_FIELDS` 均未动。
- 记录 1/2/3/4 **不重写**（本文件是追加式的变更台账）。

#### 5.5 未处理的发现

登记在 `docs/known-residues.md`，本次不处理。

事后核对命令：

```bash
git diff --numstat dee4e57 HEAD -- harness/contract.py harness/core/loop.py \
    harness/agent/base.py harness/tools/base.py harness/env/base.py
# 期望：contract.py、loop.py 有 + 与 - 行；后三个文件不出现
grep -rn "max_cost_cny\|pricing_currency\|price_for" harness/
# 期望：无输出
```

### 记录 6：A2 落地——客户端的单次请求超时（2026-09-14）

**基线与记录 5 相同**（主题含 `第三次移动冻结基线` 的提交），本次**没有再移基线**。
改动全在非冻结文件与新增文件，`contract.py` / `core/loop.py` / `agent/base.py` /
`tools/base.py` / `env/base.py` 一个字未动。

这一条登记的是**第五条"防线"从纸面变成执行点**。§1.2 的判定顺序、§1.3 的标签语义、
`LLM_FAILURE_CLASSES` 均**不变**；本记录不新增标签、不改字段名。

#### 6.1 A2：单次 LLM 调用挂住时，抢占点在哪里

审计 §5.2 的结论：`loop.py:81` 是**同步**调用，`timeout_step`（返回之后才查）与
`timeout_wall`（下一轮开头才查）都无法掐断一个未返回的调用。冻结的 `loop.py` 无法
抢占同步调用，故抢占由传输层自带（`harness/llm/client.py`），三层：

1. httpx 逐阶段 `Timeout(connect=5, read=45, write=10, pool=5)`；
2. httpcore 之下的真实 socket（httpx 内建，不覆写）——让第 1 层的 `read` 生效；
3. **总时限 90s** 包住**整次交换**（建连 + 收响应头 + 读正文），做成**线程级**包装：
   整次调用放进 worker 线程，主线程 `join(90)`，超时则关闭底层连接解阻塞。

第 3 层为什么不能写成"迭代 chunk 时查截止"：`read` 是**两次读之间的最大间隔**，一个
每 40s 送 1 字节的滴流网关永远骗过它；而若滴流发生在**响应头之前**，任何"响应头之后"
的截止检查一次都跑不到——请求阻塞在"等头"上，那里没有我们的代码。

#### 6.2 标签落点（照 §1.3 #13–#15，未新增标签）

- 连不上 / 连接或读写超时 / 连接被重置 / 响应编码坏掉 → `llm_transport_error`
- HTTP 非 200（含 401 / 402 / 429 / 5xx，本批不重试）→ `llm_api_rejected`
- 200 但 body 非 JSON / 缺必需结构 / `tool_calls[].function.arguments` 不是合法 JSON
  → `llm_response_invalid`
- **我们自己的 bug 不伪装成传输失败**：`base_url` 协议不支持、凭据缺失等被原样抛出，
  留给主循环落成 `harness_error`（§1.1 要保护的那条信号）。

#### 6.3 与 `timeout_step`（#7）的分工

一条挂住的调用，其唯一可能抢占者是客户端的总时限，故它**必然**先落成
`llm_transport_error`，而不是 #7 的 `timeout_step`——#7 在挂住场景下根本无法触发
（这正是 A2 的内容）。#7 因此被收窄为"慢而未挂"的情形：`configs/llm.toml` 把
`step_timeout_s` 设在总时限（90s）之上，使客户端成为先到者，拿到更具体的"网关没响应"。
这条顺序不变量**由测试钉住**，不靠注释。

#### 6.4 生产超时值（钉在测试里，改动因此可见）

`connect 5s / read 45s / write 10s / pool 5s / total 90s`，且 `read < total`——静默应
先以更具体的"读取超时"落定，总时限只兜底滴流。改这四个数必须同时改
`tests/test_llm_client_timeouts.py::ShippedTimeoutTest`。

#### 6.5 验证方式：真实回环 socket，不用 `MockTransport`

第 1/2 层超时由 httpcore 之下的 socket 实现，`httpx.MockTransport` 把整个传输层换掉，
根本走不到 socket——用它写出来的"通过"是假的。故 `tests/test_llm_client_timeouts.py`
的每个用例都把客户端指向 `127.0.0.1` 上的原始 TCP 服务器，由服务器脚本决定怎么卡住：
静默（→ 读取超时）、正文滴流（→ 总时限）、**响应头滴流且永不结束**（→ 总时限，即
A2 陷阱本身）。并配一条反向对照（正常服务器必须成功），否则"一切都超时"也会显绿。

离线、零网络、零成本：超时值经 `LlmTimeouts` 注入到亚秒级。

事后核对命令：

```bash
git diff --numstat HEAD -- harness/contract.py harness/core/loop.py \
    harness/agent/base.py harness/tools/base.py harness/env/base.py
# 期望：无输出（本批 0 冻结改动）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest \
    tests.test_llm_client_timeouts -v
# 期望：16 项通过，其中静默报"读取超时"、两种滴流报"总时限"
```

#### 6.6 接线落地：`llm_request` / `llm_response` 实际写入哪些字段

同批次的第二个提交把 agent 侧接上（`harness/llm/prompt.py`、`harness/llm/agent.py`、
`configs/llm.toml`、CLI）。**契约常量仍未动**：以下都是**新增字段**，§1.4 的规则
本就允许，`REQUIRED_FIELDS` 一个字没改（这正是本文件在阶段 2 不需要再移基线的理由）。

- `llm_request`：必需 `model`/`step`；另写
  `messages`（本次实际发给网关的 wire 消息全文）、`tools`（工具 schema 全文）、
  `params`（`max_tokens`/`stream`/`tool_choice`）。**记录全文而不记摘要**，因为
  "模型看到了什么"正是本项目的一等观测目标；提示词措辞的版本漂移因此逐条可复核。
- `llm_response`：必需 `model`/`step`；另写 `content`、`tool_calls`
  （已归一化为 `[{id,name,arguments}]`，`arguments` 是对象而非 JSON 字符串）、
  `stop_reason`、`usage{input_tokens,output_tokens}`、`latency_ms`。
- **缺 `usage` 时写 `null` 而不是炸 run**（`usage` 三个键一律可为 null）。取舍见
  `docs/known-residues.md` R-001：未知量无法触发 token 上限，但"网关没回 usage"
  本身就是该被观测到的事实。
- **写入顺序：先 `llm_request`、再发请求、再 `llm_response`。** 于是"挂住"在轨迹里
  留下"有请求、无响应"的形状——这就是审计 §5.2 说的信号，`replay` 会把它照着打出来。

`step` 的处理是本次唯一的接口妥协：它由 **agent 自计数**（`ConversationState` 里没有
step，`loop.py` 冻结且不发这两个事件）。因为本批**不重试**，一次 `next_action` 恰好
一次请求，自计数恒等于主循环的 `step`。这条隐含契约（审计 §7.1）由
`tests/test_llm_agent.py::test_the_self_counted_step_matches_the_loop_step` 机械钉住，
并登记为 R-006。

`stop_reason == "length"`（被 `max_tokens` 截断）时 agent 只能返回 `Abort`，故标签仍
是 `agent_gave_up`——§5.4 指出的语义错位**未被消除**，只是真因留在了
`llm_response.stop_reason` 里，这正是 §5.4 自己给出的辨识信号。

