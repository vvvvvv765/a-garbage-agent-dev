"""
provider 方言（共用，不属于任何体系）。

ModI（GPU 的子体系）用它构造请求，ModO（内存的子体系）用它解析事件——
两边都要，所以它不进任何一方的子体系。

现在实现三种方言：
  ResponsesAdapter   OpenAI Responses API（DeepSeek 的 /responses 兼容它）
  ChatAdapter         OpenAI Chat Completions（硅基流动 / OpenRouter / 自定义中转等）
  AnthropicAdapter    Anthropic Messages API（Claude 官方 / Anthropic 兼容中转）
以后接 Gemini 等，新增一个类实现同样的方法即可，不改引擎其余部分。

要接新 provider，需要提供：
  create(handle, bundle, schemas, thinking_on, effort="medium") -> stream
  is_text_delta / text_delta / is_completed / completed_output
  item_type / tool_call / dump_reasoning
"""
import hashlib
import base64
import json
import re
import uuid
from typing import Protocol

from Config import Providers

# DeepSeek 官方档位：low / high / max；旧值按它的别名表归并
_EFFORT_ALIASES = {"minimal": "low", "medium": "high", "xhigh": "high", "ultra": "max"}


def _effort_level(value):
    level = _EFFORT_ALIASES.get(str(value or "").lower(), str(value or "").lower())
    return level if level in {"low", "high", "max"} else "high"


def _active_provider():
    try:
        items = Providers.providers_of(config)
        active = Providers.active_id(config, items)
        return next((item for item in items if item.get("id") == active), {})
    except Exception:
        return {}


def _deepseek_like():
    provider = _active_provider()
    text = " ".join(str(provider.get(key) or "") for key in ("id", "base_url"))
    text += " " + str(config.get("llm.model", ""))
    return "deepseek" in text.lower()
from Config import config
from Log import log
from Paths import home


# GPU 每轮注入的前缀（不是用户的真人消息，不能拿来当会话指纹）
_INJECTED_PREFIXES = (
    "当前运行时上下文（覆盖之前的快照）",
    "[项目上下文]",
    "[之前对话的摘要]",
)


def _text_of(message):
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    return ""


def _opencode_session(bundle):
    """OpenCode Go 的稳定会话 id：拿**第一条真实用户消息**做指纹。

    注意 GPU 会在最前面插 [项目上下文] / 运行时快照 / 摘要，这些不是用户消息；
    拿它们当指纹会让 id 按"天 / 工作区"变，而不是按会话稳定。
    """
    first = ""
    for message in getattr(bundle, "messages", ()) or ():
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _text_of(message)
        if any(text.lstrip().startswith(prefix) for prefix in _INJECTED_PREFIXES):
            continue
        first = text
        break
    if not first:
        return "spirit-session"
    return "spirit-" + hashlib.sha256(first.encode("utf-8")).hexdigest()[:32]


def _opencode_headers(bundle):
    """只有目标是 OpenCode 网关时才补（UA + x-opencode-session）。"""
    base = str(config.get("llm.base_url") or "")
    if not Providers.is_opencode(base):
        return {}
    return Providers.opencode_headers(_opencode_session(bundle))


class LLMAdapter(Protocol):
    def create(self, handle, bundle, schemas, thinking_on, effort="medium"):
        ...

    def is_text_delta(self, event):
        ...

    def text_delta(self, event):
        ...

    def is_thinking_delta(self, event):
        ...

    def thinking_delta(self, event):
        ...

    def is_completed(self, event):
        ...

    def completed_output(self, event):
        ...

    def item_type(self, item):
        ...

    def tool_call(self, item):
        ...

    def dump_reasoning(self, item):
        ...

    def usage(self, event):
        ...


