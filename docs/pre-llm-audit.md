# MONKEY 装大脑前的结构性审计

- 日期：2026-09-13
- 范围：接入 LLM（"装上大脑"）之前，找出所有会**变贵、变难、甚至要推倒重来**的决策
- 方式：**只审计，未改任何代码**。本文所有结论都指到具体文件与行号，可逐条复核
- 判据：每项标注 **已知的已知 / 已知的未知 / 未知的未知**；已知的未知给出"现在能不能修、成本"；未知的未知给出"装大脑后靠什么信号发现"

---

## 0. 结论摘要

三类结论，按处置方式分组：

### A. 接 LLM 前必须修（否则会产生错误的观测数据或错误的标签）

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| A1 | `LocalExecutor` 把宿主环境整体交给被观测命令 → `MONKEY_DEEPSEEK_KEY` 对 agent 可见，一句 `printenv` 就进 `trace.jsonl` + `blobs/` + `report.md` | `harness/env/local.py:40` | 高 |
| A2 | 单次 LLM 调用挂住时**没有任何机制能抢占它**：`timeout_step` / `timeout_wall` 都只在调用返回后才检查 → run 永久卡住 | `harness/core/loop.py:81,142,72` | 高 |
| A3 | 多字节输出在 8KB–18KB 区间触发截断时交付文本**被复制一遍**，`elided_bytes` 为负，agent 看到 `[truncated -8193 bytes]` 的乱码标记 | `harness/trace.py:59-79` | 高 |
| A4 | 无 API key 启动检查 → 静默到第一次请求才炸，且炸成 `harness_error` | `harness/config.py` / `__main__.py` | 中 |
| A5 | LLM 传输/网关失败**没有标签落点**，全部塌缩进 `harness_error`，破坏 §1.1 刻意保护的"我们的 bug"信号 | `harness/contract.py:26-39` + `loop.py:149-152` | 高 |

### B. 与 LLM 客户端一起做（现在做最便宜，但可等）

币种/单价签名、缓存命中未命中的落点、`system_fingerprint`、启动期拒绝项、`[llm]` 配置位、`reason` 枚举集中、`verification` 流字段校验。

### C. 只能等信号（未知的未知，见 §9）

真实 usage 组成、是否回 `system_fingerprint`、模型 tool-call 风格、观测工具自身引入的偏差。

### D. 需要你裁决（阻塞下一步，见 §10）

5 个问题，其中 2 个涉及冻结文件与基线，必须你定。

---

## 1. 字段命名与语义

### 1.1 `cost_usd`：名字说的是美元，价格是人民币 —— **已知的已知**

- `harness/llm/pricing.py:10` 的注释写着"每百万输入 token 的**美元**价"，而你要填的是**人民币**价（阶段 2 价格 1 元/百万输入未命中）。
- `harness/config.py:38` 新增（未提交）了 `max_cost_usd`；`harness/core/usage.py:48,51` 的属性与关键字参数同名；`harness/core/loop.py:180` 把它写进 `run_end.totals.cost_usd`。
- `docs/trace-schema.md` 记录 1 明文宣告 `run_end.totals` 的三个字段名（含 `cost_usd`）**不变**，而"改字段语义"在 §3 冻结声明里被禁止。
- 现状：**没有任何地方声明这个字段的单位**。名字说的是 USD，实际会是 CNY。

不是学术洁癖：`max_cost_usd` 与 `cost_usd` 是预算判定的两侧（`usage.py:74-76`）。单位是 CNY 而名字是 USD，将来换一个以美元计费的网关，同一份轨迹里两个 `cost_usd` 就是两种货币，而分析代码无法区分。

**现在能不能修**：能，且分两半，成本差很多——
- `max_cost_usd`（**未提交**，`config.py:38`）：可自由改名 `max_cost_cny`，零成本。
- `totals.cost_usd`（**已冻结**，`loop.py:180`）：改名 = 改字段名 = 移基线；只改注释 = 改语义，同样违反冻结。

### 1.2 `price_for` 的签名装不下真实价格模型 —— **已知的已知**

`harness/llm/pricing.py:14` 返回 `(输入单价, 输出单价)` 的一个二元组。你的价格模型是：

- 输入分**缓存命中 / 未命中**两档（0.02 vs 1，差 **50 倍**）
- 分**空闲 / 高峰**两个时段（差 2 倍）
- 输出只有一档，也分两个时段

一个 `(in, out)` 二元组、且没有时间参数的函数，**无法表达**"命中与否"和"哪个时段"这两维。唯一调用点是 `config.py:129` 的 `if price_for(llm_model) is None`（只判非空）。**现在改造它是零成本的——没有第二个依赖方。**

### 1.3 `PRICES` 的注释把币种写死成美元 —— **已知的已知**

`pricing.py:10` 的元组注释是 `(每百万输入 token 的美元价, 每百万输出 token 的美元价, 来源, 核对日期)`。填 CNY 价而不改注释，就制造了"文件里的说明与数据不符"——同一类错误你在依赖 `env/base.py` 的文档串残留上已经遇到过一次。

### 1.4 `status` 一名三义 —— **已知的已知**

同一个字段名承载三套互不相交的词表：

| 事件 | 取值 | 定义处 |
|---|---|---|
| `tool_result.status` | `ok / error / timeout / denied` | `contract.py:57` |
| `verification.status` | `passed / failed / timeout / launcher_error` | `harness/eval/runner.py:43-48` |
| `run_end.status` | `completed / failed / aborted / error` | `contract.py:100` |

