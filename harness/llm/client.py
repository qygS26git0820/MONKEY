"""DeepSeek 聊天补全的传输层 —— 以及 A2 的三层超时。

A2（审计 §5.2）：`loop.py` 是**同步**调用 `next_action`，而 `timeout_step`
在它返回**之后**才检查、`timeout_wall` 在**下一轮开头**才检查。所以一个
永不返回的模型请求会让 run 永久挂着。冻结的 `loop.py` 无法抢占一个同步
调用，抢占必须由传输层自带。三层：

1. httpx 逐阶段超时 `Timeout(connect, read, write, pool)`：挡住连接阶段挂死，
   以及正文中途**全程静默**超过 `read` 的网关。
2. httpcore 之下的真实 socket：让第 1 层的 `read` 真正生效。这一层**必须**用
   真实回环 socket 验证——`httpx.MockTransport` 绕过 httpcore，根本走不到
   socket，测出来的"通过"是假的。
3. **总时限**（默认 90s）包住**整次交换**（建连 + 收响应头 + 读正文）：因为
   `read` 是"两次读之间的最大间隔"，不是总时长，一个每 40s 送 1 字节的滴流
   网关永远骗过它。

第 3 层为什么必须做成**线程级**包装，而不是"迭代 chunk 时查截止"：若网关在
**发完响应头之前**就开始滴流，任何"响应头之后"的检查一次都跑不到——请求会
阻塞在"等头"上，而那里没有我们的代码。于是整次交换放进 worker 线程，主线程
`join(total_s)`，超时则关闭底层连接解阻塞。这样"头之前滴流"与"头之后滴流"
被同一个截止包住。

失败标签由本层给出（`core/errors.py::ModelFailure` 的约定：只有客户端知道
失败发生在哪一层）：

- 连不上 / 连接或读写超时 / 连接被重置 / 响应编码坏掉 → `llm_transport_error`
- HTTP 非 200（含 401 / 402 / 429 / 5xx）→ `llm_api_rejected`（本批不重试）
- 200 但 body 非 JSON / 缺必需结构 / `tool_calls[].function.arguments` 不是
  合法 JSON → `llm_response_invalid`

**我们自己的 bug 不伪装成传输失败**：例如 base_url 协议不支持会被原样抛出，
留给主循环落成 `harness_error`——那才是"我们写错了"该待的地方。
"""

import json
import threading
import time
from dataclasses import dataclass

import httpx

from ..core.errors import ModelFailure
from . import credentials

DEFAULT_BASE_URL = "https://api.deepseek.com"
CHAT_COMPLETIONS_PATH = "/chat/completions"
DEFAULT_MAX_OUTPUT_TOKENS = 2048

# 总时限触发后，给 worker 这么多秒把关闭连接引起的异常带回来；带不回来也
# 无所谓，worker 是守护线程，不会挂住进程。
_DEADLINE_GRACE_S = 1.0

# 被判定为"传输层失败"（而非我们的 bug）的 httpx 异常。
# 刻意**不含** `httpx.UnsupportedProtocol` / `httpx.InvalidURL`：那是配置写错，
# 是我们的 bug，应落成 harness_error。
_TRANSPORT_ERRORS = (
    httpx.TimeoutException,   # Connect/Read/Write/Pool 四种超时
    httpx.NetworkError,       # ConnectError / ReadError / WriteError
    httpx.ProtocolError,      # Local/RemoteProtocolError
    httpx.ProxyError,
    httpx.DecodingError,      # 响应体编码坏了
)


@dataclass(frozen=True)
class LlmTimeouts:
    """三个正交的时限来源：逐阶段、总时限。单位秒。"""

    connect_s: float = 5.0
    read_s: float = 45.0
    write_s: float = 10.0
    pool_s: float = 5.0
    total_s: float = 90.0

    def httpx_timeout(self) -> httpx.Timeout:
        # httpx 要求四者要么全给、要么给一个默认值，故四个都显式写出来。
        return httpx.Timeout(
            connect=self.connect_s, read=self.read_s,
            write=self.write_s, pool=self.pool_s,
        )


