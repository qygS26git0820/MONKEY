"""验证执行与结果解析。

验证由 harness 执行、由退出码与解析出的用例计数判定，
不看 agent 自己的说法。
"""

import re

from ..env.expand import expand_command
from ..trace import prepare_stream

RAN_RE = re.compile(r"Ran (\d+) tests? in")
FAILED_RE = re.compile(r"FAILED\s*\(([^)]*)\)")


def parse_unittest(text: str) -> dict:
    ran = RAN_RE.search(text)
    total = int(ran.group(1)) if ran else None
    failures = errors = None
    match = FAILED_RE.search(text)
    if match:
        inner = match.group(1)
        fm = re.search(r"failures=(\d+)", inner)
        em = re.search(r"errors=(\d+)", inner)
        failures = int(fm.group(1)) if fm else 0
        errors = int(em.group(1)) if em else 0
    elif re.search(r"^OK\b", text, re.M):
        failures = errors = 0
    passed = None
    if total is not None and failures is not None and errors is not None:
        passed = total - failures - errors
    return {"tests_total": total, "failures": failures, "errors": errors, "passed": passed}


def run_verification(run_ctx, executor) -> dict:
    config = run_ctx.config
    spec = run_ctx.task.verify
    command = expand_command(spec["command"], executor)
    cwd = run_ctx.workspace / spec.get("cwd", ".")

    result = executor.run(command, cwd, config.budgets.verify_timeout_s)

    if result.launcher_error:
        status = "launcher_error"
    elif result.timed_out:
        status = "timeout"
    else:
        status = "passed" if result.exit_code == 0 else "failed"

    combined = f"{result.stdout}\n{result.stderr}"
    parsed = parse_unittest(combined)

    (run_ctx.verification_dir / "verify.stdout.txt").write_text(result.stdout, encoding="utf-8")
    (run_ctx.verification_dir / "verify.stderr.txt").write_text(result.stderr, encoding="utf-8")

    out_text, out_meta = prepare_stream(result.stdout, config.trace, run_ctx.blobs_dir)
    err_text, err_meta = prepare_stream(result.stderr, config.trace, run_ctx.blobs_dir)

    run_ctx.trace.emit(
        "verification",
        name="verify",
        command=command,
        cwd=executor.visible_path(cwd),
        exit_code=result.exit_code,
        status=status,
        duration_ms=result.duration_ms,
        parsed=parsed,
        stdout=out_text,
        stderr=err_text,
        stdout_stream=out_meta,
        stderr_stream=err_meta,
    )
    return {"status": status, "exit_code": result.exit_code, "parsed": parsed}
