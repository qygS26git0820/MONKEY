# 混沌实验复盘

> 命名说明：你给的两个名字是"阶段 3 的复盘"和"混沌实验复盘"。我选了后者，因为
> MONKEY 的路线图里"阶段 3"另行指代（`harness/env/base.py:3` 的过时 docstring、
> 阶段 1 复盘 §7 都拿"阶段 3"指容器后端之后的下一步），用 `stage3-retrospective.md`
> 会和那个尚未发生的阶段撞名。若你要改名，改文件名即可，内容不变。

- 覆盖范围：OpenCode 的环境准备与交接、快照审计、MONKEY 任务与配置、两次真实付费 run、
  上限改判与复核。
- 证据：`git log`、`docs/evidence/chaos-001/`、`docs/env-handoff.md`、`chaos/*.yaml`、
  `tasks/chaos-001/`、`configs/chaos.toml`。**简报原文、审计交付物、历次编号裁决与
  事前预测都在会话记录里（`e1733296-…jsonl`），不在版本控制里**——见 §0 最后一段。
- 写作约束（沿用阶段 2 复盘那套，并遵守你本次的追加要求）：只写实际发生的事；引用
  `git log` 或 `docs/evidence/`；不确定就写"不确定"；避免表功措辞；明确列出偏离计划
  的地方。
- 时间均为本机时区（+0800）。

---

## 0. 证据来源与它是否在版本控制里

| 证据 | 位置 | 在 git 里吗 |
|---|---|---|
| 本次两个提交 | `95654e6`、`636e56c` | 是 |
| 环境交接文档（ground truth） | `docs/env-handoff.md` | 是 |
| 故障注入清单原件 | `chaos/01-nginx.yaml`、`02-client.yaml`、`03-networkchaos.yaml` | 是 |
| 现场快照（9 文件，1.9 MB） | `tasks/chaos-001/repo/snapshot/` | 是 |
| MONKEY 任务定义与判据 | `tasks/chaos-001/task.json`；阳性对照 `repo_right_diagnosis/diagnosis.json` | 是 |
| 实验配置 | `configs/chaos.toml` | 是 |
| 两次实跑的 run 产物（轨迹、报告、blob、验证原始输出） | `runs/<run_id>/` | **否**，`runs/` 被 `.gitignore` 覆盖 |
| 两次实跑的关键产物副本 | `docs/evidence/chaos-001/` | 是（逐字节 + `cmp` 核对） |
| 判据正反控制探针（10 例真值表） | `tmp/probe-verify-predicate.py` | **否**，`tmp/` 被忽略 |
| 简报原文、审计交付物、历次编号裁决、事前预测 | 会话记录 `e1733296-…jsonl` | **否**——这是本文档里**引用不到版本控制的**那一类 |

最后一行是本文档的证据链上最脆的一处，比阶段 1/2 复盘指出的那处更脆：阶段 2 的"计划"
至少散落在四份已提交的文档里，而**本次实验的计划（简报与审计）只存在于会话记录**。
本文档凡是引用它们的地方，都标注了"会话记录"而不是文件路径。

关于 `runs/` 仍不进 git：与阶段 2 处置相同，只有本次实验的关键产物被**逐字节复制**进
`docs/evidence/chaos-001/`。本次与阶段 2 有一个差别——阶段 2 只复制了轨迹与报告，
本次**必须连 `blobs/` 一起复制**，理由见 §2.4。

---

## 1. 实验设计 vs 实际

### 1.1 "计划"指的是哪几处

| 来源 | 内容 |
|---|---|
| 简报 §一~§九（会话记录，2026-09-16） | 九节：环境准备交 OpenCode；Claude 设计与执行；**§三 安全审计清单（6 项）**；§四 三时段内存管理；§五 降级优先级；**§六 审计输出要求（6 项）且"审计完先不要执行"**；§七 文件路径；**§八 熔断机制**；§九 使用顺序（两个 Agent 不同时开） |
| 审计交付物（会话记录） | §0 结论 + §1 逐条对应 §三 的 6 项 + §2 风险清单 R1–R11 + §3 最小版本 A/B/C + §5 内存预估 + §6 建议 10 条 + §7 不确定 9 条 |
| 编号裁决（会话记录） | 版本 A；熔断零代价方案；R10；内存按实测 7.3GB；D-1=A3、D-2=150000、D-3=diagnosis.json、D-4；后续 D 系列改判（150000→200000） |

