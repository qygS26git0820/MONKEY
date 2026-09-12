# 阶段 1 设计文档：骨架跑通（无 LLM，假 agent）

- 状态：**待你评审**，未写任何代码
- 输入依据：`docs/env-report.md`（阶段 0 审计）
- 硬约束（你指定）：阶段 1 的假 agent 必须是可替换接口；阶段 2 接入真实 LLM 时**不得修改主循环**
- 你已确认的设计前提：被观测对象 = 自研；观察目标 = 完整消息与工具调用序列 + token/成本/耗时 + 失败模式分类；JSONL + 文本报告，回放到终端级别；阶段 1-2 用自造封闭小任务（纯 Python、无网络）

---

## 1. 阶段 1 的目标与边界

**目标**：在完全没有 LLM 的前提下，用确定性的假 agent 把整条管线跑通——任务加载 → 隔离工作区 → 工具分发 → 主循环 → 轨迹落盘 → 外部验证 → 文本报告 → 终端回放。所有"以后要改会痛"的接缝在这一阶段定型。

**明确不做**（控制范围）：
- 不接 LLM、不联网、不装任何第三方包
- 不用容器（阶段 3 才做），执行后端用宿主子进程
- 不做可视化、不做并发、不做重试
- 不引入真实仓库（阶段 3 之后）

**一个刻意选择的性质：阶段 1 零第三方依赖，只用标准库。** 任务验证用 `unittest` 而不是 `pytest`，因此**不需要 `pip install`、不需要网络、不需要下载任何东西**。解释器用 uv 已管理的 CPython 3.12.13（本地已存在，建 venv 也无需联网）。代价是任务写法不如 pytest 顺手——这个代价我建议接受，理由是第一版骨架应该"绝对跑得起来"，而不是"顺手"。

---

## 2. 目录与产物布局

代码侧（纳入 git）：

```
harness/
  __main__.py         CLI 入口：run / replay / validate-trace
  paths.py            唯一的路径解析来源（见 §4）
  config.py           配置加载（configs/*.toml，标准库 tomllib）
  runctx.py           RunContext：run_id、目录创建、trace 写入器、blob 存储
  trace.py            轨迹事件定义 + schema 版本 + JSONL 追加写入
  core/
    messages.py       中立消息类型（与任何 LLM SDK 无关）
    loop.py           主循环（**冻结文件**）
  agent/
    base.py           Agent 接口（**冻结文件**）
    scripted.py       阶段 1 的确定性假 agent
  tools/
    base.py           Tool 契约（**冻结文件**）
    registry.py       工具注册与分发
    fs_read.py        读文件
    fs_write.py       写文件
    run_shell.py      执行命令
    run_tests.py      执行任务定义的验证命令
  env/
    base.py           Executor 契约（**冻结文件**）
    local.py          宿主子进程执行器（阶段 3 加 docker.py，不改 base）
  tasks/loader.py     加载 tasks/<id>/task.json
  eval/
    runner.py         跑验证命令、解析结果
    metrics.py        从 trace 派生耗时/步骤/token/成本统计
  report/text_report.py  从 trace.jsonl 生成 report.md
configs/
  default.toml        路径、预算、执行器选择、trace 选项
tasks/
  toy-001/            task.json + repo/ + faulty.patch
  toy-002/ ...
docs/                 设计与审计文档
tests/                harness 自身的测试（不是被测任务的测试）
```

运行产物（`.gitignore` 覆盖：`runs/ tmp/ workspace/ .venv/ images/`）：

```
runs/<run_id>/
  meta.json           配置哈希、harness git sha、Python 版本、任务、执行器、时间
  trace.jsonl         轨迹（追加写，逐行 flush）
  blobs/<sha256>.blob 超长 stdout/stderr 的完整副本
  workspace/          本次运行的目标仓库副本（被 agent 改动的地方）
  verification/       验证命令的原始 stdout/stderr
  report.md           文本报告
```

`run_id` 形如 `20260912-131500-toy-001-scripted`——可按时间排序，一眼看得出任务与 agent。

---

## 3. 三段式交付与你如何验证（阶段 1 总览）