class _ResponsesStream:
    """Responses SDK 流 → 引擎事件；补终止兜底。

    SDK 只保证 completed 是正常终点；incomplete（命中 max_output_tokens）、
    failed、网关断流时没有 completed —— 以前会「屏幕有字、数据表没记录」。
    """

    def __init__(self, stream):
        self.__stream = stream

    def __iter__(self):
        return self.__events()

    def close(self):
        close = getattr(self.__stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def __events(self):
        items = []
        usage = None
        terminal = False
        for event in self.__stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_item.done":
                item = getattr(event, "item", None)
                if item is not None:
                    items.append(item)
            if kind in ("response.completed", "response.incomplete", "response.failed"):
                terminal = True
                response = getattr(event, "response", None)
                output = getattr(response, "output", None) if response is not None else None
                usage = getattr(response, "usage", None) if response is not None else None
                if kind == "response.completed":
                    yield event
                else:
                    error = getattr(response, "error", None) if response is not None else None
                    log.warning("Adapter", f"responses stream ended with {kind}: {error}")
                    if kind == "response.failed":
                        raise ProviderStreamError(f"模型流失败：{error or kind}")
                    yield _ChatCompleted(output or items, usage, truncated=True)
                break
            yield event
        if not terminal:
            log.warning("Adapter", "responses stream ended without terminal event")
            yield _ChatCompleted(items, usage)


class ResponsesAdapter:
    """OpenAI Responses API（DeepSeek /responses 兼容）。"""

    def create(self, handle, bundle, schemas, thinking_on, effort="medium"):
        kwargs = {
            "input": _to_responses_input(bundle),
            "model": config.get("llm.model", "deepseek-Flash"),
            "stream": True,
            "tools": schemas,
        }
        if bundle.instructions:
            kwargs["instructions"] = bundle.instructions

        level = _effort_level(effort or config.get("llm.reasoning", "high")) \
            if thinking_on else "none"
        kwargs["reasoning"] = {"effort": level}
        extra = _opencode_headers(bundle)
        if extra:
            kwargs["extra_headers"] = extra
        try:
            stream = handle.create(**kwargs)
        except Exception as error:
            status = getattr(error, "status_code", None)
            text_error = str(error).lower()
            if "reasoning" in kwargs and ("reasoning" in text_error or status in (400, 422)):
                # 别静默删掉：DeepSeek 默认是“开启 + high”，删了等于最坏情况
                kwargs["reasoning"] = {"effort": "low"}
                log.warning(
                    "Adapter",
                    f"responses endpoint rejected reasoning={level}; downgraded to low",
                )
                try:
                    stream = handle.create(**kwargs)
                except Exception:
                    kwargs.pop("reasoning", None)
                    log.warning(
                        "Adapter",
                        "responses endpoint still rejected reasoning; request without it "
                        "(provider may default to thinking=high)",
                    )
                    stream = handle.create(**kwargs)
            else:
                raise
        return _ResponsesStream(stream)

    @staticmethod
    def is_text_delta(event):
        return event.type == "response.output_text.delta"

    @staticmethod
    def text_delta(event):
        return event.delta

    @staticmethod
    def is_thinking_delta(event):
        """三家方言统一翻译成 response.thinking.delta。"""
        return event.type in (
            "response.thinking.delta",
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        )

    @staticmethod
    def thinking_delta(event):
        return getattr(event, "delta", "") or ""

    @staticmethod
    def is_completed(event):
        return event.type == "response.completed"

    @staticmethod
    def completed_output(event):
        return event.response.output

    @staticmethod
    def item_type(item):
        return getattr(item, "type", None)

    @staticmethod
    def tool_call(item):
        return {
            "call_id": item.call_id,
            "name": item.name,
            "arguments": item.arguments,
        }

    @staticmethod
    def usage(event):
        """从 completed 事件里抠真实 usage；没有就返回 None。

        兼容 SDK 对象和 dict；OpenAI 风格 input/output，Anthropic 风格会由
        各自的 Adapter 覆盖。
        """
        response = getattr(event, "response", None)
        raw = getattr(response, "usage", None)
        if raw is None and isinstance(response, dict):
            raw = response.get("usage")
        if raw is None:
            return None

        def value(obj, *names):
            for name in names:
                if isinstance(obj, dict):
                    if obj.get(name) is not None:
                        return obj.get(name)
                else:
                    got = getattr(obj, name, None)
                    if got is not None:
                        return got
            return 0

        input_tokens = value(raw, "input_tokens", "prompt_tokens")
        output_tokens = value(raw, "output_tokens", "completion_tokens")
        total = value(raw, "total_tokens")
        details_in = value(raw, "input_tokens_details", "prompt_tokens_details")
        details_out = value(raw, "output_tokens_details", "completion_tokens_details")
        cached = value(details_in, "cached_tokens") if details_in else 0
        reasoning = value(details_out, "reasoning_tokens") if details_out else 0
        try:
            return {
                "input": int(input_tokens or 0),
                "output": int(output_tokens or 0),
                "total": int(total or 0) or (int(input_tokens or 0) + int(output_tokens or 0)),
                "cached": int(cached or 0),
                "reasoning": int(reasoning or 0),
            }
        except (TypeError, ValueError):
            return None

    @staticmethod
    def dump_reasoning(item):
        """完整原因块，原样保存。

        DeepSeek 实测形状：model_dump(exclude_none=True)，含 encrypted_content。
        换到要求保留 opaque 字段的 provider 时，在对应 Adapter 里改成保存原始块。
        """
        if hasattr(item, "model_dump"):
            return item.model_dump(exclude_none=True)
        return dict(getattr(item, "__dict__", {}))


class _ChatItem:
    def __init__(self, kind, **fields):
        self.type = kind
        self.__dict__.update(fields)


class _ChatCompleted:
    type = "response.completed"

    def __init__(self, output, usage, truncated=False):
        self.response = type("ChatResponse", (), {"output": output, "usage": usage})()
        self.truncated = bool(truncated)


class ProviderStreamError(RuntimeError):
    """模型流以失败终止（response.failed）；交给重连 / 故障转移。"""


class _ChatEvent:
    def __init__(self, kind, delta):
        self.type = kind
        self.delta = delta


class _ChatStream:
    """把 Chat Completions 的 chunk 流翻译成引擎认的 Responses 事件。"""

    def __init__(self, stream):
        self.__stream = stream

    def __iter__(self):
        return self.__events()

    def close(self):
        close = getattr(self.__stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def __events(self):
        text = []
        reasoning = []
        calls = {}
        usage = None
        finish_reason = ""

        for chunk in self.__stream:
            raw_usage = getattr(chunk, "usage", None)
            if raw_usage is not None:
                usage = raw_usage

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content = getattr(delta, "content", None)
            if content:
                text.append(str(content))
                yield _ChatEvent("response.output_text.delta", str(content))

            thought = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if thought:
                reasoning.append(str(thought))
                yield _ChatEvent("response.thinking.delta", str(thought))

            finish = getattr(choices[0], "finish_reason", None)
            if finish:
                finish_reason = str(finish)

            for tool in getattr(delta, "tool_calls", None) or []:
                # index 不是所有兼容网关都给：有 id 就按 id 归并，否则每次单独开一条
                index = getattr(tool, "index", None)
                call_id = getattr(tool, "id", None)
                if index is None:
                    if call_id:
                        key = ("id", str(call_id))
                    else:
                        key = ("anon", len(calls))
                else:
                    key = ("idx", int(index))
                entry = calls.setdefault(key, {
                    "id": "", "name": "", "arguments": "", "order": len(calls),
                })
                if call_id:
                    entry["id"] = str(call_id)
                function = getattr(tool, "function", None)
                if function is not None:
                    name = getattr(function, "name", None)
                    if name:
                        entry["name"] = str(name)
                    arguments = getattr(function, "arguments", None)
                    if arguments:
                        entry["arguments"] += str(arguments)

        output = []
        if reasoning:
            output.append(_ChatItem("reasoning", text="".join(reasoning)))
        for entry in sorted(calls.values(), key=lambda item: item["order"]):
            output.append(_ChatItem(
                "function_call",
                call_id=entry["id"] or f"call_{uuid.uuid4().hex[:8]}",
                name=entry["name"],
                arguments=entry["arguments"] or "{}",
            ))
        truncated = finish_reason == "length"
        if truncated:
            log.warning("Adapter", "chat stream hit max_tokens (finish_reason=length)")
        yield _ChatCompleted(output, usage, truncated)


def _to_chat_tools(schemas):
    tools = []
    for schema in schemas or []:
        if not isinstance(schema, dict) or schema.get("type") != "function":
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": schema.get("name") or "",
                "description": schema.get("description") or "",
                "parameters": schema.get("parameters") or {
                    "type": "object",
                    "properties": {},
                },
            },
        })
    return tools


_IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)$")
_IMAGE_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}


def _image_blob(image):
    if not isinstance(image, dict):
        return None
    name = str(image.get("id") or "")
    if not _IMAGE_NAME.match(name):
        return None
    path = home() / "uploads" / name
    try:
        data = path.read_bytes()
    except OSError:
        return None
    ext = name.rsplit(".", 1)[-1].lower()
    mime = str(image.get("mime") or _IMAGE_MIME.get(ext, "image/png"))
    return mime, data


def _image_data_url(image):
    blob = _image_blob(image)
    if blob is None:
        return None
    mime, data = blob
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _to_responses_input(bundle):
    """Responses 请求：把带图片的 user 消息换成 input_text / input_image。"""
    items = []
    for item in bundle.messages:
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call_output"
            and item.get("images")
        ):
            content = [{"type": "input_text", "text": str(item.get("output") or "")}]
            for image in item.get("images") or []:
                url = _image_data_url(image)
                if url:
                    content.append({"type": "input_image", "image_url": url})
            items.append({
                "type": "function_call_output",
                "call_id": item.get("call_id") or "",
                "output": content,
            })
            continue
        if (
            isinstance(item, dict)
            and item.get("role")
            and item.get("images")
        ):
            content = []
            text = str(item.get("content") or "")
            if text:
                content.append({"type": "input_text", "text": text})
            for image in item.get("images") or []:
                url = _image_data_url(image)
                if url:
                    content.append({"type": "input_image", "image_url": url})
            if not content:
                content.append({"type": "input_text", "text": "[图片读取失败]"})
            items.append({"role": item["role"], "content": content})
        else:
            items.append(item)
    return items


