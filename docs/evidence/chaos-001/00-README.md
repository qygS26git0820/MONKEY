# 证据：混沌实验（chaos-001）

- 日期：2026-09-17
- 前置：`636e56c`（环境交接 + 现场快照 + 任务定义）、`95654e6`（上限改判 150000→200000）。
- 本目录是 **MONKEY 第一次跑非玩具任务**的留档。阶段 2 的冒烟是 4 步的 `toy-001`；
  这里是 13 步、工作区里躺着 1.9 MB 现场快照的诊断任务。

`runs/` 被 `.gitignore` 覆盖，所以把两次 run 的关键产物复制进来。**本次与阶段 2 的冒烟
有一个差别：必须连 `blobs/` 一起复制**——两次 run 各有一次工具输出被截断，被丢弃的
字节只存在于 `blobs/<sha>.blob` 里。只存 trace 的话，`stdout_stream.blob_ref` 会指向
一个不存在的文件，截断就只剩一个计数器、看不到被截断的内容。

| 文件 | 是什么 |
|---|---|
| `01-run1-token-budget-exceeded.trace.jsonl` | 第 1 次 run 的完整轨迹（83 条记录，逐字节复制） |
| `02-run1-token-budget-exceeded.report.md` | 由轨迹派生的文本报告（逐字节复制） |
| `03-run1-token-budget-exceeded.diagnosis.json` | 该 run 产出的诊断（判据判定对象，1,421 B） |
| `04-run1-token-budget-exceeded.verify.stdout.txt` | 判据进程的原始 stdout（86 B；stderr 为空） |
| `05-run1-token-budget-exceeded.blob-events.txt` | 被截断的那份输出的**全文**（events 文件，57,651 B） |
| `06-run2-completed.trace.jsonl` | 第 2 次 run 的完整轨迹（78 条记录，逐字节复制） |
| `07-run2-completed.report.md` | 同上（4,383 B） |
| `08-run2-completed.diagnosis.json` | 该 run 产出的诊断（1,613 B） |
| `09-run2-completed.verify.stdout.txt` | 判据进程的原始 stdout（86 B） |
| `10-run2-completed.blob-grep.txt` | 被截断的那份输出的**全文**（模型自己的 grep 结果，85,400 B） |

原 run 目录（未入库）：`runs/20260917-123127-chaos-001-llm/`、
`runs/20260917-124312-chaos-001-llm/`（各自含 `workspace/`、`verification/`、`blobs/`、
`meta.json`）。两次的 harness git sha 分别是 `636e56c4…` 与 `95654e63…`，Python 3.12.13，
执行后端 `docker`（镜像 `python:3.12-slim`）。

> 注：`04`/`09` 是**收紧判据之前**那两次运行留下的原始输出。判据在 2026-09-17 收紧过
> （见 `docs/known-residues.md` R-009），但收紧只改**失败**情形的行为——两次 run 都是
> 通过，用收紧后的判据在同一个工作区重跑，得到的 stdout 与归档的这两份逐字相同。

`workspace/snapshot/` **没有**复制进来：它由 `runctx.py` 从 `task.repo_dir` 复制而来，
与已入库的 `tasks/chaos-001/repo/snapshot/` **逐字节一致**。可复核：

```bash
diff -r tasks/chaos-001/repo/snapshot runs/20260917-124312-chaos-001-llm/workspace/snapshot
# 期望：无输出
```

## 一、两次 run 的结果

```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness run \
    --task chaos-001 --agent llm --config chaos
```

| 项 | 第 1 次 | 第 2 次 |
|---|---|---|
| run_id | `20260917-123127-chaos-001-llm` | `20260917-124312-chaos-001-llm` |
| `config_hash` | `13f4d51f…`（上限 150000） | `d87072db…`（上限 200000） |
| `failure_class` / `status` | `token_budget_exceeded` / `aborted` | **`none` / `completed`** |
| `verification_status` | **`passed`** | **`passed`** |
| 步数 | 13 | 13 |
| `llm_request` / `llm_response` | 13 / 13 | 13 / 13 |
| `tool_call` / `tool_result` | 21 / 21 | 18 / 18 |
| `step_end` / `agent_message` | 12 / **0** | 12 / 1 |
| tokens | in 149,978 / out 3,395 = **153,373** | in 102,882 / out 2,955 = **105,837** |
| 墙钟 | 27.7 s | 29.5 s |
| 估算花费 | ≈0.21 元 | ≈0.14 元 |

**第 1 次的三个反常是同一个机制**：`loop.py:88` 的用量检查排在动作分类
（loop.py:92）之前，第 13 步的累计用量 153,373 > 150,000，于是循环在识别
`Finish` 之前就 `break` 了。后果是 `agent_message` 为 0、该步无 `step_end`
（`steps=13` 而 `step_end=12`）、`status=aborted`。**但那条 `Finish` 的文本没有丢**：
它逐字存在 `01` 的 `seq 81` 号 `llm_response.content` 里（342 字符，
`llm_response` 不走截断）。细节与代价见 `docs/chaos-retrospective.md` §1.3 偏离 2 与
残差 R-008。

## 二、两次 run 的截断事件（各只有一次）

| run | 截断发生在 | 工具 | `bytes_total` | 送达 | 丢弃 | 全文在哪 |
|---|---|---|---|---|---|---|
| 第 1 次 | **step 3** | `read_file`（events 文件） | 57,651 | 6,031 | 51,651 | `05` |
| 第 2 次 | **step 9** | `run_command`（模型自己的 grep） | 85,400 | 6,031 | 79,400 | `10` |

