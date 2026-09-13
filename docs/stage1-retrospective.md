# 阶段 1 复盘

- 覆盖范围：阶段 0 的收尾复核，阶段 1 的设计、实现、回填、验证
- 证据：`git log`、`runs/` 下的运行产物、`runs/env-20260912-123911/raw/` 下的阶段 0 原始证据
- 你给的写作约束：只写实际发生的事；引用 `git log` 或 `raw/` 证据；不确定就写"不确定"；不使用表功性质的措辞（你原话点名了两个词，本文刻意不复述）；明确列出偏离设计文档的地方；D10 单列，不轻描淡写

---

## 0. 先说一处必须声明的不确定：结构

你说"按之前定的结构"。我在本次会话的全部可见记录（含两次上下文压缩留下的摘要）里检索"复盘""回顾""结构"等词，**没有找到一份我们约定过的复盘结构**。

我不确定这是哪一种情况：结构定在会话记录之外，还是我检索时漏了。

因此本文档的结构是我按你本次给的六条约束反推的：

1. 证据来源（以及哪些证据不在版本控制里）
2. 实际发生了什么
3. 偏离设计文档的地方
4. D10 单列
5. 其它没做到或返工的事
6. 我不确定的地方
7. 明确保留的残差

如果结构与你的预期不符，指出后我重排；内容不需要重做，因为约束已经规定了内容。

---

## 1. 证据来源与它是否在版本控制里

| 证据 | 位置 | 在 git 里吗 |
|---|---|---|
| 两次提交 | `git log`：`3342dcf`、`15d7ba4` | 是 |
| 阶段 1 运行产物（轨迹、报告、验证原始输出） | `runs/<run_id>/`，30 个 run 目录 | **否**，`runs/` 被 `.gitignore` 覆盖 |
| 阶段 0 原始证据 | 原件 `runs/env-20260912-123911/raw/`（20 个文件）；固化副本 `docs/evidence/stage0-raw/` | 原件**否**；副本**是**（2026-09-13 固化，见下） |
| 反证与自检留下的样本 | `tmp/settings.py.bak`（11 B）、`tmp/corrupt-trace.jsonl`（15 行）、`tmp/contract.py.bak`（2576 B） | **否**，`tmp/` 被 `.gitignore` 覆盖 |
| 冻结契约快照与阶段 1 样本轨迹 | `tests/fixtures/` | 是 |
| 被跟踪文件总数 | `git ls-files` | 61 |

**这里有一个我此前没有对你明说的性质：可复核的原始证据大部分不在版本控制里。**

阶段 0 的环境报告用"每条结论都能追到 `raw/NN`"作为可信度论据，但 `raw/` 落在被忽略的 `runs/` 目录下。它现在仍在磁盘上（我没有动过），换机器、或清空 `runs/`，它就没了；而 `docs/env-report.md` 会留在仓库里，指向一批不存在的文件。

这不是设计文档的偏差（设计文档 §4 的哈希自证测试只覆盖 `harness/ configs/ tasks/`，本来就不管 `runs/`）。但它是**证据链的一处脆点**，我认为应该在阶段 2 开始前处理。

### 处置（2026-09-13，你决定）

- 阶段 0 的 `raw/` **逐字节复制**到 `docs/evidence/stage0-raw/`，纳入版本控制；附 `README.md` 说明来源、编码与校验方式。副本与原件已核对逐字节一致（20/20）。
- **没有转码**：其中 4 个文件为 GBK 可解码，3 个既非 UTF-8 也非 GBK。转码会改变字节，证据就不再是原始字节。
- `runs/` 仍在 `.gitignore` 里——**每次实验的轨迹属运行产物，不进 git**；只有阶段 0 这份"项目起点"的证据被固化。
- 原件未改动，仍在 `runs/env-20260912-123911/raw/`。

核验命令：

```bash
git log --format='%h %ci %s'
git show --stat 3342dcf | tail -3
git show --stat 15d7ba4 | tail -3
ls runs/env-20260912-123911/raw/ | wc -l
git ls-files | wc -l
```

---