def _to_chat_messages(bundle):
    """Responses 风格的 input（function_call / function_call_output）→ Chat 消息。"""
    messages = []
    if bundle.instructions:
        messages.append({"role": "system", "content": bundle.instructions})

    pending = []
    tool_images = []

    def flush_tool_images():
        """Chat 的 tool 消息只能放文本：图片统一放到紧随其后的 user 消息里。"""
        if not tool_images:
            return
        images = list(tool_images)
        tool_images.clear()
        parts = [{"type": "text", "text": "工具结果中的图片："}]
        for image in images:
            url = _image_data_url(image)
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
        if len(parts) > 1:
            messages.append({"role": "user", "content": parts})

    def flush():
        if not pending:
            return
        calls = list(pending)
        pending.clear()
        last = messages[-1] if messages else None
        if last is not None and last.get("role") == "assistant" and "tool_calls" not in last:
            last["tool_calls"] = calls
        else:
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": calls,
            })

    for item in bundle.messages:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "function_call":
            pending.append({
                "id": item.get("call_id") or item.get("id") or "",
                "type": "function",
                "function": {
                    "name": item.get("name") or "",
                    "arguments": item.get("arguments") or "{}",
                },
            })
            continue

        if kind != "function_call_output":
            flush_tool_images()
        flush()
        if kind == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id") or "",
                "content": str(item.get("output") or ""),
            })
            tool_images.extend(item.get("images") or [])
        elif kind == "reasoning":
            continue
        elif "role" in item and item.get("content") is not None:
            images = item.get("images") or []
            if images:
                parts = []
                text = str(item.get("content") or "")
                if text:
                    parts.append({"type": "text", "text": text})
                for image in images:
                    url = _image_data_url(image)
                    if url:
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": url},
                        })
                if not parts:
                    parts.append({"type": "text", "text": "[图片读取失败]"})
                messages.append({"role": item["role"], "content": parts})
            else:
                messages.append({
                    "role": item["role"],
                    "content": item.get("content"),
                })

    flush()
    flush_tool_images()
    return messages


