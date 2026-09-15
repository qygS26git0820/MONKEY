# 阶段 2 复盘

- 覆盖范围：容器后端、成本/用量预算、装大脑前的结构性审计与修复、三次冻结基线移动、
  LLM 传输层与 A2、接线、首次真实冒烟。
- 证据：`git log`、`docs/evidence/stage2-docker|stage2-baseline-move|stage2-cost-budget|
  stage2-cost-removal|stage2-llm-client|stage2-llm-wiring|stage2-llm-smoke/`、
  `docs/pre-llm-audit.md`、`docs/trace-schema.md`、`docs/known-residues.md`、
  `docs/stage1-design.md` §5.4/§11。
- 你给的写作约束：只写实际发生的事；引用 `git log` 或 `docs/evidence/` 证据；不确定就写
  "不确定"；避免表功措辞；明确列出偏离计划的地方；点名的七条单列。
- 时间均为本机时区（+0800）。

---

## 0. 证据来源与它是否在版本控制里

| 证据 | 位置 | 在 git 里吗 |
|---|---|---|
| 阶段 2 的 9 个提交 | `git log`：`4e824e0`、`b6f983f`、`e72bacb`、`a35948e`、`5b8c445`、`eadd1a8`、`dee4e57`、`648066d`、`2e45a6e`、`6c8d01a`、`801b86a`、`77e05cf` | 是 |
| 各批次的独立验证输出 | `docs/evidence/stage2-*/`（7 个目录） | 是 |
| 每次实验的 run 产物（轨迹、报告、验证原始输出） | `runs/<run_id>/` | **否**，`runs/` 被 `.gitignore` 覆盖 |
| 首次真实冒烟的轨迹与报告 | `docs/evidence/stage2-llm-smoke/01`、`02` | 是（逐字节副本） |
| 临时探针（A2 变异、key 扫描、成本上限、单调用探针、离线 run） | `tmp/*.py` | **否**，`tmp/` 被忽略 |
| 契约快照与阶段 1 样本轨迹 | `tests/fixtures/` | 是 |

阶段 1 复盘 §1 指出的"证据链脆点"在阶段 2 复发了一次，处置方式相同：`runs/` 仍不进
git，只有首次真实冒烟那一份被**逐字节复制**进 `docs/evidence/stage2-llm-smoke/`
（`77e05cf`），并且是先用 `cmp` 核对一致、再用凭据扫描确认没有把 key 抄进去之后才提交的。

---

## 1. 实现 vs 计划

### 1.1 "计划"指的是哪几处

阶段 2 没有一份单独的阶段 2 设计文档。散落在四处的约束合起来才是计划：

| 来源 | 内容 |
|---|---|
| `docs/stage1-design.md` §5.4 | 冻结清单（5 文件）；验收方式 = 对 5 文件 `git diff` **必须为空**；只预期**一次**基线移动（移到"`loop.py` 的 token/成本读写接口定稿"那个提交） |
| `docs/stage1-design.md` §11 待决项 | 建议把容器后端从阶段 3 **提前到阶段 2 开头**；同意与否需你拍板 |
| `docs/stage1-design.md` 正文 | 你指定的硬约束："阶段 2 接入真实 LLM 时**不得修改主循环**" |
| `docs/pre-llm-audit.md`（`a35948e`） | 装大脑前必修 5 条（A1–A5）、两条口径问题、9 条"未知的未知"、§10 待裁决 5 条 |
| 会话里的编号裁决 | 砍成本面、保留 token 上限、标签改名、两次提交拆分、`requirements.txt` 钉版本等——**无法用文件引用**，只能标注为会话记录 |

### 1.2 与计划一致的部分

