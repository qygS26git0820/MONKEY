"""任务加载。任务定义非法 → harness_error，在启动前就报错。"""

import json
from dataclasses import dataclass
from pathlib import Path

from .. import paths


class TaskError(ValueError):
    pass


@dataclass
class Task:
    id: str
    dir: Path
    description: str
    repo_dir: Path
    verify: dict


def load_task(task_id: str, tasks_dir: Path | None = None) -> Task:
    base = Path(tasks_dir) if tasks_dir else paths.TASKS_DIR
    task_dir = base / task_id
    manifest = task_dir / "task.json"
    if not manifest.is_file():
        raise TaskError(f"任务不存在或缺少 task.json: {task_dir}")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    for field in ("id", "description", "repo", "verify"):
        if field not in data:
            raise TaskError(f"{manifest} 缺少字段: {field}")

    verify = data["verify"]
    command = verify.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        raise TaskError(f"{manifest} 的 verify.command 必须是非空字符串列表")
    if data["id"] != task_id:
        raise TaskError(f"{manifest} 的 id 与目录名不一致: {data['id']} != {task_id}")

    repo_dir = task_dir / data["repo"]
    if not repo_dir.is_dir():
        raise TaskError(f"任务仓库目录不存在: {repo_dir}")

    return Task(
        id=data["id"],
        dir=task_dir,
        description=data["description"],
        repo_dir=repo_dir,
        verify={"command": list(command), "cwd": verify.get("cwd", ".")},
    )
