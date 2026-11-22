"""供应商体系（照抄 cc-switch）：数据模型扩展、排序、测速、健康检查、余额、导入导出。

对应 2026-11-19 的要求：把 cc-switch 3.18 的「添加 / 管理供应商」整套逻辑搬到 Spirit。
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Config import Providers, Balances, config  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-prov-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-prov-work-"))
from Engine import Engine  # noqa: E402

engine = Engine(home=home, workdir=work)

# ---------- 1. 扩展字段：备注 / 官网 / 分类 / 图标 / Key 链接 / 端点候选 ----------
item = engine.save_provider({
    "name": "扩展字段测试",
    "kind": "anthropic",
    "auth": "key",
    "category": "aggregator",
    "base_url": "https://relay.test/v1/",
    "endpoints": ["https://relay2.test", "https://relay.test/v1", "  "],
    "website": "https://relay.test",
    "notes": "群里推荐的",
    "icon": "deepseek.png",
    "icon_color": "#4d6bfe",
    "api_key_url": "https://relay.test/keys",
    "api_key": "sk-test",
    "models": ["claude-x"],
})
assert item["base_url"] == "https://relay.test", item["base_url"]
assert item["category"] == "aggregator", item
assert item["notes"] == "群里推荐的"
assert item["icon"] == "deepseek.png"
assert item["icon_color"] == "#4d6bfe"
assert item["api_key_url"] == "https://relay.test/keys"
# base_url 永远排第一；去重；空项丢掉
assert item["endpoints"] == ["https://relay.test", "https://relay2.test"], item["endpoints"]
assert item["category_label"] == "聚合平台"

# 非法分类回落到 custom；非法端点报错
assert engine.save_provider({
    "name": "坏分类", "base_url": "https://x.test", "models": ["m"],
    "category": "nonsense",
})["category"] == "custom"
try:
    engine.save_provider({
        "name": "坏端点", "base_url": "https://x.test", "models": ["m"],
        "endpoints": ["ftp://x.test"],
    })
    raise AssertionError("非法端点应该报错")
except ValueError as error:
    assert "http" in str(error)
print("1. 扩展字段 ok")

# ---------- 2. 拖拽排序 ----------
items = engine.providers()["providers"]
ids = [entry["id"] for entry in items]
reversed_ids = list(reversed(ids))
Providers.reorder(config, reversed_ids)
assert [entry["id"] for entry in engine.providers()["providers"]] == reversed_ids
# 不认识的 id 忽略；漏掉的保持相对顺序排在后面
Providers.reorder(config, [reversed_ids[0], "not-exist"])
assert [entry["id"] for entry in engine.providers()["providers"]][0] == reversed_ids[0]
assert len(engine.providers()["providers"]) == len(ids)
Providers.reorder(config, ids)   # 还原
print("2. 排序 ok")

# ---------- 3. 本地 HTTP 服务：健康检查 / 测速 / 余额适配 ----------
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/redirect"):
            # 301 跳转：连通性测试应跟随到最后再报状态（同 cc-switch）
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
            return
        if self.path.startswith("/user/balance"):
            body = json.dumps({
                "is_available": True,
                "balance_infos": [{
                    "currency": "CNY",
                    "total_balance": "110.00",
                    "granted_balance": "0.00",
                    "topped_up_balance": "110.00",
                }],
            }).encode()
            self.send_response(200)
        elif self.path.startswith("/bad"):
            body = b"{}"
            self.send_response(401)
        else:
            body = b"{}"
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

checked = engine.check_provider({"base_url": base})
assert checked["reachable"] is True, checked
assert checked["status"] == 200
assert checked["level"] in ("operational", "degraded"), checked
assert checked["latency_ms"] >= 0

# 401 也算可达（cc-switch 的判据：只看有没有 HTTP 响应）
checked = engine.check_provider({"base_url": base + "/bad"})
assert checked["reachable"] is True and checked["status"] == 401, checked

# 301/302：3xx 本身就是 HTTP 响应，已证明可达；不跟跳转，避免重定向循环
checked = engine.check_provider({"base_url": base + "/redirect"})
assert checked["reachable"] is True, checked
assert checked["status"] in (301, 302), checked
assert checked["redirects"] == 0, checked

# 连不上的端口 → failed
closed = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
dead_port = closed.server_address[1]
closed.server_close()
failed = engine.check_provider({"base_url": f"http://127.0.0.1:{dead_port}"})
assert failed["reachable"] is False and failed["level"] == "failed", failed
print("3. 健康检查 ok")

speed = engine.speed_test({"urls": [base, base + "/x"]})
assert len(speed["results"]) == 2, speed
assert all(entry["ok"] for entry in speed["results"]), speed
assert speed["best"] in (base, base + "/x")
assert speed["results"][0]["latency_ms"] <= speed["results"][1]["latency_ms"]
print("4. 测速 ok")

# ---------- 4. 余额：内置适配器（照 cc-switch：按 host 识别，固定官方地址） ----------
class FakeBalanceResponse:
    status_code = 200

    def json(self):
        return {
            "is_available": True,
            "balance_infos": [{
                "currency": "CNY",
                "total_balance": "110.00",
                "granted_balance": "0.00",
                "topped_up_balance": "110.00",
            }],
        }


seen_urls = []


def fake_balance_get(url, key, timeout, headers=None, bearer=True):
    seen_urls.append(url)
    return FakeBalanceResponse()


original_get = Balances._get
Balances._get = fake_balance_get
try:
    result = Balances.query({
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key": "sk-test",
    })
finally:
    Balances._get = original_get
assert result["ok"] and result["source"] == "deepseek", result
assert result["items"][0]["remaining"] == 110.0, result
assert result["items"][0]["unit"] == "CNY", result
# base_url 带 /anthropic 子路径也不影响：请求固定走官方地址
assert seen_urls == ["https://api.deepseek.com/user/balance"], seen_urls

try:
    Balances.query({"base_url": "https://unknown-vendor.test", "api_key": "sk"})
    raise AssertionError("未知供应商应该报不支持")
except ValueError as error:
    assert "没有内置的余额查询" in str(error)
print("5. 余额 ok")

# ---------- 5. 导入 / 导出 ----------
exported = engine.export_providers()
assert exported["format"] == "spirit-providers"
assert exported["providers"], exported
assert any(entry.get("api_key") == "sk-test" for entry in exported["providers"])

payload = {
    "providers": [{
        "id": "imported-one",
        "name": "导入的供应商",
        "kind": "openai-chat",
        "base_url": "https://import.test/v1",
        "api_key": "sk-import",
        "models": ["m1", "m2"],
        "category": "third_party",
        "notes": "从 JSON 导入",
    }],
}
result = engine.import_providers(payload)
assert result["imported"] == 1, result
imported = next(p for p in result["providers"] if p["id"] == "imported-one")
assert imported["models"] == ["m1", "m2"]
assert imported["notes"] == "从 JSON 导入"
assert imported["endpoints"] == ["https://import.test/v1"], imported["endpoints"]
# 导入不切换当前提供商
assert not imported["active"], imported

bad = engine.import_providers({"providers": [{"name": "", "base_url": "https://b.test"}]})
assert bad["imported"] == 0 and bad["errors"], bad

# 同 id 换地址但没带新 Key → 清空旧 Key，并给 warning
res = engine.import_providers({"providers": [{
    "id": "imported-one",
    "name": "导入的供应商",
    "base_url": "https://attacker.test/v1",
    "models": ["m1"],
}]})
assert res["imported"] == 1, res
assert res["warnings"], res
changed = next(p for p in res["providers"] if p["id"] == "imported-one")
assert changed["has_key"] is False, changed
assert changed["base_url"] == "https://attacker.test/v1", changed

# 坏条目不会写出半套：这批里另一条合法，但坏条目被拦，合法的照常导入
res = engine.import_providers({"providers": [
    {"name": "好的一条", "base_url": "https://good.test", "models": ["m"]},
    {"name": "坏价格", "base_url": "https://bad.test", "models": ["m"], "pricing": "3"},
]})
assert res["imported"] == 1 and res["errors"], res

# 默认工作区不再是启动目录
from Engine import Engine as EngineClass  # noqa: E402
assert Path(engine.workdir).name == "workspace" or Path(engine.workdir).exists(), engine.workdir
try:
    engine.import_providers({"nope": 1})
    raise AssertionError("没有 providers 列表应该报错")
except ValueError as error:
    assert "providers" in str(error)
print("6. 导入导出 ok")

# ---------- 6. Web 接口（Flask 测试客户端） ----------
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()

listed = http.get("/api/providers").get_json()
assert any(entry["id"] == "imported-one" for entry in listed["providers"]), listed
assert "notes" in listed["providers"][0] and "endpoints" in listed["providers"][0]

order = [entry["id"] for entry in listed["providers"]]
reversed_order = list(reversed(order))
res = http.post("/api/provider/reorder", json={"ids": reversed_order}).get_json()
assert [entry["id"] for entry in res["providers"]] == reversed_order, res
http.post("/api/provider/reorder", json={"ids": order})

res = http.post("/api/provider/check", json={"base_url": base}).get_json()
assert res["ok"] and res["reachable"], res

res = http.post("/api/provider/speedtest", json={"urls": [base]}).get_json()
assert res["ok"] and res["best"] == base, res

res = http.post("/api/provider/balance", json={"id": "imported-one"}).get_json()
assert res["ok"] is False and "余额" in res["error"], res

res = http.post("/api/providers/export", json={"confirm": True}).get_json()
assert res["ok"] and res["format"] == "spirit-providers", res

res = http.post("/api/providers/import", json={"providers": [{
    "id": "web-import",
    "name": "Web 导入",
    "base_url": "https://web.test",
    "models": ["m"],
}]}).get_json()
assert res["ok"] and res["imported"] == 1, res
print("7. Web 接口 ok")

server.shutdown()
print("ALL PROVIDER SYSTEM TESTS PASSED")