| 计划 | 实际 | 证据 |
|---|---|---|
| 容器后端提前到阶段 2 开头 | 是第一个提交 | `4e824e0`，`harness/env/docker.py` 151 行 |
| `configs/docker.toml` 的 budgets 与 default 逐字相同（同一把尺子） | 是 | `4e824e0` 提交正文；`docs/evidence/stage2-docker/00-README.md` |
| 8 组脚本化对照在两个后端下标签逐条相同 | 是 | `stage2-docker/03`、`04` |
| `llm_request`/`llm_response` 追加 `usage`/`latency_ms`/`stop_reason` | 是，且**未动 schema** | `801b86a`；`trace-schema.md` 记录 6 §6.6；`tests/fixtures/contract_snapshot.json` 未因接线而改 |
| 假 agent 接口可替换；真 LLM agent 实现同一接口 | 是——`LlmAgent` 实现 `Agent`，`scripted.py` 一字未动 | `801b86a`；裁定 2 选 A |
| "不得修改主循环"这条硬约束 | **结构上成立、字面上让路**：`loop.py` 被改了三次（见 1.3 第 1、3 条），但与 agent 的接口未变 | 见下 |

### 1.3 偏离计划的地方（逐条）

**偏离 1：基线移动了三次，不是一次。**

设计文档只预期一次。实际：

| 次序 | 提交 | 冻结文件 numstat | 触发原因 |
|---|---|---|---|
| 1 | `b6f983f` | `loop.py 15 3` | 计划内：loop.py 的 token 读写接口定稿 |
| 2 | `eadd1a8` | `contract.py 15 0`、`loop.py 14 1` | 计划外：审计 A5——12 个标签没有 LLM 传输失败的落点，而修它必须动冻结的 `loop.py`（agent 只能返回 `Abort`，无法设置 `failure_class`） |
| 3 | `648066d` | `contract.py 2 2`、`loop.py 5 7` | 计划外：你的三条裁定（删成本面、保留 token、标签改名并与本次移动合并） |

核对命令：`git diff --numstat <A> <B> -- <5 个冻结文件>`；`648066d..HEAD` 为空。

**这条偏离的根源是计划本身**：设计文档要求"冻结 5 个文件 + `git diff` 必须为空"，
同时又要求在阶段 2 加三类 LLM 失败标签、并要求成本面落地。前者要求 `loop.py` 和
`contract.py` 不动，后者要求它们动。两个要求在写下来的时候就互相冲突，不是我执行时
选错。审计 `a35948e` 把这条冲突点名了（"冻结声明说允许新增标签，验收条件却是 `diff`
为空，两者对同一件事的处理相反"）。

**偏离 2：成本面建成又拆掉。**

| 提交 | 动作 |
|---|---|
| `b6f983f` | 移基线，`run_end.totals` 预留 `cost_usd_estimate` 位 |
| `e72bacb` | 建：`UsageLedger.record()` + `exceeded()`、`Budgets.max_cost_usd`、`harness/llm/pricing.py`、缺单价拒绝启动；新增 26 项测试 |
| `eadd1a8` | 改：`cost_usd` → `cost` + 新增 `pricing_currency`（CNY）；`max_cost_usd` → `max_cost_cny` |
| `648066d` | **删干净**：`harness/llm/pricing.py` 整文件删除、`usage.py` 的 cost 三处、`config.py` 的成本不变量、`runctx.pricing_currency`、报告的成本行、`tests/test_cost_budget.py` 整个测试文件（191 行） |

即：一个提交建、一个提交改名、一个提交拆。净结果与"从未实现成本面"接近，但仓库里
留了 `stage2-cost-budget/` 与 `stage2-cost-removal/` 两份互相矛盾的证据目录，以及
`known-residues.md` R-002/R-003/R-004 三条指针。

写这份复盘时（本次核对）发现还有一处遗漏：删模块留下了两个**孤儿字节码**
`harness/llm/__pycache__/pricing.cpython-312.pyc` 与
`tests/__pycache__/test_cost_budget.cpython-312.pyc`，源文件已不在。它们被 `.gitignore`
忽略、不进版本控制、也不影响 import（Python 3 不导入 `__pycache__` 里的孤儿 `.pyc`），
但它们是"删干净"这个动作没有覆盖到的一角。当时的删除证据用的是
`grep -rn --include=*.py`（`stage2-cost-removal/02`），限定后缀，所以当时没有看见它们。
**【已处理：2026-09-15】** 经你授权后删除这两个文件；删除动作不进 git（它们在
`.gitignore` 覆盖下），故这次提交只含本文档。