简报复述（**未逐字引用**，§三/§六/§八 的逐字原文见 §1.3 的引用块）：§三 要求审计
"网络连通性 / 工具集 / 任务可验证性 / 内存与资源 / 隔离边界 / 实验有效性"6 项；§六 要求
产出"可实施性 / 风险清单 / 最小版本 / 建议 / 内存预估 / 不确定"6 项，并且**审计完先不要
执行**；§八 要求加熔断，并在设计里说明"N 是多少、检测在哪一层做、会不会动冻结文件、
终止后落在哪个 failure_class"，且"如果检测要动冻结文件，先说明代价，不要自己决定"。

### 1.2 与计划一致的部分

| 计划 | 实际 | 证据 |
|---|---|---|
| 审计先行，且"审计完先不要执行" | 审计交付后停在原地等裁决，未自行开工 | 会话记录 |
| 版本 A：MONKEY 只诊断、不碰集群 | 后端选 docker、默认 `--network none`、镜像里没有 kubectl；两次 run 的 18/21 条工具调用**全部落在 `/workspace` 内**，无一次越界尝试 | `configs/chaos.toml`；`trace.jsonl` 的 `tool_call.cwd` |
| 任务描述写"恢复服务"、不写"修 bug"（R10） | `task.json` 正文逐字如此，并明写"你没有集群访问权限" | `tasks/chaos-001/task.json` |
| 判定物是 `diagnosis.json`（D-3） | 两次 run 都产出文件，判据两次都 `exit 0` | 两个 run 的 `workspace/diagnosis.json`、`verification/verify.stdout.txt` |
| §七 的四条路径 | `docs/env-handoff.md`、`chaos/`、`tasks/chaos-001/`、`runs/<run_id>/` 四处齐备 | `git ls-files` |
| §八 熔断"零代价" | 四种终止检测全部落在**配置值**上，5 个冻结文件零改动 | `git diff --numstat 636e56c HEAD -- <冻结5文件>` 输出为空 |
| 内存：按实测跑、不动 `.wslconfig` | 未动。跑前预检 WSL `available` 5.2G | `docs/env-handoff.md` §4；会话记录 |
| §四 三时段、两个 Agent 不同时开 | 时段 1 由 OpenCode 建环境；时段 2 由我离线建任务/配置/测试/谓词控制；时段 3 跑 MONKEY。**本次会话中未同时调用 OpenCode** | 会话记录 |

一条值得单独记下的巧合：审计给出的三个阻断项里，有两个在选定版本 A 之后**从缺陷变成了保证**——
`network="none"`（审计 R? 阻断项 2）原本是"MONKEY 碰不到集群"的证据，选版本 A 后正好
是"不碰集群"的机械保证；镜像里没有 kubectl（阻断项 3）同理。剩下的阻断项 1
（Docker Desktop 没运行）由你自己起。这也解释了为什么版本 A 是最小改动的那条路：
它把两个需要"补"的东西变成了不需要补。

### 1.3 偏离计划的地方（逐条）

**偏离 1：事前预测把"触顶"与"观测失败"绑成了一件事，实际是两件事。**

跑前最后一份预估（会话记录）里我写过这么一句，逐字：

> 如果 MONKEY 反复用命令把大段输出灌进上下文，150k 会在 12~15 步之间触发，
> 那时会得到 `token_budget_exceeded` 而不是诊断——那也是一种观测结果。

实际第一次跑：上限**确实**在第 13 步（落在预测的 12~15 区间内）触发，
`failure_class = token_budget_exceeded`，`input 149,978 + output 3,395 = 153,373`。
但同一份 `run_end` 里 `verification_status = passed`——诊断**已经写出来并通过了判据**。