按事件类型读是对的（`report/text_report.py` 就是这么做的），但任何"按 status 聚合"的分析都会被三套词表搅在一起。是可接受的既有选择，但**装大脑前值得记一笔**，因为 LLM 事件族还会带来第四套（如 `stop_reason`）。

### 1.5 `reason` 是自由文本，却被当成分组键 —— **已知的已知 + 已知的未知**

`harness/core/messages.py:25` 注释：`reason` = "归一化错误签名，用于连续失败计数"。`loop.py:129` 用它做等值比较来累计 `tool_error_repeated` 的连续计数。

- 枚举值散落在三个文件：`registry.py:31,37,41`、`shell_tools.py:18,22,28,31`、`fs_tools.py:20,24,36,45`。
- `contract.py` 里**没有** `reason` 的枚举，`validate_records`（`trace.py:145-184`）**完全不检查** `reason` → 拼错一个 reason，`tool_error_repeated` 的连击计数就永不成立，而轨迹校验仍报 OK。
- 已知的未知：LLM 侧需要多细的 reason 粒度（"schema 违例" vs "参数类型错"）现在不知道。

### 1.6 `parsed` 不在 `REQUIRED_FIELDS` —— **已知的已知**

`contract.py:89-92` 的 `verification` 必需字段里没有 `parsed`，它的形状只在 `eval/runner.py:32` 的返回值里定义。报告（`text_report.py:81-85`）依赖它。新增 LLM 事件族前，这里已经是一处"契约之外的数据形状"。

### 1.7 `head_bytes` / `tail_bytes` 在 `strategy=none` 时语义未定义 —— **已知的已知**

`trace-schema.md` §2.1 只定义"`head_tail` 策略下两段各自保留的字节数"，没定义 `none` 分支。实现（`trace.py:50-51`）填的是 `(total, 0)`。于是 `head_bytes` 在 `none` 下等于全文、在 `head_tail` 下等于头部切片——同一个字段名，两种含义。

### 1.8 `exit_code=None` 的语义未声明 —— **已知的已知**

`None` 表示"根本没有进程跑起来"（`denied`、`unknown_tool`、`launcher_error`），不是 0，也不是"未知"。未声明，`validate_records` 也不做类型检查。

### 1.9 `llm_request.model` 在浮动模型名下不足以复现 —— **已知的未知**

你要填的 `deepseek-flash` 是浮动名称。若 DeepSeek 不回 `system_fingerprint`，那么两条不同版本的轨迹在结构上**完全无法区分**——你的"靠归档请求/响应保证可复现"就降级成"靠归档 + 接受版本漂移"。
**信号**：第一条真实响应里有没有 `system_fingerprint` 键（见 §9.2）。

---

## 2. 时间与时区

### 2.1 `ts_wall` 的单位与时区没有声明 —— **已知的已知**

`harness/clock.py:16` 用 `time.time()`（epoch 秒，UTC）。`trace.py:110` 原样写入。`trace-schema.md` 的字段表**没有**声明这两个时间字段的单位与时区。跨机器比对轨迹的人只能靠猜。

### 2.2 `ts_mono` 的原点没有声明 —— **已知的已知**

`trace.py:99` 的 `self._t0 = clock.now()` 在 `TraceWriter` **构造时**取，即 `ts_mono` 的原点是"写入器创建"，不是"run 开始"（`run_start` 事件在 `loop.py:49` 才发，中间还夹着 `ConversationState` 构造）。差值正确、原点未声明；`perf_counter` 还是**进程内**时基，跨进程/跨重启无意义。这是设计如此（`clock.py:1-7` 说明用 perf_counter 是为了分辨率），但没有写进 schema。

### 2.3 高峰时段判定缺少时区锚点 —— **已知的未知**

你的规则：高峰 = 工作日 09:00–12:00、14:00–18:00（**北京时间**）。全项目现在**没有任何时区处理**（无 `zoneinfo`、无 `pytz` 使用）。当单价表落地时，把 `time.time()`（UTC epoch）转成"北京几点"只有两种写法：

- 显式 `ZoneInfo("Asia/Shanghai")` —— 正确，与宿主在哪无关。
- `time.localtime()` —— 取**宿主**时区。本机是 Windows 11 "Home China"，恰好是 Asia/Shanghai，**这是巧合不是保证**。任何在其他时区的机器上重跑，peak/off-peak 切分会不同，同一份归档数据算出不同成本。

**现在能不能修**：能，成本极低（一行 `ZoneInfo`），而且在写客户端之前修就是零成本——写完之后就是"发现同一 run 在两台机器上成本不同"这一类贵 bug。
**信号**（若不修）：同一批归档响应在两台机器上 `cost_usd` 不一致；或一天的成本曲线在错误的小时上出现台阶。

### 2.4 夏令时 —— **已知的已知（钉住时区后即为无风险）**

`Asia/Shanghai` 自 1991 年起无夏令时，**钉住时区即无 DST 风险**。反之，若用 `time.localtime()` 而宿主在 US/Eastern 之类的区域，一年会漂两次，每次一周，期间高峰判定整体错位。风险与 §2.3 是同一个根因。

### 2.5 高峰的**边界语义**未定义 —— **已知的未知（需要你裁决）**

至少有四个未定：

