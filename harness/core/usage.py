"""token 与成本的累计处——读写只有这一个点。

单独成一个模块，因为读写两侧分属不同层：**写**发生在 agent 侧（模型
每次响应后记一笔），**读**发生在主循环侧（算 totals、判预算）。两边各写
各的计数一定会漂移，而"本次 run 花了多少"是必须唯一确定的事实。

主循环不 import 本模块：它只读注入进来的 `run_ctx.usage`。这样 loop.py
不会依赖 harness.llm，后端与 agent 的替换都不牵连主循环。

本提交（基线移动）**只有读取侧，没有 record()**：因此三个累计量恒为
None、exceeded() 恒为 False，主循环的行为与移动前逐字节相同。
"没有写入侧"是结构事实，不是靠注释保证的。
"""


class UsageLedger:
    def __init__(self):
        self.input_tokens = None
        self.output_tokens = None
        self.cost_usd = None

    def exceeded(self, budgets) -> bool:
        """累计用量是否已越过预算。在本提交下恒为 False——还没有东西往里写。

        budgets 参数现在就出现在签名里，是为了让主循环的**调用点**在基线
        移动这一次就定稿。若等实现预算判定时再补参数，loop.py 就得改第二次，
        而"只移动一次"是这个提交存在的全部理由。
        """
        return False
