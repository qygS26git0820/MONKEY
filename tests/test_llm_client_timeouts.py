"""A2 的离线证明：模型/网关卡住时，超时必须能**抢占**。

为什么必须用**真实回环 socket**、而不能用 `httpx.MockTransport`：A2 的第 1 层
超时（`read`）由 httpcore 之下的 socket 实现，MockTransport 把整个传输层换掉，
根本走不到 socket——用它写出来的"通过"是假的。本文件的每个用例都把客户端指向
一个 `127.0.0.1` 上的原始 TCP 服务器，由服务器脚本精确决定怎么"卡住"。

三层各自的承重证据：

- `test_silence_mid_body_trips_the_read_timeout` —— 第 1/2 层：正文中途静默，
  必须是**读取超时**（更具体），且发生在总时限之前。
- `test_a_body_dribble_trips_the_total_deadline` —— 第 3 层：每 100ms 送 1 字节，
  `read` 永远不触发，只有总时限能救。
- `test_a_header_dribble_that_never_finishes_trips_the_total_deadline` —— A2 陷阱：
  滴流发生在**响应头之前**，任何"响应头之后"的截止检查一次都跑不到。

`test_a_well_behaved_server_completes` 是反向对照：没有它，"一切都超时"也会显得
全绿，而那不是抢占，是坏掉。

超时值经 `LlmTimeouts` 注入到亚秒级，故整个文件秒级跑完、零网络、零成本。
"""

import json
import os
import socket
import socketserver
import threading
import time
import unittest
from contextlib import contextmanager
from unittest import mock

from harness.core.errors import ModelFailure
from harness.llm import credentials
from harness.llm.client import SHIPPED_TIMEOUTS, LlmClient, LlmTimeouts
from harness.llm.client import DEFAULT_MAX_OUTPUT_TOKENS

# 生产比例（read < total）必须在测试值里保持，否则"静默先于滴流落定"这条就测不到。
TEST_TIMEOUTS = LlmTimeouts(connect_s=0.5, read_s=0.3, write_s=0.5, pool_s=0.5,
                            total_s=1.0)

# 假 key。只用来断言它出现在请求头里，绝不代表任何真实凭据。
_SENTINEL_KEY = "probe-sentinel-key"

_TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读工作区内的一个文件",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}]

_DRIBBLE_GAP_S = 0.1          # < read(0.3)：读取超时永不触发，逼出总时限
_MIDBODY_SILENCE_S = 3.0      # > read 且 > total


@contextmanager
def _key_present():
    with mock.patch.dict(os.environ, {credentials.API_KEY_ENV: _SENTINEL_KEY}):
        yield


@contextmanager
def _key_absent():
    with mock.patch.dict(os.environ):
        os.environ.pop(credentials.API_KEY_ENV, None)
        yield


# --------------------------------------------------------------------------
# 原始 TCP 服务器：由脚本决定怎么回应
# --------------------------------------------------------------------------

def _read_request(conn) -> bytes:
    """读到完整的 HTTP 请求（含 Content-Length 声明的正文）。"""
    conn.settimeout(5.0)
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            return buf
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(rest) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        rest += chunk
    return head + b"\r\n\r\n" + rest


def _raw_response(status_line: str, body: bytes, content_type: str) -> bytes:
    head = status_line.encode("utf-8") + b"\r\n"
    head += b"Content-Type: " + content_type.encode("utf-8") + b"\r\n"
    head += b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
    head += b"Connection: close\r\n\r\n"
    return head + body


def _ok_body(**overrides) -> dict:
    body = {
        "model": "probe-model",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": "done"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    body.update(overrides)
    return body


def _json_ok(body: dict) -> bytes:
    return _raw_response("HTTP/1.1 200 OK",
                         json.dumps(body, ensure_ascii=False).encode("utf-8"),
                         "application/json")


def script_ok(conn):
    _read_request(conn)
    conn.sendall(_json_ok(_ok_body()))


def script_silent_midbody(conn):
    """发完响应头就静默：`read` 该先于总时限落定。"""
    _read_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Content-Length: 4096\r\n\r\n")
    time.sleep(_MIDBODY_SILENCE_S)


def script_dribble_body(conn):
    """正文滴流，间隔小于 `read`：读取超时永远不触发。"""
    _read_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                 b"Content-Length: 100000\r\n\r\n")
    while True:
        conn.sendall(b"x")
        time.sleep(_DRIBBLE_GAP_S)


def script_dribble_header(conn):
    """响应头滴流且永不结束：A2 陷阱。请求会阻塞在"等头"上。"""
    _read_request(conn)
    conn.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
    while True:
        conn.sendall(b"a")
        time.sleep(_DRIBBLE_GAP_S)


def script_http_401(conn):
    _read_request(conn)
    conn.sendall(_raw_response("HTTP/1.1 401 Unauthorized",
                               b'{"error":{"message":"invalid key"}}',
                               "application/json"))


