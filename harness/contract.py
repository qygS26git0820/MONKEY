"""冻结的契约常量。

规则见 docs/trace-schema.md 第三部分：只增不改。
禁止改字段名、改语义、删除、改判定顺序。
任何修改都必须同步更新 tests/fixtures/contract_snapshot.json，
并在 docs/trace-schema.md 的变更记录中登记。
"""

SCHEMA_VERSION = 1

COMMON_FIELDS = ("schema_version", "run_id", "seq", "ts_mono", "ts_wall", "type")

EVENT_TYPES = (
    "run_start",
    "agent_message",
    "llm_request",
    "llm_response",
    "tool_call",
    "tool_result",
    "step_end",
    "verification",
    "error",
    "run_end",
)

FAILURE_CLASSES = (
    "none",
    "agent_loop_limit",
    "agent_gave_up",
    "tool_error_repeated",
    "verification_failed",
    "timeout_wall",
    "timeout_step",
    "policy_denied",
    "env_error",
    "harness_error",
    "aborted_by_user",
    "cost_budget_exceeded",
    "llm_transport_error",
    "llm_api_rejected",
    "llm_response_invalid",
)

# 先到者胜。主循环顺序执行，终止条件在时间上有序，故每次 run 精确命中一个。
FAILURE_DECISION_ORDER = (
    "aborted_by_user",
    "harness_error",
    "env_error",
    "llm_transport_error",
    "llm_api_rejected",
    "llm_response_invalid",
    "cost_budget_exceeded",
    "timeout_wall",
    "timeout_step",
    "tool_error_repeated",
    "policy_denied",
    "agent_gave_up",
    "agent_loop_limit",
    "verification_failed",
    "none",
)

# 模型调用失败的三个标签。它们排在 env_error 之后：与"执行环境不可用"同属
# 外部原因，而不是我们代码的 bug——这正是把它们从 harness_error 里分出来的
# 理由。三者内部无先后语义：一次 run 只可能由其中一个信号终止。
LLM_FAILURE_CLASSES = (
    "llm_transport_error",
    "llm_api_rejected",
    "llm_response_invalid",
)

TOOL_RESULT_STATUSES = ("ok", "error", "timeout", "denied")

TRUNCATION_STRATEGIES = ("none", "head_tail")

STREAM_FIELDS = (
    "bytes_total",
    "bytes_delivered",
    "elided_bytes",
    "truncated",
    "strategy",
    "head_bytes",
    "tail_bytes",
    "marker_text",
    "sha256_full",
    "sha256_delivered",
    "blob_ref",
)

REQUIRED_FIELDS = {
    "run_start": (
        "task_id", "agent", "executor", "config_hash",
        "harness_git_sha", "python_version", "schema_version",
    ),
    "agent_message": ("role", "content"),
    "llm_request": ("model", "step"),
    "llm_response": ("model", "step"),
    "tool_call": ("call_id", "tool", "args", "cwd"),
    "tool_result": (
        "call_id", "tool", "status", "exit_code", "duration_ms",
        "stdout", "stderr", "stdout_stream", "stderr_stream",
    ),
    "step_end": ("step", "duration_ms"),
    "verification": (
        "name", "command", "exit_code", "status", "duration_ms",
        "stdout", "stderr", "stdout_stream", "stderr_stream",
    ),
    "error": ("where", "exception_type", "message"),
    "run_end": (
        "status", "failure_class", "steps", "duration_ms", "totals",
    ),
}

# run_end.status 由 failure_class 映射而来，语义固定。
RUN_END_STATUSES = ("completed", "failed", "aborted", "error")
