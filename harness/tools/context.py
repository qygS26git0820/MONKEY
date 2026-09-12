from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolContext:
    workspace: Path
    executor: object
    config: object
    task: object
    verification_dir: Path
