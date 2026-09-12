"""配置加载与不变量校验。

配置不变量保证"外层预算不会遮蔽内层更具体的原因"：
    max_denied_calls < max_tool_error_streak < max_steps
    step_timeout_s < wall_timeout_s
不满足则拒绝启动，不创建 run 目录。
"""

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import paths


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
        )
        t = raw["trace"]
        trace = TraceOptions(
            truncate_threshold_bytes=int(t["truncate_threshold_bytes"]),
            head_chars=int(t["head_chars"]),
            tail_chars=int(t["tail_chars"]),
        )
        executor_kind = str(raw["executor"]["kind"])
    except KeyError as exc:
        raise ConfigError(f"配置缺少字段: {exc}") from exc

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

    return Config(executor_kind=executor_kind, budgets=budgets, trace=trace, raw=raw)
