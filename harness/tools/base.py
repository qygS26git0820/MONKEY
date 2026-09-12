"""工具契约（冻结文件）。

工具只负责执行并返回事实；截断、落盘、失败分类由主循环统一处理，
这样"每个工具各自一套日志格式"的分裂不会发生。
"""

from ..core.messages import ToolOutcome


class Tool:
    name = "base"

    def execute(self, ctx, args) -> ToolOutcome:
        raise NotImplementedError
