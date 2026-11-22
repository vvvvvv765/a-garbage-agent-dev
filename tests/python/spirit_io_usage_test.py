"""批 D：写文件不翻译换行、大文件分块读、缓存价 / 币种聚合。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities.Files import MAX_READ_BYTES, read_text, write_text  # noqa: E402
from Usage import _aggregate, cost, record  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="spirit-io-"))

# ---------- 1. 写文件不把 LF 翻成 CRLF ----------
script = work / "run.sh"
write_text(script, "#!/bin/sh\necho hi\n")
raw = script.read_bytes()
assert b"\r\n" not in raw, raw
assert raw == b"#!/bin/sh\necho hi\n", raw
print("1. 写文件换行 ok")

# ---------- 2. 大文件分块读：截断标记、不整读 ----------
big = work / "big.log"
with open(big, "w", encoding="utf-8", newline="") as file:
    line = "x" * 99 + "\n"
    for _ in range((MAX_READ_BYTES // 100) + 2000):
        file.write(line)
lines, total, truncated = read_text(big, 0, 5)
assert truncated is True, truncated
assert len(lines) == 5 and total > 5, (len(lines), total)
assert big.stat().st_size > MAX_READ_BYTES
print("2. 大文件分块读 ok")

# ---------- 3. 缓存价按 cached_input 计 ----------
usage = {"input": 1000, "output": 100, "cached": 400}
amount, priced, currency = cost(usage, {"input": 1, "output": 2, "cached_input": 0.5, "currency": "CNY"})
assert priced and currency == "CNY"
assert abs(amount - (600 * 1 + 400 * 0.5 + 100 * 2) / 1_000_000) < 1e-9, amount
# 没给 cached_input 时按输入价（与以前一致）
amount2, _, _ = cost(usage, {"input": 1, "output": 2, "currency": "CNY"})
assert abs(amount2 - (1000 * 1 + 100 * 2) / 1_000_000) < 1e-9, amount2
print("3. 缓存价 ok")

# ---------- 4. 聚合按币种分桶 ----------
cny = record({"input": 1000, "output": 0}, "chat", pricing={"input": 1, "output": 0, "currency": "CNY"})
usd = record({"input": 1000, "output": 0}, "chat", pricing={"input": 2, "output": 0, "currency": "USD"})
totals = _aggregate([cny, usd])
assert totals["mixed"] is True, totals
assert set(totals["costs"]) == {"CNY", "USD"}, totals
assert abs(totals["costs"]["CNY"] - 0.001) < 1e-9
assert abs(totals["costs"]["USD"] - 0.002) < 1e-9
assert totals["cost"] == totals["costs"][totals["currency"]]
# 单一币种不会标 mixed
single = _aggregate([cny])
assert not single.get("mixed") and single["currency"] == "CNY"
print("4. 币种聚合 ok")

print("ALL IO / USAGE TESTS PASSED")
