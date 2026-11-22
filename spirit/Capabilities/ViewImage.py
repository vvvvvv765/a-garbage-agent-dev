"""
viewImage 能力：把本地图片作为图像附件交给模型看。

用途：渲染结果 / 页面截图 / 图表 / 照片的视觉检查。
比让模型用 PIL 输出像素值“盲猜”直接得多；模型自己判断能不能看图、要不要调用。
"""
import hashlib
import os
import uuid

from Paths import home

from .Files import resolve
from .Output import CapabilityResult
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_BYTES = 8 * 1024 * 1024


class ViewImageCapability:
    name = "viewImage"
    description = (
        "把本地图片（截图 / 渲染图 / 图表 / 照片）作为图像附件直接给模型看。"
        "支持 png / jpg / jpeg / webp / gif，单张 ≤8MB，重复看同一张不会重复占空间。"
        "检查渲染结果、看页面截图、看图表时优先用它，不要用 PIL 输出像素值盲猜。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "图片路径；相对路径按工作目录解析"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="untrusted", side_effect="read",
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            path = resolve(self.__workdir, arguments["path"])
            if not path.exists():
                return f"文件不存在：{path}"
            if path.is_dir():
                return f"这是文件夹，不是图片：{path}"
            suffix = path.suffix.lower()
            if suffix not in IMAGE_MIME:
                return (
                    f"不是支持的图片格式：{path}\n"
                    "支持 png / jpg / jpeg / webp / gif；文本文件用 readFile。"
                )
            size = path.stat().st_size
            if size <= 0:
                return f"图片是空文件：{path}"
            if size > MAX_BYTES:
                return (
                    f"图片太大：{size} 字节（上限 8MB）。"
                    "先用工具压缩或缩小尺寸，再调用 viewImage。"
                )
            data = path.read_bytes()
        except SandboxDenied:
            raise
        except Exception as error:
            return f"读取图片失败：{error}"

        # 内容哈希做文件名：同一张图反复看只占一份；32 位十六进制满足上传区命名规则
        digest = hashlib.sha256(data).hexdigest()[:32]
        ext = "jpg" if suffix == ".jpeg" else suffix.lstrip(".")
        name = f"{digest}.{ext}"
        uploads = home() / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        target = uploads / name
        if not target.exists():
            # 先写临时文件再原子替换：批内并行看同一张图时不会互相截断
            temp = uploads / f".{name}.{uuid.uuid4().hex}.tmp"
            try:
                temp.write_bytes(data)
                os.replace(temp, target)
            finally:
                try:
                    temp.unlink()
                except OSError:
                    pass

        mime = IMAGE_MIME[suffix]
        return CapabilityResult(
            f"图片已附上：{path}（{size} 字节，{mime}）。接下来的上下文里可以直接看到这张图。",
            {
                "images": [{"id": name, "mime": mime, "path": str(path)}],
                "kind": "image",
            },
        )