**偏离 3：`env/base.py` 的 docstring 残差登记后仍未处理。** 阶段 1 复盘 §7 第 3 条登记
"该文件写着阶段 3 增加 DockerExecutor，而容器后端提前到了阶段 2；故意不改，等阶段 2
因其它理由动 `base.py` 时合并"。阶段 2 三次移动都没有动 `base.py`，所以这条**仍然开着**：
`harness/env/base.py:3` 现在依旧写着"阶段 3 增加 DockerExecutor"。这是登记的处置条件
没有触发的必然结果，不是遗忘。

### 1.4 点名的七条

#### (a) 砍成本计算（时区、峰谷、缓存命中率）

审计 §2 与 §3 把这三件事拆得很细，实际处置分两类：

- **时区**（审计 §2.3、§2.4）：那条"高峰 = 工作日 09:00–12:00、14:00–18:00 北京时间"
  的规则要落地，必须把 `time.time()`（UTC epoch）转成北京几点。项目里**没有任何时区
  处理**（无 `zoneinfo`、无 `pytz`）。用 `time.localtime()` 等于取宿主时区——本机恰好是
  Asia/Shanghai，审计原文写明"**这是巧合不是保证**"，换机器重跑同一份数据会算出不同成本。
  **结局：随成本面一起砍掉，这个坑没有被填，而是被绕开了。** 现在项目里仍然没有时区
  处理，`ts_wall` 的单位与时区在 `trace-schema.md` 字段表里仍然没有声明（审计 §2.1
  标为"已知的已知"）。
- **峰谷判定、缓存命中率**：从未实现，无代码可删（`stage2-cost-removal/00-README.md` 第 6–7 行
  原文）。但审计 §3.1/§3.2 指出的问题没有消失：兼容接口同时报 `prompt_tokens` 与
  `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`，三者加减关系**未从任何真实响应核实**；
  缓存命中依赖请求间的前缀共享，故"同样步数"的两个 run 成本不可比（审计 §3.2）。
  客户端 `_parse()` 只读 `prompt_tokens`/`completion_tokens`，**忽略**了
  `prompt_cache_hit_tokens`——首次真实冒烟回显的原始 JSON 里有没有这几个字段，**我没有核对**。

#### (b) 保留 token 上限

你裁定：钩掉 `max_cost_cny`、峰谷、缓存命中率，但**保留 `max_total_tokens` 与 `max_steps`**。
另单独裁定 `run_end.totals` 保留 `input_tokens`/`output_tokens`，只删 `cost` 与
`pricing_currency`。

理由写在 `trace-schema.md` §5.3：`max_total_tokens` 保留 ⇒ token 仍必须计数；一条因 token
越限而死的轨迹必须能看到超了多少——"有标签、没数量"正是要避免的不可观测。落地后
`run_end.totals` 的形状是 `{steps, tool_calls, input_tokens, output_tokens}`。

阶段 2 结束时 `max_total_tokens` 在 `configs/llm.toml` 里**留空**（本轮裁定），
所以这条上限在当前配置下不生效；预算路径本身由 `tests/test_token_budget.py` 覆盖。

#### (c) `cost_budget_exceeded` 改名 `token_budget_exceeded`

- 位置：`contract.py` 的 `FAILURE_CLASSES` 与 `FAILURE_DECISION_ORDER` 各一处，
  `tests/fixtures/contract_snapshot.json` 同步。
- 理由（§5.1）：成本上限被砍，该标签所指的上限只剩 token，名字必须跟着所指的东西走，
  否则又是一次"名字说的是成本、判的是 token"，与 D7 同类。
- **这是唯一一次对冻结标签名的删除，也是三次基线移动里第一次出现删除行。**
- 可行性依据：**没有任何已归档轨迹带此标签**——唯一产生点是测试，
  `tests/fixtures/phase1-sample-trace.jsonl` 的 `run_end` 是 `none`。故改名不使任何历史
  产物失效。我核对过这一条（`grep` 证据在 `stage2-cost-removal/02-removed-names-grep.txt`，
  `harness/` 下无悬挂引用）。
- 标签数量未变（仍 15 个），判定顺序中位置未变（仍第 4）。

#### (d) 第三次基线移动（第一次出现删除行）

前两次移动的判据是"`contract.py` 形如 `N 0`（0 删除行）"。第三次 `contract.py` 是 `2 2`。
`trace-schema.md` §5 开头原文："**这次移动与前两次有一个机械差别，必须记在最前面**……
'只增不改'在标签名这一处被**有意让路**一次……此判据在本次作废；若以后再有人拿'冻结清单
0 删除行'当不变式，以本条为准。"

