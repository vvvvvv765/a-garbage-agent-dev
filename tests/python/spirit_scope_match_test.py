"""渗透范围写法：精确主机 / 通配符子域 / CIDR 网段。"""
import sys

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Scenarios import scope  # noqa: E402

# ---------- 1. 主机提取 ----------
assert scope.host_of("https://XY-API.sccc.edu.cn:443/x?y=1") == "xy-api.sccc.edu.cn"
assert scope.host_of("10.0.0.5:8080") == "10.0.0.5"
assert scope.host_of("[2001:db8::1]:443") == "2001:db8::1"
assert scope.host_of("") == ""
print("host_of ok")

# ---------- 2. 通配符子域 ----------
assert scope.matches("*.sccc.edu.cn", "a.sccc.edu.cn")
assert scope.matches("*.sccc.edu.cn", "a.b.sccc.edu.cn")
assert scope.matches("*.sccc.edu.cn", "https://A.SCCC.EDU.CN:443/x")
assert not scope.matches("*.sccc.edu.cn", "sccc.edu.cn"), "通配符不含裸域"
assert not scope.matches("*.sccc.edu.cn", "xsccc.edu.cn")
assert not scope.matches("*.sccc.edu.cn", "a.sccc.edu.cn.evil.com")
print("wildcard ok")

# ---------- 3. 精确主机 ----------
assert scope.matches("xy-api.sccc.edu.cn", "https://XY-API.sccc.edu.cn/")
assert not scope.matches("xy-api.sccc.edu.cn", "api.sccc.edu.cn")
print("exact ok")

# ---------- 4. CIDR ----------
assert scope.matches("192.168.170.0/24", "192.168.170.160")
assert not scope.matches("192.168.170.0/24", "192.168.171.1")
assert scope.matches("2001:db8::/32", "2001:db8::1")
assert scope.matches_any(["a.example", "*.b.example"], "x.b.example")
assert not scope.matches_any([], "x.b.example")
print("cidr ok")

# ---------- 5. 校验 / 归一化 ----------
assert scope.validate("https://xy-api.sccc.edu.cn:8443/path") == "xy-api.sccc.edu.cn"
assert scope.validate(" *.sccc.edu.cn ") == "*.sccc.edu.cn"
for bad in ("192.168.0.0/33", "a b.com", "https://"):
    try:
        scope.validate(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"应该拒绝：{bad}")
print("validate ok")

print("ALL SCOPE MATCH TESTS PASSED")