1. 端点开闭：09:00 整算高峰吗？12:00 整算高峰吗？（`[9,12)` vs `(9,12]` vs `[9,12]`）
2. 节假日：中国法定节假日算空闲还是高峰？（DeepSeek 的空闲优惠历史上按"工作日/周末"或"非高峰时段"定义，节假日的归属需核实）
3. 定价时刻：以**请求发起**时刻、还是**响应结束**时刻定档？跨边界的长请求（比如 11:59 发起、12:01 完成）按哪档？
4. 一次 run 跨档：`max_cost_usd` 是逐笔按当时档位累加，还是整个 run 用一个档位？

**现在能不能修**：能，成本 = 你回答即可（零代码）。不回答的代价：单笔成本估算有一个**最多 2 倍**的歧义带，7 元预算的实际含义可能是 3.5–14 元。

### 2.6 `duration_ms` 的取整 —— **已知的已知（可忽略）**

`clock.py:21` 四舍五入到整数毫秒。`loop.py:142` 用它和 `step_timeout_s * 1000` 比较，边界处有半毫秒误差。记录在案，不必修。

---

## 3. 单位与精度

### 3.1 token 的语义未声明 —— **已知的未知**

- `input_tokens` 是否包含缓存命中的部分？DeepSeek/OpenAI 兼容接口同时报 `prompt_tokens` 与 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，三者的加减关系需要从**一次真实响应**核实。
- 是否有 reasoning/thinking token 另计？
- `usage.py:72` 声明 `max_total_tokens` 的"总量"= 输入 + 输出；如果 `prompt_tokens` 已含 hit+miss，这个口径是否与计费口径一致？

**信号**：第一条真实 `llm_response` 的 usage 字段，与官方单价表能算出的金额对账。对不上就说明组成理解错了。

### 3.2 缓存命中/未命中**没有落点** —— **已知的已知（严重）**

- `UsageLedger.record(*, input_tokens, output_tokens, cost_usd)`（`usage.py:51`）只有三个量。
- `run_end.totals`（`loop.py:175-181`）只有 `input_tokens / output_tokens / cost_usd / steps / tool_calls`。

而你的价格里**输入分命中/未命中两档，差 50 倍**——成本的主要变量恰恰落在一个没有归宿的位置。后果：

1. 事后无法从轨迹重算成本，只能相信一个**不可审计**的估算数字。
2. 成本异常时无法回答"是因为上下文长，还是因为缓存没命中"——而这正是你会问的第一个问题。

**现在能不能修**：能，且**不需要动冻结文件**。两条路：
- 便宜路：把 `cache_hit_tokens` / `cache_miss_tokens` / 逐笔 `cost` 写进 `llm_response` **事件**（属于冻结声明允许的"新增字段"，`trace.py:115` 的 `record.update(fields)` 接受任意额外键）。`totals` 一字不改，无需移基线。逐笔有了，总和自然可加。
- 贵路：往 `totals` 加键 —— 必须在冻结的 `loop.py` 里改 `totals` 字典，等于又一次基线移动。

### 3.3 成本精度：真风险不是浮点，是打印 —— **已知的已知**

- 浮点本身够用：IEEE754 双精度的相对误差约 1e-16，`0.00021` 这类量级完全够。
- 真正的两个风险：
  1. 若**逐笔 round 后再累加**，误差会累积（一次性累加则不累积）。
  2. `report/text_report.py:117` 直接 `f"{totals['cost_usd']}"` 打印原始浮点 → 会输出 `0.00021000000000000002` 或 `3.0000000000000004e-05` 这类字符串。报告是给人看的，这既难看又显得不可信，且**跨平台可能不一致**。

**现在能不能修**：能，极低成本（报告侧定点格式化 + 声明成本保留几位有效数字）。

### 3.4 货币单位不统一 —— **已知的已知**

见 §1.1。补充：**没有任何字段携带币种代码**。`llm_response.cost_usd_estimate`（`trace-schema.md` 记录 1 里命名）同样带 `usd` 后缀。零成本的做法是在成本负载里加一个显式 `currency` 键（新增字段，不碰冻结）。

### 3.5 逐笔 vs 累计的口径 —— **未知的未知**

一个 run 内多次模型调用，每次都是一次**独立计费**（各自命中/未命中、各自档位）。逐笔累计在数学上可加，但若供应商的"缓存命中"依赖请求间的前缀共享（prompt caching），那么**调用顺序会影响总成本**，而顺序又由 agent 的行为决定。这意味着"同样步数"的两个 run 成本不可比。
**信号**：同一任务两次 run 的 `cost_usd` 差异远超 token 数差异；或命中率与上下文构造顺序强相关。

---

## 4. 配置项

### 4.1 没有 API key 的启动检查 —— **已知的已知（必修）**

`config.py:121-133` 已经为"配了成本上限却查不到单价"建立了"拒绝启动、不建 run 目录"的模式，但**没有对应的 key 检查**。缺 key 时：run 目录照建、`run_start` 照发、第一次模型请求 401 → agent 侧异常 → `loop.py:149-152` → `harness_error`（把"你没配 key"误导成"我们的代码有 bug"）。

**现在能不能修**：能，低成本（非冻结文件；与 `config.py` 现有拒绝逻辑同构）。

### 4.2 `[llm]` 只有 `model` 一个读点 —— **已知的已知**

`config.py:98` 只取 `[llm].model`。base_url、超时、最大输出 token、重试次数/退避**都没有配置位** → 只能硬编码在客户端里 → 换网关/调超时要改代码。而 §4.1 的"拒绝启动"逻辑又依赖配置能表达"我要用哪个端点"。

