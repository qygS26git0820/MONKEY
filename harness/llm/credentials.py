"""凭据的唯一读取点。

环境变量名只在本模块出现一次。

- `api_key_present()` 只回答"在不在"，供启动期校验（`config.py`）使用。
- `api_key()` 是**唯一**把值取进内存的函数，唯一的合法调用点是构造
  `Authorization` 头。

"不泄露"因此不靠每处调用点都记得小心，而靠这条路径的收口：值只从
`api_key()` 出来一次，直接交给 HTTP 头，绝不进入轨迹、日志、报告或任何提交。
"""

import os

API_KEY_ENV = "MONKEY_DEEPSEEK_KEY"


def api_key_present() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def api_key() -> "str | None":
    """返回凭据值；环境变量未设置时返回 `None`。

    调用约定：返回值只用于构造 `Authorization` 头。禁止 `print`、禁止写入
    任何文件（含 `trace.jsonl` / `meta.json` / `report.md` / `blobs/**`）。
    """
    return os.environ.get(API_KEY_ENV)