| 交付物 | 内容 | 你的最小验证 |
|---|---|---|
| D1 可运行骨架 | `harness` 能在零依赖 venv 里跑完一个任务 | 你在自己的终端跑一次，看退出码 0 且 `runs/<id>/` 生成 |
| D2 完整轨迹 | `trace.jsonl` + `meta.json` + `report.md` + 验证原始输出 | 逐行读 trace，与 `report.md` 对照是否一致；打开 `verification/` 看原始测试输出 |
| D3 schema 校验 | `validate-trace` 能校验轨迹合法性 | 手工改坏 trace 一行，校验器必须报错（负向对照） |
| D4 确定性复现 | 同任务同 agent 重跑，去除时间戳后轨迹逐字节一致 | 你自己跑两次并 diff |
| D5 三个负向对照 | 错误补丁 → `verification_failed`；工具报错 → 记录不崩溃；注入 harness 异常 → `run_end` 仍写出 | 逐个跑，对照报告里的 failure_class |
| D6 无污染自证 | 跑完后 `harness/ configs/ tasks/` 哈希清单与运行前一致 | 我在报告里贴首尾哈希，你抽验 |
| D7 终端回放 | `replay` 把轨迹打印成人可读序列 | 你跑一次 replay，看是否与 trace 对应 |

---

## 4. 路径隔离：用机制而不是纪律保证"产物不污染代码"

阶段 0 已经建立了"首尾哈希比对"的手法，阶段 1 把它制度化：

1. **唯一路径来源**：所有路径由 `paths.py` 计算，其他模块**禁止**出现相对路径或 `os.getcwd()`。
2. **越界即抛错**：任何要写入的路径在解析时断言其位于 `D:\SWE Agent` 之下，否则直接异常。这条同时防止"跑到项目外去建文件"。
3. **RunContext 独占写权限**：只有 `RunContext` 能创建运行目录。`run_id` 已存在时**拒绝覆盖**（不静默覆盖上一次的结果）。
4. **哈希自证测试**：`tests/` 里有一个测试，跑完一个完整任务后，比对 `harness/ configs/ tasks/` 的文件哈希清单与运行前一致。
5. **被测仓库永远不在原地改**：`runs/<id>/workspace/` 是任务仓库的副本，agent 只碰副本。任务模板 `tasks/toy-001/repo/` 保持不变。

---

## 5. 硬约束的落点：Agent 接口与主循环

这是本阶段最需要你过目的部分，因为你指定的硬约束（阶段 2 不动主循环）成败全在这里。

### 5.1 接口形状必须是"状态驱动"，不能是"计划生成器"

一个看似自然但会**导致阶段 2 重写主循环**的设计是：让假 agent 一次性返回整串动作，主循环顺序执行。这样阶段 2 接了 LLM 就必须改成"每步把工具结果喂回模型再问下一步"——主循环被推翻。

因此接口定为**状态驱动**：Agent 只有**一个**方法，接收当前对话状态，返回**一个**动作。主循环每次执行完工具后把结果追加进状态，再问下一次。假 agent 内部忽略状态、按步号吐脚本；真 LLM agent 读状态构造提示词。**同一个主循环，两者无差别。**

### 5.2 动作是一个三选一的联合

| 动作变体 | 载荷 | 主循环行为 |
|---|---|---|
| `ToolCalls` | 一组工具调用（**支持一次多个**，为 LLM 的并行工具调用预留） | 逐个执行，结果追加进状态 |
| `Finish` | 结束说明 | 跳出循环，进入验证阶段 |
| `Abort` | 放弃原因 | 跳出循环，标记对应 failure_class |

### 5.3 主循环的不变量

- 主循环**不按名字 import** 任何具体 agent 或具体工具，只依赖注入的 Agent 与工具注册表。这是"可替换"的机械保证。
- 任何**工具**抛出的异常都被转成 `tool_result(status=error)` 记入轨迹，**永不**让一次工具失败炸掉整个 run。
- 任何 **harness 自身**的异常被记成 `error` 事件，且 `run_end` 通过 `finally` **保证写出**——即使中途崩溃，轨迹也是完整可读的。观察失败行为正是本平台的核心用途。
- 预算全部来自配置：`max_steps`、`wall_timeout`、`per_tool_timeout`、`max_stdout_bytes`。触发即结束并打上对应 failure_class。

### 5.4 冻结清单与它的验收方式

**冻结**（阶段 2 不得修改，只允许纯增量）：`core/loop.py`、`agent/base.py`、`tools/base.py`、`env/base.py`，以及 `trace.py` 的事件名与字段（只增不改不删）。
**阶段 2 允许新增**：`agent/llm.py`、`llm/client.py`、若干真实工具、配置项。

**验收方式（把软要求变成硬证据）**：阶段 2 结束时，对冻结清单内文件做 `git diff`，**必须为空**。这条我会在阶段 2 的交付里主动执行并贴出结果给你核对。

---

## 6. 轨迹 schema（最难事后更改的决策，故在此定型）

