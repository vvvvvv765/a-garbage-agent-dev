"""项目资产写入：模型把整理好的行写回项目资产库，总表 assets.csv 随之刷新。"""
from .Assets import add_assets, project_csv_path
from .Executions import executions
from .Output import CapabilityResult
from .Spec import CapabilitySpec


def _session():
    execution = executions.current()
    return execution.session_id if execution is not None else ""


class AssetsWriteCapability:
    name = "assetsWrite"
    description = (
        "把整理好的资产行写进当前项目资产库，并同步刷新项目总表 assets.csv。"
        "用于把导入的 CSV（测绘平台导出、nmap / ffuf 结果、手工表）整理成统一行。"
        "每行可填 kind / domain / ip / port / url / title / server / protocol / sources / note；"
        "其它列（如「学号」「姓名」）原样作为总表的额外列保留。"
        "同一域名 / IP / URL 再次写入会合并来源与字段，不会产生重复行。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "records": {
                "type": "array",
                "description": "资产行列表，每项是一个对象（字段名即列名）",
                "items": {"type": "object"},
                "minItems": 1,
            },
            "source": {
                "type": "string",
                "description": "来源标记，例如「fofa 导出整理」「手工整理」",
            },
        },
        "required": ["records"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="write", trust="internal", timeout=60)

    def run(self, arguments):
        rows = arguments.get("records") or []
        if not isinstance(rows, list) or not rows:
            return CapabilityResult("records 不能为空；每项是一个对象", ok=False)
        source = str(arguments.get("source") or "整理").strip() or "整理"
        records = [row for row in rows if isinstance(row, dict)]
        if not records:
            return CapabilityResult("records 里没有对象行", ok=False)
        session_id = _session()
        added, total = add_assets(session_id, records, source=source,
                                  query=f"assetsWrite ×{len(records)}")
        path = project_csv_path(session_id)
        return CapabilityResult(
            f"写入 {len(records)} 行：新增 {added} 条，项目资产库共 {total} 条。\n"
            f"项目总表已刷新：{path}",
            {"path": str(path)},
        )
