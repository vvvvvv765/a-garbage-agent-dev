"""场景包读取：不 import 任何体系，保持中立。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_SCENARIO = "daily"

_PROMPTS = {}   # id -> {"mtime": ..., "text": ...}


def _scenario_dirs():
    return sorted(
        path for path in ROOT.iterdir()
        if path.is_dir() and (path / "scenario.json").exists()
    )


def list_scenarios():
    """所有可用场景（按文件夹排序）。"""
    items = []
    for folder in _scenario_dirs():
        try:
            data = json.loads((folder / "scenario.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        data.setdefault("id", folder.name)
        data.setdefault("name", data["id"])
        data.setdefault("description", "")
        items.append(data)
    return items


def get_scenario(name):
    name = str(name or "").strip() or DEFAULT_SCENARIO
    for item in list_scenarios():
        if item["id"] == name:
            return item
    return None


def public_scenarios():
    return [
        {
            "id": item["id"],
            "name": item.get("name", item["id"]),
            "description": item.get("description", ""),
        }
        for item in list_scenarios()
    ]


def common_capabilities():
    """所有场景共享的能力（common.json）；不存在就当空。"""
    try:
        data = json.loads((ROOT / "common.json").read_text(encoding="utf-8"))
        return list(data.get("capabilities") or [])
    except Exception:
        return []


def capabilities_for(name):
    """common ∪ 场景清单（去重、保持顺序）；场景不存在返回 None。"""
    item = get_scenario(name)
    if item is None:
        return None
    ordered = []
    seen = set()
    for cap in common_capabilities() + list(item.get("capabilities") or []):
        cap = str(cap or "").strip()
        if cap and cap not in seen:
            seen.add(cap)
            ordered.append(cap)
    return ordered


def defaults_for(name):
    item = get_scenario(name)
    if item is None:
        return {}
    return dict(item.get("defaults") or {})


def prompt_for(name):
    """场景提示词（增量）；按 mtime 缓存。"""
    item = get_scenario(name)
    if item is None:
        return ""
    folder = ROOT / item["id"]
    path = folder / str(item.get("prompt") or "prompt.md")
    try:
        mtime = path.stat().st_mtime
        cached = _PROMPTS.get(item["id"])
        if cached and cached["mtime"] == mtime:
            return cached["text"]
        text = path.read_text(encoding="utf-8").strip()
        _PROMPTS[item["id"]] = {"mtime": mtime, "text": text}
        return text
    except Exception:
        return ""
