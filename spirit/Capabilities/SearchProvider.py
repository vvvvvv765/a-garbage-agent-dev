"""
搜索提供方接缝：webSearch 能力只认这个接口，换后端只加一个类、改一行配置。

接口：
    search(query, max_results) -> [{"title": str, "url": str, "snippet": str}]
    失败抛 SearchError（带人话原因）

已实现：
    deepseek —— DeepSeek 的 Anthropic 兼容端点 + 原生 web_search_20250305 服务器工具
                （每次搜索 = 一次完整模型轮次；复用 DEEPSEEK_API_KEY）
    tavily   —— 纯检索端点，LLM 友好，返回更快（需要 TAVILY_API_KEY，要走代理）

配置：llm.search_provider = deepseek | tavily
"""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from Config import config


class SearchError(Exception):
    """搜索失败（缺 key / HTTP 错 / 没触发原生搜索）。"""


QUERY_TEMPLATE = "Perform a web search for the query: {query}"


class DeepSeekProvider:
    """DeepSeek 原生搜索（Anthropic 兼容 Messages API）。"""

    name = "deepseek"

    def search(self, query, max_results):
        key = str(config.get("llm.api_key", "") or "").strip()
        key_name = str(config.get("llm.api_key_env", "DEEPSEEK_API_KEY") or "")
        if not key and key_name:
            key = os.environ.get(key_name, "").strip()
        if not key:
            raise SearchError(f"没有搜索密钥：配置 llm.api_key 或环境变量 {key_name} 未设置")

        base = str(config.get("llm.search_base_url", "https://api.deepseek.com/anthropic/v1")).rstrip("/")
        payload = {
            "model": str(config.get("llm.search_model", "deepseek-v4-flash")),
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": QUERY_TEMPLATE.format(query=query)}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        }
        request = Request(
            f"{base}/messages",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "authorization": f"Bearer {key}",
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urlopen(request, timeout=80) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise SearchError(f"HTTP {error.code} {detail}".strip()) from error
        except Exception as error:
            raise SearchError(str(error)) from error

        return self.__parse(data, max_results)

    @staticmethod
    def __parse(data, max_results):
        """只从结构化块取；没触发原生搜索就报错，不从模型文本里抓链接。"""
        sources = []
        citations = {}
        failures = []

        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "web_search_tool_result":
                items = block.get("content")
                if isinstance(items, dict):          # 错误块
                    failures.append(str(items.get("error_code") or items))
                    continue
                for item in items or []:
                    if isinstance(item, dict) and item.get("type") == "web_search_result":
                        url = item.get("url")
                        if url:
                            sources.append({
                                "url": url,
                                "title": item.get("title") or url,
                            })
            elif kind == "text":
                for cite in block.get("citations") or []:
                    url = (cite or {}).get("url")
                    text = (cite or {}).get("cited_text")
                    if url and text:
                        citations.setdefault(url, []).append(text)

        if not sources:
            if failures:
                raise SearchError(f"没有结果：{', '.join(failures)}")
            raise SearchError("DeepSeek 这次没有触发原生搜索")

        results = []
        seen = set()
        for source in sources:
            if source["url"] in seen:
                continue
            seen.add(source["url"])
            snippet = " ".join(citations.get(source["url"], []))[:300].strip()
            results.append({
                "title": source["title"],
                "url": source["url"],
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break
        return results


class TavilyProvider:
    """Tavily 纯检索端点（需要 TAVILY_API_KEY；国内一般要走代理）。"""

    name = "tavily"

    def search(self, query, max_results):
        key = str(config.get("llm.tavily_api_key", "") or "").strip()
        key_name = str(config.get("llm.tavily_api_key_env", "TAVILY_API_KEY") or "")
        if not key and key_name:
            key = os.environ.get(key_name, "").strip()
        if not key:
            raise SearchError(f"没有 Tavily 密钥：配置 llm.tavily_api_key 或环境变量 {key_name} 未设置")

        payload = {
            "api_key": key,
            "query": query,
            "max_results": max(1, min(max_results, 20)),
            "search_depth": "basic",
        }
        request = Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"content-type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise SearchError(f"HTTP {error.code} {detail}".strip()) from error
        except Exception as error:
            raise SearchError(str(error)) from error

        results = []
        for item in data.get("results") or []:
            url = item.get("url")
            if not url:
                continue
            results.append({
                "title": item.get("title") or url,
                "url": url,
                "snippet": (item.get("content") or "")[:300].strip(),
            })
        return results[:max_results]


_PROVIDERS = {
    DeepSeekProvider.name: DeepSeekProvider,
    TavilyProvider.name: TavilyProvider,
}


def get_provider(name=None):
    """按配置取搜索提供方；不认识的配置直接报清楚。"""
    selected = str(name or config.get("llm.search_provider", "deepseek")).lower()
    factory = _PROVIDERS.get(selected)
    if factory is None:
        raise SearchError(
            f"不认识的搜索提供方：{selected}（可选：{', '.join(sorted(_PROVIDERS))}）"
        )
    return factory()