也就是说预测的前半段（步数区间）命中得相当准，后半段（"而不是诊断"）错了：
**上限触顶与有没有拿到诊断是两个独立的事实**。我在预测里把它们绑在一起，是因为
当时默认"触顶 = 中途被杀 = 没产出"。实际是"触顶 = 在产出并自证之后的下一步被杀"。

**偏离 2：一个完全没预料到的现象——成功收尾的那一步被丢弃。**

`harness/core/loop.py` 的检查顺序是：先 `step += 1`（loop.py:83），再取动作
（loop.py:85），**再查一次用量**（loop.py:88），然后才分类动作（loop.py:92 起）。
第 13 步的用量是 153,373 > 150,000，于是循环在 loop.py:88 直接 `break`——
**在动作被识别为 `Finish` 之前**。

后果是三条同时出现，而我在设计里一条都没写到：

| 观察 | 值 | 正常路径下应该是 |
|---|---|---|
| `agent_message` 事件数 | **0** | 1（`Finish` 会发一条，loop.py:94） |
| `step_end` 事件数 | 12（`steps` 却是 13） | 第 13 步要么发 `step_end`，要么走 `Finish` 分支 |
| `run_end.status` | `aborted` | `completed` |

那一步的模型输出**并没有丢**：它完整地存在 `llm_response` 事件（`seq 81`）的 `content`
字段里，342 字符，逐字可取（`llm_response` 不走 `prepare_stream`，只有工具输出才截断）。
丢的是**分类事件**——轨迹里没有任何东西标记"这段文本是一次 Finish"。

设计为什么要这么排？loop.py:86 的注释写着：不等到下一轮开头，"否则被观测到的越限会
多出整整一步"。这个理由是成立的（否则越限的步数会被多记 1），但它的副作用——**丢弃
一个已经成功的 `Finish`**——当时没有被想到。

**偏离 3：上限改判了一次（150000 → 200000），未移动冻结基线。**

改判由偏离 1/2 那次实跑直接触发：既然那次只差 3,373 就能干净收尾。`configs/chaos.toml`
**不在冻结清单**（冻结的是 `contract.py`/`loop.py`/`agent/base.py`/`tools/base.py`/
`env/base.py`），所以这是一次纯配置改动。裁定同时明确"不动 `loop.py` 的检查顺序
（那是第 4 次基线移动，不值得）"。

**偏离 4：§八 要求的四条检测里，一条被加、又被撤、最终没有实现。**

§八 原本要求"同一工具+同一参数连续调用 N 次 → 终止"。你的第一版裁决是"新增'同一工具
+同一参数+同一结果'检测，N=3"，随后改判 **D-1 = A3，即不加**。理由记在
`configs/chaos.toml` 的注释里：`max_steps`/`max_total_tokens`/`wall_timeout_s` 已把
花费锁在小额内，而"卡住"本身正是这次要观测的现象，熔断器会把它剪掉。

§八 四项要求的最终落点：

| §八 要求 | N | 检测在哪一层 | 动冻结文件吗 | 终止后的 failure_class |
|---|---|---|---|---|
| 同一工具+同一参数连续 N 次 | — | — | — | **未实现**（D-1=A3） |
| 同一失败标签连续出现 N 次 | **4**（`max_tool_error_streak`，3→4） | `loop.py` 内、工具结果分类之后（loop.py:132–140） | 否（改的是配置值） | `tool_error_repeated` |
| token 超过阈值 | `max_total_tokens`（60000→150000→200000） | 循环顶（loop.py:73）与每次响应后（loop.py:88） | 否（配置值） | `token_budget_exceeded` |
| 墙钟 / 单步 | 600s / 120s | loop.py:76 / loop.py:146 | 否（配置值） | `timeout_wall` / `timeout_step` |

所以 §八 那句"会不会动冻结文件（如果动，说明代价）"的答案是：**四条全部零代价，
未动任何冻结文件**。而"检测在哪一层"这条，第 2、3、4 条都在**主循环内**，不是工具层
或 agent 层——这也解释了为什么第 3 条会丢弃 `Finish`（循环内的检查早于动作分类）。