送达量都是 6,031 B（头 3000 字符 + 尾 3000 字符 + 31 字符的截断标记）。第 2 次被丢弃的
字节**更多**，但整体更便宜：截断发生在第 9 步而不是第 3 步，那 6,031 字节被重发的次数
从 9 次降到 3 次。这是 `token_budget_exceeded` 那次与 `none` 那次之间最主要的量级差来源
（详见复盘 §2.2）。

## 三、这份证据证明什么、不证明什么

**证明**：

- MONKEY 在**非玩具任务**上能给出**正确且被判据接受**的诊断：两次 `diagnosis.json`
  的 `root_cause_kind`/`namespace`/`workload` 均与 `docs/env-handoff.md` 的 ground truth
  一致，判据两次 `exit 0`。
- 判据是**外部证据**，不是 agent 自述：`04`/`09` 是判据进程自己的 stdout，且可用
  `task.json` 里那段脚本在 run 的工作区里**绕过 harness** 重跑复现。
- 观测面完整：每条 `llm_request` 带当时的完整 `messages`/`tools`，每条 `tool_result`
  带 `stdout_stream`（含 `blob_ref`/`bytes_total`/`elided_bytes`），截断可离线复核。

**不证明**：

- **n = 2，同一个任务、同一个模型**。两次都对，不能推成"MONKEY 能诊断混沌故障"。
  本次只有"一次 NetworkChaos delay"这一格，没有 loss / DNS / Pod kill，没有跨模型。
- **200000 这个上限没有被验证过是否有用**：第 2 次只用 105,837，连旧的 150,000 都没碰到。
  第 1 次那条路径在新上限下会不会干净收尾，**没有重跑**（LLM 不保证可复现，严格说也
  无法重跑同一条路径）。
- **判据通过 ≠ 诊断正确**：判据对 `workload` 只做子串匹配（含 `nginx` 即可）。两次都
  答得比要求更细，所以这个宽松没有被暴露成问题。见复盘 §3.3 与残差 R-009（**已修**；
  修完后本目录两 run 的诊断仍判通过）。
- **花费是估算**：≈0.21 / ≈0.14 元来自阶段 2 探针的单点混合单价外推，没有价目表背书。
- **截断参数是任意值**：`head_chars=3000` / `tail_chars=3000` / 阈值 8192 B 无实验依据。

## 四、独立复核命令（离线、零成本）

```bash
# ① 轨迹合法（本目录里不是默认名 trace.jsonl，要指到文件本身）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/chaos-001/01-run1-token-budget-exceeded.trace.jsonl
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness validate-trace \
    --trace docs/evidence/chaos-001/06-run2-completed.trace.jsonl

# ② 回放到终端（第 1 次末行 END status=aborted failure_class=token_budget_exceeded steps=13；
#    第 2 次末行 END status=completed failure_class=none steps=13）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay \
    --run runs/20260917-123127-chaos-001-llm
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m harness replay \
    --run runs/20260917-124312-chaos-001-llm

# ③ 绕过 harness，用 task.json 里那段判据在 run 的工作区里直跑（期望两次都 exit 0，
#    输出"命中: 根因类型 / 命名空间 / 受影响工作负载 三者均与现场一致"）。
#    两个坑，都实测踩过：①判据脚本从 task.json 运行时读出，包装器自身必须只含 ASCII
#    ——本机 bash 把中文脚本经变量转手会破坏编码（报 SyntaxError: unterminated
#    string literal）；②路径要在 subprocess 里给绝对/仓库根相对的，别在 bash 里 cd。
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import json,subprocess,sys
from pathlib import Path
cmd=list(json.loads(Path('tasks/chaos-001/task.json').read_text(encoding='utf-8'))['verify']['command'])
cmd[0]=sys.executable
for r in ('20260917-123127-chaos-001-llm','20260917-124312-chaos-001-llm'):
    p=subprocess.run(cmd,cwd=str(Path('runs')/r/'workspace'),capture_output=True,text=True,encoding='utf-8',errors='replace')
    print(r,'-> exit',p.returncode,'|',p.stdout.strip())
"

# ④ 归档副本与源文件逐字节一致（期望：无输出）
cmp docs/evidence/chaos-001/01-run1-token-budget-exceeded.trace.jsonl \
    runs/20260917-123127-chaos-001-llm/trace.jsonl
cmp docs/evidence/chaos-001/06-run2-completed.trace.jsonl \
    runs/20260917-124312-chaos-001-llm/trace.jsonl
```

第 ③ 条是关键：它绕过 harness 直接对 agent 留下的工作区跑判据，所以"诊断正确"由外部
证据背书，而不是由 `agent_message` 的自述背书。

## 五、未覆盖 / 交给后续

- **故障类型只有一种**：`NetworkChaos` + `action: delay`。loss / DNS / StressChaos /
  Pod kill 都没跑。
- **判据偏松的影响未验证**：没有"故意给含糊但能过的答案"的对照。
- **截断参数的敏感性未测**：换个 `head_chars`/`tail_chars` 这个任务会不会变难，未知。
- **`00-COLLECTED.md` 的导航作用未隔离**：两次都读了它，所以"它自己从 1.8 MB 里找出来"
  与"清单指了路"无法区分。
- **环境未收尾**：Kind 集群 `chaos` 未删除，`NetworkChaos/nginx-delay` 未删除
  （`duration: 30m`，自 2026-09-17T05:02:55Z 起，此刻是否已自然过期**未核实**）。
