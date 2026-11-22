"""PyInstaller 入口：桌面版引擎（等价于 python -m MoBo.main web）。"""
import sys

from MoBo.main import main

if __name__ == "__main__":
    # --capability-worker 要原样传进去；其它参数沿用 web
    main(sys.argv[1:] or ["web"])