**偏离 5：交接物里有一句泄漏答案的话，改掉了。**

OpenCode 交接的 `00-COLLECTED.md` 在"全量资源原始清单"那一项的"为什么有用"栏里，
原文写着"故障注入的痕迹就保留在这份原始输出里"，并在"未采集"一节里直接点名
`networkchaos`。这等于把根因的 **kind** 提前写进了清单——虽然答案的具体内容仍要
自己去 1.8 MB 里找，但"去看 chaos 类资源"这个关键跳跃被提前给了。

审计交接物时发现，逐字替换掉两句。事后核对两条：

```
git log -S '故障注入' -- <该文件>            # 输出为空
grep -c '故障注入\|networkchaos' <该文件>    # 0
```

即**泄漏原文从未进入版本控制**——它在快照入库之前就被改掉了，所以 git 历史里查不到它，
本文档是它唯一的记录。

**偏离 6：两次实跑的 token 差 30.9%，而上限改判并不是第二次干净收尾的原因。**

见 §2 与 §4 第 2 条。这一条严格说是"计划里没有的东西"而不是偏离，但它推翻了偏离 3
那次改判的预期收益，必须记在这里。

### 1.4 点名的两条

#### (a) §三 的 6 项审计：交付了，且三个阻断项都真实存在

6 项逐条有结论，总结论是"能做，但不是现在这份方案描述的那样做"，三个阻断项：
Docker Desktop 没运行；`harness/env/docker.py:38` 的默认 `--network none` 让容器没有
任何网络；`DEFAULT_IMAGE = "python:3.12-slim"` 里没有 kubectl 且 `--pull never` 只用
本地镜像。第 2、3 项在选版本 A 后从缺陷变成保证（§1.2 末段），第 1 项由你解决。

**这次审计的价值是可核对的**：三个阻断项没有一个是"理论上可能"，都是当时当场跑命令
或读代码看到的。

#### (b) §六 的 6 项输出要求：齐备

§0/§1 对应可实施性；§2 风险清单 R1–R11（含概率与影响）；§3 最小版本 A/B/C；§5 内存预估；
§6 建议 10 条；§7 不确定 9 条。§六 最后那句"审计完先不要执行"被执行了——审计交付后
没有自行开工，等裁决。

---

## 2. 两次跑的差异（策略层面的方差）

### 2.1 两次 run 的对照

| | 第一次 | 第二次 |
|---|---|---|
| run_id | `20260917-123127-chaos-001-llm` | `20260917-124312-chaos-001-llm` |
| `config_hash` | `13f4d51f…`（上限 150000） | `d87072db…`（上限 200000） |
| `harness_git_sha` | `636e56c4…` | `95654e63…` |
| `failure_class` / `status` | `token_budget_exceeded` / `aborted` | **`none` / `completed`** |
| `verification_status` | `passed` | `passed` |
| 步数 | 13 | 13 |
| `tool_call` | 21 | 18 |
| `llm_request` / `llm_response` | 13 / 13 | 13 / 13 |
| `agent_message` | **0** | 1 |
| tokens | in 149,978 / out 3,395 = **153,373** | in 102,882 / out 2,955 = **105,837** |
| 墙钟 | 27.7 s | 29.5 s |
| 估算花费 | ≈0.21 元 | ≈0.14 元 |

同样 13 步、同一模型（`deepseek-flash`）、同一份快照、同一个判据，token 差 **47,536
（−30.9%）**。

### 2.2 差在哪里：不是"读了多少"，是"多早把大段文本放进上下文"

两次的**截断事件各只有一次**：

| run | 截断发生在 | 工具 | `bytes_total` | 送达 | 丢弃 |
|---|---|---|---|---|---|
| 第一次 | **step 3** | `read_file`（events 文件） | 57,651 | 6,031 | 51,651 |
| 第二次 | **step 9** | `run_command`（模型自己的 grep） | 85,400 | 6,031 | 79,400 |

