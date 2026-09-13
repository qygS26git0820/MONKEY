"""Docker 容器执行器（阶段 2）。

与 LocalExecutor 实现同一 Executor 契约，env/base.py 一个字不改。

三处必须与 local 不同，都源于"容器里的世界和宿主不是同一个"：

1. visible_path —— 宿主路径要映射成**容器内路径**。阶段 1 的记录是
   "workspace"（相对 run_dir），容器里是 "/workspace"。这不是美化，
   是事实：agent 看到的世界确实变了。跨后端可比性的已知混杂项由此而来。
2. 解释器 —— 任务验证命令用 {python} 占位。阶段 1 解析成宿主
   sys.executable，那是 D:\\SWE Agent\\.venv\\Scripts\\python.exe，容器里
   不存在。容器里就是 `python`。解析逻辑因此下移到执行器（见
   python_argv），shell_tools/eval.runner 用 getattr 取，故 base.py 不需声明。
3. 隔离面 —— 只把工作区挂进容器（-v workspace:/workspace），容器看不到
   宿主其余部分；--network none 断开网络。
"""

import itertools
import os
import subprocess
from pathlib import Path

from .. import clock
from .base import ExecResult, Executor

DEFAULT_IMAGE = "python:3.12-slim"
CONTAINER_WORKSPACE = "/workspace"

# docker run 自身的失败（镜像不在、daemon 连不上）用 125 与容器进程的退出码区分。
DOCKER_ERROR_EXIT = 125

_HEADS = itertools.count(1)


class DockerExecutor(Executor):
    kind = "docker"

    def __init__(self, workspace_root, image: str = DEFAULT_IMAGE, network: str = "none"):
        self._root = Path(workspace_root).resolve()
        self.image = image
        self._network = network

    def python_argv(self) -> list:
        """容器内的解释器。镜像里就是 `python`，不依赖宿主 venv。"""
        return ["python"]

    def _container_path(self, host_path) -> str:
        resolved = Path(host_path).resolve()
        try:
            rel = resolved.relative_to(self._root)
        except ValueError:
            # 挂载点之外：容器里根本看不到它。如实返回宿主路径，不假装可见。
            return resolved.as_posix()
        rel_posix = rel.as_posix()
        if rel_posix in ("", "."):
            return CONTAINER_WORKSPACE
        return f"{CONTAINER_WORKSPACE}/{rel_posix}"

    def visible_path(self, host_path) -> str:
        return self._container_path(host_path)

    def run(self, args, cwd, timeout_s, env=None) -> ExecResult:
        name = f"harness-{os.getpid()}-{next(_HEADS)}"
        argv = [
            "docker", "run", "--rm",
            # --pull never：只用本地已存在的镜像。否则同一次实验可能在
            # 中途拉到不同的镜像位，可复现性就没了。
            "--pull", "never",
            "--name", name,
            "--network", self._network,
            "-v", f"{self._root}:{CONTAINER_WORKSPACE}",
            "-w", self._container_path(cwd),
            "-e", "PYTHONHASHSEED=0",
            "-e", "PYTHONIOENCODING=utf-8",
        ]
        for key, value in (env or {}).items():
            argv += ["-e", f"{key}={value}"]
        argv += [self.image] + [str(a) for a in args]

        started = clock.now()

        def elapsed_ms() -> int:
            return clock.ms_since(started)

        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                shell=False,
            )
        except FileNotFoundError as exc:
            return ExecResult(
                exit_code=None, stdout="", stderr=str(exc),
                duration_ms=elapsed_ms(),
                launcher_error="docker 可执行文件不存在",
            )
        except subprocess.TimeoutExpired as exc:
            # 与 local 不同：这里能真正清干净。--rm 只在 docker run 正常
            # 退出时生效，客户端被 kill 后容器会留下，故显式删。
            self._force_remove(name)
            return ExecResult(
                exit_code=None,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                duration_ms=elapsed_ms(),
                timed_out=True,
            )

        if proc.returncode == DOCKER_ERROR_EXIT:
            return ExecResult(
                exit_code=None, stdout=proc.stdout or "", stderr=proc.stderr or "",
                duration_ms=elapsed_ms(),
                launcher_error=f"docker run 失败: {(proc.stderr or '').strip()[:400]}",
            )

        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=elapsed_ms(),
        )

    @staticmethod
    def _force_remove(name: str) -> None:
        try:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True,
                           timeout=20, shell=False)
        except (OSError, subprocess.SubprocessError):
            pass


def image_present(image: str = DEFAULT_IMAGE) -> bool:
    """镜像是否已在本地。测试用它决定 skip 还是 run。"""
    try:
        proc = subprocess.run(["docker", "image", "inspect", image],
                              capture_output=True, timeout=30, shell=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