### 4.3 改 `configs/*.toml` 会断掉阶段 1 的配置归属 —— **已知的已知**

`config_hash` = 原始 TOML 字典的 sha256（`config.py:63-65`）。往 `configs/default.toml` 加一个 `[llm]` 节：

- `tests/test_backcompat.py::Phase1ConfigHashTest` 会变红（它正是为此而设）；
- 阶段 1 那批轨迹的 `meta.json.config_hash` 与现行配置**对不上**，配置归属断链。

**现在能不能修**：能，零成本——**新建一个配置文件**（如 `configs/local-llm.toml`），`default.toml` / `docker.toml` 逐字节不动。这样 pin 保持绿，阶段 1 归因完好。

### 4.4 截断不变量"配了但不生效" —— **已知的已知**

`config.py:116` 校验 `head_chars + tail_chars <= truncate_threshold_bytes`，但**左边是字符、右边是字节**。默认配置下是 `3000 + 3000 <= 8192`（通过）。而 §A3 的多字节重叠恰恰发生在"字符总数 ≤ 6000 且字节数 > 8192"时——这个不变量**拦不住它**，因为它把字符当字节比。一个看起来在保护某件事的校验，实际保护不了那件事。

### 4.5 `max_total_tokens` 可能永不可达 —— **已知的已知（机制）+ 已知的未知（是否发生）**

`usage.py:77-79`：总量 = 输入 + 输出，**任一侧未知则总量未知**，而未知不触发终止（`usage.py:66-70` 的设计）。所以只要客户端某次没报 `output_tokens`，`max_total_tokens` 就**静默失效**，run 一路跑下去。

机制是已知且刻意的（"无法证明它超了就不凭它终止"）；**是否会发生取决于客户端的回报完整性**——这是未知的。
**现在能不能修**：机制上不建议改（改了就违反"未知不触发"）。低成本缓解：在 `run_end` / 报告里显式告警"设了上限但对应总量为 `None`，本次上限未生效"。这是一个诚实的信号，且不碰冻结文件。

### 4.6 `step_timeout_s` 的默认值会掩盖问题 —— **已知的已知**

`step_timeout_s = 30.0`（`configs/default.toml` / `support.make_config:46`）是**阶段 1（无 LLM）**的取值。装上大脑后一个 step 含模型调用延迟，一次长响应很容易超过 30 秒。而 `loop.py:142` 的检查在模型返回后才跑 → 会得到一批 `timeout_step` 标签、但 `verification.status=passed` 的 run。默认值让"上限"从保护变成假阳性来源。

**现在能不能修**：能，零成本——新配置文件给更大的 `step_timeout_s` / `wall_timeout_s`（与 §4.3 同一个新文件）。

### 4.7 生产侧没有 agent 注入路径 —— **已知的已知**

`__main__.py:174` 的 `--agent` 是 `choices=list(AGENT_NAMES)`（只有 scripted），`__main__.py:85` 硬编码 `agent = ScriptedAgent(args.agent)`。而"把 `run_ctx.usage` / `run_ctx.trace` 注入 agent"这条路径**只存在于 `tests/support.py:105-106` 的 `attach` 钩子**。也就是说：真 LLM agent 要拿到账本与写入器，`cmd_run` 必须改，而这条生产路径**目前没有任何测试在覆盖**（测试走的是 `support.run_scenario`，不是 `cmd_run`）。
**现在能不能修**：能，低成本——让 `cmd_run` 与 `run_scenario` 共用同一个 agent 构造/注入函数。

---

## 5. 错误分类

### 5.1 现状：LLM 相关失败会落到哪里

逐一核对 12 个标签与 `loop.py` 的赋值点，结论如下表。**核心事实：agent 只能返回 `Abort`，无法设置 `failure_class`**（`agent/base.py:16` 的返回类型只有 `ToolCalls | Finish | Abort`）。因此所有"在 agent 内部发生的失败"只有两条出路：

- 抛异常 → `loop.py:149-152` 的 `except Exception` → **`harness_error`**
- 返回 `Abort` → `loop.py:93-98` → **`agent_gave_up`**

| LLM 失败 | 现状落到 | 应该落到 | 问题 |
|---|---|---|---|
| 网络错误 / DNS / 连接拒绝 | `harness_error` | 独立的 LLM 传输类标签 | 污染"我们代码有 bug"信号 |
| HTTP 401 / 402（key / 余额） | `harness_error` | 401 应在启动期拒绝；402 需运行期独立标签 | 同上 |
| HTTP 429 限流 | `harness_error` | 可恢复：先重试，重试耗尽才终止并独立标签 | 同上，且把可恢复的当致命 |
| HTTP 5xx / 503 | `harness_error` | 同上 | 同上 |
| **单次调用挂住** | **什么都不发生** | `timeout_step` | 见 §5.2，**最严重** |
| 非法 tool-call JSON | `harness_error` | 独立标签（模型的输出格式问题） | 同上 |
| 幻觉出未注册工具 | `tool_error_repeated` | 独立的"模型误用"类 | 见 §5.3，**语义不符** |
| 上下文超长 400 | `harness_error` | 独立标签（可恢复：裁剪历史重试） | 同上 |
| `stop_reason=length` / 空响应 | `agent_gave_up`（若 agent 放弃） | 独立标签 | 见 §5.4，**语义错位** |

