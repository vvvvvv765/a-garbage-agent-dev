"""真实 agent 工具全量测试：按组并行，逐个用工具并收集结果。

用法：
  SPIRIT_SUITE=1 python spirit_toolsuite_test.py pentest 1
  SPIRIT_SUITE=1 python spirit_toolsuite_test.py daily 2
组内任务一次发完；不同组用不同端口/独立数据目录，可以同时起。
结果写到 tool_suite_<mode>_g<group>.json。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

RELEASE = Path(r"D:\wangj\dai ma\Spirit\desktop\release\Spirit")
EXE = RELEASE / "resources" / "engine" / "spirit-engine.exe"
MODE = (sys.argv[1] if len(sys.argv) > 1 else "pentest").lower()
GROUP = int(sys.argv[2]) if len(sys.argv) > 2 else 1
PORT = 5095 + GROUP
BASE = f"http://127.0.0.1:{PORT}"

PENTEST_GROUPS = {
    1: """授权测试，目标 aywh168.com。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. fofaSearch：query = domain="aywh168.com"，size 20
2. domainCollect：domain=aywh168.com，brute=false
3. httpProbe：上一步得到的站点（最多 5 个）
4. gauUrls：domain=aywh168.com
5. naabuScan：host=aywh168.com，top_ports=100
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
    2: """授权测试，目标 aywh168.com。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. ffufScan：url=https://www.aywh168.com/FUZZ，filter_status=404，timeout=60
2. nucleiScan：target=https://www.aywh168.com，severity=critical,high，timeout=120
3. httpRequest：GET https://www.aywh168.com/
4. webSearch：搜 "aywh168.com"
5. browser：打开 https://www.aywh168.com/ 并截图到工作目录 shot.png
6. viewImage：看 shot.png
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
    3: """授权测试。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. bash：pwd
2. listDir：列当前目录
3. writeFile：写 test_note.txt，内容 "hello spirit"
4. readFile：读 test_note.txt
5. replaceInFile：把 hello 换成 hi
6. searchFiles：搜 "hi"
7. parseData：解析项目总表 assets.csv（没有就先用 assetsWrite 写一行）
8. assetsWrite：加一行 {"domain":"test.example.com","note":"工具测试"}
9. archiveCreate：把 test_note.txt 打成 zip
10. archiveList：列出 zip
11. archiveExtract：解压 zip
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
    4: """授权测试。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. todoWrite：建 3 条计划
2. sandboxRun：跑 `echo sandbox_ok`
3. processStart：启动 `ping -n 3 127.0.0.1`
4. processOutput：读它的输出
5. processKill：结束它
6. sessionSearch：搜 "spirit"
7. todoRead：读回待办
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
}

DAILY_GROUPS = {
    1: """日常工具测试。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. fetchUrl：抓 https://www.baidu.com/（只取前 20 行）
2. httpRequest：GET https://www.baidu.com/
3. webSearch：搜 "百度"
4. dnsLookup：查 baidu.com
5. httpProbe：探活 https://www.baidu.com/
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
    2: """日常工具测试。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. bash：pwd
2. listDir：列当前目录
3. writeFile：写 daily_note.txt，内容 "daily test"
4. readFile：读它
5. replaceInFile：把 daily 换成 everyday
6. searchFiles：搜 "everyday"
7. findFiles：找 *.txt
8. parseData：解析 assets.csv（没有就造一个）
9. assetsWrite：加一行 {"domain":"daily.example.com"}
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
    3: """日常工具测试。请**连续**调用下面工具，每调用完不要写总结，最后统一汇总。
1. archiveCreate：把 daily_note.txt 打包
2. archiveList：列出它
3. archiveExtract：解压它
4. sandboxRun：跑 `echo daily_sandbox`
5. processStart：启动 `ping -n 3 127.0.0.1`
6. processOutput：读输出
7. processKill：结束它
8. processList：列出 python 进程
9. todoWrite：建 2 条计划；todoRead 读回
10. sessionSearch：搜 "daily"
最后汇总：每个工具一行「工具名 — 结果一句话」。""",
}

TASK = (PENTEST_GROUPS if MODE == "pentest" else DAILY_GROUPS).get(GROUP)
if not TASK:
    raise SystemExit(f"没有第 {GROUP} 组任务")


def _request(path, data=None, token="", method=None):
    url = BASE + path
    body = None
    headers = {}
    if token:
        headers["X-Spirit-Token"] = token
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
        method = method or "POST"
    req = urllib.request.Request(url, data=body, headers=headers, method=method or "GET")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _token():
    with urllib.request.urlopen(BASE + "/", timeout=30) as response:
        html = response.read().decode("utf-8", "replace")
    match = re.search(r'name="spirit-api-token" content="([^"]+)"', html)
    return match.group(1) if match else ""


def main():
    home = Path(tempfile.mkdtemp(prefix=f"spirit-suite-{MODE}{GROUP}-home-"))
    work = Path(tempfile.mkdtemp(prefix=f"spirit-suite-{MODE}{GROUP}-work-"))
    shutil.copy2(RELEASE / "data" / "config.json", home / "config.json")
    # 测试没有界面：审批必须全自动，否则工具调用会一直等“允许”
    cfg_path = home / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("engine", {})["approval"] = "auto"
    cfg["engine"]["thinking"] = False
    cfg.setdefault("llm", {})["reasoning"] = "low"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    env = dict(os.environ)
    env["SPIRIT_HOME"] = str(home)
    env["SPIRIT_WORKDIR"] = str(work)
    env["SPIRIT_SESSION_DIR"] = str(home)
    env["SPIRIT_APPROVAL"] = "auto"
    env["SPIRIT_WEB_PORT"] = str(PORT)
    proc = subprocess.Popen(
        [str(Path(os.environ.get("SPIRIT_PY") or os.sys.executable)), "-m", "WebUI.server"],
        env=env, cwd=str(Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(90):
            try:
                _request("/api/status")
                break
            except Exception:
                time.sleep(1)
        else:
            raise SystemExit("引擎没有起来")
        token = _token()
        _request("/api/approval-mode", {"mode": "auto"}, token)
        _request("/api/settings", {"thinking": False}, token)
        _request("/api/scenario", {"id": MODE}, token)
        time.sleep(1)
        _request("/api/send", {"text": TASK}, token)
        deadline = time.time() + 900
        while time.time() < deadline:
            time.sleep(4)
            kernel = _request("/api/kernel", token=token)
            cpu = kernel.get("cpu") or {}
            if not cpu.get("turn_active") and not kernel.get("queued"):
                break
        else:
            print("超时未完成（15 分钟）")
        events = (_request("/api/history?limit=300", token=token).get("events") or [])
        out = Path(__file__).resolve().parent / f"tool_suite_{MODE}_g{GROUP}.json"
        out.write_text(json.dumps({"mode": MODE, "group": GROUP, "events": events},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"group {GROUP}: events={len(events)} saved={out.name}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"engine stopped (group {GROUP})")


if __name__ == "__main__":
    if os.environ.get("SPIRIT_SUITE") != "1":
        print("真实工具测试：设置 SPIRIT_SUITE=1 才运行（不会自动跑）")
        raise SystemExit(0)
    main()