注意第二次被截断的那一份**更大**（丢弃 79,400 > 51,651），但第二次整体更便宜。差别在于
**时点**：第一次的 6,031 字节从第 4 步起就留在上下文里，要被重发 9 次；第二次的从第 10
步起才在，只被重发 3 次。而每一步都要重发整段历史，所以"早一步进上下文"的代价是复利。

每步输入拼起来看更清楚：

```
第一次:  978  1434  5210  8331  9443 12000 12393 12985 14799 17031 17631 18836 18907
第二次:  978  1126  1643  3014  5434  6004  7886  8898 10766 13257 14157 14824 14895
```

第一次在第 3 步就一次读了**三份**文件（events + describe + logs），第 4 步上下文已经过万；
第二次把同样的三份拆到第 3、5、8 步，且前期先花两步做 `ls` 侦察。

**这是解释而不是归因。** n=2，我无法证明"先侦察、后分批读"是它做对的原因，只能说这次
这样走便宜了 30.9%。

### 2.3 上限改判与干净收尾之间**没有因果关系**

第二次跑只用掉 105,837，**连旧的 150,000 上限都没碰到**。所以第二次能干净收尾，
原因是它换了一条更省的路径，不是因为上限被抬高了。

这条要单独记：偏离 3 那次改判的**直接理由是**"第一次只差 3,373 就能干净收尾"，而第二次
跑既没有验证那个假设（没有重跑第一次的路径），也没有用上新上限。改判本身仍然合理
（3,373 的余量太薄），但它**没有被本次实验证实或证伪**。

### 2.4 为什么这次必须把 `blobs/` 一起归档

阶段 2 的冒烟没有触发截断，所以只存了 trace 与 report。本次两份 trace 里各有一次截断，
而**被丢弃的那 51,651 / 79,400 字节只存在于 `blobs/<sha>.blob` 里**。若只归档 trace，
`stdout_stream.blob_ref` 会指向一个不存在的文件，截断这件事就只剩一个计数器、看不到
被截断的内容。故 `docs/evidence/chaos-001/` 必须含两个 blob。

---

## 3. 观测结论：MONKEY 在混沌场景下的行为边界

先声明口径：**n = 2，同一个任务、同一个模型**。下面每一条都只说"这两次里观察到"，
不说"MONKEY 在混沌场景下如何如何"。

### 3.1 它做到了什么（两次都观察到）

| # | 行为 | 证据 |
|---|---|---|
| 1 | **read_file 撞上截断后改走 `run_command` 精确切段**，而不是在截断上反复重试 | 第一次 step 4–9、第二次 step 6–10；两次都**没有**触发 `tool_error_repeated`（连续错误计数一次都没涨到 4） |
| 2 | **主动构造对照**：两次都读了注入前（04:58:56Z，`HTTP/1.1 200 OK`）与注入后（05:03:31Z，`download timed out`）两个 wget 文件，并在最终小结里把对照作为论据写出 | 第一次 step 10、第二次 step 5；两次的 `agent_message` / `llm_response.content` |
| 3 | **主动排除竞争假设**：都读了 pods / describe / logs / svc，得出"Pod 与 Service 正常，故障在网络层" | 两次的 `diagnosis.json.evidence` |
| 4 | **产出超出判据要求**：判据只查 3 个必填字段，两次都另外写了证据字段（第一次 5 条 `evidence`，第二次也带证据） | 两个 `diagnosis.json`（1,421 B / 1,613 B） |
| 5 | **自发自证**：两次都在写完文件后主动调 `run_verify` | 第一次 step 12、第二次 step 12 |
| 6 | **不越界**：18/21 条工具调用全部在 `/workspace` 内 | `tool_call.cwd` 逐条 |

### 3.2 它的边界在哪里（本次观察到的）

**(1) 只靠 `read_file` 拿不到答案——这个任务里"必须用命令"是被结构逼出来的。**
答案在 1.8 MB 转储的第 28,806 行附近；`read_file` 单次可达的窗口只有头 3000 + 尾 3000
字节（`prepare_stream`，阈值 8192 B），永远够不到。两次都自己换成了
`grep -n` + `sed -n 'A,Bp'`。**n=2 都是这样，但这是设计上的可达性结论，不是能力结论**：
它证明了"这个任务不可用纯 read_file 解"，没有证明"MONKEY 总能想到换工具"。