格式：JSONL，一行一个事件，追加写、**逐行 flush**。每行公共字段：`schema_version`、`run_id`、`seq`（单调递增）、`ts_mono`（单调时钟，用于算时长）、`ts_wall`（墙上时钟，用于跨日志对齐）、`type`、`step`。

| 事件 | 关键字段 | 阶段 1 是否产生 |
|---|---|---|
| `run_start` | 任务、agent 名、配置哈希、harness git sha、Python 版本、执行器、时间 | 是 |
| `agent_message` | role、content（假 agent 的说明文本） | 是 |
| `llm_request` | model、messages 摘要、请求参数 | 否（阶段 2） |
| `llm_response` | model、content、tool_calls、**usage{input/output/cache_read/cache_creation tokens}**、latency_ms、stop_reason、**cost_usd_estimate** | 否（阶段 2） |
| `tool_call` | call_id、tool、args、cwd（**执行器可见路径**）、executor | 是 |
| `tool_result` | call_id、status、exit_code、duration_ms、stdout/stderr 摘要、**stdout_bytes/stdout_truncated**、blob 引用、artifacts | 是 |
| `step_end` | step、duration_ms | 是 |
| `verification` | 命令、exit_code、status、duration_ms、解析出的用例数 | 是 |
| `error` | 位置、异常类型、message、traceback 尾部 | 是 |
| `run_end` | status、steps、总时长、**token/成本汇总**、**failure_class** | 是 |

三条设计要点：

1. **token 与成本的字段从第一天就在**，阶段 1 填 `null`。这正是你要的"避免二次迁移历史数据"——阶段 2 只需开始填值，不需要改 schema、不需要重写已有轨迹的分析代码。
2. **失败分类枚举现在就定死**：`none / agent_loop_limit / agent_gave_up / tool_error_repeated / verification_failed / timeout_wall / timeout_step / policy_denied / env_error / harness_error`。阶段 1 会真实走通其中 `verification_failed`、`harness_error`、`tool_error_repeated` 三种（对应 D5 的三个负向对照）。枚举只增不改，后面的分析脚本因此稳定。
3. **大载荷不外联**：stdout/stderr 超过阈值（默认 8KB）时，轨迹里只存头部摘要 + `truncated: true` + 完整内容的 sha256 与 byte 数，完整内容放 `blobs/`。理由：真实仓库的测试输出会轻易撑爆轨迹，既毁可读性也推高阶段 2 的 token 成本；而且"截断了多少"本身就是要观察的数据。

---

## 7. Executor 抽象（阶段 3 的接缝，现在只留最小钩子）

`Executor` 契约只有一件事：接收命令、工作目录、超时、环境变量，返回 `{exit_code, stdout, stderr, duration, timed_out}`。

- 阶段 1 实现 `LocalExecutor`（宿主子进程）。
- 阶段 3 加 `DockerExecutor`，实现同一契约，`env/base.py` 不改。
- 为此现在引入**一个**小概念：`host_to_visible(path)`——把宿主路径映射成"执行器可见路径"，写进 `tool_call.cwd`。阶段 1 恒等映射；阶段 3 变成"宿主路径 → 容器内路径"。这一个方法避免阶段 3 时改动工具层签名。

**一处我建议调整顺序，需要你拍板**：阶段 2 是真实 LLM 在**宿主**上执行 shell，破坏面从"我自己的假 agent"变成"模型决定跑什么"。我建议把容器后端从阶段 3 **提前到阶段 2 开头**（阶段 0 已证明 Docker 可用，成本很低），让模型从第一次运行起就在容器里。若你希望严格保持原阶段划分，替代方案是阶段 2 在宿主执行但加命令策略层（白名单/拒用列表）+ 工作区限定，我会明确告知这仍是**运维隔离而非安全边界**。见 §11 待决项。

---

## 8. 封闭小任务的设计

`tasks/<task_id>/task.json` 字段：`id`、`description`（当作 issue 文本喂给 agent）、`repo`（本地目录）、`verify`（命令 + 解析规则 + 工作目录）、`faulty_patch`（**负向对照专用**）。

要点：

- **验证由 harness 执行，不由 agent 决定**，agent 无法选择"用哪条命令证明自己对了"。
- **通过/失败以外在证据判定**：验证命令的退出码 + 从输出解析出的用例计数，**不看** agent 自己的说法。
- **每个任务自带 `faulty.patch`**：一个必然让测试失败的补丁。harness 必须对它报 `verification_failed`。这把你在阶段 0 认可的"负向对照"纪律固化进任务格式——每个任务天然自带一个"必须判错"的样本。
- 任务仓库是纯标准库的 Python 小包（`unittest` 可跑），bug 是人为植入的一行错。
- 阶段 1 至少两个任务：`toy-001`（明显的单行逻辑错）+ `toy-002`（需要读两个文件才能定位的错），后者用于验证"多步 + 多工具"路径而不只是最短路径。

