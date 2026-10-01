"""逾期阈值模拟器接口。

- GET  /api/simulator/config        滑块边界、天气/风险字典、当前生效规则
- GET  /api/simulator/sections      路段风险档案（含适用方案）
- GET  /api/simulator/plans         项目专用阈值方案
- POST /api/simulator/plans/{id}/approve  批复草案（演示「以批准方案为准」）
- GET  /api/simulator/preview       拖动滑块后预览将转督办的巡查记录
- POST /api/simulator/apply         模拟处置：落巡查待办、路面病害、督办派车
- POST /api/simulator/publish       发布规则：版本锁 + 启动集中重排批次
- GET  /api/simulator/batches       批次游标
- POST /api/simulator/batches/{id}/resume  断线后从游标续算
- GET  /api/simulator/todos         巡查待办（督办）
- GET  /api/simulator/vehicle-summary 车辆排班汇总
- GET  /api/simulator/landing-stats 三个落库页面的角标统计
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.threshold import (
    RISK_MAX,
    WEATHER_MAX,
    CYCLE_MAX,
    threshold_service,
)

router = APIRouter(prefix="/api/simulator", tags=["逾期阈值模拟器"])


class SliderValues(BaseModel):
    cycle: int = Field(default=7, ge=1, le=CYCLE_MAX, description="巡查周期（天）草案")
    weather: int = Field(default=0, ge=0, le=WEATHER_MAX, description="天气等级 0-4")
    risk: int = Field(default=0, ge=0, le=RISK_MAX, description="路段风险 0-2")
    asOf: str | None = Field(default=None, description="模拟基准日，缺省取演示基准日")


class PublishPayload(SliderValues):
    baseVersion: int | None = Field(default=None, description="前端当前看到的规则版本，做版本锁校验")
    operator: str = Field(default="值班负责人")


def _conflict(result: dict[str, Any]) -> dict[str, Any]:
    raise HTTPException(status_code=409, detail=result)


@router.get("/config")
def get_config() -> dict[str, Any]:
    """返回滑块取值边界、天气/风险字典与当前生效规则版本。"""
    return threshold_service.config()


@router.get("/sections")
def list_sections() -> dict[str, Any]:
    """路段风险档案；适用方案非空时该路段阈值由批准方案决定。"""
    return {"items": threshold_service.list_sections()}


@router.get("/plans")
def list_plans() -> dict[str, Any]:
    """项目专用阈值方案；待批准草案不参与阈值计算。"""
    return {"items": threshold_service.list_plans()}


@router.post("/plans/{plan_id}/approve")
def approve_plan(plan_id: int) -> dict[str, Any]:
    """批复专项方案：批复后路段阈值即刻以方案为准（滑块对该路段失效）。"""
    result = threshold_service.approve_plan(plan_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/preview")
def preview(
    cycle: int = Query(7, ge=1, le=CYCLE_MAX),
    weather: int = Query(0, ge=0, le=WEATHER_MAX),
    risk: int = Query(0, ge=0, le=RISK_MAX),
    as_of: str | None = Query(default=None, alias="asOf"),
) -> dict[str, Any]:
    """拖动滑块后的预览：返回各路段生效阈值、将转督办清单与留痕清单。"""
    return threshold_service.preview(cycle=cycle, weather=weather, risk=risk, as_of=as_of)


@router.post("/apply")
def apply_simulation(payload: SliderValues) -> dict[str, Any]:
    """模拟处置：结果落到巡查待办、路面病害清单和车辆排班汇总页；不集中处理本月月历。"""
    return threshold_service.apply_simulation(
        cycle=payload.cycle, weather=payload.weather, risk=payload.risk, as_of=payload.asOf
    )


@router.post("/publish")
def publish_rule(payload: PublishPayload) -> dict[str, Any]:
    """发布规则并启动集中重排；版本过期/批次占用返回 409，相同指纹重复发布不生效。"""
    result = threshold_service.publish_rule(
        cycle=payload.cycle,
        weather=payload.weather,
        risk=payload.risk,
        base_version=payload.baseVersion,
        operator=payload.operator,
    )
    if not result.get("ok"):
        _conflict(result)
    return result


@router.get("/batches")
def list_batches() -> dict[str, Any]:
    """重排批次与游标进度。"""
    return {"items": threshold_service.list_batches()}


@router.post("/batches/{batch_id}/resume")
def resume_batch(batch_id: int) -> dict[str, Any]:
    """重算连接断开后，从批次游标继续处理下一块工作项。"""
    result = threshold_service.resume_batch(batch_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.get("/todos")
def list_todos(status: str | None = None) -> dict[str, Any]:
    """巡查待办：模拟处置生成的逾期督办项。"""
    return {"items": threshold_service.list_todos(status)}


@router.get("/vehicle-summary")
def vehicle_summary() -> dict[str, Any]:
    """车辆排班汇总：按车辆聚合原计划、本月保留、督办派车与规则回填班次。"""
    return threshold_service.vehicle_schedule_summary()


@router.get("/landing-stats")
def landing_stats() -> dict[str, Any]:
    """三个落库页面（巡查待办/路面病害/排班汇总）读取的角标统计。"""
    return threshold_service.landing_stats()