**(2) 轨迹里没有"我不确定"这个行为可观测。**
两次都以高置信度直接给结论，两次都对。本次**没有触发**任何"证据不足、拒答、要求更多
信息"的路径，所以轨迹中这一段是空白的——不是"它不会"，是"这次没机会看到"。

**(3) 预算耗尽是策略敏感的，不是任务固有的。**
同一个任务、同一个模型、同一步数，token 差 30.9%（§2.1）。这意味着
`max_total_tokens` 这种绝对闸门挡住的可能是"某次走了弯路"，而不是"任务本身贵"。
把这条推到一般情形：**一条因 token 越限而死掉的轨迹，不能直接读作"这个任务超出了预算"。**

**(4) "成功"与"花了多少"在本次是负相关的。**
更贵的那次（0.21 元）被判 `aborted`，更便宜的（0.14 元）被判 `completed`。
扣掉偏离 2 那个机制性原因，剩下的部分是：第一次的路径本来就更啰嗦。

### 3.3 判据本身的宽松度（我自己设计出来的，现在看起来偏松）

`task.json` 的判据只做三件事：三个字段非空、`root_cause_kind` 归一后等于
`networkchaos`、`namespace` 归一后等于 `default`、`workload` 小写后**含子串** `nginx`。

也就是说 `workload` 写 `"nginx"`、`"deployment/nginx"`、`"default/nginx"` 都算过——
**它没要求写对"受影响的工作负载"这个对象本身**。两次 run 都远超出这个要求
（都写了 `deployment/nginx` 或等价物），所以宽松**没有被暴露成问题**。但它意味着
"判据通过"≠"诊断正确"，只是"诊断没有错到判据能看出来的程度"。

这是本次实验里我唯一想主动指出的设计缺陷，且它是**可复核的**：`tasks/chaos-001/task.json`
的 `verify.command` 原文在版本控制里。**它已在收到裁定后修复**，见 §5 的 R-009——
修复后两次实跑的诊断仍判通过，所以这次修复没有推翻本节的观测，只是把判据的口径收紧
到"指向工作负载这个对象"。

---

## 4. 我自己最不确定的部分

1. **n = 2 什么都证明不了。** 两次都对，不能推成"MONKEY 能诊断混沌故障"。要谈能力至少
   需要：多种故障类型（loss / DNS / Pod kill）、多种快照组织方式、多个模型。本次只做了
   "一次 NetworkChaos delay"这一格。**不确定**这与"MONKEY 在混沌场景下的行为边界"这个
   提法之间的距离有多大——我认为很大。

2. **200000 这个新上限，本次没有被验证过是否有用。** 第二次跑只用 105,837，连旧上限都
   没碰到。我们**不知道**第一次那条路径在 200000 下会不会干净收尾——因为没有重跑它，
   而且严格说**无法重跑**：LLM 不保证可复现，重跑得到的是另一个路径，不是同一条。
   所以偏离 3 的收益至今是"推理上成立、证据上没有"。**不确定。**

3. **事前预测 2 从未被验证。** 我曾在 D-2 那轮写过"60000 大概在第 8–10 步触发——那时
   MONKEY 可能还没看完快照，你会得到 `token_budget_exceeded`，而不是一份诊断"。因为
   上限改判为 150000，这条**一次都没有被检验**。它现在是一条悬空的历史陈述。

4. **花费仍是单点外推。** ≈0.21 元 / ≈0.14 元都来自阶段 2 冒烟那一次探针调用
   （in 788 / out 44 → 0.0012 元）的混合单价，**没有价目表背书**。两次合计 ≈0.35 元
   同样如此。审计早就点过"`prompt_cache_hit_tokens` 等缓存字段被客户端忽略"，
   而缓存命中率会直接改变单价——**未知量级可能是一个数量级。**

