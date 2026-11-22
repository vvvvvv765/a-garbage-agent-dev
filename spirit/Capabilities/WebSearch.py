"""
webSearch 能力：联网搜索，返回「标题 / 链接 / 摘要」。

具体走哪家由搜索提供方接缝决定（SearchProvider.py）：
  llm.search_provider = deepseek（默认，原生搜索，一次搜索 = 一次模型轮次）
                      | tavily（纯检索端点，需 TAVILY_API_KEY）
"""
from .SearchProvider import SearchError, get_provider
from .Spec import CapabilitySpec


class WebSearchCapability:
    name = "webSearch"
    description = (
        "联网搜索，返回「标题 / 链接 / 摘要」。"
        "要细看某个结果，再对它的链接用 fetchUrl。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索词"},
            "max_results": {"type": "integer", "description": "最多返回多少条，默认 8"},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=60,
            trust="untrusted", side_effect="external",
        )

    def run(self, arguments):
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "搜索词为空"

        limit = max(1, min(int(arguments.get("max_results", 8)), 20))
        try:
            results = get_provider().search(query, limit)
        except SearchError as error:
            return f"搜索失败：{error}"
        except Exception as error:
            return f"搜索失败：{error}"

        if not results:
            return "没有搜索结果"

        lines = []
        for index, item in enumerate(results, 1):
            line = f"{index}. {item['title']} — {item['url']}"
            if item.get("snippet"):
                line += f"\n   {item['snippet']}"
            lines.append(line)
        return "\n".join(lines)
