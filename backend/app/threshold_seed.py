"""逾期阈值模拟器专用种子数据。

模拟基准日固定为 2026-10-01，演示数据围绕它展开：
- 6 条路段：4 条普通路段 + 2 个专项工程段（阈值方案 1 个已批准、1 个待批准）；
- 12 条巡查记录并入 patrol 表：覆盖逾期、临界、未来在办与历史留痕；
- 11 条巡查排班：3 条本月月历（集中重排不得触碰）+ 8 条未来排班（发布后回填）。

这里只放数据结构，业务口径在 app.services.threshold 里。
"""
from __future__ import annotations

from typing import Any

# 模拟基准日：负责人打开模拟器时“今天”的日期，整个模拟器以此算逾期。
REFERENCE_DATE = "2026-10-01"

WEATHER_LEVELS = ["无", "蓝色（低）", "黄色（中）", "橙色（高）", "红色（暴雨）"]
RISK_LEVELS = ["无", "中风险", "高风险"]

# 路段风险档案；适用方案非空时，该路段阈值以批准方案为准，滑块不再生效。
SIMULATOR_SECTIONS: list[dict[str, Any]] = [
    {
        "id": 1,
        "路段编号": "RS-P01",
        "路段名称": "北三环主线",
        "风险等级": "中",
        "既有巡查周期": 7,
        "默认车辆": "VEHI-0001",
        "适用方案": None,
    },
    {
        "id": 2,
        "路段编号": "RS-P02",
        "路段名称": "滨河路下行",
        "风险等级": "高",
        "既有巡查周期": 5,
        "默认车辆": "VEHI-0002",
        "适用方案": None,
    },
    {
        "id": 3,
        "路段编号": "RS-P03",
        "路段名称": "南山隧道接线",
        "风险等级": "低",
        "既有巡查周期": 10,
        "默认车辆": "VEHI-0003",
        "适用方案": None,
    },
    {
        "id": 4,
        "路段编号": "RS-P04",
        "路段名称": "站前广场匝道",
        "风险等级": "高",
        "既有巡查周期": 3,
        "默认车辆": "VEHI-0002",
        "适用方案": None,
    },
    {
        "id": 5,
        "路段编号": "RS-P05",
        "路段名称": "机场快速路改建段",
        "风险等级": "中",
        "既有巡查周期": 7,
        "默认车辆": "VEHI-0001",
        "适用方案": "PLAN-2026-017",
    },
    {
        "id": 6,
        "路段编号": "RS-P06",
        "路段名称": "港区立交扩建段",
        "风险等级": "中",
        "既有巡查周期": 10,
        "默认车辆": "VEHI-0003",
        "适用方案": None,
    },
]

# 项目专用阈值：已批准的立即生效；待批准的草案不参与阈值计算（路段暂按普通口径）。
SIMULATOR_PLANS: list[dict[str, Any]] = [
    {
        "id": 1,
        "方案编号": "PLAN-2026-017",
        "方案名称": "机场快速路改建段养护专项方案",
        "路段编号": "RS-P05",
        "巡查周期": 3,
        "天气等级": 2,
        "风险等级": 1,
        "方案状态": "已批准",
        "批准日期": "2026-09-12",
        "备注": "改建段施工期间加密巡查，专项阈值以本批准方案为准。",
    },
    {
        "id": 2,
        "方案编号": "PLAN-2026-021",
        "方案名称": "港区立交扩建专项方案（草案）",
        "路段编号": "RS-P06",
        "巡查周期": 4,
        "天气等级": 1,
        "风险等级": 1,
        "方案状态": "待批准",
        "批准日期": None,
        "备注": "尚未批复；批复前 RS-P06 继续沿用既有 10 天周期。",
    },
]