结论：**12 个标签没有 LLM 传输/网关失败的落点**。全部塌缩进 `harness_error`，而这恰好是 `trace-schema.md` §1.1 明确要保护的那条信号（"我们代码有 bug"）。

### 5.2 挂住的模型调用无法被抢占 —— **已知的已知（高危）**

`loop.py:81` 是**同步**调用 `agent.next_action(state)`。

- `timeout_step` 的检查在 `loop.py:142`，位于 `next_action` **返回之后**、该步工具跑完之后。
- `timeout_wall` 的检查在 `loop.py:72`，位于**下一轮循环开头**。

所以：如果模型请求永不返回，主线程就停在 `loop.py:81` 上，**两个超时都不会触发，也没有任何抢占机制**。run 会永久挂着（只能靠外部 kill → `aborted_by_user`）。`trace-schema.md` #7 声称"阶段 2 起该标签涵盖模型挂住"——**标签的语义写对了，但执行点不存在**。`timeout_step` 目前只是一个"事后给慢步贴的标签"，不是"能掐断慢步的守卫"。

**现在能不能修**：能，但**不能靠冻结的 `loop.py`**（它无法抢占一个同步调用）。必须由客户端在 HTTP 层自带超时（socket/TCP + 读取超时），超时后抛异常或返回可识别的失败。于是又回到 §5.1 的标签问题：客户端抛出的超时异常到 `loop.py:149` 仍是 `harness_error`，除非改冻结文件。
**信号**（若不修）：run 目录下 `trace.jsonl` 长时间不增长、无 `run_end`；或外部 kill 后 `failure_class=aborted_by_user` 而实际原因是模型无响应。

### 5.3 `tool_error_repeated` 的语义与实现不符 —— **已知的已知**

`trace-schema.md` #4 的边界明文写着："工具必须**真的执行过**；被策略拒绝的不算（归 #8）"。

但未注册的工具（模型幻觉出的工具名）走的是 `registry.py:29-31`：记 `tool_result(status=error, reason=unknown_tool)`，然后 `loop.py:128-136` 把它**计入** `tool_error_repeated` 的连击。**幻觉的工具名从来没有执行过**——按契约它不该走 #4。

更实际的影响：模型若反复幻觉同一个工具名，会得到一个 `tool_error_repeated` 标签，读起来像是"工具本身有缺陷"，而事实是"模型不认识工具集"。这是最典型的"标签名与实际含义不符"。

### 5.4 截断/放弃的语义错位 —— **已知的未知**

`stop_reason=length`（被截断）或空响应时，agent 若选择停手并 `Abort`，标签是 `agent_gave_up`——语义是"agent 主动放弃"，而事实可能是"模型被截断了"。同理，上下文超长导致的重试耗尽，最终也会读成 `agent_gave_up`。
**信号**：`agent_gave_up` 的 run 里，`llm_response.stop_reason` 大量是 `length`；或 `Abort.reason` 文本里出现 context/token 字样。

### 5.5 新增标签的代价：不得不移一次基线 —— **已知的已知（结论）**

要给出 LLM 失败一个正确的标签，需要：

1. `contract.py` 的 `FAILURE_CLASSES` 加一项 + `FAILURE_DECISION_ORDER` 加一项（**冻结文件**）；
2. `loop.py` 加一个赋值点——即让"agent 内部的基础设施失败"能传到 `failure_class`（**冻结文件**）；
3. `loop.py:19-24` 的 `_STATUS_BY_CLASS` 加映射，否则新标签落到默认值 `aborted`（**冻结文件**）；
4. `tests/fixtures/contract_snapshot.json` 同步；
5. `tests/test_contract.py:43` 把硬编码的 12 改掉。

**现在改 vs 以后改**：

| | 现在改 | 以后改（已有真实 LLM 轨迹之后） |
|---|---|---|
| 代码 | 一次性移动基线，5 个文件 | 同样 5 个文件 |
| 轨迹 | 无历史 LLM 轨迹要迁移 | 已产生的 LLM 轨迹带着错标签（`harness_error`），要迁移或标注 |
| 分析 | 无基于标签的分析代码 | 已写好的失败模式分析代码要跟着改，且"哪些 harness_error 其实是网关问题"事后**无法从轨迹区分** |
| 0 元的替代 | 用 `error` 事件的 `where="llm"` + `sub_reason` 降级表达（`trace-schema.md` §1.4 提过的方案） | 同左 |

我的建议：**合并成一次基线移动，在任何真实 LLM 轨迹产生之前完成**。理由是"以后改"多出来的不是代码量，而是**已经不可挽回的数据污染**——一旦有了几百条标签为 `harness_error` 的 LLM 轨迹，你再也分不清哪些是我们的 bug、哪些是网关抽风。

---

## 6. 冻结清单

冻结 5 文件：`contract.py`、`core/loop.py`、`agent/base.py`、`tools/base.py`、`env/base.py`。验收基线 `b6f983f`，验收条件是"diff 为空"。