## 2. 实际发生了什么

时间均为本机时区（+0800）。只列有据可查的节点。

| 时间 | 发生了什么 | 证据 |
|---|---|---|
| 09-12 12:39–12:52 | 阶段 0 环境审计执行，产出 `docs/env-report.md` 与 `raw/01`–`raw/15`。其中注册表探测用错方法，失败样本保留为 `raw/05b`–`raw/05e`，改用 `raw/05f` 的 `.bat` 才拿到可信结果 | `raw/` 下 20 个文件；`env-report.md` 中对该次自我纠错有记录 |
| 09-12 13:29–13:41 | 初始化 git 仓库、`.gitignore`、目录骨架 | `.gitignore` 内容 |
| 09-12 13:35–13:58 | 阶段 1 实装；8 组脚本化对照跑通；测试套件与 fixtures 落盘 | 提交 `3342dcf`，60 files changed, 3214 insertions |
| 09-12（`3342dcf` 之前） | 发现 `time.monotonic()` 在本机的分辨率是 16 ms，`time.perf_counter()` 是 100 ns；新增 `harness/clock.py` 并把 6 处计时调用迁移过去。**这是返工，不是新增功能** | `git show 3342dcf --stat` 里有 `harness/clock.py`；分辨率本次重测复核，输出见下 |
| 09-13 09:50–10:37 | 给你独立验证指引（命令 + 预期输出 + 应读文件 + 三条故意失败检查） | 会话记录 |
| 09-13 10:37–10:39 | 回填 9 处文档-实现偏差；同批修正 D11/D12；补 D10 漏写的测试 | 提交 `15d7ba4`，2 files changed, 191 insertions(+), 41 deletions(-) |
| 09-13 10:38–10:46 | 对新增的无污染测试做反证（向任务模板注入一个字节 → 被检出 → 还原），留下 `tmp/settings.py.bak` 等样本 | `tmp/` 下文件 |
| 09-13（你侧） | 你手动跑完三条故意失败检查，回报结果：检查 A 报 7 个问题退出码 1；检查 B `FAILED (failures=2)` 退出码 1，还原后 `git status --short` 无输出；检查 C 同一秒两次，退出码 0 与 2 | **你的报告，我没有复跑这三条** |

时钟分辨率，本次重测（非引用旧结论）：

```
time.monotonic   min delta: 0.016000000 s
time.perf_counter min delta: 0.000000100 s
```

当前仓库状态（本次复核）：

```
15d7ba4 2026-09-13 10:39:55 +0800 回填 9 处文档-实现偏差
3342dcf 2026-09-12 13:58:06 +0800 阶段 1：可观测 harness 骨架（零依赖，8 组对照全中）

作者: qygS26git0820 <3223218075@qq.com>（两次提交一致，local config）
测试: Ran 57 tests in 5.430s, OK
工作区: git status --short 无输出
```

---

## 3. 偏离设计文档的地方

偏离分两类。**第一类是措辞层**——文档写的是另一件事，代码是对的。**第二类是性质层**——文档描述的性质本身不成立，代码也只能改成较弱的性质。第二类比第一类严重，D7 属于第二类。

### 3.1 措辞层：D1–D6、D8、D9、D11、D12

