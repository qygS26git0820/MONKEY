"""模型单价表——成本估算的唯一来源。

**这张表目前是空的，这是刻意的，不是缺口**：端点与模型名还没定，价格必须
由你提供，我不臆造。空表的后果由 `harness/config.py` 接住——配了
`budgets.max_cost_usd` 却查不到单价就拒绝启动，而不是让成本上限静默失效。

加价时请连来源与核对日期一起写：半年后没人能从数字本身判断它是否还成立。
"""

# 模型名 -> (每百万输入 token 的美元价, 每百万输出 token 的美元价, 来源, 核对日期)
PRICES: dict = {}


def price_for(model):
    """返回 (输入单价, 输出单价) 或 None。None 表示"没有可信价格"。

    只吐单价、丢掉来源与日期，是为了让调用方无法在不核对来源的前提下
    依赖一个具体数字——来源留在表里给人和审查用。
    """
    entry = PRICES.get(model)
    if entry is None:
        return None
    return entry[0], entry[1]