也就是说：**阶段 1 复盘 §7 承诺的那条不变式，在阶段 2 被作废了一次**，并且是明文作废，
不是悄悄放宽。作废的依据是可核对的（无归档轨迹带旧标签名），不是"应该没事"。

#### (e) A2 和 `client.py` 同提交

计划里这条是我自己提的，原话："A2 和 LLM 客户端必须在同一个提交里。不允许'先装大脑，
再补超时。'"实际：`6c8d01a` 一个提交同时含 `harness/llm/client.py`（314 行）、
`tests/test_llm_client_timeouts.py`（442 行、16 项）、`credentials.py` 的 `api_key()`、
`requirements.txt`、`trace-schema.md` 记录 6。**没有出现"先装大脑再补超时"的中间状态。**

A2 的三层实现（`trace-schema.md` §6.1）：
1. httpx 逐阶段 `Timeout(connect=5, read=45, write=10, pool=5)`；
2. httpcore 之下的真实 socket；
3. **总时限 90s** 包住整次交换，做成**线程级**包装。

第 3 层为什么不能写成"迭代 chunk 时查截止"：`read` 是"两次读之间的最大间隔"，一个每 40s
送 1 字节的滴流网关永远骗过它；而若滴流发生在**响应头之前**，任何"响应头之后"的截止检查
一次都跑不到——请求阻塞在"等头"上，那里没有我们的代码。

#### (f) 单调用探针

这一步**不在任何计划文档里**，是我在执行真实冒烟前提的，你采纳并定为你流程的一环
（"真实冒烟前，先跑单调用探针，我确认后再跑完整任务"）。它对真实端点发了**恰好一次**
请求，没有循环、没有重试。结果：

| 问题 | 答案 | 状态 |
|---|---|---|
| `base_url` 要不要 `/v1` 前缀 | **不要**，`https://api.deepseek.com` 直接用 | 已确认 |
| 鉴权头格式 | `Authorization: Bearer <key>`，接受 | 已确认 |
| 模型回原生 `tool_calls` 还是正文 JSON | **原生 `tool_calls`**，`stop_reason="tool_calls"` | 已确认 |
| 模型名 | 请求 `deepseek-chat`（别名）时端点**回显** `deepseek-flash` | 已确认，促成改名 |

最后一条是计划外发现：配置里那个名字是我填的唯一一个未经证实的值，而端点在响应里回显了
**另一个**名字。若按原状跑，轨迹里每条 `llm_request.model` 都会写着 `deepseek-chat` 而
实际跑的是 `deepseek-flash`——"模型看到了什么"这条一等观测目标上就掺了假。故 `77e05cf`
把配置改成 `deepseek-flash`（以回显为准），并把那段已被证伪的注释（"名字如出入会以
400/404 暴露"）改成实测记录。

探针另有一条我当时**没有预料到**的副产物：它证明"请求名字"与"服务名字"可以不同，这本身
是阶段 3 做跨版本对比时的一个混杂项（见 §3）。

#### (g) 首次真实冒烟

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness run \
    --task toy-001 --agent llm --config llm