| # | 文档原表述（错） | 修正后 | 实装位置 |
|---|---|---|---|
| D1 | §5.3/§10：`run_end` 通过 `finally` 保证写出 | 由 `except KeyboardInterrupt` + `except Exception` 穷尽后无条件落盘；`BaseException` 不在覆盖内 | `harness/core/loop.py:135`、`:137`、`:171` |
| D2 | §5.4 冻结清单只列 4 个文件 + `trace.py` 字段 | 清单以 `harness/contract.py` 为首 | `harness/contract.py`；`tests/test_contract.py` |
| D3 | §5.3 配置项 `max_stdout_bytes` | 实为 `truncate_threshold_bytes`/`head_chars`/`tail_chars` 等 | `configs/default.toml`；`harness/config.py` |
| D4 | §6/§11：失败标签 10 个 | 12 个 | `harness/contract.py` |
| D5 | §2/§8：`task.json` 含 `faulty_patch` 字段 | 只有 `id/description/repo/verify`；负向对照是 `repo_faulty/` 目录 + `--variant` | `harness/tasks/loader.py`；`harness/runctx.py:34` |
| D6 | §3/§8.1：三种假 agent | 六种 | `harness/agent/scripted.py` |
| D8 | §6 表：`tool_call` 含 `executor` | `executor` 在 `run_start` | `harness/contract.py` |
| D9 | §6 表：`stdout_bytes`/`stdout_truncated`，截断"只存头部" | 嵌套的 `stdout_stream`/`stderr_stream`，策略 head+tail | `harness/trace.py` |
| D11 | §2 目录树列了 `fs_read.py`/`fs_write.py`/`run_shell.py`/`run_tests.py`/`eval/metrics.py` | 实为 `fs_tools.py`/`shell_tools.py`；`metrics.py` 不存在 | 目录树按实重写 |
| D12 | 文档头"状态：待你评审，未写任何代码" | "状态：已实现" | 文档头 |

D2 是这批里后果最直接的一条：它是**唯一一处会让你的验收条件失效的偏差**。原清单漏掉 `contract.py`，而事件名与字段的真源在那个文件里——按原清单做 `git diff`，最该冻的东西反而在验收范围之外。你在决策时也点了这一条。

### 3.2 性质层：D7

原表述（§3、§8、§10、§12 四处）：重跑"去掉时间戳后轨迹**逐字节一致**"。

这个性质**不成立**，而且不是实现没做到，是它写下来的时候就错了。两类抖动无法从源头消除：

1. 验证子进程**自报**的 unittest 运行时长（`Ran 2 tests in 0.000s` 里的数字）及其派生的 sha256；
2. 失败用例回溯里嵌的**工作区绝对路径**——而工作区路径含 `run_id`，由 `unittest` 自己打印，不由 harness 控制。

第 2 条在阶段 2/3 会变形：换容器后端后同一段输出变成 `/workspace/...`，**agent 看到的自身失败信息会随后端而变**。这不是测试的缺陷，是被观测的现实。

修正后的表述是"**动作序列一致**"，并把上面两条抖动来源写进文档。现象本身没有被藏起来——它被钉成了断言（`tests/test_determinism.py::test_failure_output_embeds_run_path`），这样将来换后端时这条会主动提醒重估，而不是被静默地归一化掉。

我此前把这条列为"文档偏差"之一是**低估了它的性质**：它不是文档跟不上代码，是设计文档承诺了一个不可保的性质。

### 3.3 交付遗漏：D10

见 §4，单列。

---

## 4. D10：上一轮"文档-实现一致"这个结论不成立

这一节按你的要求写清楚，不轻描淡写。

**上一轮我说了什么。** 阶段 1 实现完成后，我向你报告文档与实现一致。这个结论当时是错的。

**实际是什么。** 设计文档 §3 的交货物表 D6 行与 §4 第 4 点，白纸黑字承诺了一个"哈希自证测试"：跑完任务后，`harness/ configs/ tasks/` 的文件哈希清单必须与运行前逐条一致，并明确指向 `tests/test_no_pollution.py`。**这个文件当时不存在。** 承诺存在，实现在。我上一轮汇报时没有核到这一处。

**这一轮怎么发现的。** 不是靠重跑测试发现的——测试当时全绿，因为它们不检查"文档承诺的测试是否存在"。是靠回填 D1–D9 时**逐节重读设计文档**，读到 §4 才撞上：文档点名了一个文件，而这个文件在目录里没有。

**我做了什么。** 按"文档-实现一致"的标准，选择**补测试而不是删承诺**。新增 `tests/test_no_pollution.py`，断言跑完 4 组场景后 `harness/ configs/ tasks/` 的哈希清单逐条不变（`__pycache__` 除外），并单独断言最要紧的那条：agent 的修复写进的是副本，不是任务模板。

