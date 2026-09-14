"""token 的累计处——读写只有这一个点。

单独成一个模块，因为读写两侧分属不同层：**写**发生在 agent 侧（模型
每次响应后记一笔），**读**发生在主循环侧（算 totals、判预算）。两边各写
各的计数一定会漂移，而"本次 run 用了多少 token"是必须唯一确定的事实。

主循环不 import 本模块：它只读注入进来的 `run_ctx.usage`。这样 loop.py
不会依赖 harness.llm，后端与 agent 的替换都不牵连主循环。

**未知是粘的**：只要有一笔 record 没给出某个量（值为 None），该量就此
变为"未知"，此后再补多少有值的记录也变不回一个偏小的和。理由是预算判定
要拿它卡上限——部分和冒充完整和，越限就会发生在预算之外，而这恰恰是最不
该漏掉的一类观测。代价是未知量无法触发终止，见 `exceeded`。
"""

_UNKNOWN = object()


def _acc(total, value):
    """把一个报告值并进累计量。

    total 有三种形态，必须分开：None=还没有任何记录、_UNKNOWN=已有记录但
    至少一笔未报告、数值=已知累计。前两者对外都表现为 None，但对内不能
    合并，否则"头一笔缺失、第二笔才有值"会被算成一个偏小的和。
    """
    if total is _UNKNOWN or value is None:
        return _UNKNOWN
    if total is None:
        return value
    return total + value


class UsageLedger:
    def __init__(self):
        self._input = None
        self._output = None

    @property
    def input_tokens(self):
        return None if self._input is _UNKNOWN else self._input

    @property
    def output_tokens(self):
        return None if self._output is _UNKNOWN else self._output

    def record(self, *, input_tokens=None, output_tokens=None) -> None:
        """记一笔用量。两个量缺省 None，表示"这次响应没有报告它"。

        强制 keyword-only：调用点必须写明记的是哪个量。input/output 写反
        不会有任何报错，只会静静地把总量算错，而这类错误在轨迹里看不出。
        """
        self._input = _acc(self._input, input_tokens)
        self._output = _acc(self._output, output_tokens)

    def exceeded(self, budgets) -> bool:
        """累计用量是否已**越过**上限。

        两处刻意的选择：

        - **严格大于**：刚好用满上限不算越限，上限是"允许用这么多"。
        - **未知不触发**：累计量是 None（没有记录，或记录缺失已污染）时，
          比较直接短路为假。我们无法证明它超了，就不凭它终止。代价是这个
          量上的越限会漏判——这条已知残差登记在 `docs/known-residues.md`。

        `max_total_tokens` 的"总量"指输入 + 输出之和。
        """
        if (budgets.max_total_tokens is not None
                and self.input_tokens is not None and self.output_tokens is not None
                and self.input_tokens + self.output_tokens > budgets.max_total_tokens):
            return True
        return False