```

| 项 | 值 | 证据 |
|---|---|---|
| failure_class | `none`，`run_end.status = completed`，退出码 0 | `stage2-llm-smoke/01`、`02` |
| 步数 / 调用次数 | 4 步，`llm_request` **4 条**，`llm_response` 4 条 | 同上 |
| tokens | in 4214 / out 208 | 同上 |
| 花费 | **≈ 0.006 元** | 以探针实测 0.0012 元为锚点**单点外推**，不是价目表反算 |
| 验证 | `passed`，3/3 通过 | 任务自带命令，绕过 harness 独立重跑为 `OK` |
| 模型动作 | 同一轮并发读实现与测试 → 改 `a - b` 为 `a + b` → `run_verify` 自证 → 纯文本收尾 | `replay` 输出 |

**一次到位**（run 没有重试，也没有第二次尝试）：`max_steps` 上界 20，实际 4。
"一步到位"这个说法的口径要说清楚——它指的是**这一次 run 内部没有反复**，不指
"模型稳定能修对"。n = 1，见 §3 与 §4。

---

## 2. 实现中遇到的坑及解决方式

只列有据可查、且属于"当时不知道，做的时候才发现"的。

| 坑 | 怎么发现的 | 处置 |
|---|---|---|
| `.venv` 里没有 pip | 装 httpx 时 | `python -m ensurepip`（pip 25.0.1），再 `pip install httpx==0.28.1` |
| `httpx.MockTransport` 测不出真实超时 | 写 A2 测试时意识到 MockTransport 把整个传输层换掉、根本走不到 socket | 改用真实回环 TCP 服务器：`127.0.0.1` + 原始 socket，由服务器脚本决定怎么卡住；配一条反向对照（正常服务器必须成功），否则"一切都超时"也会显绿 |
| 滴流网关骗过 `read` 超时 | 设计第 3 层时 | 总时限做成**线程级**（worker 线程 + `join(total_s)` + 关闭底层连接解阻塞），而不是"迭代 chunk 时查截止" |
| A2 变异探针的线程计数被自己混淆 | 探针第一次跑，判"有没有泄漏线程"时，上一个总时限用例挂住的线程已经被算进去了 | 把泄漏检查排到**最前面**、从干净基线起算；确认 0 个泄漏的 `llm-post` 线程 |
| `requirements.txt` 里引用了一个不存在的文件名 | 提交前的自查 | 查明并保留内容、改掉引用、把"这个文件的存在我无法解释"如实披露 |
| `harness/llm/agent.py` 的 import 写错（`.agent_base`） | 跑测试时 | 改成 `from ..agent.base import Agent` |
| `SystemPromptTest` 两条断言断言错了东西 | 分支覆盖自查 | 一条在中文提示词里找英文单词 "workspace"（永远找不到）；一条的花括号用例没有插值，因此没有真正走到 format 的危险路径。重写为用独特标记验证工作区替换、并用含花括号的路径 |
| `LlmAgent` 把本次发出的 `tool_call` id 漏记 | **我自己的测试当场抓住**：`test_the_next_request_carries_the_tool_result_with_its_call_id` 报 `'c1' != 'orphan_3'`；根因是 `_to_action` 是模块级函数、改不到 `self._pending_ids` | 在 `next_action` 里显式记录 id 顺序。证据与自述见 `stage2-llm-wiring/00-README.md` §"一个我自己写错、被测试抓住的 bug" |
| `--agent llm --config default` 会先建 run 目录再炸 | 自查启动路径时 | 加启动前拒绝（缺 `[llm].model` 即 exit 2、不建目录）；补 `LlmCliRefusalTest` 并实测两条拒绝路径 |
| 基线移动前后对比轨迹时，`bytes_total` 出现 12 字节差 | `b6f983f` 的证据生成 | 根因是两批 `run_id` 前缀**长度不等**（9 字符 vs 3 字符），路径长度进了 `bytes_total`，与行为无关。修正后逐字段只差 `harness_git_sha` 一个字段（构建来源字段）。这条被当作**真实混杂项**留在 `stage2-baseline-move/02` |
| 证据 README 里的测试计数是陈旧的 | 提交前复核 | 用 `Edit` 工具改了 4 处（146 / 25）。此前用 python heredoc 做同样的替换，命令报了"counts updated"但实际没生效——**命令的自我报告不可信**，我改用能在 diff 里看见的方式 |
| 我写进 README 的两条复核命令是错的 | 提交前实测 | ① `validate-trace` 指向目录但该目录里是 `01-smoke-trace.jsonl`（非默认名），要指到文件；③ 相对路径少一层（`../../.venv` 应为 `../../../.venv`）。三条命令现在都实测跑过 |
| `python -m unittest discover -s tests` 会破坏相对 import | `stage2-cost-removal` 的验证阶段 | 正确形式是 `discover` 或 `discover -s tests -t .`，须在仓库根运行 |

---

## 3. 对阶段 3 的预判：哪些设计现在看起来可能有问题

以下都是"现在看起来"，不是"已证明有问题"。分三类。

### 3.1 已经登记、有测试或文档盯着的

| # | 问题 | 为什么可能出问题 |
|---|---|---|
| R-006 | `step` 由 agent 自计数，靠"不重试"维持与主循环对齐 | `contract.py` 要求 `llm_request`/`llm_response` 带 `step`，但 `ConversationState` 里没有 step、`loop.py` 不发这两个事件。正确的修法是让 `loop.py` 发（要移基线）。**一旦阶段 3 引入重试，自计数会与主循环 `step` 错位，且 `validate_records` 发现不了**。缓解：`test_the_self_counted_step_matches_the_loop_step` 钉住等号关系 |
| R-007 | 工具 schema 与系统提示词的措辞是**未版本化**的实验条件 | 模型看到什么本身就是观测的一部分，但这些文本只随代码走，`config_hash` 覆盖不到——换一版提示词不会改变配置归属，跨版本对比时看不出改过 |
| R-001 | token 未知量无法触发终止 | 未知是**粘的**（一笔缺就恒缺），`exceeded()` 对未知短路为假，故未知量上的越限漏判。这是刻意的取舍（"无法证明它超了就不凭它终止"），但阶段 3 若出现"网关不回 usage"的端点，`max_total_tokens` 会形同不存在 |
| R-002/003 | 历史文档与冻结样本上留着三代 `totals` 形状（`cost_usd` / `cost` / 无 `cost`） | 任何按 `totals` 子键做聚合的分析代码需对三代都容错。当前无此类代码 |
| — | `env/base.py` docstring 过时（§1.3 偏离 3） | 冻结一个文件，就同时冻结了它已经过时的陈述。阶段 3 若为别的理由动 `base.py`，该合并处理 |

### 3.2 阶段 2 结束时新出现、尚未登记的

| # | 问题 | 依据 |
|---|---|---|
| 1 | **真实端点上的慢调用、挂住、401/402/429/5xx 一次都没触发过。** A2 的三层超时只在 `127.0.0.1` 的回环 socket 上验过 | `stage2-llm-smoke/00-README.md` §五。真实网关是否与回环行为一致，未知 |
| 2 | **请求的模型名与服务回显的模型名可以不同**（`deepseek-chat` → `deepseek-flash`） | 探针结果。跨版本/跨网关对比时，"同一模型"这个前提需要靠回显而不是靠配置来确认 |
| 3 | **`prompt_cache_hit_tokens` 等缓存字段被客户端忽略**，且成本面已删 | 审计 §3.1/§3.2；`client._parse()` 只读 `prompt_tokens`/`completion_tokens`。若阶段 3 重新引入成本，这几个字段的加法关系仍未核实 |
| 4 | **容器隔离不完整**：只有命令执行进容器，`read_file`/`write_file` 仍在宿主侧 | `4e824e0` 登记的已知边界。agent 的读写在容器外，靠 bind mount 看到同一份字节 |
| 5 | **跨后端失败输出的可比性**：同一 `read_file` 在 local 记 `workspace`、在 docker 记 `/workspace` | `stage2-docker/05-replay-path-diff.txt`；阶段 1 复盘 §7 第 2 条要求"切容器后端时重估"，实测差异已落地但重估本身**没有做** |
| 6 | **`totals` 里的 token 数在预算关闭时不构成任何约束** | `configs/llm.toml` 的 `max_total_tokens` 留空。阶段 3 若跑长任务，花费的唯一上界是 `max_steps` |
| 7 | **审计 §10 的 5 条待裁决与 9 条"未知的未知"里，有一部分在阶段 2 结束时没有明确处置** | `docs/pre-llm-audit.md`。我**没有逐条核对**这 14 条各自的现状，因此不确定留了几条 |

### 3.3 与"观测工具污染观测对象"同源的一条

步骤 A1 修掉了 `MONKEY_` 前缀环境变量泄漏给 agent 的通道（`5b8c445`）。但 `trace.jsonl`
现在**逐条记录完整 `messages` 与 `tools` 全文**（记录 6 §6.6），这是有意为之——"模型看到
了什么"是一等观测目标。副作用是轨迹体积随步数增长，且**提示词内容进了版本控制之外的
运行产物**。阶段 2 的冒烟只有 4 步、26 KB，没有触发问题；阶段 3 若跑长任务，轨迹体积与
截断策略需要重新看。

---

## 4. 我自己最不确定的部分

1. **第三次基线移动该不该做。** 你的裁定是"选 B 删干净"，执行上没有含糊。但我到现在
   也不确定"删干净"比"留一套休眠骨架"更好：删的行为让 `contract.py` 出现了删除行、
   作废了阶段 1 承诺的一条不变式，代价是真实的；收益是"不留死代码"。我执行了你的裁定，
   但我没有能力判断这个权衡，只能记录它的代价。**不确定。**

2. **成本面会不会在阶段 3 回来。** 如果回来，`b6f983f → e72bacb → eadd1a8 → 648066d`
   这四个提交的净效果是把同一个东西建了又拆，其中 `pricing.py` 的 `PRICES` 空表设计
   （"空表不是缺口，是结构保证"）会需要重做一遍。我倾向认为会回来（一旦要跑多任务、
   比成本），但**不确定**，也没有证据。

3. **A2 的线程级总时限在真实网关上的行为。** 回环测试覆盖了三种卡法（静默、正文滴流、
   响应头滴流），但真实网关的慢是另一回事：DNS、TLS 握手、网关排队、上游限流。三层
   超时在真实端点上一次都没触发过，我**不确定**它们的分工在那时是否还成立——特别是
   `read(45s) < total(90s)` 这条顺序不变量，只在回环上验过。

4. **`step` 自计数的隐含契约能撑多久。** R-006 的缓解是一条测试。但"一次
   `next_action` 恰好发一次请求"这个前提不写在任何接口里，只在 `client.py` 的 docstring
   里有一句"不重试是刻意的"。**不确定**阶段 3 引入任何形式的重试/流式/多轮内部循环时，
   这条测试是不是第一批变红的。

5. **提示词质量对冒烟结果的影响无法归因。** 4 步修对，可能是提示词写得好，可能是
   toy-001 太简单，可能是模型本来就会。n = 1，我**无法区分**这三种。R-007 说明措辞是
   未版本化的实验条件，所以将来想区分也缺一个变量。

6. **0.006 元这个数。** 它是用**一次**探针调用（in 788 / out 44 → 0.0012 元）做单点外推
   得到的，不是价目表反算。真实花费可能与它差一个量级，**不确定**。要准确核算必须拿
   到单价表；审计 §3.1 说"三者加减关系需要从一次真实响应核实"，我也没有核实。

7. **阶段 2 的"装大脑"验收标准是否真的回答了"管线可信"。** 阶段 1 用 8 组对照证明
   管线可信；阶段 2 用一个真 LLM 跑通一个玩具任务。这两件事我自己认为不是同一个强度
   的证据，但**不确定**你对阶段 2 的验收是否是"跑通即可"。若你期望的是"管线在真实
   负载下仍然可信"，那本次冒烟只覆盖了其中最窄的一条路径。

---

## 5. 明确保留的已知残差

阶段 2 新增 7 条，全部登记在 `docs/known-residues.md`（只增不改不删）：

| # | 一句话 |
|---|---|
| R-001 | token 未知量无法触发终止（粘性未知 + `exceeded()` 短路） |
| R-002 | 历史文档与证据仍命名已删除的成本面 |
| R-003 | `phase1-sample-trace.jsonl` 的 `totals` 键名与现行 schema 不同 |
| R-004 | 审计 §8.6 针对的旧测试文件已删除 |
| R-005 | 部分标签在 §1.3 表里仍标着"【建议新增】" |
| R-006 | `step` 自计数靠"不重试"维持对齐 |
| R-007 | 工具 schema 与提示词措辞是未版本化的实验条件 |

阶段 1 遗留、阶段 2 结束时**仍然开着**的：

1. **`run_end` 的 `BaseException` 缺口**：`SystemExit`/`GeneratorExit` 会同时漏掉
   `run_end` 与 `run_ctx.close()`。阶段 2 引入了线程（A2 的 worker 线程），但它是
   daemon 线程、不抛这两类异常，所以缺口未被激活也未被修。
2. **跨后端失败输出的可比性**：实测差异已落地（`stage2-docker/05`），重估未做。
3. **`harness/env/base.py` docstring 过时**：三次移动都没有动 `base.py`，处置条件未触发。

---

## 6. 阶段 2 结束时的状态（事实陈述）

```
77e05cf MONKEY 阶段 2：装大脑（LLM 客户端 + 首次真实冒烟通过）
801b86a MONKEY 阶段 2：接线（prompt / LLM agent / llm.toml / CLI --agent llm）
6c8d01a MONKEY 阶段 2：LLM 传输层 + A2 三层超时（httpx，真实回环 socket 验证）
2e45a6e MONKEY：把 .claude/ 加入 .gitignore
648066d MONKEY 阶段 2：第三次移动冻结基线
dee4e57 MONKEY：修正 §2.1 里 elided_bytes 的公式
eadd1a8 MONKEY 阶段 2：第二次移动冻结基线
5b8c445 MONKEY 阶段 2：装大脑前的结构修复
a35948e MONKEY：装大脑前的结构性审计
e72bacb MONKEY 阶段 2：成本/用量预算
b6f983f 阶段 2：移动冻结基线
4e824e0 阶段 2 第一步：容器后端
```

- 12 个提交，工作区干净（`git status --short` 只剩被忽略的 `thought/`）。
- 测试：57（阶段 1）→ 67（docker）→ 93（成本预算）→ 105（删成本后）
  → 146（接线，`skipped=6`）。中间 105 → 146 之间的两个中间值没有留证据文件，
  其中 `stage2-cost-removal/00-README.md` 声称删成本前是 112，**这个数字我没有
  一条录下来的测试运行可以引用**，只有 README 的自述。
- 冻结面：`648066d..HEAD` 对 5 个冻结文件 diff 为空；阶段 2 期间共 3 次有意的移动，
  逐次 numstat 见 §1.3。
- 首次真实冒烟：`failure_class = none`，4 步，in 4214 / out 208，≈ 0.006 元（单点外推）。
- 阶段 2 的两次付费调用：单调用探针 1 次（≈ 0.0012 元）+ 全量任务 1 次（≈ 0.006 元）。

---

## 附：本文全部事实的可核验命令

```bash
# 提交与统计
git log --format='%h %ci %s'
git show --stat --format='' 4e824e0 b6f983f e72bacb 5b8c445 eadd1a8 648066d 6c8d01a 801b86a 77e05cf