**为什么这条测试必须做反证。** 一个从不失败的测试等于没有测试。所以我往 `tasks/toy-002/repo/settings.py` 注入了一个字节，清单立刻检出该文件；还原后哈希复原。留下的 `tmp/settings.py.bak` 就是这个过程的副产物。

**这条意味着什么。** 有三点，我认为都成立：

1. 我上一轮的"文档-实现一致"是一个**未经核对的结论**，不是谎言，但也不是证据。你按那个结论往下走，就会带着一个假的已核项进阶段 2。
2. 发现它的机制不是测试（测试不会检查自己被承诺过），是**逐节重读文档**。也就是说这一类遗漏只能靠人工重读发现，机械手段拦不住。这一点应该反过来影响阶段 2 的验收设计：**"文档承诺但代码里没有"这类偏差，需要一条专门的检查**，我想不出自动化的办法，不确定有没有。
3. 它恰好证明了你要求"回填"这个动作的价值。如果当时只把 D1–D9 当措辞问题随手改掉、不逐节重读全文，D10 不会被发现，D11/D12 同样不会。

---

## 5. 其它没做到或返工的事（不属于文档偏差）

这些不是文档写错，是实装期的返工或操作性发现，同样记下来。

| 事项 | 性质 | 处置 |
|---|---|---|
| `time.monotonic()` 在本机分辨率 16 ms；轨迹里的耗时被量化成 0/15/16 ms，`ts_mono` 在相邻事件上塌成同一个值 | **真实缺陷**。耗时是你三个一等观察目标之一，量化过的耗时数据是不可用的 | 新增 `harness/clock.py`（`perf_counter` 计时、`time.time` 对齐墙上时钟），迁移 6 处调用点。本次重测复核分辨率差异仍在 |
| `run_id` 是秒级粒度（`YYYYMMDD-HHMMSS-<task>-<agent>`），同一秒内跑同一个任务同一个 agent 会撞名 | 设计如此（拒绝覆盖），但对批量脚本是操作性麻烦 | 未改。撞名时退出码 2 并打印"run_id 已存在"，可用 `--run-id` 显式指定绕过 |
| `validate-trace` 指向非 run 目录（如 `runs/env-20260912-123911`）时抛 traceback 而非干净报错 | 实装疏漏 | 加 `is_dir()`/`is_file()` 判断与 `OSError`/`UnicodeDecodeError` 捕获，改为退出码 2 |
| `TraceWriter.emit` 一度误报 `ContractViolation: step_end 缺少必需字段 ['step']`，因为校验只看 `**fields`、漏掉了具名参数 `step` | 实装缺陷，会让每次 run 都以 `harness_error` 收尾 | 改为先组装完整 record 再校验，`step` 纳入 record |
| 我未能让提交信息与你给的指令字面一致 | 见下 | 见下 |

最后一条展开说：你要求提交信息为 `"回填 9 处文档-实现偏差 + 自查发现 D10–D12"`。实际提交的**标题**是 `回填 9 处文档-实现偏差`，D10–D12 在**正文**里分节写清楚（"补齐一处交付遗漏 D10"、"同批修正的两处额外偏差 D11/D12"）。标题少了 `+ 自查发现 D10–D12` 这半句。

我没有为此再建一个提交，也没有 amend（你明确禁止）。理由：`15d7ba4` 已包含全部内容，补一个空提交只会让历史里多一条无内容的记录，并且会让人误以为有第三次改动。**如果你要标题字面一致，那只能用 amend 改写 `15d7ba4` 的信息——这一步需要你明确授权，我不会自己动。**

---

## 6. 我不确定的地方

- **复盘结构**：见 §0。（2026-09-13 你已确认：结构由我按六条约束反推，认可，不用改。）
- **`tmp/corrupt-trace.jsonl`（15 行）与 `tmp/contract.py.bak` 的产生时刻**：文件时间戳是 09-13 10:45/10:46，落在回填提交之后。我可以确定它们是我在回填期间做自检时的样本，但不能确定具体是哪一次操作产生的，因此没有在本文里给它们指派用途。
- **阶段 0 `raw/` 中 `05`/`05a` 缺失**（编号从 `04` 直接跳到 `05b`）：不确定是被清理了，还是本来就没生成。`env-report.md` 里没有交代这两个编号。
- **标签覆盖的口径**：`docs/stage1-design.md` §6 第 2 点里我写过"阶段 1 的测试真实走通了其中 11 个"。这个 11 是**测试断言覆盖**，不是"真实运行中出现过"。我没有逐条统计过 30 个 run 目录里实际出现过哪些标签，因此不确定"11/12"在两种口径下是否都成立。

