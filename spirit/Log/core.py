"""
日志体系（中立工具）：把各体系的事件写进一个日志文件。

默认位置：源码运行 = spirit/Logs/spirit.log；安装后 = 用户数据目录/Logs
日志写入失败不抛出——日志不能把主程序带崩。
"""
import logging
import threading
from logging.handlers import RotatingFileHandler

from Config import config
from Paths import log_dir
from Redact import redact


class Log:
    def __init__(self):
        self.__logger = None
        self.__lock = threading.Lock()

    def rebind(self):
        """数据根变了：关掉旧日志文件，下次写入按新目录重建。"""
        with self.__lock:
            logger = self.__logger
            if logger and logger is not False:
                for handler in list(logger.handlers):
                    try:
                        handler.close()
                    except Exception:
                        pass
                    logger.removeHandler(handler)
            self.__logger = None

    def __ensure(self):
        if self.__logger is not None:
            return self.__logger
        with self.__lock:
            if self.__logger is not None:
                return self.__logger
            try:
                directory = log_dir()
                directory.mkdir(parents=True, exist_ok=True)
                logger = logging.getLogger("spirit")
                logger.setLevel(logging.INFO)
                if not logger.handlers:
                    try:
                        max_bytes = int(config.get("engine.log_max_bytes", 5 * 1024 * 1024) or 5 * 1024 * 1024)
                    except (TypeError, ValueError):
                        max_bytes = 5 * 1024 * 1024
                    try:
                        backups = int(config.get("engine.log_backups", 3) or 3)
                    except (TypeError, ValueError):
                        backups = 3
                    handler = RotatingFileHandler(
                        directory / "spirit.log",
                        maxBytes=max(64 * 1024, max_bytes),
                        backupCount=max(1, backups),
                        encoding="utf-8",
                    )
                    handler.setFormatter(logging.Formatter(
                        "%(asctime)s | %(levelname)s | %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S",
                    ))
                    logger.addHandler(handler)
                self.__logger = logger
            except Exception:
                self.__logger = False  # 日志不可用，直接禁用
        return self.__logger

    def info(self, system, message):
        self.__write("INFO", system, message)

    def warning(self, system, message):
        self.__write("WARNING", system, message)

    def error(self, system, message):
        self.__write("ERROR", system, message)

    def __write(self, level, system, message):
        logger = self.__ensure()
        if not logger:
            return
        try:
            safe = redact(str(message), extra=[config.get("llm.api_key", "")])
            logger.log(getattr(logging, level), f"[{system}] {safe}")
        except Exception:
            pass


log = Log()