# 并入 patrol 表的模拟巡查记录（id 由 Store 启动时接续分配）。
# 记录性质=历史留痕 的已结案记录只做留痕，任何滑块与集中重排都不改变它们。
SIMULATOR_PATROL_ROWS: list[dict[str, Any]] = [
    {"巡查编号": "PATR-SIM-01", "路段编号": "RS-P01", "计划日期": "2026-09-20",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-02", "路段编号": "RS-P01", "计划日期": "2026-09-24",
     "status": "巡查中", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-03", "路段编号": "RS-P01", "计划日期": "2026-09-27",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-04", "路段编号": "RS-P02", "计划日期": "2026-09-26",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-05", "路段编号": "RS-P02", "计划日期": "2026-09-28",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-06", "路段编号": "RS-P04", "计划日期": "2026-09-30",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-07", "路段编号": "RS-P05", "计划日期": "2026-09-26",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-08", "路段编号": "RS-P05", "计划日期": "2026-09-29",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-09", "路段编号": "RS-P06", "计划日期": "2026-09-25",
     "status": "巡查中", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-10", "路段编号": "RS-P03", "计划日期": "2026-09-10",
     "status": "已完成", "pending": False, "abnormal": False, "记录性质": "历史留痕", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-11", "路段编号": "RS-P02", "计划日期": "2026-09-15",
     "status": "已复核", "pending": False, "abnormal": False, "记录性质": "历史留痕", "督办状态": "无"},
    {"巡查编号": "PATR-SIM-12", "路段编号": "RS-P03", "计划日期": "2026-10-03",
     "status": "待巡查", "pending": True, "abnormal": False, "记录性质": "在办", "督办状态": "无"},
]

_DRIVERS = {"VEHI-0001": "张伟", "VEHI-0002": "李娜", "VEHI-0003": "王强"}


def _schedule_row(
    row_id: int,
    code: str,
    planned: str,
    vehicle: str,
    *,
    keep_current: bool = False,
) -> dict[str, Any]:
    section = next(item for item in SIMULATOR_SECTIONS if item["路段编号"] == code)
    return {
        "id": row_id,
        "排班编号": f"PS-ORIG-{row_id:02d}",
        "排班日期": planned,
        "路段编号": code,
        "路段名称": section["路段名称"],
        "车辆编号": vehicle,
        "驾驶员": _DRIVERS[vehicle],
        "班次": "日班",
        "周期天数": section["既有巡查周期"],
        "来源": "原计划",
        "规则版本": None,
        "重排状态": "本月保留" if keep_current else "待重排",
        "幂等键": None,
        "关联巡查": None,
    }


# 本月 3 条：规则发布只能保留，不能集中处理；未来 8 条：发布后按新阈值回填重排。
SIMULATOR_SCHEDULES: list[dict[str, Any]] = [
    _schedule_row(1, "RS-P01", "2026-10-08", "VEHI-0001", keep_current=True),
    _schedule_row(2, "RS-P02", "2026-10-15", "VEHI-0002", keep_current=True),
    _schedule_row(3, "RS-P04", "2026-10-22", "VEHI-0002", keep_current=True),
    _schedule_row(4, "RS-P01", "2026-11-03", "VEHI-0001"),
    _schedule_row(5, "RS-P02", "2026-11-05", "VEHI-0002"),
    _schedule_row(6, "RS-P05", "2026-11-06", "VEHI-0001"),
    _schedule_row(7, "RS-P03", "2026-11-08", "VEHI-0003"),
    _schedule_row(8, "RS-P04", "2026-11-09", "VEHI-0002"),
    _schedule_row(9, "RS-P06", "2026-11-10", "VEHI-0003"),
    _schedule_row(10, "RS-P01", "2026-11-11", "VEHI-0001"),
    _schedule_row(11, "RS-P02", "2026-11-12", "VEHI-0002"),
    _schedule_row(12, "RS-P05", "2026-11-13", "VEHI-0001"),
]

# 模拟器独立表（patrol 相关的 12 条记录单独并入既有 patrol 表）。
SIMULATOR_TABLES: dict[str, list[dict[str, Any]]] = {
    "threshold_section": [dict(row) for row in SIMULATOR_SECTIONS],
    "threshold_plan": [dict(row) for row in SIMULATOR_PLANS],
    "threshold_rule": [],
    "threshold_batch": [],
    "threshold_schedule": [dict(row) for row in SIMULATOR_SCHEDULES],
    "patrol_todo": [],
}


def build_patrol_rows() -> list[dict[str, Any]]:
    """把模拟巡查记录补齐成 patrol 表行：路段名、车辆、人员等冗余字段一次性填好。"""
    rows: list[dict[str, Any]] = []
    for raw in SIMULATOR_PATROL_ROWS:
        section = next(item for item in SIMULATOR_SECTIONS if item["路段编号"] == raw["路段编号"])
        row = dict(raw)
        row["巡查路段"] = section["路段名称"]
        row["巡查日期"] = raw["计划日期"]
        row["巡查人员"] = "值班巡查员"
        row["巡查车辆"] = section["默认车辆"]
        row["发现问题"] = ""
        row["处置措施"] = ""
        row["巡查状态"] = raw["status"]
        row["风险等级"] = section["风险等级"]
        row["既有周期"] = section["既有巡查周期"]
        row["督办批次"] = None
        rows.append(row)
    return rows
