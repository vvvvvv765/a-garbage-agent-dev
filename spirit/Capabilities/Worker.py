"""
能力 worker 进程（K2）：在内核之外跑具体能力。

为什么是独立进程：
  - 超时 / 取消 / OOM / ReDoS 只杀死这个进程，不带走内核
  - 持久 shell 状态留在 worker 里；worker 重启后状态丢失（结果里说明）

协议：stdin 一行一个 JSON 请求，stdout 一行一个 JSON 响应；插件自己的 print 走 stderr。
"""
import hashlib
import json
import os
import sys


def main():
    # 父进程已经通过环境变量给了数据根 / 工作区；这里再显式对齐一次
    from Config import config
    from Paths import config_file, set_home

    set_home(os.environ.get("SPIRIT_HOME") or None)
    config.load()
    workdir = os.environ.get("SPIRIT_WORKDIR")
    if workdir:
        config.set("engine.workdir", workdir)

    from Capabilities import capabilities

    state = {"stamp": None}

    def sync_config():
        try:
            stamp = hashlib.sha256(config_file().read_bytes()).hexdigest()
        except OSError:
            stamp = ""
        if stamp == state["stamp"]:
            return
        state["stamp"] = stamp
        config.load()
        if workdir:
            config.set("engine.workdir", workdir)
        capabilities.rebind()

    sync_config()

    protocol = sys.stdout
    sys.stdout = sys.stderr        # 插件 print 不能污染协议
    protocol.write(json.dumps({"__ready__": True}) + "\n")
    protocol.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        name = request.get("name", "")
        arguments = request.get("arguments") or {}
        try:
            # 配置可能被内核改过：只有文件变了才重读 / rebind
            sync_config()

            entry = capabilities.registry.get(name)
            if entry is None:
                response = {"id": request_id, "ok": False,
                            "content": f"未知能力：{name}"}
            elif not entry.enabled:
                response = {"id": request_id, "ok": False,
                            "content": f"能力已停用：{name}"}
            else:
                content = entry.capability.run(arguments)
                if not isinstance(content, str):
                    content = str(content)
                response = {"id": request_id, "ok": True, "content": content}
        except Exception as error:   # noqa: BLE001 — 所有失败都回给内核
            response = {
                "id": request_id,
                "ok": False,
                "content": f"{type(error).__name__}: {error}",
            }
        protocol.write(json.dumps(response, ensure_ascii=False) + "\n")
        protocol.flush()


if __name__ == "__main__":
    main()
