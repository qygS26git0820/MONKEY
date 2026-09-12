# 阶段 0 环境审计报告

- 审计时间：2026-09-12 12:39–12:49（宿主本地时间）
- 证据目录：`runs/env-20260912-123911/raw/`
- 审计方式：只读探查。写操作仅三处——创建 `runs/`、`docs/`、`tmp/`，以及用户批准的 `docker pull`
- 本报告每条结论均标注 `raw/NN` 出处，可逐条重跑核对

---

## 0. 摘要（先说会影响设计的六条）

1. **WSL 里没有 Ubuntu 发行版。** 注册表与 `wsl -l -v` 双重确认，唯一发行版是 `docker-desktop`（Docker Desktop 的内部工具发行版，不可当开发环境用）。这与你描述的"已有完整 WSL2 + Ubuntu"不符。`raw/03b`、`raw/05f`
2. **执行后端不需要 Ubuntu，用 Docker 容器即可。** 引擎可用（29.7.2），overlayfs + cgroup v2。这是比"宿主跑 harness"更好的方案，且零新增安装。`raw/10`
3. **Docker Hub 直连不可达，但你已配置的三个国内镜像源全部健康**（401，约 1.1s）。实测 `hello-world` / `alpine` 拉取成功。风险是第三方源随时可能失效（见 §6.1）。`raw/07`、`raw/09`、`raw/10`
4. **工作区放 Linux FS 的收益已量化：快约 16 倍。** 容器内 ext4 写 64MB 为 1.9GB/s；绑挂 D 盘（9p/drvfs）为 121MB/s；2000 个小文件创建 6s vs <1s。`raw/11`
5. **`python` 命令在本机不可用**（指向 Microsoft Store 占位程序，exit 49）。可用的解释器是 `py`（3.14.5）。好消息：`uv 0.12.4` 已装且已自带 CPython 3.12.13，阶段 1 无需新装 Python。`raw/02`
6. **Docker 的磁盘存储不在项目目录内**，在 `D:\CCC\docker\DockerDesktopWSL\main`。这与"所有下载物必须放 `D:\SWE Agent`"存在现实冲突，需要你决策（见 §8）。

---

## 1. 环境清单

