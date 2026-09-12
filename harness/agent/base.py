"""Agent 接口（冻结文件）。

硬约束的落点：接口是**状态驱动**的——只有一个方法，接收当前对话状态，
返回**一个**动作。假 agent 内部忽略状态、按步号吐脚本；阶段 2 的 LLM agent
读状态构造提示词。同一个主循环，两者无差别。

若改成"一次性返回整串动作"，阶段 2 必须重写主循环，故不采用。
"""

from ..core.messages import Abort, Finish, ToolCalls


class Agent:
    name = "base"

    def next_action(self, state) -> ToolCalls | Finish | Abort:
        raise NotImplementedError