5. **截断参数是任意值。** `head_chars=3000` / `tail_chars=3000` / 阈值 8192 B 没有任何
   实验依据。换成别的值会不会让这个任务变得不可解或更容易，**没有测**。本次任务恰好
   落在一个"头尾都够不到、必须用命令"的窗口里，这个巧合值得警惕：**这个任务的难度有
   多大程度是截断参数造成的假象？** 我不确定。

6. **`workload` 判据偏松这件事的影响面。** §3.3 说了它偏松。但我**不确定**它偏松到了
   会放行错误诊断的程度——本次没有反例（两次都答得比要求更细）。要判断它，需要一次
   "故意给一个含糊但能过的答案"的对照，本次没做。

7. **模型是否受 `00-COLLECTED.md` 影响无法归因。** 两次都读了这份清单（第一次 step 2、
   第二次 step 3）。清单已不含泄漏句，但它仍然**列出了有哪些文件、每个文件"为什么有用"**
   ——这本身就是一份导航。没有对照组（例如一份只有文件名、没有说明的清单），**无法区分**
   "它自己从 1.8 MB 里找出来"与"清单指了路"。

8. **冷启动条件不可复现。** 镜像摘要、WSL 内存、Docker 版本都只在这一天这一台机器上核过。
   集群本身（`kind` 集群 `chaos`、`nginx-delay` 仍在生效）**未删除**，见 §6。

---

## 5. 明确保留的已知残差

本文档新增两条，已按台账"只增不改不删"的约定登记在 `docs/known-residues.md`。
裁定（2026-09-17）：**R-008 登记、不修；R-009 登记、并同时修判据**。

**R-008：成功收尾的那一步被预算检查丢弃时，轨迹缺少分类事件。**
- 是什么：`loop.py:88` 的用量检查排在动作分类（loop.py:92）之前。若次数在第 N 步
  因 `Finish` 之外的原因使累计用量越过上限，则该步的 `Finish` 被丢弃：轨迹里
  `agent_message` 为 0、该步无 `step_end`、`status = aborted`，而 `verification_status`
  可以是 `passed`。文本仍逐字存在于 `llm_response.content`（不走截断），丢的是"这是一次
  Finish"这个标记。
- 为什么不处理：修它必须改 `loop.py` 的检查顺序（冻结文件），代价是第 4 次基线移动；
  裁定已明确"不值得"。
- 影响：任何按 `agent_message` 或 `status` 判断"agent 是否给出了收尾陈述"的下游分析，
  在这个情形下会漏读或误读。

**R-009：`chaos-001` 的判据对 `workload` 只做子串匹配。**
- 是什么：`tasks/chaos-001/task.json` 的判据里 `'nginx' not in str(d['workload']).lower()`
  只要 `workload` 含 `nginx` 即通过，不校验它是否指向"受影响的工作负载"这个对象。
  于是 `nginx-svc`（Service）、`nginx-6559559688-ggv7d`（Pod 名）、`endpoints/nginx`
  都会被放行。
- 处理：**已修**（2026-09-17，与本批同提交）。新规则：alnum 归一后剥掉前后缀的
  `default`/`deployment`/`deploy` 令牌，余下必须**恰好等于** `nginx`。真值表从 10 例
  扩到 17 例，全部符合预期；**两次已归档的实跑诊断仍 `exit 0`**，故收紧不使任何历史
  证据失效。`task.json` 的 `description` 未改（改它等于改实验条件）。
- 影响：判据"通过"与"诊断正确"之间的这道空隙被收紧，但没被消除——`workload` 写成
  散文（如 `"nginx 三副本"`）仍会被判失败而不是被解析。

阶段 2 遗留、本次结束时**仍然开着**的（未逐条复核，只列我本次确实碰到的）：
R-007（提示词与工具 schema 是未版本化的实验条件）在本次**被实际踩到**——两次 run 的
`config_hash` 不同（13f4d51f / d87072db）但那是配置改动，而**任务描述、系统提示词、
工具 schema 这三样在两次之间逐字相同却没有任何哈希能证明这一点**。要证明"两次的
实验条件相同"，只能去比对两条 trace 里逐条 `llm_request.messages`/`tools` 全文。