# 三次基线移动的冻结面（期望：loop.py 15 3 / contract.py 15 0 + loop.py 14 1 / contract.py 2 2 + loop.py 5 7）
git diff --numstat 3342dcf b6f983f -- harness/contract.py harness/core/loop.py harness/agent/base.py harness/tools/base.py harness/env/base.py
git diff --numstat b6f983f eadd1a8 -- harness/contract.py harness/core/loop.py harness/agent/base.py harness/tools/base.py harness/env/base.py
git diff --numstat eadd1a8 648066d -- harness/contract.py harness/core/loop.py harness/agent/base.py harness/tools/base.py harness/env/base.py
git diff --numstat 648066d HEAD -- harness/contract.py harness/core/loop.py harness/agent/base.py harness/tools/base.py harness/env/base.py

# 工作区与全套测试（期望：Ran 146 tests / OK (skipped=6)）
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover

# 已删名字无悬挂引用（期望：无输出）。--include=*.py 不能省：
# 删掉的两个模块留下了孤儿字节码，不加限制会命中 __pycache__
grep -rn --include=*.py "max_cost_cny\|pricing_currency\|price_for\|cost_usd\|cost_budget_exceeded" harness/

# 代价：删模块留下的孤儿 .pyc（本地产物，已被 .gitignore 忽略，不影响 import）
# 2026-09-15 已删除，故现在期望无输出
find harness tests \( -name "pricing.*.pyc" -o -name "test_cost_budget.*.pyc" \)

# 阶段 1 遗留的第 3 条残差仍在（期望：打出 "阶段 3 增加 DockerExecutor"）
grep -n "阶段 3" harness/env/base.py

# 首次真实冒烟的三条复核
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/stage2-llm-smoke/01-smoke-trace.jsonl
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay \
    --run runs/20260915-052422-toy-001-llm
cd "runs/20260915-052422-toy-001-llm/workspace" && \
  PYTHONIOENCODING=utf-8 "../../../.venv/Scripts/python.exe" -m unittest discover -s tests -t . -v
```
