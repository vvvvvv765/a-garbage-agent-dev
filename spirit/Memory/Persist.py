"""
上下文子体系（内存体系的子体系）：把数据表落盘 / 恢复。

职责：
  1. 落盘：把内存里的新记录追加到 JSONL（只追加、不重写）
  2. 恢复：启动时把最新一份会话读回内存

不负责：
  - 加工 / 清洗（那是 GPU 的事）
  - 读快照 / 统计（那是数据表自己的读接口：self.__mem.snapshot() / self.__mem.stats()）

注意：本模块是内存体系的子体系，但**不在 Memory/__init__.py 里导出**。
因为它 import Faults，而 Faults import Memory —— 从包初始化里导出会成环。
使用方：from Memory.Persist import persist
"""
import json
import os
import threading
import time
from pathlib import Path

from Faults import faults
from Log import log
from Paths import session_dir

from .Memory import mem, Record

# 会话目录按当前数据根解析（Engine 构造时可能换根）
_faults = faults.for_system("Persist")

# 稀疏行偏移索引：每 N 行记一个字节偏移（写在 sidecar 里）。
# “加载更早”时从最近的锚点 seek，按区间读，不再整份解析会话文件。
INDEX_STRIDE = 512


class PersistSystem:
    def __init__(self, memory=None):
        self.__mem = memory if memory is not None else mem
        self.__path = None
        self.__saved_seq = 0
        self.__scenario = ""     # 这份会话属于哪个场景（写在 sidecar 里）
        self.__title = ""        # 会话标题（sidecar 索引，列表页不再整份扫 JSONL）
        self.__summary_end = 0   # 最新摘要覆盖到的 seq：<= 它的冷记录可以退役
        self.__lines = 0         # 当前会话文件行数（= 索引里的总行号）
        self.__anchors = {}      # 行号 -> 字节偏移（每 INDEX_STRIDE 行一个）
        self.last_skipped = 0       # 上次 load 跳过了多少损坏行
        # 读水位 → 追加 → 更新水位 必须在同一临界区：
        # 两个调用方同时进来会拿到同一批新记录，重复写进 JSONL，
        # 重新加载后上下文会出现多份同样内容（静默、坏行数为 0）。
        self.__lock = threading.Lock()

    # ---------- 落盘 ----------
    def save(self, path=None):
        """把新记录追加到硬盘；返回文件路径，失败返回 None。

        调用级锁：建文件、读水位、追加、更新水位是一段原子操作。
        """
        try:
            with self.__lock:
                return self.__save(path)
        except Exception as error:
            _faults.report(error, "save")
            return None

    def __save(self, path=None):
        self.__mem.flush()
        if path is not None:
            self.__path = Path(path)
        if self.__path is None:
            directory = session_dir()
            directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            candidate = directory / f"session-{stamp}.jsonl"
            # 多会话并发可能同一秒各自新建：用独占创建占位，避免两个 Persist
            # 同时 exists() 都返回 False 后追加进同一份文件
            index = 2
            while True:
                try:
                    with open(candidate, "x", encoding="utf-8"):
                        pass
                    break
                except FileExistsError:
                    candidate = directory / f"session-{stamp}-{index}.jsonl"
                    index += 1
            self.__path = candidate

        # 只取水位之后的新记录（O(新增)，不要再复制整张表）
        new_records = self.__mem.records_after(self.__saved_seq)
        if not new_records:
            return str(self.__path)

        # 二进制追加：字节偏移可以直接存进索引（文本模式在 Windows 会做换行转换）
        try:
            offset = self.__path.stat().st_size
        except OSError:
            offset = 0
        with open(self.__path, "ab") as file:
            for record in new_records:
                line_no = self.__lines + 1
                if line_no == 1 or (line_no - 1) % INDEX_STRIDE == 0:
                    self.__anchors[line_no] = offset
                data = (json.dumps(
                    {
                        "seq": record.seq,
                        "address": record.address,
                        "payload": record.payload,
                    },
                    ensure_ascii=False,
                ) + "\n").encode("utf-8")
                file.write(data)
                offset += len(data)
                self.__lines = line_no
        self.__saved_seq = new_records[-1].seq
        if not self.__title:
            self.__title = self.__first_user_title(new_records)
        for record in new_records:
            if record.address == "summary" and isinstance(record.payload, dict):
                try:
                    end = int(record.payload.get("end_seq") or 0)
                except (TypeError, ValueError):
                    end = 0
                self.__summary_end = max(self.__summary_end, end)
        self.__write_meta()
        log.info("Persist", f"saved {len(new_records)} records -> {self.__path}")
        return str(self.__path)

    @staticmethod
    def __first_user_title(records):
        """从记录里取会话标题：第一条有文字的用户消息前 24 字。"""
        for record in records:
            if record.address != "user":
                continue
            payload = record.payload
            text = payload.get("text") if isinstance(payload, dict) else payload
            text = str(text or "").strip()
            if text:
                return text[:24]
        return ""

    # ---------- 恢复 ----------
    def restore_latest(self):
        """启动恢复：把最新一次会话读回内存（只允许内存为空时）。

        懒加载：摘要覆盖过的冷记录不铺回主表（磁盘上还在，回放时按需读）。
        """
        self.__mem.flush()
        if self.__mem.last_seq():
            log.info("Persist", "restore skipped: memory not empty")
            return None
        directory = session_dir()
        directory.mkdir(parents=True, exist_ok=True)
        files = sorted(directory.glob("session-*.jsonl"))
        if not files:
            log.info("Persist", "restore skipped: no session file")
            return None
        return self.load(files[-1])

    def load(self, path):
        """从 JSONL 恢复到内存（启动阶段用）。"""
        try:
            with self.__lock:
                return self.__load(path)
        except Exception as error:
            _faults.report(error, "load")
            return None

    def __load(self, path):
        self.last_skipped = 0
        meta = self.__read_meta(path)
        try:
            summary_end = int(meta.get("summary_end") or 0)
        except (TypeError, ValueError):
            summary_end = 0

        items = []           # (seq, address, payload)，按文件顺序
        last_seq = 0
        lines = 0
        anchors = {}
        offset = 0
        with open(path, "rb") as file:
            for index, raw in enumerate(file, start=1):
                if index == 1 or (index - 1) % INDEX_STRIDE == 0:
                    anchors[index] = offset
                offset += len(raw)
                lines = index
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    raw_seq = item.get("seq")
                    seq = int(raw_seq) if raw_seq is not None else index
                    address = item["address"]
                    payload = item["payload"]
                except Exception as error:
                    # 半行 / 坏行：跳过继续，别让整份会话变成空
                    self.last_skipped += 1
                    log.warning("Persist", f"skip broken line in {path}: {error}")
                    continue
                last_seq = max(last_seq, seq)
                items.append((seq, address, payload))
                if address == "summary" and isinstance(payload, dict):
                    # 老会话 sidecar 没记 summary_end：从摘要记录里补
                    try:
                        summary_end = max(summary_end, int(payload.get("end_seq") or 0))
                    except (TypeError, ValueError):
                        pass

        keep_views = ("usage", "summary", "todo")
        main = []
        views = {address: [] for address in keep_views}
        for seq, address, payload in items:
            record = Record(seq, address, payload)
            if seq > summary_end:
                main.append(record)
            if address in views:
                views[address].append(record)
        self.__mem.restore(main, floor=summary_end, views=views, last_seq=last_seq)

        self.__path = Path(path)
        self.__saved_seq = last_seq
        self.__summary_end = summary_end
        self.__lines = lines
        self.__anchors = anchors
        self.__scenario = str(meta.get("scenario") or "")   # 老会话没有 sidecar → 空串
        self.__title = str(meta.get("title") or "")
        if not self.__title:
            for _seq, address, payload in items:
                if address != "user":
                    continue
                text = payload.get("text") if isinstance(payload, dict) else payload
                text = str(text or "").strip()
                if text:
                    self.__title = text[:24]
                    break
        log.info(
            "Persist",
            f"loaded {path} ({len(items)} records; hot {len(main)}, cold <= {summary_end})",
        )
        return path

    def reset(self):
        """新会话：落盘水位和文件都重置（场景选择留到 set_scenario）。"""
        with self.__lock:
            self.__path = None
            self.__saved_seq = 0
            self.__title = ""
            self.__summary_end = 0
            self.__lines = 0
            self.__anchors = {}

    @property
    def saved_seq(self):
        """已落盘的最大 seq（内存退役前必须满足 saved_seq >= 退役边界）。"""
        return self.__saved_seq

    # ---------- 会话场景 / 索引（sidecar） ----------
    @staticmethod
    def meta_path(path):
        return Path(str(path) + ".meta.json")

    @property
    def scenario(self):
        return self.__scenario

    @property
    def title(self):
        return self.__title

    def set_scenario(self, scenario):
        """记下当前会话的场景；文件还没建时先挂内存，首次落盘时写 sidecar。"""
        self.__scenario = str(scenario or "")
        self.__write_meta()

    def scenario_of(self, path):
        return str(self.__read_meta(path).get("scenario") or "")

    @staticmethod
    def __read_meta(path):
        try:
            data = json.loads(PersistSystem.meta_path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def __write_meta_file(path, data):
        """sidecar 原子写：reader 永远不会读到半截 JSON。"""
        target = PersistSystem.meta_path(path)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)

    def __write_meta(self):
        if self.__path is None:
            return
        try:
            self.__write_meta_file(self.__path, {
                "scenario": self.__scenario,
                "title": self.__title,
                "records": self.__saved_seq,
                "summary_end": self.__summary_end,
                "lines": self.__lines,
                "anchors": sorted(self.__anchors.items()),
            })
        except Exception as error:
            _faults.report(error, "meta")

    def rebind(self):
        """数据根变了：当前会话文件不在新目录下，就另起一份（旧文件不动）。"""
        with self.__lock:
            if self.__path is None:
                return
            try:
                self.__path.relative_to(session_dir())
            except ValueError:
                self.__path = None
                self.__saved_seq = 0

    # ---------- 会话索引 ----------
    @property
    def current_path(self):
        return str(self.__path) if self.__path is not None else None

    def read_records(self, limit_turns=None, path=None):
        """按需从磁盘读会话记录（回放超出内存热窗口时用）。

        有稀疏索引就从最近锚点 seek、按区间读：给 limit_turns 时先读尾部一段，
        用户轮数不够再往前扩，**不再整份解析**。冷记录只有这里能拿回原文。
        """
        target = Path(path) if path else self.__path
        if target is None or not Path(target).exists():
            return []
        meta = self.__read_meta(target)
        anchors = {}
        lines = 0
        try:
            anchors = {int(key): int(value) for key, value in (meta.get("anchors") or [])}
            lines = int(meta.get("lines") or 0)
        except (TypeError, ValueError):
            anchors, lines = {}, 0
        if not anchors or lines <= 0:
            anchors, lines = self.__index_file(target)

        if limit_turns is None:
            return self.__read_interval(target, anchors, 1)

        span = max(64, int(limit_turns) * 8)
        start_line = max(1, lines - span + 1)
        while True:
            records = self.__read_interval(target, anchors, start_line)
            users = sum(1 for record in records if record.address == "user")
            if users >= int(limit_turns) or start_line <= 1:
                return records
            span *= 2
            start_line = max(1, start_line - span)

    @staticmethod
    def __index_file(path):
        """没有索引的旧文件：扫一遍建锚点（只算偏移，不解析 JSON）。"""
        anchors = {}
        offset = 0
        lines = 0
        try:
            with open(path, "rb") as file:
                for index, raw in enumerate(file, start=1):
                    if index == 1 or (index - 1) % INDEX_STRIDE == 0:
                        anchors[index] = offset
                    offset += len(raw)
                    lines = index
        except OSError as error:
            _faults.report(error, "index")
            return {}, 0
        return anchors, lines

    def __read_interval(self, path, anchors, start_line):
        """从 start_line 起读到文件尾；从它前面最近的锚点 seek。"""
        start_line = max(1, int(start_line or 1))
        anchor_line = ((start_line - 1) // INDEX_STRIDE) * INDEX_STRIDE + 1
        offset = int(anchors.get(anchor_line, 0))
        out = []
        line_no = anchor_line - 1
        try:
            with open(path, "rb") as file:
                file.seek(offset)
                for raw in file:
                    line_no += 1
                    if line_no < start_line:
                        continue
                    text = raw.decode("utf-8", "replace").strip()
                    if not text:
                        continue
                    try:
                        item = json.loads(text)
                        raw_seq = item.get("seq")
                        out.append(Record(
                            int(raw_seq) if raw_seq is not None else line_no,
                            item["address"],
                            item["payload"],
                        ))
                    except Exception:
                        continue
        except OSError as error:
            _faults.report(error, "read_records")
            return []
        return out

    def list_sessions(self, limit=50):
        """会话索引：新的在前。

        优先读 `.meta.json` sidecar（标题 / 记录数 / 场景）；
        老会话没有索引就**扫一次并补写**，之后列表不再整份解析 JSONL。
        """
        try:
            files = sorted(
                session_dir().glob("session-*.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            files = []

        items = []
        for path in files[:limit]:
            meta = self.__read_meta(path)
            title = str(meta.get("title") or "")
            records = meta.get("records")
            if not title or not isinstance(records, int):
                scanned_title, scanned_records = self.__summary(path)
                if not title:
                    title = scanned_title
                if not isinstance(records, int):
                    records = scanned_records
                # 补写索引（失败不影响列表）
                try:
                    self.__write_meta_file(path, {
                        **meta,
                        "title": title,
                        "records": records,
                        "scenario": str(meta.get("scenario") or ""),
                    })
                except OSError:
                    pass
            if not title:
                title = "新会话"
            try:
                mtime = int(path.stat().st_mtime)
            except Exception:
                mtime = 0
            items.append({
                "path": str(path),
                "title": title,
                "records": int(records or 0),
                "mtime": mtime,
                "scenario": str(meta.get("scenario") or ""),
            })
        return items

    @staticmethod
    def __summary(path):
        """老会话补索引：只解析文件头部找标题，记录数按字节数数行，不整份 JSON 解析。

        改标题会同步写 sidecar，因此这里只需要处理“从未建过索引”的文件；
        标题记录通常也在头部附近（新会话第一条 user 就是标题来源）。
        """
        title = None
        override = None
        records = 0
        try:
            with open(path, "rb") as file:
                head = file.read(65536)
                records = head.count(b"\n")
                while True:
                    chunk = file.read(1024 * 1024)
                    if not chunk:
                        break
                    records += chunk.count(b"\n")
                if head and not head.endswith(b"\n"):
                    records += 1
            for line in head.decode("utf-8", "replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                address = item.get("address")
                if address == "title":
                    text = str(item.get("payload") or "").strip()
                    if text:
                        override = text
                elif address == "user" and title is None:
                    text = str(item.get("payload") or "").strip()
                    if text:
                        title = text[:24]
        except Exception:
            pass
        return override or title or "新会话", records

    def rename(self, path, title):
        """改标题：往会话文件追加一条 title 记录（最新一条生效）。"""
        title = str(title).strip()
        if not title:
            raise ValueError("标题为空")
        with self.__lock:
            target = Path(path)
            if not target.exists():
                raise FileNotFoundError(f"会话不存在：{target}")
            # 标题记录**不占序号**（seq=0）：否则下一次 save 的第一条会和它撞号
            seq = 0
            # 索引跟着改：标题立即生效；行数 / 锚点也要更新
            meta = self.__read_meta(target)
            try:
                lines = int(meta.get("lines") or 0)
                anchors = {int(key): int(value) for key, value in (meta.get("anchors") or [])}
            except (TypeError, ValueError):
                lines, anchors = 0, {}
            if lines <= 0:
                anchors, lines = self.__index_file(target)
            line_no = lines + 1
            try:
                offset = target.stat().st_size
            except OSError:
                offset = 0
            data = (json.dumps({
                "seq": seq,
                "address": "title",
                "payload": title,
            }, ensure_ascii=False) + "\n").encode("utf-8")
            with open(target, "ab") as file:
                file.write(data)
            if line_no == 1 or (line_no - 1) % INDEX_STRIDE == 0:
                anchors[line_no] = offset
            meta.update({
                "title": title,
                "records": int(meta.get("records") or 0),
                "lines": line_no,
                "anchors": sorted(anchors.items()),
            })
            try:
                self.__write_meta_file(target, meta)
            except OSError:
                pass
            if self.__path is not None and str(self.__path) == str(target):
                self.__title = title
                self.__lines = line_no
                self.__anchors = anchors
        return title

    def delete(self, path):
        """删除会话文件（连同场景 sidecar）；如果删的是当前会话，落盘状态一起重置。"""
        with self.__lock:
            target = Path(path)
            try:
                target.unlink()
            except FileNotFoundError:
                return False
            try:
                self.meta_path(target).unlink()
            except FileNotFoundError:
                pass
            if self.__path is not None and str(self.__path) == str(target):
                self.__path = None
                self.__saved_seq = 0
                self.__lines = 0
                self.__anchors = {}
            return True

    @staticmethod
    def __last_seq(path):
        seq = 0
        with open(path, encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    seq = int(json.loads(line).get("seq") or seq)
                except Exception:
                    continue
        return seq


persist = PersistSystem()
