"""
主板：引擎的启动入口

启动逻辑统一在 Engine 里，主板只负责“开机”。

运行方式（在 spirit 目录下）：
  python -m MoBo.main          # 控制台对话
  python -m MoBo.main web      # Web UI（浏览器 http://127.0.0.1:5000）
"""
import logging
import os
import signal
import sys
import time
import traceback

from Config import config
from Engine import Engine
from MoBo.lock import acquire_for_current_home
from UserInput.Console import console


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    # 能力 worker 进程：不拿单实例锁、不开机，只跑插件
    if argv and argv[0] == "--capability-worker":
        from Capabilities.Worker import main as worker_main
        worker_main()
        return

    mode = argv[0].lower() if argv else "cli"

    # 一个数据根只允许一个进程：两个进程同时写 config / 会话会互相覆盖
    try:
        acquire_for_current_home()
    except RuntimeError as error:
        print(f"[Spirit] {error}", file=sys.stderr)
        raise SystemExit(2)

    if mode == "web":
        from WebUI.server import main as web_main
        web_main()
        return

    _cli()


def _cli():
    """控制台模式：stdin 只有一个属主（console），引擎只拿队列里的行。"""
    engine = Engine()
    console.start()
    engine.set_input_source(lambda: console.read("用户输入："))
    engine.set_approver(_console_approver, console.cancel_pending)

    last = {"at": 0.0}
    signal.signal(signal.SIGINT, _sigint_handler(engine, last))
    code = 0
    try:
        if engine.start():
            engine.run()
    except KeyboardInterrupt:
        code = 130
    except SystemExit as error:
        code = int(error.code or 0)
    except BaseException:
        traceback.print_exc()
        code = 1
    finally:
        console.close()
    _exit_cleanly(code)


def _sigint_handler(engine, last):
    """Ctrl+C：按当前状态分派；两秒内第二次退出。

    - 审批挂起 → 拒绝该审批 + 中断本轮
    - 空闲等输入 → 作废当前输入行
    - 其余（流式 / 工具中）→ 中断本轮
    """

    def _sigint(_signum, _frame):
        now = time.monotonic()
        if now - last["at"] < 2.0:
            print("\n[Ctrl+C] 退出", flush=True)
            console.close()
            engine.stop()
            return
        last["at"] = now
        if console.asking:
            print("\n[Ctrl+C] 取消审批并中断本轮（再按一次退出）", flush=True)
            engine.interrupt()
        elif console.reading:
            console.discard_next()
            print("\n[Ctrl+C] 已作废当前输入（再按一次退出）", flush=True)
        else:
            print("\n[Ctrl+C] 已请求中断（再按一次退出）", flush=True)
            engine.interrupt()

    return _sigint


def _exit_cleanly(code=0):
    """引擎已经收尾后直接退出。

    console 的读线程是 daemon，关机时可能还阻塞在 input() 上；正常解释器
    收尾会和它抢 stdout 的缓冲锁（Python 会报 _enter_buffered_busy）。
    先把日志/输出刷掉，再 os._exit，是控制台程序的常规收尾方式。
    """
    try:
        logging.shutdown()
    except Exception:
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def _console_approver(request):
    """控制台的审批出口：显示统一走 console（它是 stdin 的唯一属主）。"""
    timeout = float(config.get("engine.approval_timeout", 300) or 300)
    return console.ask(request, timeout=timeout)


if __name__ == "__main__":
    main()
