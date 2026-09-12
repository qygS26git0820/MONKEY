"""文件读写工具。两者都受工作区路径策略约束。"""

from .. import clock
from ..core.messages import ToolOutcome
from .base import Tool
from .policy import PathPolicyError, resolve_in_workspace


class ReadFile(Tool):
    name = "read_file"

    def execute(self, ctx, args) -> ToolOutcome:
        started = clock.now()
        rel = args.get("path", "")
        try:
            target = resolve_in_workspace(ctx.workspace, rel)
        except PathPolicyError as exc:
            return ToolOutcome("denied", None, stderr=str(exc), reason="path_outside_workspace")
        if not target.is_file():
            return ToolOutcome("error", None, stderr=f"file not found: {rel}", reason="file_not_found")
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolOutcome("error", None, stderr=str(exc), reason="read_error")
        return ToolOutcome("ok", 0, stdout=text, duration_ms=_ms(started))


class WriteFile(Tool):
    name = "write_file"

    def execute(self, ctx, args) -> ToolOutcome:
        started = clock.now()
        rel = args.get("path", "")
        content = args.get("content")
        if not isinstance(content, str):
            return ToolOutcome("error", None, stderr="content 必须是字符串", reason="bad_args")
        try:
            target = resolve_in_workspace(ctx.workspace, rel)
        except PathPolicyError as exc:
            return ToolOutcome("denied", None, stderr=str(exc), reason="path_outside_workspace")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            return ToolOutcome("error", None, stderr=str(exc), reason="write_error")
        return ToolOutcome("ok", 0, stdout=f"wrote {len(content)} chars to {rel}",
                           duration_ms=_ms(started))


def _ms(started: float) -> int:
    return clock.ms_since(started)
