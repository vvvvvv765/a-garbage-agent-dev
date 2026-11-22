"""uploads 清理：只删没被会话引用的图片，引用中的保留。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-uploads-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Disk import disk  # noqa: E402
from Paths import home as data_home, session_dir  # noqa: E402

uploads = data_home() / "uploads"
uploads.mkdir(parents=True, exist_ok=True)
names = [f"{i:032x}.png" for i in range(1, 4)]
for name in names:
    (uploads / name).write_bytes(b"fake-png")

sessions = session_dir()
sessions.mkdir(parents=True, exist_ok=True)
(sessions / "session-test.jsonl").write_text(
    '{"address":"user","payload":{"text":"x","images":[{"id":"%s"}]}}\n' % names[0],
    encoding="utf-8",
)

removed = disk.clear("uploads")
assert removed == 2, removed
assert (uploads / names[0]).exists(), "被会话引用的图片不能删"
assert not (uploads / names[1]).exists()
assert not (uploads / names[2]).exists()
print("uploads cleanup ok:", removed, "removed, referenced kept")
print("\nDISK UPLOADS TEST OK")