---

## 7. 明确保留的已知残差

前两条写进了 `docs/stage1-design.md` §13，不是本文档独家；第三条发生在这份设计文档冻结之后，登记处改在阶段 2 的证据目录：

1. **`run_end` 的 `BaseException` 缺口**。`SystemExit`/`GeneratorExit` 会同时漏掉 `run_end` 与 `run_ctx.close()`。阶段 1 没有任何代码路径会抛这两类异常，所以本阶段未修；阶段 2 若引入，在 `loop.py` 外层补 `finally`。
2. **跨后端失败输出的可比性**。见 §3.2 第 2 条。阶段 2 切容器后端时必须重新评估，否则"agent 看到的自己失败的原因"会随后端而变。
3. **`harness/env/base.py` 的 docstring 已过时（2026-09-13 登记）**。它写着"阶段 3 增加 DockerExecutor"，而容器后端按决定被提前到阶段 2 落地。该文件在冻结清单内，故意不改：一次 docstring 修改不值得单独移动冻结基线；阶段 2 若因其它理由动 `base.py`，与那次改动合并做一次基线移动。登记处：`docs/evidence/stage2-docker/00-README.md` 限制第 3 条。

第 2 条的实测已经落地：`docs/evidence/stage2-docker/05-replay-path-diff.txt` 里同一个 `read_file` 在 local 记 `workspace`、在 docker 记 `/workspace`。第 3 条与 D7/D10 同性质——冻结一个文件，就同时冻结了它已经过时的陈述。

这三条我**没有偷偷抹掉，也没有在文档里软化**，它们各自有一条测试或一节文档盯着。

---

## 8. 阶段 1 的当前状态（事实陈述）

- 两次提交，工作区干净，57 项测试通过（`Ran 57 tests in 5.430s, OK`）
- 冻结清单的五个文件（`contract.py`、`core/loop.py`、`agent/base.py`、`tools/base.py`、`env/base.py`）与 `3342dcf` 提交时一致，无未提交改动（`git status --short` 为空可证）
- 8 组脚本化对照的 failure_class 与设计一致；12 个标签中 11 个有测试断言覆盖，`cost_budget_exceeded` 在阶段 1 结构上不可达（无 LLM 即无 token）
- 你侧的两轮独立验证（阶段 0 三条环境复核、阶段 1 三条故意失败检查）均已完成，结果由你报告

**未进入阶段 2。** §0（结构）与 §1（`raw/` 固化）均已由你于 2026-09-13 处置完毕，见对应小节。

---

## 附：本文全部事实的可核验命令

```bash
# 提交与统计
git log --format='%h %ci %an <%ae> %s'
git show --stat 3342dcf | tail -3
git show --stat 15d7ba4 | tail -3

# 工作区与测试
git status --short
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests -t .

# 证据是否在版本控制里（预期：均无输出，因为它们被忽略）
git ls-files runs/ tmp/

# 时钟分辨率（预期：monotonic 约 0.016s，perf_counter 约 0.0000001s）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe - <<'EOF'
import time
def min_delta(f, n=200000):
    t0 = f(); best = 1e9
    for _ in range(n):
        t1 = f(); d = t1 - t0
        if 0 < d < best: best = d
        t0 = t1
    return best
print("time.monotonic   min delta: %.9f s" % min_delta(time.monotonic))
print("time.perf_counter min delta: %.9f s" % min_delta(time.perf_counter))
EOF

# 文档偏差的回填位置
grep -n 'D10\|D11\|D12\|明确保留的已知残差' docs/stage1-design.md
```
