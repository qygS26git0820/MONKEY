"""宿主子进程执行器。

一律 shell=False + 参数列表：既避开路径含空格的问题，也消除命令注入。
显式 utf-8 解码：Windows 默认走本地代码页（GBK），不指定会乱码。

子进程**不继承**宿主环境里 HIDDEN_ENV_PREFIX 开头的变量。docker 后端本就不
继承宿主环境（只透传显式 -e），这里补的是同一件事的宿主版本——否则同一份
观测在两种后端下能看到的环境不同。
"""

import os
import subprocess
import sys
from pathlib import Path

from .. import clock
from .base import ExecResult, Executor

# 被观测命令看不到以这个前缀开头的宿主环境变量。凭据（MONKEY_DEEPSEEK_KEY）
# 就在这个前缀下：agent 一句 printenv 就能读到它，而那条输出会进 trace.jsonl
# 与 blobs/——观测数据里出现自己的凭据，就是观测工具污染了观测对象。
# 显式传入的 env 不受此限制：那条路径是调用方有意为之。
HIDDEN_ENV_PREFIX = "MONKEY_"


def _child_env(extra) -> dict:
    child_env = {k: v for k, v in os.environ.items()
                 if not k.startswith(HIDDEN_ENV_PREFIX)}
    child_env["PYTHONHASHSEED"] = "0"
    child_env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        child_env.update(extra)
    return child_env


class LocalExecutor(Executor):
    kind = "local"

    def __init__(self, visible_root: Path):
        self._root = Path(visible_root).resolve()

    def python_argv(self) -> list:
        """任务验证命令里 {python} 的解析结果。

        阶段 1 这个解析写死在 shell_tools/eval.runner 里，等于假设
        "解释器就在宿主上"。容器后端打破了这个假设，故下移到执行器：
        同一个问题，两种答案。local 的答案与阶段 1 逐字节相同。
        """
        return [sys.executable]

    def visible_path(self, host_path) -> str:
        resolved = Path(host_path).resolve()
        try:
            rel = resolved.relative_to(self._root)
        except ValueError:
            return resolved.as_posix()
        return rel.as_posix() or "."

    def run(self, args, cwd, timeout_s, env=None) -> ExecResult:
        child_env = _child_env(env)

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
