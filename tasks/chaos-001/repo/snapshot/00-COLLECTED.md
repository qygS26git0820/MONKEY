# cmd: 采集清单（本文件为时段 1 汇总，非某条命令的输出）
# at: 2026-09-17T05:22:39Z

# 现场快照采集清单

- 采集时刻（UTC）：2026-09-17T05:14Z ~ 05:17Z
- 采集人：OpenCode（时段 1）
- 采集环境：Kind 集群 `chaos`，命名空间 `default`，工作负载 `deployment/nginx`（3 副本）
- 说明：每条快照文件头部两行是 `# cmd:`（原样命令行）与 `# at:`（ISO 8601 时刻）；文件名取自产生它的命令本身。

---

## 采集项

### 1. `kubectl get pods -A -o wide`
- 时刻：2026-09-17T05:14:26Z
- 输出文件：`kubectl_get_pods_-A_-o_wide.txt`
- 为什么有用：全集群 Pod 布局与就绪状态。用于确认 `default/nginx` 三个副本是否健康、有无重启，从而把"服务不可用"与"Pod 本身挂了"区分开。

### 2. `kubectl get svc -A`
- 时刻：2026-09-17T05:14:26Z
- 输出文件：`kubectl_get_svc_-A.txt`
- 为什么有用：全集群 Service 与 ClusterIP。客户端访问的是 Service，需要拿到 `default/nginx-svc` 的 ClusterIP 与端口。

### 3. `kubectl get events -A`
- 时刻：2026-09-17T05:14:26Z
- 输出文件：`kubectl_get_events_-A.txt`
- 为什么有用：集群事件流。可看到 Pod 调度/重启/OOM 等，用于排除"Pod 侧故障"这一竞争假设。

### 4. 全量资源原始清单（约 1.8 MB）
- 命令：`kubectl get $(kubectl api-resources --verbs=list --namespaced -o name | grep -v secrets) -A -o yaml`
- 时刻：2026-09-17T05:17:43Z
- 输出文件：`kubectl_get_all-namespaced-resources-except-secrets_-A_-o_yaml.txt`
- 为什么有用：把集群所有命名空间下的资源按原样转储，任何异常/额外资源都会在这里现形，无需事先知道它是什么类型。
- 备注：命令中排除了 `secrets`（集群 Secret 约 3.2 MB 且含凭据），其余 namespaced 资源类型全部完整包含。

### 5. `kubectl describe pod nginx-6559559688-ggv7d -n default`
- 时刻：2026-09-17T05:15:46Z
- 输出文件：`kubectl_describe_pod_nginx-6559559688-ggv7d_-n_default.txt`
- 为什么有用：事发工作负载单个副本的详细状态：就绪、重启次数、容器状态、事件。用于确认 Pod 本身是否正常。

### 6. `kubectl logs nginx-6559559688-ggv7d -n default`
- 时刻：2026-09-17T05:15:46Z
- 输出文件：`kubectl_logs_nginx-6559559688-ggv7d_-n_default.txt`
- 为什么有用：nginx 访问日志。可看到成功请求的痕迹，用于判断请求是否真正到达了 nginx。

### 7. 故障前基线：客户端访问 Service（成功）
- 命令：`kubectl exec -n default client -- sh -c "wget -S -O /dev/null --timeout=5 http://nginx-svc.default.svc.cluster.local/ 2>&1"`
- 时刻：2026-09-17T04:58:56Z
- 输出文件：`kubectl_exec_-n_default_client_--_sh_-c_wget_-S_-O_dev_null_--timeout=5_http_nginx-svc.default.svc.cluster.local_2_&1@2026-09-17T045856Z.txt`
- 为什么有用：同一客户端命令在注入前返回 `HTTP/1.1 200 OK`，证明客户端与 Service 通路本来正常。

### 8. 故障证据：客户端访问 Service（超时）
- 命令：`kubectl exec -n default client -- sh -c "wget -S -O /dev/null --timeout=5 http://nginx-svc.default.svc.cluster.local/ 2>&1"`
- 时刻：2026-09-17T05:03:31Z
- 输出文件：`kubectl_exec_-n_default_client_--_sh_-c_wget_-S_-O_dev_null_--timeout=5_http_nginx-svc.default.svc.cluster.local_2_&1@2026-09-17T050331Z.txt`
- 为什么有用：同一命令在注入后超时（`wget: download timed out`，exit 1，耗时约 5s）。第 7 与第 8 条是同一命令的两个时刻，一正一反，构成对照。

---

## 未采集（及原因）

- 针对某一具体资源类型的定制查询（例如按类型单独列举）：**未采集**。通用命令已把集群全部资源原样转储（第 4 项），需要什么请自行从原始输出里找。
- Secret 内容：**未采集**（避免凭据进入快照）。

## 备注

- 第 5、6 项针对 `default/nginx` 的一个副本；另两个副本状态一致（见第 1 项）。
