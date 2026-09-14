"""凭据的唯一读取点。

环境变量名只在本模块出现一次；本模块只回答"在不在"，不返回、不打印值。
调用方因此没有任何机会把 key 写进轨迹、日志或报告——"不泄露"靠的不是
每处调用点都记得小心，而是这条路径上根本拿不到值。
"""

import os

API_KEY_ENV = "MONKEY_DEEPSEEK_KEY"


def api_key_present() -> bool:
    return bool(os.environ.get(API_KEY_ENV))
