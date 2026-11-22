"""
项目资产库：侦察 / 测绘工具收集到的域名、IP、端口、URL 按项目落盘。

项目 = 当前会话（primary 或额外会话 id）。每个项目独立目录：
  <数据根>/Projects/<项目>/
    assets.csv      项目总表（引擎同步 + 模型可整理，一张表装全部来源）
    assets.json     归一化、去重后的资产
    queries.jsonl   每次查询 / 扫描的流水
    raw/            平台 / 工具的原始响应
"""
import csv
import hashlib
import io
import json
import os
import re
import threading
import time
from pathlib import Path

from Paths import home

_LOCK = threading.Lock()
_SAFE = re.compile(r"[^0-9A-Za-z._-]+")
IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def project_key(session_id=""):
    key = str(session_id or "primary").strip() or "primary"
    return _SAFE.sub("_", key)[:80]


def project_dir(session_id=""):
    path = home() / "Projects" / project_key(session_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "raw").mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def asset_key(record):
    """同一资产只留一条：域名 / ip:port / URL。"""
    domain = str(record.get("domain") or "").strip().lower().rstrip(".")
    port = record.get("port")
    if domain:
        return f"domain:{domain}:{port}" if port else "domain:" + domain
    ip = str(record.get("ip") or "").strip()
    if ip:
        return f"ip:{ip}:{port}" if port else f"ip:{ip}"
    url = str(record.get("url") or "").strip()
    if url:
        return "url:" + url.rstrip("/")
    host = str(record.get("host") or record.get("value") or "").strip().lower()
    return "host:" + host if host else ""


def normalize(record, source=""):
    record = dict(record or {})
    for field in ("host", "ip", "domain", "url", "title", "server", "protocol",
                  "os", "org", "country", "province", "city", "banner"):
        if field in record and record[field] is not None:
            record[field] = str(record[field])
    port = record.get("port")
    try:
        record["port"] = int(port) if port not in (None, "", 0) else None
    except (TypeError, ValueError):
        record["port"] = None
    key = asset_key(record)
    if not key:
        return None
    record["kind"] = ("domain" if record.get("domain") else
                      "ip" if record.get("ip") else
                      "url" if record.get("url") else "host")
    record["key"] = key
    record["id"] = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    source = str(source or "").strip()
    if source:
        record["sources"] = [source]
    else:
        record["sources"] = list(record.get("sources") or [])
    now = time.time()
    record.setdefault("first_seen", now)
    record["last_seen"] = now
    return record


def add_assets(session_id, records, source="", query="", raw=None):
    """写入项目资产库；同 key 合并来源，不重复。返回 (新增数, 总数)。"""
    path = project_dir(session_id) / "assets.json"
    with _LOCK:
        existing = _read_json(path, [])
        by_key = {item.get("key"): item for item in existing if isinstance(item, dict)}
        added = 0
        for raw_record in records or []:
            item = normalize(raw_record, source)
            if item is None:
                continue
            old = by_key.get(item["key"])
            if old is None:
                by_key[item["key"]] = item
                added += 1
            else:
                sources = list(dict.fromkeys((old.get("sources") or []) + item["sources"]))
                for field, value in item.items():
                    if value not in (None, "", [], {}) and field not in ("first_seen", "sources"):
                        old[field] = value
                old["sources"] = sources
                old["last_seen"] = item["last_seen"]
        data = sorted(by_key.values(), key=lambda row: row.get("last_seen") or 0, reverse=True)
        _write_json(path, data)
        _sync_project_csv(session_id, data)
        if raw is not None:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            name = f"{_SAFE.sub('_', source or 'query')}-{stamp}.json"
            try:
                (project_dir(session_id) / "raw" / name).write_text(
                    json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8"
                )
            except OSError:
                name = ""
        if query:
            with open(project_dir(session_id) / "queries.jsonl", "a", encoding="utf-8") as file:
                file.write(json.dumps({
                    "at": time.time(), "source": source, "query": query,
                    "count": len(records or []), "added": added,
                    "raw": name if raw is not None else "",
                }, ensure_ascii=False) + "\n")
        return added, len(data)