---

## 6. 混沌实验结束时的状态（事实陈述）

```
95654e6 2026-09-17 20:38:33 +0800 MONKEY 混沌实验：max_total_tokens 150000 → 200000
636e56c 2026-09-17 19:48:05 +0800 混沌实验：环境交接 + 现场快照 + MONKEY 任务定义（版本 A：只诊断）
```

- 2 个提交，工作区干净（`git status --short` 只剩被忽略的 `thought/`）。
- 冻结面：`git diff --numstat 636e56c HEAD -- <5 个冻结文件>` **输出为空**，
  本次实验**一次基线移动都没有**（含上限改判那次）。
- 测试：`Ran 146 tests / OK`（`skipped=0`，Docker 在线）。
- 两次付费 run：`636e56c` 下的 13 步（超限）与 `95654e6` 下的 13 步（干净收尾），
  合计 ≈0.35 元（估算）。
- 环境未收尾：Kind 集群 `chaos` **未删除**，`NetworkChaos/nginx-delay` **仍在生效**
  （`duration: 30m`，自 2026-09-17T05:02:55Z 起，此刻应已自然过期——**未核实**）。
- 时段 2 建的两个离线段对照 run（`runs/ZCTL-chaos-positive`、`runs/ZCTL-chaos-negative`）
  **已按你的指令删除**，删除动作不进 git（`runs/` 被忽略）。

---

## 附：本文全部事实的可核验命令

```bash
# 提交
git log --format='%h %ci %s' -3

# 冻结面零改动（期望：无输出）
git diff --numstat 636e56c HEAD -- harness/contract.py harness/core/loop.py \
    harness/agent/base.py harness/tools/base.py harness/env/base.py

# 全套测试（期望：Ran 146 tests / OK）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover

# 快照里没有泄漏词（期望：两条都为 0；且 git log -S 无输出）
grep -c '故障注入\|networkchaos' tasks/chaos-001/repo/snapshot/00-COLLECTED.md
git log -S '故障注入' --oneline -- tasks/chaos-001/repo/snapshot/00-COLLECTED.md

# 两次 run 的三条复核（把 run_id 换成另一个即复核另一次）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace runs/20260917-124312-chaos-001-llm/trace.jsonl
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay \
    --run 20260917-124312-chaos-001-llm
# 判据原样直跑（两次都要过）。脚本从 task.json 运行时读出，全程不经过 bash 变量——
# 本机的 bash 在把中文脚本经变量转手时会破坏编码（实测报 SyntaxError: unterminated
# string literal），所以包装器自身必须只含 ASCII。
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import json,subprocess,sys
from pathlib import Path
cmd=list(json.loads(Path('tasks/chaos-001/task.json').read_text(encoding='utf-8'))['verify']['command'])
cmd[0]=sys.executable
for r in ('20260917-123127-chaos-001-llm','20260917-124312-chaos-001-llm'):
    p=subprocess.run(cmd,cwd=str(Path('runs')/r/'workspace'),capture_output=True,text=True,encoding='utf-8',errors='replace')
    print(r,'-> exit',p.returncode,'|',p.stdout.strip())
"

# 判据的可复算部分：两次 run 各自的 verification 原始输出
cat runs/20260917-123127-chaos-001-llm/verification/verify.stdout.txt
cat runs/20260917-124312-chaos-001-llm/verification/verify.stdout.txt

# 归档副本与源文件逐字节一致（期望：无输出；本目录 10 份全部如此核过）
cmp docs/evidence/chaos-001/01-run1-token-budget-exceeded.trace.jsonl \
    runs/20260917-123127-chaos-001-llm/trace.jsonl
cmp docs/evidence/chaos-001/06-run2-completed.trace.jsonl \
    runs/20260917-124312-chaos-001-llm/trace.jsonl

# 归档副本可独立校验（不依赖 runs/ 是否还在）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/chaos-001/01-run1-token-budget-exceeded.trace.jsonl
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/chaos-001/06-run2-completed.trace.jsonl
```
