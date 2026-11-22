"""Provider 探测：DeepSeek /anthropic 基址也能拉到模型；401 能区分有没有带 Key。"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Config import Providers  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        key = auth.replace("Bearer ", "")
        if self.path == "/models":
            if key == "good":
                body = {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]}
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(401)
            self.end_headers()
            return
        if self.path in ("/anthropic", "/anthropic/models", "/anthropic/v1/models"):
            self.send_response(200 if key == "good" else 401)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"

# 1. /anthropic 基址没有 /anthropic/models，回退到根地址的 /models
models = Providers.probe_models(f"{base}/anthropic", "good", "anthropic", "token")
assert models == ["deepseek-flash", "deepseek-v4-pro"], models
print("1. anthropic base model fallback ok:", models)

# 2. 其他兼容子路径（/api/anthropic）同样剥离后回退
models = Providers.probe_models(f"{base}/api/anthropic", "good", "anthropic", "token")
assert models == ["deepseek-flash", "deepseek-v4-pro"], models
print("2. api/anthropic fallback ok")

# 3. 连通性测试只测可达：不带 Key 的 401 也算可达（cc-switch 语义）
result = Providers.check(f"{base}/anthropic")
assert result["reachable"] and result["status"] == 401, result
assert result["level"] == "operational", result
print("3. reachability 401 ok")

# 4. 真网络错误才算不可达
result = Providers.check("http://127.0.0.1:1", timeout=1.0)
assert not result["reachable"], result
print("4. network error -> unreachable ok")

# 5. 模型返回里的 models[].slug 也能解析
assert Providers._extract_models({"models": [{"slug": "models/foo"}]}) == ["foo"]
print("5. slug extraction ok")

server.shutdown()
print("\nPROVIDER PROBE TEST OK")