| 冻结文件 | 装大脑后是否必然要改 | 具体要改什么 | 现在改 vs 以后改 |
|---|---|---|---|
| `core/loop.py` | **必然** | (i) LLM 失败标签的赋值点；(ii) `_STATUS_BY_CLASS` 映射；(iii) 若要让 loop 拥有 step 编号，`llm_request`/`llm_response` 改由 loop 发 | 见 §5.5：以后改多出**不可挽回的轨迹污染** |
| `contract.py` | **必然**（若加标签） | `FAILURE_CLASSES`、`FAILURE_DECISION_ORDER`、快照 | 见 §6.1 的张力 |
| `agent/base.py` | **不一定** | 若想让 agent 表达"网关失败不是我的错"，理想是加一个返回类型；但**可以不改**——agent 抛类型化异常即可（Python 不需要在接口里声明），代价是 `loop.py` 的 `except` 必须认得它（回到 loop.py 的必改项） | 不改则接口语义靠约定，无机械保证 |
| `tools/base.py` | **不必改** | `Tool` 只有 `execute`，没有 schema/description → LLM 看不到工具。但 schema 可以放一个**非冻结**模块，并加测试"每个注册工具都有 schema"防漂移 | 现在做零成本；等漂移发生后再补，会先出现"工具加了但模型看不见"的静默故障 |
| `env/base.py` | **不必改** | LLM 客户端不经过 executor。但有两处残留见 §6.2 | — |

### 6.1 冻结声明与验收条件互相矛盾 —— **已知的已知（需要你裁决）**

`trace-schema.md` §3 明文："冻结后允许：**新增**事件类型、**新增**字段、**新增**标签。" 但同一份文档与项目约定把验收条件定为"diff against `b6f983f` 为空"。**一个被允许的"新增标签"必然让 diff 非空，从而验收失败。**

这不是文字游戏：§5.5 建议的基线移动，与"只增不改"是**相容的**，但与"diff 为空"这个机械判据是**不相容的**。二者必须选一个口径：

- 口径甲：验收看"是否只增不改"（新增允许，改动/删除禁止），需要一份逐项登记的清单；
- 口径乙：验收看"diff 为空"，那么"允许新增"这句话是假的，任何新增都要起草新的验收描述。

我倾向前者，因为它是你写进冻结声明的本意，而且它是"0 元补标签"的前提（`trace-schema.md` §1.4 正是用这个理由说服你现在补 #11/#12）。

### 6.2 冻结文件里的两处残留 —— **已知的已知**

1. `env/base.py:1-6` 的文档串写着"阶段 1 只有 LocalExecutor；**阶段 3 增加 DockerExecutor**"，而 DockerExecutor 已在阶段 2 落地（`env/docker.py`）。**冻结文件里的一句假话。** 修它要移基线。
2. `env/base.py:21-28` 的 `Executor` 契约**没有声明** `python_argv`。`harness/env/expand.py:24-25` 用 `getattr` + `[sys.executable]` 兜底——一个**新增的、忘记写 `python_argv` 的执行器**，在容器里会拿到**宿主解释器路径**，静默算错。`expand.py` 的注释承认了这是冻结的代价。

建议：若做一次基线移动，顺手把 (1) 的文档串改对；把 (2) 声明进契约（或至少加一条测试"每个 executor 都回答 python_argv"）。

---

## 7. 接口契约

### 7.1 Agent 拿不到 step 编号，但事件要求它填 —— **已知的已知**

- `ConversationState`（`messages.py:45-52`）只有 `task_id / description / workspace / messages`，**没有 step**。
- 而 `contract.py:81-82` 要求 `llm_request` / `llm_response` **必须**带 `step` 字段。
- `loop.py:79` 在调用 `next_action` 前把 `step` 自增；agent 只能在内部**自己复刻**这个计数（从 1 开始数调用次数）才能对上。

耦合的脆弱点：一旦某个 step 内发生重试并多发一条 `llm_request`，agent 的自计数与轨迹的 `step` 就错位，且**没有任何校验能发现**（`validate_records` 不检查 step 的合理性）。这条隐含契约不写在任何接口里。

### 7.2 Agent 无法表达基础设施失败 —— **已知的已知**

见 §5.1。返回类型只有三个，没有"我这边遇到了环境/网关问题"的表达。这是 `agent/base.py` 作为冻结接口最实际的缺口。

### 7.3 Tool 没有 schema / description —— **已知的已知**

`tools/base.py:10-14` 只有 `name` 与 `execute`。LLM 需要结构化的工具描述（名称、参数 JSON Schema、说明）才能发出可解析的调用。放哪里有两个选择：改冻结的 `base.py`（贵），或放一个非冻结模块 + 一条"每个注册工具都有 schema"的测试（便宜，防漂移）。**推荐后者**：工具的**实现**是可变的，而"模型看到的工具描述"是**观测的一部分**，它应该在非冻结侧被显式版本化（换一版措辞 = 换一个实验条件）。

### 7.4 `ToolOutcome.reason` 一字段三用 —— **已知的已知**

`messages.py:25`：它同时是 (a) 连击计数的分组键（等值比较）、(b) 报告里给人看的原因、(c) 未来要作为反馈文本回给模型的字符串。三种用途对格式的要求不同（键要稳定、人看要清楚、给模型要可操作），现在只满足 (a)。

### 7.5 Executor 的环境可见性在两个后端不同 —— **已知的已知（必修，与 A1 同源）**

- `local.py:40-44`：`child_env = dict(os.environ)` —— **继承宿主全部环境变量**，再叠加显式 `env`。
- `docker.py:76-77`：只把显式 `env` 作为 `-e` 传入，**不继承宿主环境**。

后果有二：

1. **`MONKEY_DEEPSEEK_KEY` 对被观测的 agent 可见**（local 后端）。agent 一句 `run_command(["python","-c","import os;print(os.environ)"])` 就把 key 写进 `tool_result.stdout` → 落进 `trace.jsonl`、`blobs/`、`report.md`。这**直接击穿**你要求的"断言 key 不出现在这些文件里"。
2. **跨后端行为差异**：同一个 agent 在 local 下能读到宿主环境、在 docker 下读不到。"agent 能不能发现环境里的东西"本身变成了随后端而变的实验条件。

