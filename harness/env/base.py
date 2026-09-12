"""执行器契约（冻结文件）。

阶段 1 只有 LocalExecutor；阶段 3 增加 DockerExecutor，实现同一契约，
本文件不改。visible_path 的存在是为了让宿主路径与容器内路径的映射
不至于在阶段 3 改动工具层签名。
"""

from dataclasses import dataclass


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    launcher_error: str = ""  # 非空表示命令根本没跑起来 → env_error


class Executor:
    kind = "base"

    def run(self, args, cwd, timeout_s, env=None) -> ExecResult:
        raise NotImplementedError

    def visible_path(self, host_path) -> str:
        raise NotImplementedError