### 8.1 三种假 agent（三份负向对照的载体）

| 假 agent | 行为 | 期望结果 |
|---|---|---|
| `scripted_ok` | 读文件 → 正确修改 → 跑测试 → Finish | `run_end.status=completed`，`failure_class=none`，验证通过 |
| `scripted_bad_edit` | 读文件 → **错误**修改 → 跑测试 → Finish | `failure_class=verification_failed` |
| `scripted_tool_error` | 连续对一个不可写路径执行写操作 | 工具错误被记录，达到阈值后 `failure_class=tool_error_repeated`，run 不崩溃 |

三者确定性、无随机、无网络。**确定性是阶段 1 的核心可验证性质**：同任务同 agent 重跑，去掉时间戳后轨迹应逐字节一致。为此轨迹里**不记录绝对路径**（只记项目相对路径与 run 相对路径），子进程设 `PYTHONHASHSEED=0`。

---

## 9. 文本报告与终端回放

- `report.md` **由 `trace.jsonl` 派生**，不读内存状态。这样报告与原始记录天然一致，不可能出现"报告说成功、轨迹里有错"。
- 报告内容：任务与配置摘要、最终状态与 failure_class、步骤时间线表（步号/工具/状态/耗时/退出码）、token 与成本（阶段 1 为 null，字段已在）、验证结果与原始输出引用、产物清单、**以及"如何复现本次 run"的一行命令**。
- `replay`：读 trace.jsonl，把工具调用与结果打印成终端可读序列（截断长输出，指向 blob）。这就是你要的"回放到终端级别"的第一版。

---

## 10. 阶段 1 的具体风险与规避

| 风险 | 规避 | 依据 |
|---|---|---|
| **Windows 子进程编码**：宿主任一命令输出按本地代码页（GBK）解码会乱码 | 所有 `subprocess` 显式 `encoding="utf-8", errors="replace"` | 阶段 0 亲眼见到 GBK 乱码（`raw/01`、`raw/05b`），这不是假想风险 |
| **路径含空格**（`D:\SWE Agent`）导致命令拼接出错 | 一律 `shell=False` + 参数列表，**禁止** `shell=True` 拼接路径；顺带消除命令注入 | 阶段 0 §2 已识别 |
| **`python` 是 Store 占位程序**（exit 49） | 所有解释器调用走 `sys.executable` 或 venv 绝对路径，禁止裸 `python` | `raw/02` |
| 超时后子进程树未清理（Windows 上 `kill()` 可能留子进程） | 阶段 1 任务都是单进程，风险低；记为**已知限制**，阶段 3 容器化后自然消解 | — |
| 轨迹写入被缓冲，崩溃后无轨迹 | 逐行 flush；`run_end` 写在 `finally` | — |
| 非确定性（字典序、时间戳、哈希种子） | 轨迹不记绝对路径、子进程 `PYTHONHASHSEED=0`、比对时归一化时间戳与 run_id | — |

---

## 11. 待你拍板的四点

1. **是否同意把容器后端从阶段 3 提前到阶段 2 开头？**（理由：阶段 2 是真实 LLM 在宿主执行 shell，是破坏面第一次实质化。）不同意的话我会在阶段 2 加命令策略层，但会明确标注它只是运维隔离。
2. **是否接受把"冻结清单 `git diff` 为空"作为阶段 2 的正式验收条件？** 这把你指定的硬约束变成可证伪的证据。
3. **阶段 1 用标准库 `unittest` 而非 `pytest`**（换取零依赖、零网络、绝对可复现）——是否接受？
4. **失败分类枚举**（§6 第 2 点列出的 10 个标签）现在定死，是否认可？后续只增不改。

---

## 12. 阶段 1 完成后的样子

一条命令在零依赖 venv 里跑完，产出 `runs/<id>/`：可逐行阅读的 `trace.jsonl`、与之一致的 `report.md`、被修改过的工作区副本、验证命令的原始输出、以及一个明确写在 `run_end.failure_class` 里的结论。三个负向对照各自的失败分类正确。重跑两次轨迹逐字节一致。`replay` 能在终端把这次运行演一遍。

到这一步，"管线是否可信"就被证明了；阶段 2 只是把一个真 LLM 装进已经验证过的 `Agent` 接口。