**现在能不能修**：能，非冻结文件，低成本（`LocalExecutor` 默认剔除 `MONKEY_*` 前缀键，只有显式 `env` 传入的才放行）。**这是接 LLM 前必修项**：不修，你要求的 key 断言要么失败，要么变成假绿（见 §8.8）。

### 7.6 `python_argv` 的静默兜底 —— **已知的已知**

见 §6.2 第 2 条。`expand.py:25` 的 `[sys.executable]` 兜底在容器语境下是**静默错误**。

---

## 8. 测试

### 8.1 `test_failure_classes_are_12_and_unique` 会挡路 —— **已知的已知**

`tests/test_contract.py:43` 硬编码 `assertEqual(12, len(...))`。任何新增标签都会让它变红，而冻结声明**允许**新增标签。应改成 `>= 12` + 唯一性（或对快照比对，让"新增"走登记流程）。

### 8.2 `test_determinism.py` 的前提对随机模型不成立 —— **已知的已知（假绿陷阱）**

`test_determinism.py:59-82` 的前提是"同任务同 agent 重跑，抹掉时间戳后逐字段相等"。对确定性 scripted agent 成立，对随机 LLM 不成立。

**危险的做法**是把 `VOLATILE`（第 24 行）扩大到覆盖 `llm_*` 的全部内容——那样测试仍然绿，但它已经**什么都不检查**了。正确做法：把该测试的范围显式限定为**非 LLM agent**（改名/加 skip 条件），另立一条"同 prompt + 同归档响应 → 可比"的测试（比对的是**归档与派生物**，不是重新请求的结果）。

### 8.3 `test_truncate.py` 是假绿 —— **已知的已知（与 A3 同源）**

`test_truncate.py:15` 的 `OPTS = (threshold=100 字节, head=10 字符, tail=10 字符)`；测试数据最多 500 字符（`test_reconstruction_holds_across_many_sizes` 的 `range(0,500,7)`）。**永远不会进入"多字节重叠区"**（进入条件是 `总字符数 ≤ head+tail` 且 `字节数 > threshold`；head+tail=20 字符，而最小触发截断的数据也有 34 字符，永远满足 34 > 20）。

于是：重建性质（§2.3 的机械断言）**确实成立**——我实测 `reconstruct_ok=True` 在所有重叠场景下都成立；但该文件文档串宣称的**更强的性质**"只要它成立，观察者就不会被观测工具自身的截断引入偏差"——在重叠区是**假的**（见 A3）。**测试是绿的，它代表的观测有效性性质是红的。** 这正是"装大脑后会变成假绿"的样本。修法：补一组多字节、`总字符数 ≤ head+tail` 且 `字节数 > threshold` 的用例，并把 `elided_bytes >= 0`、`bytes_delivered <= bytes_total` 立成断言。

### 8.4 `validate_records` 的校验有洞 —— **已知的已知**

- `trace.py:161-173` 的流字段检查**只对 `tool_result`**；`verification` 的 `stdout_stream` / `stderr_stream` **完全不查**（不对称）。
- 对 `llm_*` 只查 `model` / `step`（`contract.py:81-82`）。而 `emit` 接受任意额外字段（`trace.py:115`）→ 一个拼错的 `usage_` 键**静默通过**校验。
- `reason` 完全不检查（§1.5）。

装 LLM 事件族**之前**扩展校验是低成本的：把 verification 的流字段纳入检查、为 `llm_response` 声明并检查关键字段、给 `reason` 加枚举。

### 8.5 `Phase1ConfigHashTest` 会在改配置时变红 —— **已知的已知**

`tests/test_backcompat.py` 的阶段 1 配置哈希 pin。这是**好的守卫**，但意味着不能用往 `default.toml` 加字段的方式来配 LLM → 用新配置文件（§4.3）。

### 8.6 `test_cost_budget.py` 的"恰好等于上限"用例 —— **已知的已知（温和）**

浮点成本下"恰好等于上限"在生产几乎不可达。该用例测的是**算子边界**（`>` 而非 `>=`），不是生产场景。保留，但报告里若引用它作为"上限不会误伤"的证据，是**过度解读**。

### 8.7 `test_no_pollution.py` 是好的守卫 —— **已知的已知（注意）**

`test_no_pollution.py:23` 监视 `harness/ configs/ tasks/` 的哈希。若 LLM 客户端把响应缓存写进 `harness/llm/` 下，这条测试会红——**这是正确的行为**（缓存放 `runs/` 或 `tmp/` 下）。接客户端时不要为了让它变绿而收窄 `WATCHED`。

### 8.8 你要求的"key 不出现"断言目前是假绿 —— **已知的已知（必修）**

你要求的断言（key 不出现在 `trace.jsonl` / `meta.json` / `report.md` / `blobs/**`）在当前 `LocalExecutor` 环境下，**只要被测 agent 不主动打印环境变量就会通过**——它测的是"我们自己的代码不泄露 key"，而真正的泄露通道是"被观测的 agent 主动读宿主环境"（§7.5）。测试绿，通道开着。

必须先修 §7.5（对子进程隐藏宿主环境），这条断言才有意义；并且要补一条**负向测试**：让一个假 agent 主动 `printenv` / `os.environ`，断言 key **仍然**拿不到。

