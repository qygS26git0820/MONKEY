"""运行上下文：唯一被允许创建运行目录与写入产物的对象。"""

import json
import platform
import shutil
from pathlib import Path

from . import contract, paths
from .env.docker import DEFAULT_IMAGE
from .trace import TraceWriter


class RunContext:
    def __init__(self, *, run_id, config, task, agent_name, harness_git_sha,
                 executor_kind, repo_variant=None):
        self.run_id = run_id
        self.config = config
        self.config_hash = config.config_hash()
        self.harness_git_sha = harness_git_sha
        self.python_version = platform.python_version()
        self.task = task

        self.run_dir = paths.ensure_within(paths.RUNS_DIR / run_id)
        if self.run_dir.exists():
            raise RuntimeError(f"run_id 已存在，拒绝覆盖: {run_id}")

        self.blobs_dir = self.run_dir / "blobs"
        self.verification_dir = self.run_dir / "verification"
        self.workspace = self.run_dir / "workspace"

        self.run_dir.mkdir(parents=True)
        self.blobs_dir.mkdir()
        self.verification_dir.mkdir()

        source = task.repo_dir if repo_variant is None else task.dir / repo_variant
        if not source.exists():
            raise RuntimeError(f"任务仓库不存在: {source}")
        shutil.copytree(source, self.workspace)

        self.trace = TraceWriter(self.run_dir / "trace.jsonl", run_id)

        meta = {
            "schema_version": contract.SCHEMA_VERSION,
            "run_id": run_id,
            "task_id": task.id,
            "agent": agent_name,
            "executor": executor_kind,
            "repo_variant": repo_variant or "repo",
            "config_hash": self.config_hash,
            "harness_git_sha": self.harness_git_sha,
            "python_version": self.python_version,
        }
        if executor_kind == "docker":
            # 记录用的是哪个镜像位，否则两条 docker 轨迹无法判断是否同一后端。
            # 注意 python_version 仍是**宿主**版本，不是容器里的：容器里的
            # python 只是镜像的属性，这里没有多起一个容器去问它。
            meta["executor_image"] = config.docker_image or DEFAULT_IMAGE
        (self.run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def close(self) -> None:
        self.trace.close()
