"""配置加载与不变量校验。

配置不变量保证"外层预算不会遮蔽内层更具体的原因"：
    max_denied_calls < max_tool_error_streak < max_steps
    step_timeout_s < wall_timeout_s
不满足则拒绝启动，不创建 run 目录。

成本上限比上面几条更严：`max_cost_usd` 要求成本可被算出（模型名已知且
有单价），否则那条上限永远不可能触发。同样在建 run 目录之前拒绝启动。
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .env.factory import EXECUTOR_KINDS
from .llm.pricing import price_for


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Budgets:
    max_steps: int
    wall_timeout_s: float
    step_timeout_s: float
    per_tool_timeout_s: float
    verify_timeout_s: float
    max_tool_error_streak: int
    max_denied_calls: int
    # 新上限默认不设（None）。阶段 1 的配置文件因此逐字节不变，config_hash
    # 也就没变——那批轨迹还能和现在的配置对得上。
    max_cost_usd: "float | None" = None
    max_total_tokens: "int | None" = None


@dataclass(frozen=True)
class TraceOptions:
    truncate_threshold_bytes: int
    head_chars: int
    tail_chars: int


@dataclass(frozen=True)
class Config:
    executor_kind: str
    budgets: Budgets
    trace: TraceOptions
    raw: dict
    # 必须排在 raw 之后：raw 无默认值，带默认值的字段只能跟在后面。
    # 选了 local 后端的配置里没有 [executor].image，此处为 None 表示
    # "用 DockerExecutor 自己的 DEFAULT_IMAGE"，而不是"没有镜像"。
    docker_image: "str | None" = None
    # [llm].model。阶段 1 的配置里没有这一节，故为 None；阶段 2 的 LLM
    # 配置靠它查单价、记 llm_request.model。local 假 agent 不看它。
    llm_model: "str | None" = None

    def config_hash(self) -> str:
        blob = json.dumps(self.raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def load_config(name: str = "default") -> Config:
    path = paths.CONFIGS_DIR / f"{name}.toml"
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    try:
        b = raw["budgets"]
        budgets = Budgets(
            max_steps=int(b["max_steps"]),
            wall_timeout_s=float(b["wall_timeout_s"]),
            step_timeout_s=float(b["step_timeout_s"]),
            per_tool_timeout_s=float(b["per_tool_timeout_s"]),
            verify_timeout_s=float(b["verify_timeout_s"]),
            max_tool_error_streak=int(b["max_tool_error_streak"]),
            max_denied_calls=int(b["max_denied_calls"]),
            max_cost_usd=None if b.get("max_cost_usd") is None else float(b["max_cost_usd"]),
            max_total_tokens=(
                None if b.get("max_total_tokens") is None else int(b["max_total_tokens"])
            ),
        )
        t = raw["trace"]
        trace = TraceOptions(
            truncate_threshold_bytes=int(t["truncate_threshold_bytes"]),
            head_chars=int(t["head_chars"]),
            tail_chars=int(t["tail_chars"]),
        )
        executor_kind = str(raw["executor"]["kind"])
        executor_image = raw["executor"].get("image")
        llm_model = (raw.get("llm") or {}).get("model")
    except KeyError as exc:
        raise ConfigError(f"配置缺少字段: {exc}") from exc

    if executor_kind not in EXECUTOR_KINDS:
        raise ConfigError(
            f"未知的 executor kind: {executor_kind!r}（已知: {', '.join(EXECUTOR_KINDS)}）"
        )
    if not (budgets.max_denied_calls < budgets.max_tool_error_streak < budgets.max_steps):
        raise ConfigError(
            "不变量被破坏，要求 max_denied_calls < max_tool_error_streak < max_steps，"
            f"实际为 {budgets.max_denied_calls} / {budgets.max_tool_error_streak} / {budgets.max_steps}"
        )
    if not budgets.step_timeout_s < budgets.wall_timeout_s:
        raise ConfigError(
            "不变量被破坏，要求 step_timeout_s < wall_timeout_s，"
            f"实际为 {budgets.step_timeout_s} / {budgets.wall_timeout_s}"
        )
    if trace.head_chars + trace.tail_chars > trace.truncate_threshold_bytes:
        raise ConfigError(
            "不变量被破坏，要求 head_chars + tail_chars <= truncate_threshold_bytes，"
            f"实际为 {trace.head_chars} + {trace.tail_chars} > {trace.truncate_threshold_bytes}"
        )
    if budgets.max_cost_usd is not None:
        # 有成本上限就必须能算出成本。模型名缺失或查不到单价时成本恒为
        # 未知，上限永远不可能触发——那是"看起来有预算、实际没有"的假象，
        # 比不设上限更危险。与其让它静默失效，不如拒绝启动。
        if not llm_model:
            raise ConfigError(
                "配置了 budgets.max_cost_usd 但没有 [llm].model，无法估算成本；拒绝启动"
            )
        if price_for(llm_model) is None:
            raise ConfigError(
                f"模型 {llm_model!r} 在 harness/llm/pricing.py 里没有单价，"
                "无法用 max_cost_usd 约束成本；拒绝启动"
            )

    return Config(executor_kind=executor_kind, budgets=budgets, trace=trace, raw=raw,
                  docker_image=executor_image, llm_model=llm_model)