def script_non_json(conn):
    _read_request(conn)
    conn.sendall(_raw_response("HTTP/1.1 200 OK", b"<html>gateway</html>", "text/html"))


def script_bad_tool_arguments(conn):
    _read_request(conn)
    body = _ok_body(choices=[{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": "{not json"},
            }],
        },
        "finish_reason": "tool_calls",
    }])
    conn.sendall(_json_ok(body))


def script_tool_call(conn):
    _read_request(conn)
    body = _ok_body(choices=[{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "calc.py"}'},
            }],
        },
        "finish_reason": "tool_calls",
    }])
    conn.sendall(_json_ok(body))


def script_no_usage(conn):
    _read_request(conn)
    body = _ok_body()
    del body["usage"]
    conn.sendall(_json_ok(body))


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.server.script(self.request)
        except OSError:
            # 客户端在截止触发后关了连接 → sendall 抛错。这是预期路径，不是失败。
            pass


@contextmanager
def loopback(script):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    server.script = script
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> int:
    """拿一个没人监听的端口（绑定后立刻释放）。"""
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _Probe:
    """把一次 `complete()` 的三种结局（成功 / 失败 / 耗时）一起带回来。"""

    def __init__(self, timeouts=None):
        self._timeouts = timeouts or TEST_TIMEOUTS

    def to(self, base_url):
        client = LlmClient(model="probe-model", base_url=base_url,
                           timeouts=self._timeouts)
        started = time.monotonic()
        try:
            reply = client.complete(messages=[{"role": "user", "content": "hi"}],
                                    tools=_TOOLS)
        except BaseException as exc:      # 失败也是结果，要断言它的类型与标签
            return None, exc, time.monotonic() - started
        return reply, None, time.monotonic() - started

    def script(self, script):
        with loopback(script) as base_url:
            return self.to(base_url)


class A2PreemptionTest(unittest.TestCase):
    """超时必须能抢占一次卡住的调用——而不是等它返回。"""

    def setUp(self):
        self.enterContext(_key_present())
        self.probe = _Probe()

    def _assert_transport_error(self, err):
        self.assertIsInstance(err, ModelFailure, f"期望 ModelFailure，得到 {err!r}")
        self.assertEqual("llm_transport_error", err.failure_class)

    def test_a_well_behaved_server_completes(self):
        # 反向对照。没有它，"一切都超时"看起来也会全绿。
        reply, err, elapsed = self.probe.script(script_ok)

        self.assertIsNone(err, f"正常响应不该失败: {err!r}")
        self.assertEqual("probe-model", reply.model)
        self.assertEqual("done", reply.content)
        self.assertEqual("stop", reply.stop_reason)
        self.assertEqual(11, reply.input_tokens)
        self.assertEqual(7, reply.output_tokens)
        self.assertEqual([], reply.tool_calls)
        self.assertLess(elapsed, 1.0)

    def test_silence_mid_body_trips_the_read_timeout(self):
        _, err, elapsed = self.probe.script(script_silent_midbody)

        self._assert_transport_error(err)
        self.assertIn("读取超时", err.detail, "第 1/2 层没有生效")
        self.assertLess(elapsed, 0.9, "应是读取超时先落定，而不是总时限")

    def test_a_body_dribble_trips_the_total_deadline(self):
        _, err, elapsed = self.probe.script(script_dribble_body)

        self._assert_transport_error(err)
        self.assertIn("总时限", err.detail, "第 3 层没有兜住滴流")
        # 关键：它活过了整个 read 窗口才被总时限掐掉。若 read 抢了先，下面这条
        # 或上面的 detail 就会露馅——这正是"滴流"区别于"静默"的地方。
        self.assertGreaterEqual(elapsed, TEST_TIMEOUTS.read_s)
        self.assertLess(elapsed, 3.0)

    def test_a_header_dribble_that_never_finishes_trips_the_total_deadline(self):
        # A2 陷阱：滴流在响应头**之前**。任何"响应头之后"的截止检查都跑不到。
        _, err, elapsed = self.probe.script(script_dribble_header)

        self._assert_transport_error(err)
        self.assertIn("总时限", err.detail)
        self.assertGreaterEqual(elapsed, TEST_TIMEOUTS.read_s,
                                "read 抢了先，说明这条没在测总时限")
        self.assertLess(elapsed, 3.0)

    def test_connect_refused_is_a_transport_error(self):
        _, err, elapsed = self.probe.to(f"http://127.0.0.1:{_closed_port()}")

        self._assert_transport_error(err)
        self.assertLess(elapsed, 2.0)


