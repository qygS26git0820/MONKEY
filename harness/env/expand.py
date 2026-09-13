"""任务命令里的占位符展开。

放在 env/ 下是因为"占位符该展开成什么"是**后端属性**，不是工具属性：
{python} 在宿主上是 venv 的绝对路径，在容器里是 `python`。阶段 1 把它
写死在 shell_tools 与 eval.runner 两处，等于假设解释器一定在宿主上。

shell_tools（agent 主动跑验证）与 eval.runner（run 结束时 harness 跑验证）
共用这一处，避免两边各写一份而漂移。
"""

import sys


def expand_command(command, executor) -> list:
    """把占位符展开成执行器视角的真实参数列表。

    向执行器询问解释器（python_argv），而非写死 sys.executable。
    用 getattr 取而不是在 env/base.py 里声明：base.py 是冻结文件，
    这是有代价的——那份契约因此无法表达"执行器必须能回答自己的解释器在哪"。
    """
    out = []
    for token in command:
        if token == "{python}":
            argv = getattr(executor, "python_argv", None)
            out.extend(list(argv()) if callable(argv) else [sys.executable])
        elif token == "{workspace}":
            out.append(".")
        else:
            out.append(token)
    return out
