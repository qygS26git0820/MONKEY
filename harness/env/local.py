"""宿主子进程执行器。

一律 shell=False + 参数列表：既避开路径含空格的问题，也消除命令注入。
显式 utf-8 解码：Windows 默认走本地代码页（GBK），不指定会乱码。
"""

import os
import subprocess
from pathlib import Path

from .. import clock
from .base import ExecResult, Executor


class LocalExecutor(Executor):
    kind = "local"

    def __init__(self, visible_root: Path):
        self._root = Path(visible_root).resolve()

    def visible_path(self, host_path) -> str:
        resolved = Path(host_path).resolve()
        try:
            rel = resolved.relative_to(self._root)
        except ValueError:
            return resolved.as_posix()
        return rel.as_posix() or "."

    def run(self, args, cwd, timeout_s, env=None) -> ExecResult:
        child_env = dict(os.environ)
        child_env["PYTHONHASHSEED"] = "0"
        child_env["PYTHONIOENCODING"] = "utf-8"
        if env:
            child_env.update(env)

        argv = [str(a) for a in args]
        started = clock.now()

        def elapsed_ms() -> int:
            return clock.ms_since(started)

        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=child_env,
                shell=False,
            )
        except FileNotFoundError as exc:
            return ExecResult(
                exit_code=None, stdout="", stderr=str(exc),
                duration_ms=elapsed_ms(),
                launcher_error=f"command not found: {argv[0]}",
            )
        except subprocess.TimeoutExpired as exc:
            # 已知限制：Windows 上 kill() 可能留下孙进程；阶段 1 任务均为单进程。
            return ExecResult(
                exit_code=None,
                stdout=_as_text(exc.stdout),
                stderr=_as_text(exc.stderr),
                duration_ms=elapsed_ms(),
                timed_out=True,
            )
        return ExecResult(
            exit_code=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            duration_ms=elapsed_ms(),
        )


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