# 生产值。`read < total`：正文中途静默应先以**更具体的**"读取超时"落定，总时限
# 只兜底那类骗过 `read` 的滴流。反过来写，静默与滴流会塌成同一句话。
SHIPPED_TIMEOUTS = LlmTimeouts()


@dataclass
class LlmReply:
    """协议层校验并归一化之后的响应。工具名、参数都已是干净的 Python 值。"""

    model: str
    content: "str | None"
    tool_calls: list            # [{"id": str, "name": str, "arguments": dict}]
    stop_reason: "str | None"
    input_tokens: "int | None"
    output_tokens: "int | None"
    latency_ms: int
    request_json_bytes: int


@dataclass(frozen=True)
class _RawResponse:
    status_code: int
    text: str


class LlmClient:
    """一次 `complete()` 发一次请求，不重试。

    不重试是刻意的：重试会让一次 `next_action` 对应多条 `llm_request`，而
    agent 侧的 `step` 是自计数的（见接线批次），两者会错位。要重试就得先让
    轨迹能表达"一步多请求"。
    """

    def __init__(self, *, model, base_url=DEFAULT_BASE_URL,
                 max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS, timeouts=None):
        if not model:
            raise ValueError("model 不能为空")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_output_tokens = max_output_tokens
        self._timeouts = timeouts or SHIPPED_TIMEOUTS

    def complete(self, *, messages, tools=None) -> LlmReply:
        key = credentials.api_key()
        if key is None:
            # 启动期校验（config.py：配了 model 却没凭据即拒绝启动）本该拦下
            # 这种情况。走到这里说明有调用方绕过了它——那是我们的 bug，故抛
            # 普通异常，让主循环落成 harness_error，而不是伪装成网关问题。
            raise RuntimeError(
                f"凭据不存在：环境变量 {credentials.API_KEY_ENV} 未设置"
            )

        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            # 值只在此处出现一次，直接进 HTTP 头，绝不进入任何产物。
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        started = time.monotonic()
        raw = self._post_with_total_deadline(
            self.base_url + CHAT_COMPLETIONS_PATH, headers, payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        if raw.status_code != 200:
            raise ModelFailure(
                "llm_api_rejected",
                detail=f"HTTP {raw.status_code}: {_snippet(raw.text)}",
            )
        return self._parse(raw, latency_ms=latency_ms,
                          request_json_bytes=len(payload))

    def _post_with_total_deadline(self, url, headers, payload) -> _RawResponse:
        client = httpx.Client(
            timeout=self._timeouts.httpx_timeout(),
            # 环境代理会让一次 127.0.0.1 上的实验不可复现；真实端点也不需要
            # 它。关掉，让"连到哪儿"完全由 base_url 决定。
            trust_env=False,
            # API 端点上的 3xx 是可疑事实，不当成功跟随；它会以非 200 落成
            # llm_api_rejected。
            follow_redirects=False,
        )
        box = {}

        def worker():
            try:
                box["response"] = client.post(url, headers=headers, content=payload)
            except BaseException as exc:      # 原样带回主线程，由 complete 分类
                box["error"] = exc

        thread = threading.Thread(target=worker, name="llm-post", daemon=True)
        thread.start()
        thread.join(self._timeouts.total_s)

        if thread.is_alive():
            # 整次交换超时（含"响应头之前"）。关连接解阻塞 worker；它是守护
            # 线程，即便没能及时退出也不挂住进程。
            client.close()
            thread.join(_DEADLINE_GRACE_S)
            raise ModelFailure(
                "llm_transport_error",
                detail=f"总时限 {self._timeouts.total_s}s 内未完成一次请求"
                       "（建连 / 响应头 / 正文任一阶段）",
            )

        error = box.get("error")
        if error is not None:
            client.close()
            if isinstance(error, _TRANSPORT_ERRORS):
                raise ModelFailure(
                    "llm_transport_error",
                    detail=_transport_detail(error, self._timeouts),
                ) from error
            raise error

        response = box["response"]
        raw = _RawResponse(response.status_code, response.text)
        client.close()
        return raw

    def _parse(self, raw, *, latency_ms, request_json_bytes) -> LlmReply:
        try:
            data = json.loads(raw.text)
        except json.JSONDecodeError as exc:
            raise ModelFailure(
                "llm_response_invalid",
                detail=f"响应不是合法 JSON: {exc}",
            ) from exc
        if not isinstance(data, dict):
            raise ModelFailure("llm_response_invalid", detail="响应顶层不是对象")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelFailure("llm_response_invalid", detail="响应缺少非空的 choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ModelFailure("llm_response_invalid", detail="choices[0] 不是对象")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ModelFailure("llm_response_invalid", detail="choices[0].message 不是对象")

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ModelFailure("llm_response_invalid", detail="message.content 不是字符串")

        tool_calls = []
        raw_calls = message.get("tool_calls")
        if raw_calls is not None:
            if not isinstance(raw_calls, list):
                raise ModelFailure("llm_response_invalid", detail="message.tool_calls 不是数组")
            for index, call in enumerate(raw_calls):
                tool_calls.append(_parse_tool_call(call, index))

        usage = data.get("usage")
        if usage is None:
            usage = {}
        if not isinstance(usage, dict):
            raise ModelFailure("llm_response_invalid", detail="usage 不是对象")

        return LlmReply(
            model=str(data.get("model") or self.model),
            content=content,
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason"),
            input_tokens=_as_int_or_none(usage.get("prompt_tokens")),
            output_tokens=_as_int_or_none(usage.get("completion_tokens")),
            latency_ms=latency_ms,
            request_json_bytes=request_json_bytes,
        )


def _parse_tool_call(call, index: int) -> dict:
    if not isinstance(call, dict):
        raise ModelFailure("llm_response_invalid", detail=f"tool_calls[{index}] 不是对象")
    func = call.get("function")
    if not isinstance(func, dict):
        raise ModelFailure(
            "llm_response_invalid", detail=f"tool_calls[{index}].function 不是对象")
    name = func.get("name")
    if not isinstance(name, str) or not name:
        raise ModelFailure(
            "llm_response_invalid", detail=f"tool_calls[{index}].function.name 缺失")

    raw_args = func.get("arguments")
    if raw_args is None or raw_args == "":
        args = {}
    elif isinstance(raw_args, str):
        # 协议里 arguments 是 JSON **字符串**；解析失败属于"响应不合协议"。
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError as exc:
            raise ModelFailure(
                "llm_response_invalid",
                detail=f"tool_calls[{index}].function.arguments 不是合法 JSON: {exc}",
            ) from exc
    else:
        args = raw_args          # 少数网关直接给对象，按原样接受
    if not isinstance(args, dict):
        raise ModelFailure(
            "llm_response_invalid", detail=f"tool_calls[{index}] 的参数不是对象")
    return {"id": call.get("id") or f"call_{index}", "name": name, "arguments": args}


def _as_int_or_none(value):
    # bool 是 int 的子类，要排除掉，否则 True 会变成 token 计数。
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _transport_detail(exc, timeouts: LlmTimeouts) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return f"连接超时（connect={timeouts.connect_s}s）"
    if isinstance(exc, httpx.ReadTimeout):
        return f"读取超时（两次读之间静默 >{timeouts.read_s}s）"
    if isinstance(exc, httpx.WriteTimeout):
        return f"写入超时（>{timeouts.write_s}s）"
    if isinstance(exc, httpx.PoolTimeout):
        return f"连接池等待超时（>{timeouts.pool_s}s）"
    return f"{type(exc).__name__}: {exc}"


def _snippet(text, limit: int = 300) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")
