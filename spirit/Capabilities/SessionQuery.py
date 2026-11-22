"""
sessionSearch：翻历史会话（Session_Storage 里的 session-*.jsonl）。

只读文件，不碰内存；给模型一个跨会话找记忆的入口。
"""
import json
import time

from Paths import session_dir

from .Executions import executions
from .Spec import CapabilitySpec

SEARCHED = {"user": "用户", "assistant": "助手", "tool_output": "工具结果"}


class SessionSearchCapability:
    name = "sessionSearch"
    description = (
        "在历史会话里搜关键词（不区分大小写），返回「时间 / 会话标题 / 命中片段」。"
        "想找以前聊过什么时用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "要搜的关键词"},
            "limit": {"type": "integer", "description": "最多返回多少条，默认 20"},
            "max_sessions": {"type": "integer", "description": "最多翻多少个会话，默认 20"},
        },
        "required": ["keyword"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=30,
            trust="untrusted", side_effect="read",
        )

    def run(self, arguments):
        keyword = str(arguments.get("keyword", "")).strip()
        if not keyword:
            return "关键词为空"
        limit = max(1, min(int(arguments.get("limit", 20)), 100))
        max_sessions = max(1, min(int(arguments.get("max_sessions", 20)), 200))

        try:
            files = sorted(
                session_dir().glob("session-*.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:max_sessions]
        except Exception as error:
            return f"读会话目录失败：{error}"

        if not files:
            return "没有任何会话记录"

        needle = keyword.lower()
        hits = []
        for path in files:
            executions.check()
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
                title = ""
                with open(path, encoding="utf-8") as file:
                    for line in file:
                        item = self.__load(line)
                        if item is None:
                            continue
                        if not title and item.get("address") == "user":
                            title = str(item.get("payload") or "").strip().replace("\n", " ")[:30]
                        role, text = self.__text(item)
                        if not text or needle not in text.lower():
                            continue
                        hits.append(
                            f"[{stamp}] {title or path.stem} — {role}：{self.__snippet(text, needle)}"
                        )
                        if len(hits) >= limit:
                            break
            except Exception:
                continue
            if len(hits) >= limit:
                break

        if not hits:
            return f"没有找到「{keyword}」（翻了 {len(files)} 个会话）"
        result = "\n".join(hits)
        if len(hits) >= limit:
            result += f"\n…（达到上限 {limit} 条）"
        return result

    @staticmethod
    def __load(line):
        line = line.strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except Exception:
            return None

    @staticmethod
    def __text(item):
        address = item.get("address")
        if address not in SEARCHED:
            return "", ""
        payload = item.get("payload")
        if isinstance(payload, dict):
            text = str(payload.get("output") or "")
        else:
            text = str(payload or "")
        return SEARCHED[address], text

    @staticmethod
    def __snippet(text, needle):
        index = text.lower().find(needle)
        if index < 0:
            return text[:120].replace("\n", " ")
        start = max(0, index - 40)
        end = min(len(text), index + len(needle) + 60)
        piece = text[start:end].replace("\n", " ")
        return ("…" if start > 0 else "") + piece + ("…" if end < len(text) else "")