CSV_FIELDS = [
    ("kind", "类型"), ("domain", "域名"), ("ip", "IP"), ("port", "端口"),
    ("url", "URL"), ("title", "标题"), ("server", "服务"),
    ("protocol", "协议"), ("sources", "来源"), ("id", "ID"),
]
CSV_LABELS = [label for _, label in CSV_FIELDS]
PROJECT_CSV = "assets.csv"
LEGACY_CSVS = ("domain.csv", "ip.csv", "url.csv", "host.csv")
LEGACY_HEADER = "类型,域名,IP,端口,URL,标题,服务,协议,来源"


def project_csv_path(session_id=""):
    return project_dir(session_id) / PROJECT_CSV


def _csv_cell(field, item):
    if field == "sources":
        return ",".join(item.get("sources") or [])
    if field == "domain":
        value = item.get("domain") or item.get("host") or item.get("value")
    else:
        value = item.get(field)
    return "" if value is None else str(value)


def _csv_record(row):
    """总表一行 → asset_key 用的最小记录（只认定位字段）。"""
    record = {}
    for field in ("domain", "ip", "url", "port"):
        value = row.get(dict(CSV_FIELDS).get(field, field))
        record[field] = value if value not in (None, "") else None
    try:
        record["port"] = int(record["port"]) if record["port"] else None
    except (TypeError, ValueError):
        record["port"] = None
    return record


def _row_identity(row, item=None):
    """总表行的去重身份：优先 ID；其次定位字段；都没有的行按内容哈希保留。"""
    if item is not None and item.get("id"):
        return "id:" + str(item["id"])
    rid = str(row.get("ID") or "").strip()
    if rid:
        return "id:" + rid
    key = asset_key(_csv_record(row))
    if key:
        return key
    digest = hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return "raw:" + digest


def _sync_project_csv(session_id, data):
    """把资产库同步进项目总表（assets.csv）。

    双方都能写：引擎从资产库补固定列；模型在表里加的额外列 / 额外行原样保留。
    旧的按类型分表（domain/ip/url/host.csv）是引擎派生物，同步时一并清掉。
    """
    root = project_dir(session_id)
    target = root / PROJECT_CSV
    header, old_rows = [], []
    if target.exists():
        try:
            with open(target, encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                header = [name for name in (reader.fieldnames or []) if name]
                old_rows = [dict(row) for row in reader]
        except OSError:
            header, old_rows = [], []
    fields = {field for field, _ in CSV_FIELDS}
    internal = fields | {"key", "first_seen", "last_seen"}
    extra = [name for name in header if name not in CSV_LABELS]
    for item in data:
        for name, value in item.items():
            if name in internal or value in (None, "", [], {}):
                continue
            if name not in extra:
                extra.append(name)
    merged = {}
    for item in data:
        row = {label: _csv_cell(field, item) for field, label in CSV_FIELDS}
        for name in extra:
            value = item.get(name)
            if value not in (None, "", [], {}):
                row[name] = ",".join(value) if isinstance(value, list) else str(value)
        merged[_row_identity(row, item)] = row
    for old in old_rows:
        key = _row_identity(old)
        if key in merged:
            for name in extra:
                value = old.get(name)
                if value not in (None, ""):
                    merged[key][name] = value
        else:
            merged[key] = {name: old.get(name, "") for name in CSV_LABELS + extra}
    out_header = CSV_LABELS + extra
    try:
        with open(target, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=out_header, extrasaction="ignore")
            writer.writeheader()
            for row in merged.values():
                writer.writerow(row)
    except OSError:
        return
    for name in LEGACY_CSVS:
        path = root / name
        try:
            first = path.read_text(encoding="utf-8-sig").splitlines()[0]
        except (OSError, IndexError):
            continue
        if first == LEGACY_HEADER:
            try:
                path.unlink()
            except OSError:
                pass


def csv_text(session_id, kind=""):
    if not kind:
        path = project_csv_path(session_id)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8-sig")
            except OSError:
                pass
    rows = list_assets(session_id, limit=100000)
    if kind:
        rows = [item for item in rows if item.get("kind") == kind]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_LABELS)
    for item in rows:
        writer.writerow([_csv_cell(field, item) for field, _ in CSV_FIELDS])
    return output.getvalue()


