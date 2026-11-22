"""
渗透授权范围的写法与匹配（配置层工具，不是体系）。

支持的写法（大小写不敏感，可从 URL 里取主机）：
  - 精确主机：xy-api.example.edu.cn
  - 通配符：  *.example.edu.cn   （匹配任意层级的子域，**不含裸域** example.edu.cn）
  - 网段：    192.168.0.0/16     （CIDR；单个 IP 也按精确主机处理）

匹配只回答"这个目标在不在写下的模式里"，不负责判断授权本身。
"""
import fnmatch
import ipaddress
from urllib.parse import urlsplit


def host_of(value):
    """从 URL / host[:port] / 裸 IP 里取出主机名（小写、去尾点）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" in text:
        host = urlsplit(text).hostname or ""
    else:
        host = text.split("/", 1)[0]
        host = host.rsplit("@", 1)[-1]
        if host.startswith("["):            # [IPv6]:port
            end = host.find("]")
            host = host[1:end] if end != -1 else host
        elif host.count(":") == 1:          # host:port
            host = host.split(":", 1)[0]
    return host.strip().rstrip(".").lower()


def _network(pattern):
    try:
        return ipaddress.ip_network(pattern, strict=False)
    except ValueError:
        return None


def validate(pattern):
    """校验并归一化一条范围写法；不合法抛 ValueError。"""
    text = str(pattern or "").strip()
    if not text:
        raise ValueError("空的授权目标")
    if "://" in text:
        host = host_of(text)
        if not host:
            raise ValueError(f"无法从 URL 里取出主机：{text}")
        return host
    if "/" in text:                         # 只接受 CIDR，不接受 URL 路径
        if _network(text) is None:
            raise ValueError(f"不是合法网段：{text}")
        return text
    if any(char.isspace() for char in text):
        raise ValueError(f"目标里不能有空格：{text}")
    return text


def matches(pattern, target):
    """target 是否命中这条范围模式。"""
    text = str(pattern or "").strip()
    host = host_of(target)
    if not text or not host:
        return False

    network = _network(text)
    if network is not None:
        try:
            return ipaddress.ip_address(host) in network
        except ValueError:
            return False

    pattern_host = host_of(text) if "://" in text else text.lower().rstrip(".")
    try:                                    # 纯 IP 模式
        return ipaddress.ip_address(host) == ipaddress.ip_address(pattern_host)
    except ValueError:
        pass

    if "*" in pattern_host or "?" in pattern_host:
        return fnmatch.fnmatchcase(host, pattern_host)
    return host == pattern_host


def matches_any(patterns, target):
    """target 是否命中任意一条模式。"""
    return any(matches(pattern, target) for pattern in patterns or [])
