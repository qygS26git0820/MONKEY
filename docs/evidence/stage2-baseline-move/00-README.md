# 冻结基线的第一次移动（2026-09-13）

## 为什么必须移

`harness/core/loop.py` 在冻结清单里，而阶段 2 必须让它做两件事：把 `run_end.totals`
里的三个 `None` 换成真值，以及在累计用量越过预算时以 `cost_budget_exceeded` 终止。
冻结一个注定要长功能的文件是设计漏洞，现在补的代价是一次文档登记，进阶段 2 之后再补
的代价是冻结机制本身的可信度。

## 为什么只移一次

`loop.py` 对 token 与成本的**全部**知识这一次就定稿：

1. 读取侧——`totals` 从 `run_ctx.usage` 取；
2. 两处预算检查的**调用点**——一轮开头（在墙上时钟检查**之前**，因为
   `trace-schema.md` §1.2 把 `cost_budget_exceeded` 排第 4、`timeout_wall` 排第 5）
   与 `agent.next_action()` 返回之后。

被调用的东西（累计写入、`exceeded()` 的判定、预算配置项）全部落在非冻结文件里，
由下一个提交实现。若把调用点留到那时才加，`loop.py` 就会被改第二次、基线要移两次。

`harness/core/usage.py` 在本次提交里**只有读取侧，没有 `record()`**：三个累计量恒为
`None`、`exceeded()` 恒为 `False`。于是"移动不改变行为"不是靠承诺，是靠结构。

## 逐文件

| 文件 | 产生方式 | 说明 |
| --- | --- | --- |
| `01-before-after-traces.txt` | `tmp/cmp-traces.py ab-local mv-local [harness_git_sha]` | 8 组对照逐字段比较，两遍 |
| `02-run-id-length-confound.txt` | 同上，前缀长度不等的那一版 | 一条方法论发现 |
| `03-totals-unchanged.txt` | 从两批 run 的 `run_end` 抽 `totals` | 移动直接触碰的字段 |
| `04-freeze-diff.txt` | `git diff 3342dcf --stat/-- <冻结文件>` | 只有 `loop.py` 动，diff 即移动全文 |
| `05-tests.txt` | 全套件 + 三重机械保障子集 | 67 项通过 |

`tmp/cmp-traces.py` 与 `tmp/run-controls.sh` 在 `.gitignore` 覆盖的 `tmp/` 下，
不随证据提交；命令与输出都在上面。

## 结论与它成立的条件

**结论**：8 组对照、共 104 条事件，移动前后的轨迹差异**只有 `run_start.harness_git_sha`
一个字段**；把它也抹掉后逐字段零差异。`totals` 三个键在两批里都是 `None`。

**它成立的条件**（不满足则这个比较无效）：

1. **两批 run 的 `run_id` 前缀必须等长。** 第一版用了 9 字符对 3 字符，结果每组失败
   场景多出 12 字节差——那是路径长度进了 `bytes_total`，与行为无关。见 `02`。
2. **`harness_git_sha` 是构建来源字段，不是行为字段。** 两批的文件内容相同
   （`ab-local-*` 产生于 `4e824e0` 的内容上，只是当时 HEAD 还指向 `a5568b1`），
   所以这一个字段的差异是提交顺序造成的，不是移动造成的。它在第一遍里被**如实列出**，
   没有一开始就抹掉。
3. 归一化口径沿用 `tests/test_determinism.py`：抹时间戳、耗时、`run_id`、子进程自报
   耗时、由它派生的 `sha256_*`、以及源目录绝对路径。

`before` 用的是 `4e824e0` 那批 run 而不是新跑的，因为文件内容相同、重跑无新信息；
但这也意味着 `before` 的 `harness_git_sha` 记的是 `a5568b1`——这正是条件 2 的由来。
