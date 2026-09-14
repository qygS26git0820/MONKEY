"""主循环认识的中立失败信号。

放在 `core/` 而不是 `harness/llm/`：冻结的 `loop.py` 必须能捕获它，而
`loop.py` 一旦 import `harness.llm`，主循环就绑定了具体后端——"后端与
agent 可替换"这条不变式随之失效（同样的理由见 `core/usage.py` 开头）。
"""


class ModelFailure(RuntimeError):
    """模型调用失败——由 agent 侧抛出，携带一个 `contract.LLM_FAILURE_CLASSES`。

    为什么用异常而不是给 `next_action` 增加一种返回类型：Agent 接口是冻结的
    （见 `agent/base.py`），新增返回类型等于改接口；而异常是"这条路径本来
    就该炸"的自然表达，主循环只需多一个 `except`，接口一个字不动。

    `failure_class` 由抛出方给出而不是让主循环去推断：只有客户端知道失败发生
    在哪一层（连不上 / 网关拒绝 / 响应不合协议）。主循环只校验它是不是我们
    认识的标签，不是就退回 `harness_error`。
    """

    def __init__(self, failure_class: str, detail: str = ""):
        super().__init__(detail)
        self.failure_class = failure_class
        self.detail = detail
