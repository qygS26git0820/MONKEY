"""轨迹写入与输出截断。

两条不变量：
1. 逐行 flush —— 崩溃后轨迹仍可读。
2. 交付给 agent 的文本必须能由 blob + 元数据逐字节重建（见 reconstruct）。
"""

import hashlib
import json
from pathlib import Path

from . import clock, contract


class ContractViolation(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_blob(blob_dir: Path, data: str, sha: str) -> str:
    blob_dir.mkdir(parents=True, exist_ok=True)
    name = f"{sha}.blob"
    target = blob_dir / name
    if not target.exists():
        target.write_bytes(data.encode("utf-8"))
    return name


def _marker(elided: int) -> str:
    return f"\n...[truncated {elided} bytes]...\n"


def _head_within(data: str, chars: int, byte_cap: int) -> str:
    """取前若干字符，字符数不超过 chars、UTF-8 字节数不超过 byte_cap。

    上限按字节、切点按字符——多字节内容下保留的字符数会少于 chars，但绝不会
    把某个字符切成两半。
    """
    text = data[:chars]
    if len(text.encode("utf-8")) <= byte_cap:
        return text
    kept, used = [], 0
    for ch in text:
        size = len(ch.encode("utf-8"))
        if used + size > byte_cap:
            break
        used += size
        kept.append(ch)
    return "".join(kept)


def _tail_within(data: str, chars: int, byte_cap: int) -> str:
    """尾部对称版本：从末尾往回取。"""
    text = data[-chars:] if chars else ""
    if len(text.encode("utf-8")) <= byte_cap:
        return text
    kept, used = [], 0
    for ch in reversed(text):
        size = len(ch.encode("utf-8"))
        if used + size > byte_cap:
            break
        used += size
        kept.append(ch)
    return "".join(reversed(kept))


def prepare_stream(data: str, opts, blob_dir: Path) -> tuple[str, dict]:
    """返回 (交付给 agent 的文本, 落盘的流元数据)。

    head/tail 按**字符**切分，因此切点不会落在多字节字符中间，
    于是字节层面的重建是精确的。

    但保留量按**字节**设上限：多字节内容下 head_chars 个字符可能是它三倍的
    字节，"只按字符切"会让 head 与 tail 合起来覆盖甚至超过原文——那样交付的
    文本比原文还长、`elided_bytes` 为负、agent 读到"截断 -8193 字节"这种乱码
    标记。上限保证 head_bytes + tail_bytes < total，即截断真的截掉了东西。
    """
    raw = data.encode("utf-8")
    total = len(raw)
    sha_full = _sha256_bytes(raw)

    # 标记自身要占字节，故上限先把它扣掉。标记里的省略量落在 [0, total]，它的
    # 十进制位数不超过 total 的位数，故用 total 算出的标记是它的**长度上界**。
    marker_reserve = len(_marker(total).encode("utf-8"))

    # 第二个条件只在阈值小到放不下标记时才成立（total 略大于阈值、且阈值 <
    # 约 30 字节）。那种配置下截断只会让交付量变大，故按原样交付。
    if total <= opts.truncate_threshold_bytes or total - marker_reserve < 1:
        delivered = data
        meta = {
            "bytes_total": total,
            "bytes_delivered": total,
            "elided_bytes": 0,
            "truncated": False,
            "strategy": "none",
            "head_bytes": total,
            "tail_bytes": 0,
            "marker_text": "",
            "sha256_full": sha_full,
            "sha256_delivered": sha_full,
            "blob_ref": None,
        }
        return delivered, meta

    kept_cap = min(opts.truncate_threshold_bytes, total - marker_reserve)
    char_total = opts.head_chars + opts.tail_chars
    head_cap = kept_cap * opts.head_chars // char_total if char_total else 0
    head_text = _head_within(data, opts.head_chars, head_cap)
    tail_text = _tail_within(data, opts.tail_chars, kept_cap - head_cap)
    head_bytes = len(head_text.encode("utf-8"))
    tail_bytes = len(tail_text.encode("utf-8"))
    elided = total - head_bytes - tail_bytes
    marker = _marker(elided)
    delivered = head_text + marker + tail_text
    meta = {
        "bytes_total": total,
        "bytes_delivered": len(delivered.encode("utf-8")),
        "elided_bytes": elided,
        "truncated": True,
        "strategy": "head_tail",
        "head_bytes": head_bytes,
        "tail_bytes": tail_bytes,
        "marker_text": marker,
        "sha256_full": sha_full,
        "sha256_delivered": _sha256_bytes(delivered.encode("utf-8")),
        "blob_ref": write_blob(blob_dir, data, sha_full),
    }
    return delivered, meta


def reconstruct(blob_bytes: bytes, meta: dict) -> bytes:
    """由完整内容 + 元数据精确重建交付内容。"""
    if not meta["truncated"]:
        return blob_bytes
    return (
        blob_bytes[: meta["head_bytes"]]
        + meta["marker_text"].encode("utf-8")
        + blob_bytes[len(blob_bytes) - meta["tail_bytes"] :]
    )


class TraceWriter:
    def __init__(self, path: Path, run_id: str):
        self._path = path
        self._fh = path.open("w", encoding="utf-8", newline="\n")
        self.run_id = run_id
        self.seq = 0
        self._t0 = clock.now()

    def emit(self, event_type: str, step: int | None = None, **fields) -> dict:
        if event_type not in contract.EVENT_TYPES:
            raise ContractViolation(f"未声明的事件类型: {event_type}")
        self.seq += 1
        record = {
            "schema_version": contract.SCHEMA_VERSION,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts_mono": round(clock.now() - self._t0, 6),
            "ts_wall": clock.wall(),
            "type": event_type,
        }
        if step is not None:
            record["step"] = step
        record.update(fields)
        missing = [f for f in contract.REQUIRED_FIELDS[event_type] if f not in record]
        if missing:
            raise ContractViolation(f"{event_type} 缺少必需字段: {missing}")
        self._fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        self._fh.flush()
        return record

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            pass


def read_trace(path: Path) -> list:
    records = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ContractViolation(f"{path}:{line_no} 不是合法 JSON: {exc}") from exc
    return records


def validate_records(records: list) -> list:
    """返回问题列表；空列表表示合法。"""
    problems = []
    seen_seq = 0
    for i, rec in enumerate(records, 1):
        where = f"第 {i} 条"
        for field in contract.COMMON_FIELDS:
            if field not in rec:
                problems.append(f"{where} 缺少公共字段 {field}")
        et = rec.get("type")
        if et not in contract.EVENT_TYPES:
            problems.append(f"{where} 未知事件类型 {et!r}")
            continue
        for field in contract.REQUIRED_FIELDS[et]:
            if field not in rec:
                problems.append(f"{where} ({et}) 缺少字段 {field}")
        if et == "tool_result":
            if rec.get("status") not in contract.TOOL_RESULT_STATUSES:
                problems.append(f"{where} 非法 tool_result.status {rec.get('status')!r}")
            for key in ("stdout_stream", "stderr_stream"):
                stream = rec.get(key)
                if not isinstance(stream, dict):
                    problems.append(f"{where} {key} 不是对象")
                    continue
                for field in contract.STREAM_FIELDS:
                    if field not in stream:
                        problems.append(f"{where} {key} 缺少截断字段 {field}")
                if stream.get("strategy") not in contract.TRUNCATION_STRATEGIES:
                    problems.append(f"{where} {key} 非法 strategy {stream.get('strategy')!r}")
        if et == "run_end":
            fc = rec.get("failure_class")
            if fc not in contract.FAILURE_CLASSES:
                problems.append(f"{where} 未声明的 failure_class {fc!r}")
            if rec.get("status") not in contract.RUN_END_STATUSES:
                problems.append(f"{where} 非法 status {rec.get('status')!r}")
        if "seq" in rec:
            if rec["seq"] != seen_seq + 1:
                problems.append(f"{where} seq 不连续：期望 {seen_seq + 1}，实际 {rec['seq']}")
            seen_seq = rec["seq"]
    return problems
