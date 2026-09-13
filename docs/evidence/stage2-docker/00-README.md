# 阶段 2 第一步（容器后端）的证据

固化日期：2026-09-13。来源是**工作区**，不是某次 `runs/` 里的一次实验：
`runs/` 在 `.gitignore` 里，随实验堆积而消失，所以能被复核的只有这里的抓取。

## 逐文件来源

| 文件 | 产生方式 | 说明 |
| --- | --- | --- |
| `01-pull-python.txt` | `docker pull python:3.12-slim` | 走 daemon.json 里记录的 mirror |
| `02-container-probe.txt` | 一次 `docker run` 探针 | 版本、unittest 可用、bind mount 是否双向 |
| `03-controls-docker.txt` | `bash tmp/ab-controls.sh docker docker controls-docker.txt` | 8 组对照，`--config docker` |
| `04-controls-local.txt` | 同上，`--config default` | 同一张脚本、同一个期望列 |
| `05-replay-path-diff.txt` | 从两条轨迹里抽 `tool_call`/`verification` 的 cwd | 唯一逐事件可见的跨后端差异 |
| `06-freeze-diff.txt` | `git diff 3342dcf --name-only -- <5 个冻结文件>` | 空输出即冻结清单零改动 |

`tmp/ab-controls.sh` 在 `.gitignore` 覆盖的 `tmp/` 下，故不随证据提交；
`03`/`04` 两个文件里已经包含它跑出来的完整结果，脚本本身可从上表的命令行重建。

## 必须一并读的三条限制

1. **这批抓取的 HEAD 是 `3342dcf`，但工作区比 `3342dcf` 多。**
   阶段 2 第一步的改动尚未提交，而 `meta.json` 里的 `harness_git_sha` 取的是
   `git rev-parse HEAD`，于是它对这些 run 记的是 `3342dcf`——一个**不含**
   `harness/env/docker.py` 的提交。因此这批证据无法只靠 `3342dcf` 复现；
   它对应的真实树是 `3342dcf` + 本次未提交改动。
2. **`meta.json` 的 `python_version` 是宿主的版本，不是容器里的。**
   容器里跑验证的是镜像自带的解释器（`02` 记的是 3.12.14）。这里没有多起一个
   容器去问它，故不声称知道；需要容器内版本时以镜像 tag/digest 为准。
3. **已知残差：`harness/env/base.py` 的 docstring 现在说错了话。**
   它写的是"阶段 1 只有 LocalExecutor；阶段 3 增加 DockerExecutor"，
   而按决定容器后端被提前到了阶段 2。该文件在冻结清单里，**故意不改**：
   一次 docstring 修改不值得单独移动冻结基线；若阶段 2 因其它缘故要动
   `base.py`，把这处措辞与那次改动合并做一次基线移动。
   这与阶段 1 复盘里的 D7/D10 同一性质：冻结一个文件，就同时冻结了它
   已经过时的陈述。

## 关于 `.gitattributes`

`docs/evidence/**` 被标为 `-text`（见仓库根 `.gitattributes`），本目录同样适用。
后果是 git 不对这些文件做行尾转换，也不在 diff 里展开内容——这是为了让
`01`/`02` 这类原始命令输出保持抓取时的字节。

行尾因此**不统一，也不需要统一**：`05` 是唯一经管道穿过 Python stdout 抓的
（Python 在 Windows 上把管道当文本模式，写出 CRLF），其余是 bash `printf`/重定向
写的 LF。`git ls-files --eol docs/evidence/stage2-docker/` 显示 `i/crlf w/crlf` 与
`i/lf w/lf` 并存，且都带 `attr/-text`——这正是"逐字节固化"，不是疏漏。
