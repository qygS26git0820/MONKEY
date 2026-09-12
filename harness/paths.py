"""唯一的路径来源。其他模块禁止出现相对路径或 os.getcwd()。"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

HARNESS_DIR = PROJECT_ROOT / "harness"
CONFIGS_DIR = PROJECT_ROOT / "configs"
TASKS_DIR = PROJECT_ROOT / "tasks"
RUNS_DIR = PROJECT_ROOT / "runs"
TMP_DIR = PROJECT_ROOT / "tmp"
DOCS_DIR = PROJECT_ROOT / "docs"
TESTS_DIR = PROJECT_ROOT / "tests"


def ensure_within(path) -> Path:
    """解析路径并断言其位于项目根目录之下；越界即抛错。"""
    resolved = Path(path).resolve()
    root = PROJECT_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"路径越出项目根目录，拒绝操作: {resolved}")
    return resolved
