"""提示词与工具描述。

工具 schema 放在这里而不是 `tools/base.py`：那个文件是冻结的，而"模型看到的工具
描述"是**观测的一部分**——换一版措辞就等于换一个实验条件，它应当能被单独改版并
被测试盯住（审计 §7.3）。`tools/base.py` 只有 `name` 与 `execute`，没有 schema。

代价是"加了工具却忘了写 schema"会是个静默故障：模型看不见那个工具。这条漂移由
`tests/test_llm_tool_schemas.py` 拦住——每个注册工具必须恰好有一条 schema。
"""

SYSTEM_PROMPT_TEMPLATE = """你是一个在隔离工作区里修 bug 的软件工程 agent。

工作区（相对路径都相对它解释）：<<WORKSPACE>>

你可以用下面这些工具。一次可以调用多个。

- read_file(path)            读工作区内的一个文件
- write_file(path, content)  写工作区内的一个文件（整份覆盖）
- run_command(command, ...)  在工作区内执行一条命令（参数列表，不经 shell）
- run_verify()               运行任务自带的验证命令并返回结果

规则：
- 先读代码再改，不要凭猜测改。
- 改完必须调用 run_verify 自证。它是唯一被接受的证据——你自述"修好了"不算数。
- 不要改工作区之外的东西，也不要改验证脚本本身。
- 认为任务已经完成时，不要再调用工具，直接回一段简短的中文小结。"""


TOOL_SCHEMAS = (
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读工作区内的一个文件，返回它的 UTF-8 文本内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "把内容写进工作区内的一个文件，整份覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对工作区的文件路径"},
                    "content": {"type": "string", "description": "文件的完整新内容"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "在工作区内执行一条命令。command 是参数列表，不经 shell。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令与参数，例如 [\"python\", \"-c\", \"print(1)\"]",
                    },
                    "cwd": {"type": "string", "description": "相对工作区的目录，默认 ."},
                    "timeout_s": {"type": "number", "description": "超时秒数"},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_verify",
            "description": "运行任务自带的验证命令。用哪条命令由任务定义，调用方不能选。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
)


def system_prompt(state) -> str:
    # 用 <<标记>> 替换而不是 str.format：提示词里出现花括号（比如示例代码）时
    # format 会直接抛错，而提示词是最不该被这类意外绊住的地方。
    return SYSTEM_PROMPT_TEMPLATE.replace("<<WORKSPACE>>", state.workspace)


def build_messages(state) -> list:
    """第一轮的 wire 消息。

    任务描述取 `state.description`——`loop.py` 已把同一段文字作为第一条 user
    消息 append 进 `state.messages`，这里与它保持一致，不另造一份。
    """
    return [
        {"role": "system", "content": system_prompt(state)},
        {"role": "user", "content": state.description},
    ]


def tool_result_text(entry: dict) -> str:
    """把 `loop.py` append 进 state 的工具结果字典，转成给模型看的文本。"""
    header = f"工具 {entry.get('tool')} → status={entry.get('status')} exit={entry.get('exit_code')}"
    stdout = (entry.get("stdout") or "").rstrip()
    stderr = (entry.get("stderr") or "").rstrip()
    parts = [header]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    if not stdout and not stderr:
        parts.append("(无输出)")
    return "\n".join(parts)
