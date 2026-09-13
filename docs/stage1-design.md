# 阶段 1 设计文档：骨架跑通（无 LLM，假 agent）

- 状态：**已实现**（阶段 1 完成）。本文档已按实装回填，变更记录见 §13
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
  contract.py         冻结的契约常量：事件名、必需字段、标签集、判定顺序（**冻结文件**，见 §5.4）
  config.py           配置加载（configs/*.toml，标准库 tomllib）
  clock.py            统一时钟：perf_counter 算时长，time.time 对齐墙上时钟
  runctx.py           RunContext：run_id、目录创建、trace 写入器、blob 存储
  trace.py            轨迹写入、head+tail 截断与精确重建、schema 校验
  core/
    messages.py       中立消息类型（与任何 LLM SDK 无关）
    loop.py           主循环（**冻结文件**）
  agent/
    base.py           Agent 接口（**冻结文件**）
    scripted.py       阶段 1 的确定性假 agent（6 种，见 §8.1）
  tools/
    base.py           Tool 契约（**冻结文件**）
    context.py        ToolContext：注入工作区、执行器、配置、任务
    policy.py         工作区路径策略：越界即拒
    registry.py       工具注册与分发
    fs_tools.py       读文件 / 写文件
    shell_tools.py    执行命令 / 执行任务定义的验证命令
  env/
    base.py           Executor 契约（**冻结文件**）
    local.py          宿主子进程执行器（阶段 3 加 docker.py，不改 base）
  tasks/loader.py     加载 tasks/<id>/task.json
  eval/runner.py      跑验证命令、从输出解析 unittest 用例计数
  report/text_report.py  从 trace.jsonl 生成 report.md
configs/
  default.toml        预算、执行器选择、trace 截断选项
tasks/
  toy-001/            task.json + repo/ + repo_faulty/（负向对照，见 §8）
  toy-002/            task.json + repo/
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
| D1 可运行骨架 | `harness` 能在零依赖 venv 里跑完一个任务 | 你在自己的终端跑一次，看退出码 0（即 `failure_class=none`）且 `runs/<id>/` 生成 |
| D2 完整轨迹 | `trace.jsonl` + `meta.json` + `report.md` + 验证原始输出 | 逐行读 trace，与 `report.md` 对照是否一致；打开 `verification/` 看原始测试输出 |
| D3 schema 校验 | `validate-trace` 能校验轨迹合法性 | 手工改坏 trace 一行，校验器必须报错（负向对照） |
| D4 确定性复现 | 同任务同 agent 重跑，**归一化时间戳与子进程自报耗时后动作序列一致**（详见 §8.1 的抖动说明） | 你自己跑两次，按 `tests/test_determinism.py` 的归一化规则 diff |
| D5 负向对照 | 共 **8 组脚本化对照**（含三份负向对照）：错误补丁 → `verification_failed`；错误仓库副本 → `verification_failed`；工具连错 → `tool_error_repeated` 且 run 不崩溃；越界写 → `policy_denied`；放弃 → `agent_gave_up`；死循环 → `agent_loop_limit` | 逐个跑，对照报告里的 failure_class；`tests/test_scripted_controls.py` 把 8 条等式一次断言 |
| D6 无污染自证 | 跑完后 `harness/ configs/ tasks/` 哈希清单与运行前一致 | 我在报告里贴首尾哈希，你抽验 |
| D7 终端回放 | `replay` 把轨迹打印成人可读序列 | 你跑一次 replay，看是否与 trace 对应 |

---

## 4. 路径隔离：用机制而不是纪律保证"产物不污染代码"

阶段 0 已经建立了"首尾哈希比对"的手法，阶段 1 把它制度化：

1. **唯一路径来源**：所有路径由 `paths.py` 计算，其他模块**禁止**出现相对路径或 `os.getcwd()`。
2. **越界即抛错**：任何要写入的路径在解析时断言其位于 `D:\SWE Agent` 之下，否则直接异常。这条同时防止"跑到项目外去建文件"。
3. **RunContext 独占写权限**：只有 `RunContext` 能创建运行目录。`run_id` 已存在时**拒绝覆盖**（不静默覆盖上一次的结果）。
4. **哈希自证测试**：`tests/test_no_pollution.py`。跑完若干任务后，比对 `harness/ configs/ tasks/` 的文件哈希清单与运行前逐条一致（`__pycache__` 除外）。
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
- 任何 **harness 自身**的异常被记成 `error` 事件；`run_end` 在每个异常分支处理完之后**无条件写出**，因此即使中途出错，轨迹也是完整可读的。观察失败行为正是本平台的核心用途。
  实现的机制是 `except KeyboardInterrupt` + `except Exception` 两个分支穷尽后再落 `run_end`，**不是 `finally`**。二者对 `Exception` 与 `KeyboardInterrupt` 等价，但 `SystemExit`/`GeneratorExit` 这类 `BaseException` 不在覆盖范围内——这是已知残差，记在 §10 风险表。
- 预算全部来自配置 `configs/default.toml`：`max_steps`、`wall_timeout_s`、`step_timeout_s`、`per_tool_timeout_s`、`verify_timeout_s`、`max_tool_error_streak`、`max_denied_calls`；截断选项 `truncate_threshold_bytes`、`head_chars`、`tail_chars`。触发即结束并打上对应 failure_class。（不变量校验见 `harness/config.py`。）

### 5.4 冻结清单与它的验收方式

**冻结**（阶段 2 不得修改，只允许纯增量）：

| 冻结文件 | 冻的是什么 |
|---|---|
| `harness/contract.py` | **事件名、每类事件的必需字段、12 个标签、判定顺序、截断字段名与策略名** |
| `harness/core/loop.py` | 主循环 |
| `harness/agent/base.py` | Agent 接口 |
| `harness/tools/base.py` | Tool 契约 |
| `harness/env/base.py` | Executor 契约 |

`harness/contract.py` 是上表里**最要紧的一个**：事件名与字段原先散在 `trace.py`，现在集中到该文件，成为唯一的机器可读定义源。没有它列入清单，验收会漏掉真正的真源。

**阶段 2 允许新增**：`agent/llm.py`、`llm/client.py`、若干真实工具、配置项。

**验收方式（把软要求变成硬证据）**：阶段 2 结束时，对**上表五个文件**做 `git diff`，**必须为空**。这条我会在阶段 2 的交付里主动执行并贴出结果给你核对。

#### 变更记录 1：冻结基线移动（2026-09-13）

**基线从 `3342dcf` 移到"登记本节的那个提交"，其主题为** `阶段 2：移动冻结基线（loop.py 的 token/成本读写接口定稿）`。
SHA 用 `git log --format=%H -1 --grep="移动冻结基线"` 解析——本节无法引用自己的 SHA，故留命令而非占位符。

- **原因**：`harness/core/loop.py` 注定要长功能，而它被冻了。阶段 2 必须让它（a）把 `run_end.totals` 的三个 `None` 换成真值，（b）在累计用量越过预算时以 `cost_budget_exceeded` 终止（`trace-schema.md` §1.3 #12）。冻结一个必须长功能的文件是设计漏洞：现在补的代价是一次登记，进阶段 2 之后再补的代价是冻结机制本身的可信度。
- **范围**：**只有 `loop.py`**。`contract.py` 不动——`trace.py:116` 的 `emit` 只校验必需字段存在、`validate_records` 不拒绝未知字段，故给 `llm_request`/`llm_response` 加 `usage`/`latency_ms`/`stop_reason`/`cost_usd_estimate` 是零 schema 代价。`agent/base.py` 不动——累计量的读写都走注入的 `run_ctx.usage`，Agent 接口无需新增方法。`tools/base.py`、`env/base.py` 不动。
- **只移一次**：`loop.py` 对 token/成本的全部知识在这一次定稿（读取侧 + 两处检查的**调用点**），被调用的实现落在非冻结文件 `harness/core/usage.py` 等。若把调用点留到实现时再加，`loop.py` 会被改第二次、基线要移两次。
- **行为保持的证据**：`docs/evidence/stage2-baseline-move/`。8 组对照共 104 条事件，移动前后逐字段差异只有 `run_start.harness_git_sha`（构建来源字段，两批之间落了 `4e824e0`），抹掉它后零差异；`totals` 三个键在两批里都是 `None`。
- **此后的验收基准**：本表五个文件的 `git diff` 相对**新基线**为空。`3342dcf` 只用于历史核对，不再是验收基准。

三重机械保障，任一层被破坏都会立刻报警：
1. `tests/fixtures/contract_snapshot.json` —— 契约常量的黄金快照，`tests/test_contract.py` 逐字段比对；
2. `tests/fixtures/phase1-sample-trace.jsonl` —— 阶段 1 真实产出的轨迹，`tests/test_backcompat.py` 断言它永远合法；
3. `git diff` 空 —— 上面两条拦不住"改完顺手把快照也改了"，这一条拦得住。

`docs/trace-schema.md` 与本文档**不在** `git diff` 空清单里：它们是散文，阶段 2 若新增字段必然要改。对它们的约束是语义性的——冻结的是"已声明的字段名与语义不得改"，新增是允许的（见 `trace-schema.md` 第三部分）。

---

## 6. 轨迹 schema（最难事后更改的决策，故在此定型）

格式：JSONL，一行一个事件，追加写、**逐行 flush**。每行公共字段：`schema_version`、`run_id`、`seq`（单调递增）、`ts_mono`（单调时钟，用于算时长）、`ts_wall`（墙上时钟，用于跨日志对齐）、`type`、`step`。

**字段名的唯一权威是 `harness/contract.py`（`REQUIRED_FIELDS`）与 `trace-schema.md` §2.1，本表只给概要，出现分歧以那两处为准。**

| 事件 | 关键字段 | 阶段 1 是否产生 |
|---|---|---|
| `run_start` | task_id、agent、executor、config_hash、harness_git_sha、python_version、schema_version | 是 |
| `agent_message` | role、content（假 agent 的说明文本） | 是 |
| `llm_request` | 最少含 model、step | 否（阶段 2） |
| `llm_response` | 最少含 model、step；阶段 2 预期额外填 usage、latency_ms、stop_reason、cost_usd_estimate | 否（阶段 2） |
| `tool_call` | call_id、tool、args、cwd（**执行器可见路径**） | 是 |
| `tool_result` | call_id、tool、status、exit_code、duration_ms、reason、artifacts、stdout/stderr 文本，以及 **`stdout_stream` / `stderr_stream`** 两个截断元数据对象 | 是 |
| `step_end` | step、duration_ms | 是 |
| `verification` | name、command、cwd、exit_code、status、duration_ms、parsed（用例计数）、stdout/stderr 及其截断元数据 | 是 |
| `error` | where、exception_type、message、traceback 尾部 | 是 |
| `run_end` | status、failure_class、steps、duration_ms、totals（token/成本汇总，阶段 1 为 null）、verification_status | 是 |

两处需要点名，因为它们在早期草稿里写错过：

- **`executor` 不在 `tool_call` 里**，它在 `run_start`。一次 run 只有一个执行器，逐次调用重复记录没有意义。
- **截断长度不是平铺的 `stdout_bytes`/`stdout_truncated`，而是嵌套的 `stdout_stream`/`stderr_stream` 对象**（`bytes_total`/`bytes_delivered`/`elided_bytes`/`truncated`/`strategy`/`head_bytes`/`tail_bytes`/`marker_text`/`sha256_full`/`sha256_delivered`/`blob_ref`）。嵌套是刻意的：`stdout` 与 `stderr` 各自独立截断，平铺会立刻撞名。

三条设计要点：

1. **token 与成本的字段从第一天就在**，阶段 1 填 `null`。这正是你要的"避免二次迁移历史数据"——阶段 2 只需开始填值，不需要改 schema、不需要重写已有轨迹的分析代码。
2. **失败分类枚举现在就定死（12 个，语义见 `trace-schema.md` §1.3）**：`none / agent_loop_limit / agent_gave_up / tool_error_repeated / verification_failed / timeout_wall / timeout_step / policy_denied / env_error / harness_error / aborted_by_user / cost_budget_exceeded`。阶段 1 的测试真实走通了其中 **11 个**；唯一没走通的是 `cost_budget_exceeded`——阶段 1 无 LLM 即无 token，该标签在本阶段**结构上不可达**，不是遗漏。枚举只增不改，后面的分析脚本因此稳定。
3. **大载荷不外联 + head/tail 截断**：stdout/stderr **各自独立**截断；超过阈值（默认 8KB）时轨迹里只存**头部 + 尾部**加省略标记，完整内容按 sha256 存进 `blobs/`，并同时落盘截断前后的字节数。**只截头部是错的**——测试失败信息通常出现在输出末尾，只截头会把 agent 最需要的那段信号切掉，于是观测工具本身成了干扰变量。完整理由与字段表见 `trace-schema.md` §2.1/§2.2。

---

## 7. Executor 抽象（阶段 3 的接缝，现在只留最小钩子）

`Executor` 契约只有一件事：接收命令、工作目录、超时、环境变量，返回 `{exit_code, stdout, stderr, duration, timed_out}`。

- 阶段 1 实现 `LocalExecutor`（宿主子进程）。
- 阶段 3 加 `DockerExecutor`，实现同一契约，`env/base.py` 不改。
- 为此现在引入**一个**小概念：`host_to_visible(path)`——把宿主路径映射成"执行器可见路径"，写进 `tool_call.cwd`。阶段 1 恒等映射；阶段 3 变成"宿主路径 → 容器内路径"。这一个方法避免阶段 3 时改动工具层签名。

**一处我建议调整顺序，需要你拍板**：阶段 2 是真实 LLM 在**宿主**上执行 shell，破坏面从"我自己的假 agent"变成"模型决定跑什么"。我建议把容器后端从阶段 3 **提前到阶段 2 开头**（阶段 0 已证明 Docker 可用，成本很低），让模型从第一次运行起就在容器里。若你希望严格保持原阶段划分，替代方案是阶段 2 在宿主执行但加命令策略层（白名单/拒用列表）+ 工作区限定，我会明确告知这仍是**运维隔离而非安全边界**。见 §11 待决项。

---

## 8. 封闭小任务的设计

`tasks/<task_id>/task.json` 字段（**实际就这四个**，见 `harness/tasks/loader.py`）：`id`、`description`（当作 issue 文本喂给 agent）、`repo`（仓库副本目录名）、`verify`（`command` 参数列表 + `cwd`）。

要点：

- **验证由 harness 执行，不由 agent 决定**，agent 无法选择"用哪条命令证明自己对了"。
- **通过/失败以外在证据判定**：验证命令的退出码 + 从输出解析出的用例计数，**不看** agent 自己的说法。
- **负向对照是仓库副本目录，不是补丁文件**：`tasks/<id>/repo_faulty/` 与 `repo/` 并列，用 `--variant repo_faulty` 选用。早期草稿写的是 `task.json` 里的 `faulty_patch` 字段——那会要求 harness 实现补丁应用逻辑；而"多一份必然失败的仓库副本"用目录就够，且不必在任务格式里引入 diff 解析。harness 对 `repo_faulty` 必须报 `verification_failed`。这把阶段 0 认可的"负向对照"纪律固化进任务布局。
- 任务仓库是纯标准库的 Python 小包（`unittest` 可跑），bug 是人为植入的一行错。
- 阶段 1 有两个任务：`toy-001`（明显的单行逻辑错）+ `toy-002`（需要读两个文件才能定位的错），后者用于验证"多步 + 多工具"路径而不只是最短路径。

### 8.1 六个假 agent（负向对照的载体）

| 假 agent | 行为 | 期望结果 |
|---|---|---|
| `scripted_ok` | 读文件 → 正确修改 → 跑测试 → Finish | `run_end.status=completed`，`failure_class=none`，验证通过 |
| `scripted_bad_edit` | 读文件 → **错误**修改 → 跑测试 → Finish | `failure_class=verification_failed` |
| `scripted_tool_error` | 连续读一个不存在的文件 | 同签名的工具错误连续达到阈值 → `failure_class=tool_error_repeated`，run 不崩溃 |
| `scripted_denied` | 连续向 `../escape.txt` 写 | 越界被策略拒绝，累计达 `max_denied_calls` → `failure_class=policy_denied` |
| `scripted_gave_up` | 立即 `Abort` | `failure_class=agent_gave_up` |
| `scripted_loop_limit` | 无限重复读同一文件、永不 `Finish` | 步数达 `max_steps` → `failure_class=agent_loop_limit` |

六者确定性、无随机、无网络。

**确定性是阶段 1 的核心可验证性质，但它的准确表述是"动作序列一致"，不是"轨迹逐字节一致"。** 同任务同 agent 重跑，归一化下述两类抖动后，事件序列必须逐步相同：

1. 验证子进程**自报**的 unittest 运行时长（`Ran 2 tests in 0.000s` 里的数字）及其派生的 sha256；
2. 失败用例回溯里嵌的**工作区绝对路径**——而工作区路径含 `run_id`，因此每次 run 都不同。

第 2 条不是测试的局限，是被观测的现实，而且它在阶段 2/3 会变：换成容器后端后同一段输出变成 `/workspace/...`，**agent 看到的自身失败信息会随后端而变**。这是跨后端可比性的已知混杂项，已在 `tests/test_determinism.py` 里钉成断言而非注释。

归一化规则见 `tests/test_determinism.py` 的 `_project()`。轨迹里**字段值仍不记绝对路径**（`tool_call.cwd` 是执行器可见路径），子进程设 `PYTHONHASHSEED=0`。

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
| 轨迹写入被缓冲，崩溃后无轨迹 | 逐行 flush；`run_end` 在每个异常分支处理之后无条件写出 | 机制是 `except KeyboardInterrupt` + `except Exception` 穷尽后落盘，**不是 `finally`**；`BaseException`（如 `SystemExit`）会漏掉 `run_end` 与 `close()`。**已知残差，本阶段未修**（阶段 2 若需要，在 `loop.py` 外层补 `finally` 即可） |
| 非确定性（字典序、时间戳、哈希种子） | 字段值不记绝对路径、子进程 `PYTHONHASHSEED=0`、比对时归一化时间戳 / run_id / 子进程自报耗时与其 sha | **"逐字节一致"不成立**：失败用例的回溯里含工作区绝对路径，由 unittest 自报，无法从源头消除。可保的性质是"动作序列一致"，见 §8.1 |

---

## 11. 待你拍板的四点

1. **是否同意把容器后端从阶段 3 提前到阶段 2 开头？**（理由：阶段 2 是真实 LLM 在宿主执行 shell，是破坏面第一次实质化。）不同意的话我会在阶段 2 加命令策略层，但会明确标注它只是运维隔离。
2. **是否接受把"冻结清单 `git diff` 为空"作为阶段 2 的正式验收条件？** 这把你指定的硬约束变成可证伪的证据。
3. **阶段 1 用标准库 `unittest` 而非 `pytest`**（换取零依赖、零网络、绝对可复现）——是否接受？
4. **失败分类枚举**（§6 第 2 点列出的 **12 个**标签）现在定死，是否认可？后续只增不改。

---

## 12. 阶段 1 完成后的样子

一条命令在零依赖 venv 里跑完，产出 `runs/<id>/`：可逐行阅读的 `trace.jsonl`、与之一致的 `report.md`、被修改过的工作区副本、验证命令的原始输出、以及一个明确写在 `run_end.failure_class` 里的结论。八组脚本化对照各自的失败分类正确。重跑两次**动作序列一致**（时间戳与子进程自报耗时归一化后，见 §8.1）。`replay` 能在终端把这次运行演一遍。

到这一步，"管线是否可信"就被证明了；阶段 2 只是把一个真 LLM 装进已经验证过的 `Agent` 接口。

---

## 13. 变更记录

### 2026-09-13：回填 9 处文档-实现偏差

阶段 1 实装完成后，逐条比对本文档与代码，发现 9 处文档写于评审期、未随实装回填的偏差。全部按实修正（不改代码语义）：

| # | 本文档原表述（错） | 修正后 | 实装位置 |
|---|---|---|---|
| D1 | §5.3/§10：`run_end` 通过 `finally` 保证写出 | 由 `except KeyboardInterrupt` + `except Exception` 穷尽后无条件落盘；`BaseException` 是已知残差 | `harness/core/loop.py:135-141, 171` |
| D2 | §5.4 冻结清单只列 4 个文件 + `trace.py` 字段 | 清单以 `harness/contract.py` 为首（事件名/必需字段/标签/顺序的唯一真源） | `harness/contract.py`；`tests/test_contract.py` |
| D3 | §5.3 配置项 `max_stdout_bytes` | 实为 `truncate_threshold_bytes`/`head_chars`/`tail_chars` 等 | `configs/default.toml`；`harness/config.py` |
| D4 | §6/§11：失败标签 10 个 | 12 个 | `contract.FAILURE_CLASSES` |
| D5 | §2/§8：`task.json` 含 `faulty_patch` 字段 | `task.json` 只有 `id/description/repo/verify`；负向对照是 `repo_faulty/` 目录 + `--variant` | `harness/tasks/loader.py`；`harness/runctx.py:34` |
| D6 | §3/§8.1：三种假 agent | 六种 | `harness/agent/scripted.py:AGENT_NAMES` |
| D7 | §3/§8/§10/§12：重跑"轨迹逐字节一致" | "动作序列一致"；抖动来源=子进程自报耗时及其 sha + 失败回溯里的 run_id 路径 | `tests/test_determinism.py` |
| D8 | §6 表：`tool_call` 含 `executor` | `executor` 在 `run_start`，不在 `tool_call` | `contract.REQUIRED_FIELDS` |
| D9 | §6 表：`tool_result` 含 `stdout_bytes`/`stdout_truncated`、截断"只存头部" | 嵌套的 `stdout_stream`/`stderr_stream`，策略为 head+tail | `harness/trace.py:33-91` |

### 同批修正的两处额外偏差

回填过程中重读全文，另发现两处同性质的过期表述，一并修正：

| # | 原表述（错） | 修正后 |
|---|---|---|
| D11 | §2 目录树列了 `fs_read.py`/`fs_write.py`/`run_shell.py`/`run_tests.py`/`eval/metrics.py` | 实为 `fs_tools.py`/`shell_tools.py`；`metrics.py` 未实现也无需实现（报告直接从 trace 派生）；`contract.py`/`clock.py`/`policy.py`/`context.py` 补入 |
| D12 | 文档头"状态：待你评审，未写任何代码" | "状态：已实现" |

### 同批补齐的一处交付遗漏

| # | 问题 | 处置 |
|---|---|---|
| D10 | §3-D6 与 §4.4 承诺"哈希自证测试"（跑完任务后 `harness/ configs/ tasks/` 哈希清单不变），**实装时漏写** | 补 `tests/test_no_pollution.py` |

D10 不是文档偏差，是我的交付遗漏：文档承诺了一个不存在的测试。按"文档-实现一致"的标准，补测试而非删承诺。

### 明确保留的已知残差

- **D1 的 `BaseException` 缺口**：`SystemExit`/`GeneratorExit` 会漏掉 `run_end` 与 `close()`。本阶段未修，理由是阶段 1 无任何代码路径会抛这两类异常；阶段 2 若引入，在 `loop.py` 外层补 `finally` 即可。
- **跨后端失败输出的可比性**：见 §8.1 第 2 条。阶段 2 切容器后端时必须重新评估，否则"agent 看到的自己失败的原因"会随后端而变。