class ChatAdapter(ResponsesAdapter):
    """OpenAI Chat Completions（Kimi / GLM / Qwen / 硅基流动 / OpenRouter 等）。"""

    def create(self, handle, bundle, schemas, thinking_on, effort="medium"):
        kwargs = {
            "model": config.get("llm.model", ""),
            "messages": _to_chat_messages(bundle),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        tools = _to_chat_tools(schemas)
        if tools:
            kwargs["tools"] = tools
        extra = _opencode_headers(bundle)
        if extra:
            kwargs["extra_headers"] = extra

        # DeepSeek Chat：thinking 开关 + reasoning_effort；关闭时必须显式 disabled
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["thinking"] = {"type": "enabled" if thinking_on else "disabled"}
        kwargs["extra_body"] = extra_body
        if thinking_on:
            kwargs["reasoning_effort"] = _effort_level(
                effort or config.get("llm.reasoning", "high")
            )

        for _ in range(4):
            try:
                stream = handle.create(**kwargs)
                return _ChatStream(stream)
            except Exception as error:
                status = getattr(error, "status_code", None)
                text_error = str(error).lower()
                retryable = status in (400, 422) or isinstance(error, TypeError)
                changed = False
                body = kwargs.get("extra_body") or {}
                if "stream_options" in kwargs and (
                        "stream_options" in text_error or "include_usage" in text_error):
                    kwargs.pop("stream_options", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected stream_options; retried without it")
                elif "thinking" in body and "thinking" in text_error:
                    body = dict(body)
                    body.pop("thinking", None)
                    if body:
                        kwargs["extra_body"] = body
                    else:
                        kwargs.pop("extra_body", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected thinking toggle; retried without it")
                elif "reasoning_effort" in kwargs and "reasoning_effort" in text_error:
                    kwargs.pop("reasoning_effort", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected reasoning_effort; retried without it")
                elif retryable and "stream_options" in kwargs:
                    kwargs.pop("stream_options", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected optional params; dropped stream_options")
                elif retryable and "thinking" in body:
                    body = dict(body)
                    body.pop("thinking", None)
                    if body:
                        kwargs["extra_body"] = body
                    else:
                        kwargs.pop("extra_body", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected optional params; dropped thinking")
                elif retryable and "reasoning_effort" in kwargs:
                    kwargs.pop("reasoning_effort", None)
                    changed = True
                    log.warning("Adapter", "chat endpoint rejected optional params; dropped reasoning_effort")
                if not changed:
                    raise
        raise RuntimeError("chat endpoint kept rejecting optional parameters")

    @staticmethod
    def dump_reasoning(item):
        text = str(getattr(item, "text", "") or "")
        return {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": text}],
        }


class _AnthropicItem:
    def __init__(self, kind, **fields):
        self.type = kind
        self.__dict__.update(fields)


class _AnthropicCompleted:
    type = "response.completed"

    def __init__(self, output, usage):
        self.response = type(
            "AnthropicResponse", (), {"output": output, "usage": usage}
        )()


class _AnthropicEvent:
    def __init__(self, kind, delta):
        self.type = kind
        self.delta = delta


def _to_anthropic_tools(schemas):
    tools = []
    for schema in schemas or []:
        if not isinstance(schema, dict) or schema.get("type") != "function":
            continue
        tools.append({
            "name": schema.get("name") or "",
            "description": schema.get("description") or "",
            "input_schema": schema.get("parameters") or {
                "type": "object",
                "properties": {},
            },
        })
    return tools


def _to_anthropic_messages(bundle):
    """Responses 风格的 input → Anthropic messages（含 thinking / tool_use / tool_result）。"""
    messages = []

    def ensure(role):
        if messages and messages[-1]["role"] == role:
            return messages[-1]
        message = {"role": role, "content": []}
        messages.append(message)
        return message

    for item in bundle.messages:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "function_call":
            call_id = item.get("call_id") or item.get("id") or ""
            name = item.get("name") or ""
            raw = item.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except (TypeError, ValueError):
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            ensure("assistant")["content"].append({
                "type": "tool_use",
                "id": call_id,
                "name": name,
                "input": arguments,
            })
        elif kind == "function_call_output":
            text = str(item.get("output") or "")
            images = item.get("images") or []
            if images:
                content = [{"type": "text", "text": text}]
                for image in images:
                    blob = _image_blob(image)
                    if blob is None:
                        continue
                    mime, data = blob
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime,
                            "data": base64.b64encode(data).decode("ascii"),
                        },
                    })
            else:
                content = text
            ensure("user")["content"].append({
                "type": "tool_result",
                "tool_use_id": item.get("call_id") or "",
                "content": content,
            })
        elif kind in {"reasoning", "thinking", "redacted_thinking"}:
            payload = item
            if item.get("redacted_thinking") or item.get("data"):
                data = item.get("data") or item.get("redacted_thinking")
                ensure("assistant")["content"].append({
                    "type": "redacted_thinking",
                    "data": str(data),
                })
            elif payload.get("signature"):
                ensure("assistant")["content"].append({
                    "type": "thinking",
                    "thinking": str(payload.get("thinking") or ""),
                    "signature": str(payload.get("signature") or ""),
                })
            # 没有 signature 的旧思考块不再回传，Anthropic 会拒
        elif "role" in item and item.get("content") is not None:
            role = item["role"]
            if role not in {"user", "assistant"}:
                continue
            text = str(item.get("content") or "")
            if text:
                ensure(role)["content"].append({"type": "text", "text": text})
            for image in item.get("images") or []:
                blob = _image_blob(image)
                if blob is None:
                    continue
                mime, data = blob
                ensure(role)["content"].append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                })

    return [message for message in messages if message["content"]]


class _AnthropicStream:
    """把 Anthropic Messages 的 SSE 事件翻译成引擎认的 Responses 事件。"""

    def __init__(self, stream):
        self.__stream = stream

    def __iter__(self):
        return self.__events()

    def close(self):
        close = getattr(self.__stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def __value(raw, name):
        if raw is None:
            return 0
        if isinstance(raw, dict):
            return raw.get(name, 0) or 0
        return getattr(raw, name, 0) or 0

    def __usage(self, target, raw, start=False):
        if raw is None:
            return
        cache_write = int(self.__value(raw, "cache_creation_input_tokens") or 0)
        cache_read = int(self.__value(raw, "cache_read_input_tokens") or 0)
        input_tokens = int(self.__value(raw, "input_tokens") or 0)
        output_tokens = int(self.__value(raw, "output_tokens") or 0)
        if start:
            target["input"] = input_tokens + cache_write + cache_read
            target["cached"] = cache_read
            target["output"] = output_tokens
        else:
            target["output"] = output_tokens or target.get("output", 0)
        target["total"] = target["input"] + target["output"]

    def __events(self):
        usage = {"input": 0, "output": 0, "total": 0, "cached": 0, "reasoning": 0}
        output = []
        blocks = {}
        done = False

        for event in self.__stream:
            kind = getattr(event, "type", "")
            if kind == "message_start":
                message = getattr(event, "message", None)
                self.__usage(usage, getattr(message, "usage", None), start=True)
            elif kind == "content_block_start":
                index = getattr(event, "index", 0)
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", "")
                entry = {
                    "type": block_type,
                    "text": "",
                    "thinking": "",
                    "signature": "",
                    "redacted": "",
                    "id": "",
                    "name": "",
                    "json": "",
                }
                if block_type == "tool_use":
                    entry["id"] = getattr(block, "id", "") or ""
                    entry["name"] = getattr(block, "name", "") or ""
                    initial = getattr(block, "input", None)
                    if isinstance(initial, dict) and initial:
                        entry["json"] = json.dumps(initial, ensure_ascii=False)
                elif block_type == "redacted_thinking":
                    entry["redacted"] = getattr(block, "data", "") or ""
                blocks[index] = entry
            elif kind == "content_block_delta":
                index = getattr(event, "index", 0)
                delta = getattr(event, "delta", None)
                delta_type = getattr(delta, "type", "")
                entry = blocks.setdefault(index, {
                    "type": "", "text": "", "thinking": "", "signature": "",
                    "redacted": "", "id": "", "name": "", "json": "",
                })
                if delta_type == "text_delta":
                    text = getattr(delta, "text", "") or ""
                    if text:
                        yield _AnthropicEvent("response.output_text.delta", str(text))
                elif delta_type == "thinking_delta":
                    thought = str(getattr(delta, "thinking", "") or "")
                    entry["thinking"] += thought
                    if thought:
                        yield _AnthropicEvent("response.thinking.delta", thought)
                elif delta_type == "signature_delta":
                    entry["signature"] += str(getattr(delta, "signature", "") or "")
                elif delta_type == "input_json_delta":
                    entry["json"] += str(getattr(delta, "partial_json", "") or "")
            elif kind == "content_block_stop":
                index = getattr(event, "index", 0)
                entry = blocks.pop(index, None)
                if entry is None:
                    continue
                if entry["type"] == "thinking" and (entry["thinking"] or entry["signature"]):
                    output.append(_AnthropicItem(
                        "reasoning",
                        thinking=entry["thinking"],
                        signature=entry["signature"],
                    ))
                elif entry["type"] == "redacted_thinking" and entry["redacted"]:
                    output.append(_AnthropicItem("reasoning", redacted=entry["redacted"]))
                elif entry["type"] == "tool_use":
                    output.append(_AnthropicItem(
                        "function_call",
                        call_id=entry["id"] or f"tool_{index}",
                        name=entry["name"],
                        arguments=entry["json"] or "{}",
                    ))
            elif kind == "message_delta":
                self.__usage(usage, getattr(event, "usage", None))
            elif kind == "message_stop":
                done = True
                yield _AnthropicCompleted(output, usage)
                return

        if not done:
            yield _AnthropicCompleted(output, usage)


class AnthropicAdapter(ResponsesAdapter):
    """Anthropic Messages API（Claude 官方 / Anthropic 兼容中转）。"""

    def create(self, handle, bundle, schemas, thinking_on, effort="medium"):
        max_tokens = Providers.active_value(config, "max_tokens", 8192)
        level = _effort_level(effort or config.get("llm.reasoning", "high"))
        kwargs = {
            "model": config.get("llm.model", ""),
            "messages": _to_anthropic_messages(bundle),
            "max_tokens": max_tokens,
            "stream": True,
        }
        if bundle.instructions:
            kwargs["system"] = bundle.instructions
        tools = _to_anthropic_tools(schemas)
        if tools:
            kwargs["tools"] = tools

        deepseek = _deepseek_like()
        if deepseek:
            # DeepSeek 的 Anthropic 兼容层：开关 + output_config.effort
            kwargs["thinking"] = {
                "type": "enabled" if thinking_on else "disabled"
            }
            if thinking_on:
                kwargs["extra_body"] = {"output_config": {"effort": level}}
        elif thinking_on:
            budget = {"low": 4096, "high": 16384, "max": 32768}[level]
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kwargs["max_tokens"] = max(max_tokens, budget + 1024)

        extra = _opencode_headers(bundle)
        if extra:
            kwargs["extra_headers"] = extra

        try:
            return _AnthropicStream(handle.create(**kwargs))
        except Exception as error:
            status = getattr(error, "status_code", None)
            text_error = str(error).lower()
            retryable = status in (400, 422) or isinstance(error, TypeError)
            if not retryable:
                raise
            if deepseek and thinking_on:
                # 不是 DeepSeek 兼容层：退回 Claude 的 budget_tokens 写法
                kwargs.pop("extra_body", None)
                budget = {"low": 4096, "high": 16384, "max": 32768}[level]
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
                kwargs["max_tokens"] = max(max_tokens, budget + 1024)
                log.warning(
                    "Adapter",
                    "anthropic endpoint rejected DeepSeek thinking params; retried with budget_tokens",
                )
                return _AnthropicStream(handle.create(**kwargs))
            if not thinking_on and "thinking" in kwargs:
                kwargs.pop("thinking", None)
                log.warning(
                    "Adapter",
                    "anthropic endpoint rejected thinking=disabled; retried without it "
                    "(provider may default to thinking=high)",
                )
                return _AnthropicStream(handle.create(**kwargs))
            raise

    @staticmethod
    def usage(event):
        raw = getattr(getattr(event, "response", None), "usage", None)
        return raw if isinstance(raw, dict) else None

    @staticmethod
    def dump_reasoning(item):
        redacted = getattr(item, "redacted", "")
        if redacted:
            return {"type": "redacted_thinking", "data": str(redacted)}
        return {
            "type": "thinking",
            "thinking": str(getattr(item, "thinking", "") or ""),
            "signature": str(getattr(item, "signature", "") or ""),
        }


_RESPONSES = ResponsesAdapter()
_CHAT = ChatAdapter()
_ANTHROPIC = AnthropicAdapter()


def get_adapter(provider):
    kind = str(provider or "").lower()
    if kind == "anthropic":
        return _ANTHROPIC
    return _CHAT if kind == "openai-chat" else _RESPONSES


class _AdapterProxy:
    """配置里切 provider kind 时，调用方不用重新 import 方言。

    流消费方应在开始时 `adapter.current()` 快照一次：中途切换 provider
    不能让已经拿到的流换一个解析器。
    """

    def current(self):
        return get_adapter(Providers.current_kind(config))

    def __getattr__(self, name):
        return getattr(self.current(), name)


adapter = _AdapterProxy()