class RequestShapeTest(unittest.TestCase):
    """客户端到底发了什么——包括 key 只出现在请求头里。"""

    def setUp(self):
        self.enterContext(_key_present())

    def test_the_request_carries_the_key_in_the_header_and_the_params(self):
        captured = {}

        def script(conn):
            captured["raw"] = _read_request(conn)
            conn.sendall(_json_ok(_ok_body()))

        reply, err, _ = _Probe().script(script)
        self.assertIsNone(err, f"不该失败: {err!r}")

        head, _, body = captured["raw"].partition(b"\r\n\r\n")
        self.assertIn(f"Authorization: Bearer {_SENTINEL_KEY}".encode("utf-8"), head)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual("probe-model", payload["model"])
        self.assertIs(False, payload["stream"])
        self.assertEqual(DEFAULT_MAX_OUTPUT_TOKENS, payload["max_tokens"])
        self.assertEqual("auto", payload["tool_choice"])
        self.assertEqual("read_file", payload["tools"][0]["function"]["name"])
        self.assertEqual("hi", payload["messages"][0]["content"])


class LabelMappingTest(unittest.TestCase):
    """失败标签：只有客户端知道失败发生在哪一层。"""

    def setUp(self):
        self.enterContext(_key_present())
        self.probe = _Probe()

    def test_http_401_is_api_rejected(self):
        _, err, _ = self.probe.script(script_http_401)

        self.assertIsInstance(err, ModelFailure)
        self.assertEqual("llm_api_rejected", err.failure_class)
        self.assertIn("401", err.detail)

    def test_a_non_json_body_is_response_invalid(self):
        _, err, _ = self.probe.script(script_non_json)

        self.assertIsInstance(err, ModelFailure)
        self.assertEqual("llm_response_invalid", err.failure_class)

    def test_unparsable_tool_arguments_is_response_invalid(self):
        _, err, _ = self.probe.script(script_bad_tool_arguments)

        self.assertIsInstance(err, ModelFailure)
        self.assertEqual("llm_response_invalid", err.failure_class)
        self.assertIn("arguments", err.detail)

    def test_tool_calls_are_normalized_to_plain_values(self):
        reply, err, _ = self.probe.script(script_tool_call)

        self.assertIsNone(err, f"不该失败: {err!r}")
        self.assertIsNone(reply.content)
        self.assertEqual("tool_calls", reply.stop_reason)
        self.assertEqual(1, len(reply.tool_calls))
        self.assertEqual("read_file", reply.tool_calls[0]["name"])
        self.assertEqual({"path": "calc.py"}, reply.tool_calls[0]["arguments"])

    def test_missing_usage_is_unknown_not_an_error(self):
        # 网关没回 usage 是可疑事实，但要**观测**它，不是炸掉 run。
        # 未知量无法触发 token 上限，这一取舍登记在 known-residues.md R-001。
        reply, err, _ = self.probe.script(script_no_usage)

        self.assertIsNone(err, f"不该失败: {err!r}")
        self.assertIsNone(reply.input_tokens)
        self.assertIsNone(reply.output_tokens)

    def test_a_missing_key_is_our_bug_not_a_transport_error(self):
        # 启动期校验本该拦下；绕过它走到这里，是我的 bug → harness_error，
        # 不能伪装成"网关连不上"。断言里只有变量名，没有值。
        client = LlmClient(model="probe-model", timeouts=TEST_TIMEOUTS)
        with _key_absent(), self.assertRaises(RuntimeError) as caught:
            client.complete(messages=[{"role": "user", "content": "hi"}])

        self.assertNotIsInstance(caught.exception, ModelFailure)
        self.assertIn(credentials.API_KEY_ENV, str(caught.exception))


class ShippedTimeoutTest(unittest.TestCase):
    """生产值本身的性质。改它们必须同时改这里，改动因此是可见的。"""

    def test_shipped_values_are_the_documented_ones(self):
        self.assertEqual(
            (5.0, 45.0, 10.0, 5.0, 90.0),
            (SHIPPED_TIMEOUTS.connect_s, SHIPPED_TIMEOUTS.read_s,
             SHIPPED_TIMEOUTS.write_s, SHIPPED_TIMEOUTS.pool_s,
             SHIPPED_TIMEOUTS.total_s),
        )

    def test_read_is_shorter_than_the_total_deadline(self):
        # 静默应先以更具体的"读取超时"落定，总时限只兜底滴流。反过来写，
        # 两者会塌成同一句话，分层就白做了。
        self.assertLess(SHIPPED_TIMEOUTS.read_s, SHIPPED_TIMEOUTS.total_s)

    def test_every_phase_has_a_positive_timeout(self):
        for field in ("connect_s", "read_s", "write_s", "pool_s", "total_s"):
            with self.subTest(field=field):
                self.assertGreater(getattr(SHIPPED_TIMEOUTS, field), 0)

    def test_the_httpx_timeout_carries_all_four_phases(self):
        # httpx 要求四者要么全给、要么给一个默认值。少一个就会在构造时抛错。
        timeout = SHIPPED_TIMEOUTS.httpx_timeout()
        self.assertEqual(5.0, timeout.connect)
        self.assertEqual(45.0, timeout.read)
        self.assertEqual(10.0, timeout.write)
        self.assertEqual(5.0, timeout.pool)