def list_csv(session_id):
    root = project_dir(session_id)
    # 老项目只有 assets.json：第一次列目录时补出总表
    if not (root / PROJECT_CSV).exists():
        with _LOCK:
            if not (root / PROJECT_CSV).exists():
                data = _read_json(root / "assets.json", [])
                if isinstance(data, list) and data:
                    _sync_project_csv(session_id, data)
    rows = []
    for path in sorted(root.glob("*.csv")):
        try:
            stat = path.stat()
            with open(path, encoding="utf-8-sig", newline="") as file:
                count = max(0, sum(1 for _ in file) - 1)
        except OSError:
            continue
        rows.append({
            "name": path.name, "bytes": stat.st_size, "rows": count,
            "updated": stat.st_mtime, "main": path.name == PROJECT_CSV,
        })
    return rows


def read_csv(session_id, name, limit=200):
    name = Path(str(name or "")).name
    if not name.lower().endswith(".csv"):
        raise ValueError("不是 CSV 文件")
    path = project_dir(session_id) / name
    if not path.exists():
        raise FileNotFoundError(name)
    with open(path, encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        rows = list(reader)
    columns = rows[0] if rows else []
    body = rows[1:1 + max(1, min(2000, int(limit)))]
    return {"name": name, "columns": columns, "rows": body, "total": max(0, len(rows) - 1)}


def import_csv(session_id, name, text):
    name = Path(str(name or "upload.csv")).name
    if not name.lower().endswith(".csv"):
        raise ValueError("只接受 .csv 文件")
    raw = str(text or "").encode("utf-8")
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("CSV 太大（上限 5MB）")
    target = project_dir(session_id) / name
    target.write_bytes(raw)
    return target.name

def list_assets(session_id, limit=500, kind="", search=""):
    path = project_dir(session_id) / "assets.json"
    data = _read_json(path, [])
    if kind:
        data = [item for item in data if item.get("kind") == kind]
    needle = str(search or "").strip().lower()
    if needle:
        data = [
            item for item in data
            if any(needle in str(item.get(field) or "").lower()
                   for field in ("host", "ip", "domain", "url", "title", "server"))
        ]
    return data[:limit]


def summary(session_id):
    data = _read_json(project_dir(session_id) / "assets.json", [])
    counts = {"domain": 0, "ip": 0, "url": 0, "host": 0}
    sources = {}
    for item in data:
        kind = item.get("kind") or ("domain" if item.get("domain") else
                                    "ip" if item.get("ip") else
                                    "url" if item.get("url") else "host")
        counts[kind] = counts.get(kind, 0) + 1
        for source in item.get("sources") or []:
            sources[source] = sources.get(source, 0) + 1
    return {"total": len(data), "kinds": counts, "sources": sources}


def queries(session_id, limit=100):
    path = project_dir(session_id) / "queries.jsonl"
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except OSError:
        return []
    return list(reversed(rows[-limit:]))


def projects():
    """项目资产目录列表（只列已经有目录的项目）。"""
    root = home() / "Projects"
    rows = []
    if not root.exists():
        return rows
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        assets = _read_json(folder / "assets.json", [])
        try:
            updated = max(
                [path.stat().st_mtime for path in folder.rglob("*") if path.is_file()] or [0]
            )
        except OSError:
            updated = 0
        rows.append({
            "session": folder.name,
            "title": folder.name,
            "total": len(assets),
            "updated": updated,
        })
    return sorted(rows, key=lambda row: row["updated"], reverse=True)


def clear(session_id):
    root = project_dir(session_id)
    removed = 0
    for path in list(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed
