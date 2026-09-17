# 环境交接文档（chaos-001）

> 本文件在项目根 `docs/` 下，**不在工作区**，MONKEY 看不到。
> 工作区里只有 `tasks/chaos-001/repo/snapshot/` 的现场快照。

---

## 1. 目标系统（ground truth）

| 项 | 值 |
|---|---|
| 集群 | Kind 集群，名称 `chaos`，单节点 `chaos-control-plane`（v1.31.0，containerd 运行时） |
| 命名空间 | `default` |
| 工作负载 | `deployment/nginx`（3 副本，标签 `app=nginx`）；对外 Service `nginx-svc`（ClusterIP `10.96.98.126:80`） |
| 客户端 | `pod/client`（busybox，命名空间 `default`），用于复现"访问 nginx 超时" |
| Chaos Mesh | 已安装于 `chaos-mesh` 命名空间，全部 Pod Running |

## 2. 故障是什么（ground truth）

| 项 | 值 |
|---|---|
| 故障类型（kind） | `NetworkChaos`（Chaos Mesh，apiVersion `chaos-mesh.org/v1alpha1`） |
| 故障资源名 | `nginx-delay` |
| 命名空间 | `default` |
| 受影响工作负载 | `deployment/nginx` |
| 动作 | `action: delay`，`latency: 10s`、`jitter: 0ms`、`correlation: "0"` |
| 方向 | `direction: to`（延迟流向 nginx 的入向流量） |
| 模式 | `mode: all`（3 副本全部注入） |
| 持续 | `duration: 30m`（2026-09-17T05:02:55Z 起） |
| 注入状态 | `status.conditions`: `Selected=True`、`AllInjected=True`、`AllRecovered=False` |

**现象**：客户端访问 `http://nginx-svc.default.svc.cluster.local/` 超时（`wget: download timed out`，exit 1，约 5s）。
nginx Pod 本身 Running/Ready、0 重启，Service/Endpoints 正常——故障在**网络层**而非工作负载本身。

**为什么选 delay 而非 loss**：loss 会被 TCP 重传部分吸收（实测 50% 丢包仅约 10% 请求超时），
10s 延迟 > 客户端 5s 超时，可**稳定复现**"每次必超时"。

## 3. 怎么算"恢复"

满足以下全部：

1. `NetworkChaos/nginx-delay`（namespace `default`）被删除或进入 `AllRecovered=True`；
2. 从 `default/client` 访问 `http://nginx-svc.default.svc.cluster.local/` 返回 `HTTP/1.1 200 OK`（延迟回到毫秒级，而非 10s）；
3. `deployment/nginx` 保持 3 副本 Ready、无重启。

**判定命令（供核验）**：

```bash
# 1) 故障资源是否已恢复
kubectl get networkchaos nginx-delay -n default -o json   # 期望 AllRecovered=True 或资源不存在

# 2) 服务是否恢复
kubectl exec -n default client -- sh -c "wget -S -O /dev/null --timeout=5 http://nginx-svc.default.svc.cluster.local/ 2>&1"
# 期望：HTTP/1.1 200 OK

# 3) 工作负载健康
kubectl get pods -n default -l app=nginx
# 期望：3/3 Running
```

## 4. 组件内存占用

采集时刻：2026-09-17T05:18Z 左右。

### WSL2（docker-desktop 发行版）`wsl -d docker-desktop -e free -h`
```
              total        used        free      shared  buff/cache   available
Mem:           7.8G        2.3G        1.7G       39.5M        3.8G        5.2G
Swap:          4.0G       36.0K        4.0G
```

### Kind 节点容器
`docker stats`：`chaos-control-plane` = **2.401 GiB / 7.756 GiB**（cpu 15.65%）
（该容器承载整个集群：kube-apiserver/etcd/scheduler、Chaos Mesh、Prometheus 栈、nginx 等全部工作负载）

### 关键 Pod（cgroup `memory.current`，仅作量级参考）
| Pod | 内存 |
|---|---|
| `default/nginx-6559559688-ggv7d` | 7.1 MiB |
| `default/client` | 1.3 MiB |
| `chaos-mesh/chaos-controller-manager-*` | 112.8 MiB |

> 注：`chaos-daemon` 为特权 + hostPID 容器，其 cgroup 读数会落到节点级（约 4.2 GiB），不代表该组件真实占用，故不采用。

## 5. 采集快照的时刻

| 快照 | 时刻 (UTC) |
|---|---|
| 故障前基线（wget 200） | 2026-09-17T04:58:56Z |
| NetworkChaos 创建 | 2026-09-17T05:02:55Z |
| 故障证据（wget 超时） | 2026-09-17T05:03:31Z |
| pods/svc/events 采集 | 2026-09-17T05:14:26Z |
| describe/logs 采集 | 2026-09-17T05:15:46Z |
| 全量资源转储 | 2026-09-17T05:17:43Z |

快照目录：`tasks/chaos-001/repo/snapshot/`（共 9 个文件，含 `00-COLLECTED.md` 采集清单）。

## 6. 清单原件

实际 apply 的清单保留在项目根 `chaos/`：

- `chaos/01-nginx.yaml` —— nginx Deployment + Service（namespace `default`）
- `chaos/02-client.yaml` —— 客户端 Pod（namespace `default`）
- `chaos/03-networkchaos.yaml` —— NetworkChaos 故障注入（namespace `default`）

## 7. 当前状态（收尾时）

- Kind 集群**未删除**（保留用于核对快照）。
- 故障**仍在生效**（NetworkChaos `nginx-delay` 未删除），未关闭任何组件。
- `chaos-test` / `monitoring` 等命名空间为既有环境，与本次实验无关。