---

## 9. 未知的未知（装大脑后靠什么信号发现）

| # | 未知项 | 发现信号 |
|---|---|---|
| 1 | 真实 usage 的组成（hit/miss 是否含在 `prompt_tokens` 内、是否有 reasoning token 另计） | 第一条真实 `llm_response` 的 usage 字段与单价表对账，金额对不上 |
| 2 | 响应里是否有 `system_fingerprint` | 归档的第一条响应里有没有这个键。**没有**则浮动模型名下无法区分版本，"靠归档保证可复现"必须降级为"靠归档 + 接受版本漂移" |
| 3 | 端点细节（是否强制 `/v1` 前缀、是否需流式、鉴权头格式） | 第一次请求的 400 / 404 / 401 |
| 4 | 模型的 tool-call 风格（原生 function calling vs 文本里的 JSON） | 解析失败率；决定 Agent 侧要不要做容错解析 |
| 5 | **观测工具自身引入的偏差**：截断（A3）、截断标记文本、工具 schema 的措辞、系统提示词 | 同一任务在不同 `head_chars`/`tail_chars` 下行为不同 → 需要一组"观测设置扰动"对照实验 |
| 6 | 一次 `next_action` 内的 HTTP 重试是否被记录 | 轨迹里 `llm_request` 条数 < 客户端日志里的 HTTP 次数 → token 与成本归属错位 |
| 7 | 并发安全：`UsageLedger` 无锁 | 若将来并发跑，累加值系统性小于单据 |
| 8 | 上下文超长错误是否可恢复（裁剪历史后重试） | agent 卡在同一个 400 上打转（表现为连续相同 `reason`） |
| 9 | 高峰判定在真实账单上的印证（§2.5 的边界） | 用一两笔真实调用与账单核对，反推边界口径 |

---

## 10. 需要你裁决（阻塞下一步）

1. **`cost_usd` 的单位**（§1.1）：改语义（违反冻结）／改字段名（移基线）／保留 `usd` 名但声明单位是 CNY 并在成本负载里加 `currency` 键（不动 `totals`）——选哪个？
2. **高峰边界**（§2.5）：端点开闭、节假日归属、用哪个时刻定价（请求发起 vs 响应结束）？
3. **是否接受"为了 LLM 失败标签，再做一次（且仅一次）合并基线移动"**（§5.5、§6）：现在做，还是接受"用 `error` 事件的 `sub_reason` 降级表达"（代价：轨迹里再也分不清网关问题与我们的 bug）？
4. **验收口径**（§6.1）："只增不改"还是"diff 为空"？两者对"新增标签"的处理相反。
5. **是否允许引入第三方依赖**：项目至今**零第三方依赖**（已确认 `.venv` 里没有 httpx / openai / requests / urllib3 / certifi）。接 LLM 有三条路——`httpx`/`openai`（要引入依赖清单 + 网络访问）、stdlib `urllib`（零依赖但要自己处理超时/重试/TLS）、或 stdlib + 注入 transport 缝（可测）。**顺带**：`MONKEY_DEEPSEEK_KEY` 在当前 shell 里读不到（我只查了长度、从未打印值），所以真实的端点探针（token > 0）现在无法进行——需要你确认注入方式。

---

## 附：本次审计的证据与可复现命令

**A3 多字节截断（实测输出，阈值 8192 字节、head/tail 各 3000 字符）：**

```
chars= 2000 total=  6000 delivered=  6000 elided=      0 trunc=False delivered>total=False elided<0=False reconstruct_ok=True
chars= 2731 total=  8193 delivered= 16417 elided=  -8193 trunc=True  delivered>total=True  elided<0=True  reconstruct_ok=True
chars= 3000 total=  9000 delivered= 18031 elided=  -9000 trunc=True  delivered>total=True  elided<0=True  reconstruct_ok=True
chars= 4000 total= 12000 delivered= 18031 elided=  -6000 trunc=True  delivered>total=True  elided<0=True  reconstruct_ok=True
chars= 6000 total= 18000 delivered= 18027 elided=      0 trunc=True  delivered>total=True  elided<0=False reconstruct_ok=True
chars= 7000 total= 21000 delivered= 18030 elided=   3000 trunc=True  delivered>total=False elided<0=False reconstruct_ok=True
```

复现：默认配置下对 N 个 CJK 字符调用 `harness.trace.prepare_stream`，打印 `bytes_total / bytes_delivered / elided_bytes / truncated / reconstruct` 是否与交付文本逐字节一致。**注意**：`reconstruct_ok` 全为 `True`——机械的重建性质成立了，被破坏的是"截断确实在截断"这个语义性质（交付量 > 原始量，`elided_bytes` 为负，agent 读到负数标记）。

**其它：**

- `python -m unittest discover -s tests -t .`（当前 93 项通过，给后续对照的基线）
- `git diff b6f983f --stat`（当前应只有 5 个非冻结文件的改动）
- 全文的时区/币种/精度声明检索：确认项目内无 `zoneinfo`/`pytz` 使用、无任何 `currency` 字段、`pricing.py:10` 的注释写死"美元"

---

## 附：本次审计**未**覆盖

- 真实的端点行为（无法进行，key 在本 shell 不可见）
- 模型的 prompt 工程质量（系统提示词怎么写、工具描述怎么措辞）——那是接上大脑之后的**实验**议题，不是本次结构性审计的范围
- 并发/多 run 并行执行（当前架构是单 run 串行）