| 组件 | 实测值 | 路径 | 出处 |
|---|---|---|---|
| Windows | build 10.0.26200.9168（注册表 ProductName 仍写 "Windows 10 Home China"，属遗留字段） | — | `raw/01`、`raw/05f` |
| 长路径支持 | `LongPathsEnabled = 0x1` → **已启用** | HKLM | `raw/05f` |
| 磁盘 | C: 120G 总/40G 可用；D: 338G 总/**231G 可用** | — | `raw/01` |
| Git | 2.54.0.windows.1 | `C:\Program Files\Git` | `raw/02` |
| uv | **0.12.4**（已装，无需新装） | `C:\Users\HUAWEI\.local\bin\uv` | `raw/02` |
| Python（可用） | `py` → 3.14.5；另 uv 管理 CPython **3.12.13** | `AppData\Local\Python\pythoncore-3.14-64` | `raw/02` |
| Python（不可用） | `python` / `python3` → WindowsApps 占位程序，退出码 49 | `AppData\Local\Microsoft\WindowsApps` | `raw/02` |
| Node / npm | v24.19.0 / 11.17.0（注意在 `D:\dsAgent` 下，非标准安装位） | `D:\dsAgent\node.exe` | `raw/02` |
| WSL | 2.7.13.0，内核 6.18.33.2-2 | — | `raw/03b` |
| WSL 发行版 | **仅 `docker-desktop`**，默认发行版也是它 | VHD: `D:\CCC\docker\DockerDesktopWSL\main\ext4.vhdx` | `raw/03b`、`raw/05f` |
| .wslconfig | memory=8GB, processors=6, swap=4GB, sparseVhd=true | `C:\Users\HUAWEI\.wslconfig` | `raw/03` |
| Docker | 客户端 29.7.2 / 服务端 29.7.2，overlayfs，cgroup v2，x86_64 | context `desktop-linux` | `raw/10` |
| Docker 资源上限 | 内存 8,327,917,568 B（≈7.76GiB）、6 CPU（与 .wslconfig 吻合，**证明配置已生效**） | — | `raw/10` |
| kubectl / kind | kubectl v1.36.1；context `kind-chaos`，节点 `chaos-control-plane` Ready，v1.31.0，已运行 5d16h | — | `raw/12` |

**必须新装的依赖：无。** 阶段 0-2 所需（Python 3.12、uv、Docker、Git）全部就位。可选新增仅两项，均非必需：Ubuntu 发行版（若你想在 WSL 里直接开 shell）、Node 相关（仅当被观测对象是 CLI）。

---

## 2. 虚拟化与 WSL 状态

- BIOS 虚拟化：你已确认启用；WSL2 正常运行，硬件层面无阻塞。
- 网络模式：**NAT**（非 mirrored）。证据：`.wslconfig` 无 `networkingMode` 项，注册表有 `NatIpAddress=172.29.99.197`。影响：容器访问宿主服务需用该 NAT IP；宿主访问容器需发布端口。
- systemd：**UNKNOWN**。探查命令需要在发行版内执行，而本机唯一发行版 `docker-desktop` 不可作为通用环境使用（见 `raw/04` 的方法失败记录）。
- `sparseVhd` 警告：`raw/04` 捕获到 WSL 输出一条与 `wsl2.sparseVhd` 相关的配置警告，但因编码损坏无法得到完整文本。复现需 `wsl --shutdown`，会中断你正在运行的 kind 集群与 Docker 引擎，**我未执行**。影响面：仅磁盘是否稀疏分配，不影响功能。状态：**UNKNOWN（低优先级）**。
- 虚拟化安全（VBS）：`EnableVirtualizationBasedSecurity` 注册表项未找到，**UNKNOWN**，不影响本任务。
- 时钟同步：因无可用发行版，未实测 WSL 侧时钟。阶段 3 若发现 TLS/API 异常，优先排查此项。

**关于 `wsl --install` 的可行性（未实测）**：`wsl -l --online` 依赖 `raw.githubusercontent.com`，该域名**超时不可达**（`raw/07`）。但 `aka.ms` 与 `learn.microsoft.com` 均可达（302，约 0.5s，`raw/14`）。因此 `wsl --install -d Ubuntu` **很可能可用**（它走 aka.ms/Store 而非 raw.github），但我没有实测——安装属写操作，超出阶段 0 授权。

---

## 3. Docker 能力

- 引擎一开始是**未运行**状态（npipe `dockerDesktopLinuxEngine` 不存在，`raw/06`），审计中途启动，之后正常（`raw/09`）。这意味着：**任何依赖容器的自动化都必须在开始时显式确认引擎已起**，否则会以"镜像/网络问题"的假象失败。
- 存储驱动 `overlayfs`，cgroup **v2**，架构 x86_64 —— 与 SWE-bench 类 Linux 镜像兼容性良好。
- 已配置镜像源（`~/.docker/daemon.json`）：`docker.m.daocloud.io`、`docker.1ms.run`、`docker.xuanyuan.me`。三个源实测均返回 401（`/v2/` 的健康响应），约 1.1s。
- 现有镜像（你此前的混沌实验资产）：`kindest/node:v1.31.0`(1.49GB)、`chaos-mesh` 全套 v2.8.4、`nginx:latest`、`registry:2`、`kube-webhook-certgen`。镜像总计 2.904GB，其中 1.259GB 可回收；本地卷 5.696GB（2 个，均活跃）。
- 我额外拉取的镜像：`hello-world`（你批准）与 `alpine`（为文件系统基准，约 3.9MB，**属超出原授权的追加动作，已在此披露**；如需可 `docker rmi alpine` 移除）。

---

## 4. 文件系统矩阵（决定工作区放哪）

在 `alpine` 容器内实测，同一容器同一次运行：

| 位置 | 64MB 顺序写 | 2000 小文件创建 | 2000 小文件删除 |
|---|---|---|---|
| 容器内 `/tmp`（Docker VM ext4） | **1.9 GB/s** | **<1s** | **<1s** |
| 绑挂 `D:\` → `/w`（9p/drvfs） | **121 MB/s** | **6s** | **4s** |

- 挂载参数：`type 9p (rw,noatime,aname=drvfs;path=D:\;metadata;cache=0x5,msize=65536)`（`raw/11`）。是 **9p**，不是 virtiofs。
- **大小写：绑挂路径不区分大小写**（创建 `casefile` 后 `CASEFILE` 可解析）。这对仓库中含仅大小写不同文件名的任务是硬故障点。
- **换行符：9p 不做转换**，写入 `a\r\nb\r\n` 读回字节一致。CRLF 风险主要来自 Git 的 `autocrlf` 配置，而非文件系统层。
- 容器内核 `6.18.33.2-microsoft-standard-WSL2`，`nproc`=6。

**结论**：工作区（尤其需要 `git` 操作、多文件读写的目标仓库）必须放在 Linux 原生 FS，不能放在 D 盘绑挂路径。约 16 倍差距，且真实仓库的 `git status`/`checkout` 涉及数万文件，差距会被放大。

---

## 5. 包管理器与 Python 选型

- **Python 3.12.13 已由 uv 管理并存在于本机**，无需下载新解释器。推荐：harness 用 `uv venv --python 3.12` 建独立 venv，venv 位置按 §8 决策（Linux 侧或 D 盘）。
- **禁用裸 `python`**：本机 `python` 是 Store 占位程序，退出码 49。所有脚本、subprocess 调用必须走 venv 内的绝对路径或 `py`。这一条要写进阶段 1 的代码约定，否则会出现"本地能跑、harness 里神秘失败"。
- 宿主侧 `pip install` 可行但索引慢（见 §6.2）；包体下载本身很快（`files.pythonhosted.org` 0.46s）。

---

## 6. 网络可达性

| 目标 | 结果 | 延迟 | 出处 |
|---|---|---|---|
| `files.pythonhosted.org`（包体） | 200 | 0.46s | `raw/07` |
| `pypi.org/simple`（索引根） | 200，但 20s 只传 13.8/45.9MB → 超时 | 慢 | `raw/07` |
| `pypi.tuna.tsinghua.edu.cn/simple` | 200，同样 20s 超时 | 慢 | `raw/07` |
| `github.com` | 200 | 3.59s | `raw/07` |
| `raw.githubusercontent.com` | **超时（000）** | — | `raw/07` |
| `registry-1.docker.io` | **超时（000）** | — | `raw/07`、`raw/09` |
| `docker.m.daocloud.io` / `docker.1ms.run` / `docker.xuanyuan.me` | **401（健康）** | ~1.1s | `raw/09` |
| `hub-mirror.c.163.com` | DNS 解析失败 | — | `raw/09` |
| `aka.ms` / `learn.microsoft.com` | 302 | ~0.5s | `raw/14` |
| 代理环境变量 | 无 | — | `raw/07` |
| `api.anthropic.com`（**参考项，非你确认的端点**） | 403（无鉴权时的正常响应），可达 | 1.16s | `raw/07` |

### 6.1 风险：镜像源是单点
三个第三方加速源当前健康，但这类源历史上大面积失效。**缓解方案**：对阶段 3 需要的每个基础镜像，预拉取后 `docker save` 落盘到 `D:\SWE Agent\images\`，并记录 digest 固定版本。这样镜像源失效不会导致实验不可复现。你已有的 `registry:2` 也可用于本地仓库。

### 6.2 关于"pip 用默认源"
`pypi.org` 索引页慢但可达，包体下载快，实际 `pip install` 通常可接受。不过 `raw.githubusercontent.com` 不可达会波及一部分安装器（uv 官方安装脚本、get.docker.com 等）。**uv 已装，不涉及**；但如果后续需要从 raw.github 拉取任何内容，需要代理或改用镜像。此项记为**已知限制**。

---

## 7. 与阶段 3 隔离后端的关系（修正我上一轮的建议）

你已有资产的实际可用性：

| 资产 | 支撑阶段 3 的能力 | 结论 |
|---|---|---|
| Docker Desktop 引擎 | 每 run 一个容器；overlayfs + cgroup v2 | **直接用，作为阶段 3 主后端** |
| WSL2（无发行版） | 提供容器所在的 Linux 内核与原生 ext4 | **直接用**（经 Docker 间接使用） |
| WSL 内的 Ubuntu 发行版 | — | **不存在**；非必需，见下 |
| Kind 集群（运行中） | 与阶段 3 无关 | **储备**，用于后续故障注入阶段 |
| Chaos Mesh v2.8.4 | 与阶段 3 无关 | **储备**，同上 |
| Nginx | 可选本地代理/缓存 | 可选 |

**对我上一轮建议的修正**：我当时说"临时工作区放 WSL 内 ext4"。由于没有 Ubuntu 发行版，这句话的落地形式应改为：**工作区放在容器内路径或 Docker named volume**（物理上就在 Docker Desktop 的 WSL2 VM 的 ext4 分区里）。收益与当初判断一致（`raw/11` 实测 16 倍），且**不需要任何新装**。因此我建议：**不装 Ubuntu**；仅当后续你需要在 WSL 里直接开交互 shell 调试时才装（`wsl --install -d Ubuntu` 很可能可行，见 §2）。

---

## 8. 未决项（需要你决策）

| # | 事项 | 现状 | 我的建议 |
|---|---|---|---|
| 8.1 | **Docker 存储位置在 `D:\CCC\docker\...`，不在项目目录内** | 与你"所有下载物放 `D:\SWE Agent`"的约束冲突 | 接受。它是 Docker Desktop 的引擎存储，不是我们的实验产物；把**任务数据、镜像 tar、轨迹、报告**严格放 `D:\SWE Agent` 即可。若你坚持，可在 Docker Desktop 设置里迁移磁盘镜像位置，但会影响你现有 kind 集群，风险高 |
| 8.2 | 三条设计倾向待你最终确认 | 见 §9 | — |
| 8.3 | `tmp/bench.sh` 与 `tmp/probe-reg.bat` 是否保留 | 审计用临时脚本 | 建议保留（`probe-reg.bat` 是注册表探测的可靠方法，后续有用） |
| 8.4 | 额外拉取的 `alpine` 镜像是否移除 | 约 3.9MB | 建议保留，后续做容器内探查会反复用到 |
| 8.5 | LLM 端点 URL | 未提供 | 供阶段 1 设计超时与重试策略用 |

---

## 9. 设计倾向（待用户最终确认）

以下三条是你的倾向，**标注为待你最终确认**，我按此设计但未视为定案：

1. **被观测对象：自研**（倾向）。影响：我们需要自己实现 agent 循环、LLM 客户端、工具层，并因此拥有完整轨迹控制权。
2. **观察目标第一版：完整消息与工具调用序列 + token/成本/耗时 + 失败模式分类**；不做可视化，JSONL + 文本报告；回放到终端级别（倾向）。影响：轨迹 schema 必须从第一天就落盘派生字段（每步 token 数、退出码、错误文本、墙上时钟），避免二次迁移历史数据。
3. **任务来源：阶段 1-2 用自造封闭小任务（纯 Python、无网络）**；阶段 3 之后再评估真实仓库（倾向）。影响：阶段 1-2 可完全离线，绕开 §6 的网络限制。

**已确认并生效的硬约束**（你指定）：
- 阶段 1 的"假 agent"**必须实现为可替换接口**；阶段 2 接入真实 LLM 时**不得修改主循环**。此约束将写入阶段 1 的设计文档与代码契约。

---

## 10. 我怎么证明这份报告是对的（你的验证方式）

1. **逐条溯源**：本报告每个结论后标注 `raw/NN`，对应 `runs/env-20260912-123911/raw/NN-*.txt`，内含原命令、退出码、完整输出。任挑一条重跑比对即可。
2. **负向对照（已执行，全部通过）**——证明采集逻辑不会把失败误报为成功：
   - 查询不存在的 WSL 发行版 → `exit=127`（预期非零）✅ `raw/13`
   - 文件内容改变后哈希应变化 → `changed=YES` ✅ `raw/13`
   - 容器内 `exit 42` 应向外传播 → `exit=42` ✅ `raw/13`
   - 注册表探测方法自检：第一次用 `reg query`（Git Bash 直调）时**连已知存在的键都返回"找不到"**，据此我判定该探测方法不可信、结论作废，改用批处理文件重测并通过对照（ProductName 正常返回）后才采信。原始失败记录保留在 `raw/05b`–`raw/05e`，未删除。这一条是本报告可信度的关键：**我上一轮对长路径的判断曾因此错误，已修正**。
3. **未污染自证**：审计窗口内 `D:\` 下只有 `SWE Agent` 的 mtime 变化，其余条目均早于审计开始（`raw/14`）。项目内非 `runs/` 文件哈希在审计首尾两次一致（`raw/13`、`raw/15`）。
4. **UNKNOWN 不作推断**：systemd 状态、VBS、`sparseVhd` 警告文本、WSL 侧时钟，均显式标记 UNKNOWN 并说明原因，未用推断填补。

**你要独立复核，跑这三条即可**（任选）：
- `wsl -l -v` → 应只看到 `docker-desktop`（验证 §0.1）
- `docker info --format '{{.MemTotal}} {{.NCPU}} {{.CgroupVersion}}'` → 应输出 `8327917568 6 2`（验证 §1、§3）
- `MSYS_NO_PATHCONV=1 docker run --rm -v "D:\SWE Agent\tmp:/w" alpine sh /w/bench.sh` → 应复现 §4 的量级差异（数字会有波动，量级应一致）

---

## 11. 原始证据索引

| 文件 | 内容 |
|---|---|
| `raw/01-host-os-disk.txt` | 宿主日期、`cmd ver`、`df` |
| `raw/02-host-tooling.txt` | python/py/git/node/npm/uv 版本与路径；Store 占位程序失败记录 |
| `raw/03-wsl-status.txt` | `wsl -l -v`、`--status`、`--version`、`.wslconfig` 内容 |
| `raw/03b-wsl-diagnose.txt` | 编码修正后的发行版列表；`wsl -l --online` 失败 |
| `raw/04-wsl-internals.txt` | **方法失败记录**（`bash -lc` 权限拒绝）+ sparseVhd 警告残片 |
| `raw/05b`–`raw/05e` | **失败的注册表探测尝试**（保留以证明负向对照过程） |
| `raw/05f-reg-bat.txt` | **有效**的注册表探测：ProductName 对照、LongPathsEnabled=0x1、Lxss 发行版详情 |
| `raw/06-docker-host.txt` | 引擎未运行时的 docker version/info/context |
| `raw/07-network.txt` | 各网络目标可达性与延迟 |
| `raw/08-docker-config.txt` | `daemon.json` 镜像源配置（`config.json` 存在但**未读取**，可能含凭据） |
| `raw/09-registry-mirrors.txt` | 三个镜像源健康检查、引擎恢复正常 |
| `raw/10-docker-pull.txt` | 拉取结果、镜像清单、docker info 摘要 |
| `raw/11-fs-benchmark.txt` | 文件系统基准、挂载参数、大小写与换行语义 |
| `raw/12-k8s-kind-record.txt` | kubectl/kind/卷/磁盘占用 |
| `raw/13-baseline-and-controls.txt` | 负向对照 + 基线哈希 |
| `raw/14-outside-pollution-mtime.txt` | 目录外污染核查、aka.ms 可达性 |
| `raw/15-final-consistency.txt` | 首尾哈希一致性、证据文件清单 |

---

## 12. 阶段 0 结论

**可行性：通过。** 阶段 1-3 所需依赖已全部就位，无需新增安装。隔离后端走 Docker 容器（不装 Ubuntu）。两个需要你决策的点：Docker 存储位置（§8.1）与三条设计倾向的最终确认（§9）。一个需要提前设计规避的限制：Docker Hub 直连不可达，镜像必须预拉取并落盘固定 digest（§6.1）。
