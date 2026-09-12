"""阶段 1 的确定性假 agent。

每个脚本都无随机、无网络、无时间依赖，因此同任务同 agent 重跑，
去掉时间戳后的**动作序列**应逐步一致。

注意这不是"整条轨迹逐字节一致"：验证子进程自报的 unittest 运行
时长本身有抖动（"Ran 2 tests in 0.000s" 里的数字会变），它会落进
verification 事件的 stdout/stderr。确定性断言因此必须把子进程自报
耗时与由它派生的 sha 一并规范化，见 tests/test_determinism.py。

脚本按 task_id 选取——这正是"状态驱动"接口的用法：真 LLM agent 会读
state.messages 构造提示词，假 agent 只读 state.task_id 挑脚本，两者走同一条路。
"""

from ..core.messages import Abort, Finish, ToolCall, ToolCalls
from .base import Agent

FIXED_CALC = "def add(a, b):\n    return a + b\n"
BROKEN_CALC = "def add(a, b):\n    return a + b + 100\n"

FIXED_SCALE = "from settings import FACTOR\n\n\ndef scale(x):\n    return x * FACTOR\n"
BROKEN_SCALE = "from settings import FACTOR\n\n\ndef scale(x):\n    return x * (FACTOR - 1)\n"

TASK_FIXES = {
    "toy-001": {
        "read": "calc.py",
        "write": "calc.py",
        "fixed": FIXED_CALC,
        "bad": BROKEN_CALC,
    },
    "toy-002": {
        "extra_read": "settings.py",
        "read": "scale.py",
        "write": "scale.py",
        "fixed": FIXED_SCALE,
        "bad": BROKEN_SCALE,
    },
}

AGENT_NAMES = (
    "scripted_ok",
    "scripted_bad_edit",
    "scripted_tool_error",
    "scripted_denied",
    "scripted_gave_up",
    "scripted_loop_limit",
)


def build_script(agent_name: str, task_id: str) -> list:
    if agent_name == "scripted_gave_up":
        return [Abort("这个 bug 我定位不到")]

    spec = TASK_FIXES.get(task_id)
    if spec is None:
        raise KeyError(f"没有为任务 {task_id} 定义脚本素材")

    if agent_name == "scripted_tool_error":
        return [[("read_file", {"path": "does_not_exist.py"})] for _ in range(5)]
    if agent_name == "scripted_denied":
        return [[("write_file", {"path": "../escape.txt", "content": "x"})] for _ in range(4)]
    if agent_name == "scripted_loop_limit":
        return [[("read_file", {"path": spec["read"]})] for _ in range(20)]
    if agent_name == "scripted_ok":
        entries = []
        if "extra_read" in spec:
            entries.append([
                ("read_file", {"path": spec["extra_read"]}),
                ("read_file", {"path": spec["read"]}),
            ])
        else:
            entries.append([("read_file", {"path": spec["read"]})])
        entries.append([("write_file", {"path": spec["write"], "content": spec["fixed"]})])
        entries.append([("run_verify", {})])
        entries.append(Finish("已修复并验证"))
        return entries
    if agent_name == "scripted_bad_edit":
        return [
            [("read_file", {"path": spec["read"]})],
            [("write_file", {"path": spec["write"], "content": spec["bad"]})],
            [("run_verify", {})],
            Finish("改完了"),
        ]
    raise KeyError(f"未知的假 agent: {agent_name}")


class ScriptedAgent(Agent):
    def __init__(self, name: str):
        if name not in AGENT_NAMES:
            raise KeyError(f"未知的假 agent: {name}")
        self.name = name
        self._script = None
        self._index = 0
        self._call_seq = 0

    def next_action(self, state):
        if self._script is None:
            self._script = build_script(self.name, state.task_id)
        if self._index >= len(self._script):
            return Finish("脚本已耗尽")
        entry = self._script[self._index]
        self._index += 1
        if isinstance(entry, (Finish, Abort)):
            return entry
        calls = []
        for tool, args in entry:
            self._call_seq += 1
            calls.append(ToolCall(call_id=f"c{self._call_seq}", tool=tool, args=args))
        return ToolCalls(calls)
