"""按配置选后端执行器。

单独一个模块，是因为有两个调用方（__main__.cmd_run 与 tests/support.run_scenario），
两处各写一份 if/elif 一定会漂移：某一方加了后端、另一方没加，测试就测的不是
线上跑的东西了。阶段 1 的写法是两边都硬编码 LocalExecutor，那是当时只有一个后端
的合理简化；现在有两个，就该有一处唯一的答案。
"""

from pathlib import Path

from .base import Executor
from .docker import DEFAULT_IMAGE, DockerExecutor
from .local import LocalExecutor

# config.load_config 用它做启动前校验：配置文件写错后端名应当在建 run 目录
# 之前就失败，而不是跑起来才发现。
EXECUTOR_KINDS = ("local", "docker")


def make_executor(config, run_dir: Path, workspace: Path) -> Executor:
    """run_dir 与 workspace 都是**宿主视角**路径，且 workspace 在 run_dir 之内。

    两个后端拿到的根不同，这不是笔误：

    - local 的根是 run_dir，因为 visible_path 决定轨迹里记什么。阶段 1 的
      语料记的是 "workspace/<file>"（相对 run_dir），改根会让整个阶段 1
      语料不再可比。这里是逐字节保持。
    - docker 的根是 workspace，因为根同时就是**挂载点**。若挂 run_dir，
      trace.jsonl / meta.json / blobs/ 会一起进容器，被观测的 agent 就能
      改掉观察它自己的证据；且 cwd 会记成 "/workspace/workspace"，多一层
      没有意义的嵌套。挂 workspace 后 cwd 记 "/workspace"。
    """
    kind = config.executor_kind
    if kind == "local":
        return LocalExecutor(run_dir)
    if kind == "docker":
        return DockerExecutor(workspace, image=config.docker_image or DEFAULT_IMAGE)
    raise ValueError(f"未知的 executor kind: {kind!r}（已知: {', '.join(EXECUTOR_KINDS)}）")
