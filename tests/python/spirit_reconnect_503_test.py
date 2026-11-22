"""503 快速失败：重试 3 次后给可读原因，不再拖 5 次 20 秒。"""
import sys

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from DC.Reconnect import Reconnect  # noqa: E402


class Unavailable(Exception):
    status_code = 503


def run(error, max_attempts=5):
    client = Reconnect(max_attempts=max_attempts, base_delay=0, max_delay=0)
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        raise error

    result = client.chat(fetch, lambda stream: [])
    return client, calls["n"], result


client, count, result = run(Unavailable("temporarily unavailable"))
assert count == 3, count
assert not result.ok and "HTTP 503" in result.error and "切换模型" in result.error, result
assert not client.snapshot()["active"], client.snapshot()
print("1. 503 三次快速失败 ok:", result.error)


class OtherError(Exception):
    status_code = 500


client, count, result = run(OtherError("boom"))
assert count == 5, count
assert "重连 5 次仍失败" in result.error, result
print("2. 其它 5xx 仍重试 5 次 ok")

print("\nRECONNECT 503 TEST OK")
