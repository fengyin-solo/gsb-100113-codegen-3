"""逾期阈值模拟器接口：模拟预览、规则发布、批次游标续做与结果落点查询。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ActionResult, PageResult, PublishPayload, SimulatePayload
from app.services.threshold import ThresholdService

router = APIRouter(prefix="/api/threshold", tags=["逾期阈值模拟器"])

service = ThresholdService()


@router.get("/rules", response_model=PageResult[dict])
def list_rules() -> PageResult[dict]:
    """阈值规则列表：普通路段既有周期 + 项目专用批准方案（只读）。"""
    items = service.list_rules()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.post("/simulate", response_model=dict)
def simulate(payload: SimulatePayload) -> dict:
    """按滑杆参数预演哪些巡查记录会转为督办；项目专用路段始终走批准方案。"""
    return service.simulate(
        cycle_days=payload.cycle_days,
        weather_level=payload.weather_level,
        risk_level=payload.risk_level,
    )


@router.post("/rules/{rule_id}/publish", response_model=ActionResult)
def publish_rule(rule_id: int, payload: PublishPayload) -> ActionResult:
    """发布规则：幂等键拦截重复发布，版本锁防止基于过期规则发文；返回待推进的批次。"""
    batch, message = service.publish(
        rule_id,
        expected_version=payload.expected_version,
        idempotency_key=payload.idempotency_key,
        cycle_days=payload.cycle_days,
        weather_level=payload.weather_level,
        risk_level=payload.risk_level,
    )
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/batches", response_model=PageResult[dict])
def list_batches() -> PageResult[dict]:
    """发布批次列表：游标、总量与结果汇总，工作计划不随列表返回。"""
    items = service.list_batches()
    return PageResult(items=items, total=len(items), page=1, size=len(items) or 1)


@router.get("/batches/{batch_id}", response_model=dict)
def get_batch(batch_id: int) -> dict:
    """单个批次状态：前端断连重进后凭批次号找回游标。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"发布批次 {batch_id} 不存在或已清理")
    return batch


@router.post("/batches/{batch_id}/resume", response_model=ActionResult)
def resume_batch(batch_id: int) -> ActionResult:
    """从批次游标续做：每步一个事务，连接断开后重调本接口即可接着推进。"""
    batch, message = service.resume(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/results", response_model=dict)
def results() -> dict:
    """结果落点：巡查待办、路面病害清单、车辆排班汇总，外加当前月历留痕说明。"""
    return service.results()
