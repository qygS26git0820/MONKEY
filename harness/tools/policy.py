"""工作区路径策略：agent 只能触碰工作区之内的路径。"""

from pathlib import Path


class PathPolicyError(Exception):
    pass


def resolve_in_workspace(workspace: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise PathPolicyError("path 必须是非空字符串")
    root = Path(workspace).resolve()
    candidate = Path(raw_path)
    target = (root / candidate if not candidate.is_absolute() else candidate).resolve()
    if target != root and root not in target.parents:
        raise PathPolicyError(f"路径越出工作区，拒绝访问: {raw_path}")
    return target
