"""逾期阈值模拟器业务规则：模拟预览、规则发布、批次游标续做与结果落点。

口径约定：
- 项目专用阈值以批准方案为准，滑杆只作用于普通路段（既有周期）；
- 规则发布只回填未来排班，当前月历不纳入集中处理，旧巡查按原计划留痕；
- 集中重排按批次步进，每步一个事务，规则版本锁贯穿整个批次；
- 幂等键拦截重复发布，工作项用内容键兜底，断连后从批次游标续做。
"""
from __future__ import annotations

import threading
from copy import deepcopy
from datetime import date, datetime
from typing import Any

from app.store import store

RULE_MODULE = "threshold_rule"
BATCH_MODULE = "threshold_batch"
SCHEDULE_MODULE = "patrol_schedule"
PATROL_MODULE = "patrol"
PAVEMENT_MODULE = "pavement"
VEHICLE_MODULE = "vehicle"

OPEN_STATUSES = ("待巡查", "巡查中")  # 未闭环的巡查才参与逾期判定
CLOSED_STATUSES = ("已完成", "已复核")  # 旧巡查按原计划留痕，不再改动
WEATHER_FACTORS = {1: 1.0, 2: 0.9, 3: 0.8, 4: 0.7, 5: 0.6}
WEATHER_LABELS = {1: "晴好", 2: "多云", 3: "降雨", 4: "暴雨", 5: "冰雪"}
RISK_FACTORS = {1: 1.0, 2: 0.85, 3: 0.7}
RISK_LABELS = {1: "低风险", 2: "中风险", 3: "高风险"}
FUTURE_MONTHS = 2  # 发布时回填未来两个月的排班
STEP_SIZE = 5  # 每个批次步长：游标按步推进，断连后从游标续做


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _month_key(day: date) -> str:
    return day.strftime("%Y-%m")


def _shift_month(month_key: str, offset: int) -> str:
    year, month = (int(part) for part in month_key.split("-"))
    month += offset
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return f"{year:04d}-{month:02d}"


def _effective_cycle(cycle_days: int, weather_level: int, risk_level: int) -> int:
    """普通路段有效周期：既有周期按天气等级、路段风险折减，天气越差/风险越高周期越短。"""
    factor = WEATHER_FACTORS.get(weather_level, 1.0) * RISK_FACTORS.get(risk_level, 1.0)
    return max(1, round(cycle_days * factor))


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


class _StepTransaction:
    """单步事务：先快照再落账，出错整体回滚，保证集中重排不留半截数据。"""

    def __init__(self) -> None:
        self._backup: list[tuple[str, int, dict[str, Any] | None]] = []

    def snapshot(self, module: str, row: dict[str, Any]) -> None:
        row_id = int(row.get("id", 0))
        if not any(m == module and i == row_id for m, i, _ in self._backup):
            self._backup.append((module, row_id, deepcopy(row)))

    def insert(self, module: str, row: dict[str, Any]) -> None:
        store.rows(module).append(row)
        self._backup.append((module, int(row.get("id", 0)), None))

    def rollback(self) -> None:
        for module, row_id, snap in reversed(self._backup):
            rows = store.rows(module)
            if snap is None:
                rows[:] = [row for row in rows if int(row.get("id", 0)) != row_id]
                continue
            for row in rows:
                if int(row.get("id", 0)) == row_id:
                    row.clear()
                    row.update(snap)
                    break


class ThresholdService:
    def __init__(self) -> None:
        # 发布与续做共用一把锁，等价于数据库的事务边界，避免并发批次互相踩数据
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 查询
    def list_rules(self) -> list[dict[str, Any]]:
        return sorted(store.rows(RULE_MODULE), key=lambda row: int(row.get("id", 0)))

    def list_batches(self) -> list[dict[str, Any]]:
        rows = sorted(store.rows(BATCH_MODULE), key=lambda row: int(row.get("id", 0)), reverse=True)
        return [self._public_batch(row) for row in rows]

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = store.find(BATCH_MODULE, batch_id)
        return self._public_batch(batch) if batch else None

    def results(self) -> dict[str, Any]:
        """结果落点：巡查待办、路面病害清单、车辆排班汇总，外加当前月历留痕说明。"""
        current_month = _month_key(_today())
        schedules = store.rows(SCHEDULE_MODULE)
        supervised = [row for row in store.rows(PATROL_MODULE) if row.get("督办")]
        supervised.sort(key=lambda row: int(row.get("逾期天数") or 0), reverse=True)
        defects = sorted(store.rows(PAVEMENT_MODULE), key=lambda row: int(row.get("id", 0)), reverse=True)[:20]
        future = [row for row in schedules if str(row.get("计划月份")) > current_month and row.get("status") == "待巡查"]
        current = [row for row in schedules if str(row.get("计划月份")) == current_month]
        return {
            "巡查待办": supervised,
            "路面病害": defects,
            "车辆排班": self._vehicle_summary(schedules),
            "当前月历": {
                "月份": current_month,
                "说明": "当前月历不纳入集中处理，排班与巡查仍按原计划执行",
                "排班": sorted(current, key=lambda row: str(row.get("计划日期"))),
            },
            "未来排班": sorted(future, key=lambda row: (str(row.get("计划日期")), str(row.get("巡查路段"))))[:50],
        }

    # ------------------------------------------------------------------ 模拟
    def simulate(self, *, cycle_days: int, weather_level: int, risk_level: int) -> dict[str, Any]:
        """按滑杆参数预演：项目专用路段走批准方案，普通路段走折减后的既有周期。"""
        today = _today()
        plans = self._project_plans()
        items: list[dict[str, Any]] = []
        supervised = 0
        traced = 0
        for row in sorted(store.rows(PATROL_MODULE), key=lambda item: int(item.get("id", 0))):
            status = str(row.get("status") or "")
            if status in CLOSED_STATUSES:
                traced += 1  # 旧巡查按原计划留痕，不参与判定
                continue
            section = str(row.get("巡查路段") or "")
            effective, source = self._resolve_cycle(section, plans, cycle_days, weather_level, risk_level)
            patrol_date = _parse_date(row.get("巡查日期"))
            elapsed = (today - patrol_date).days if patrol_date else 0
            overdue = elapsed - effective
            hit = overdue > 0
            supervised += 1 if hit else 0
            items.append({
                "id": row.get("id"),
                "巡查编号": row.get("巡查编号"),
                "巡查路段": section,
                "巡查日期": row.get("巡查日期"),
                "巡查状态": status,
                "阈值来源": source,
                "有效周期": effective,
                "已间隔": elapsed,
                "逾期天数": max(overdue, 0),
                "转督办": hit,
                "发现问题": row.get("发现问题"),
            })
        return {
            "items": items,
            "summary": {
                "参与判定": len(items),
                "预计转督办": supervised,
                "项目专用": sum(1 for item in items if str(item["阈值来源"]).startswith("批准方案")),
                "普通路段": sum(1 for item in items if item["阈值来源"] == "既有周期"),
                "留痕旧巡查": traced,
            },
            "params": {
                "巡查周期": cycle_days,
                "天气等级": weather_level,
                "天气标签": WEATHER_LABELS.get(weather_level, "未知"),
                "路段风险": risk_level,
                "风险标签": RISK_LABELS.get(risk_level, "未知"),
                "普通路段有效周期": _effective_cycle(cycle_days, weather_level, risk_level),
            },
            "当前月历": _month_key(today),
        }

    # ------------------------------------------------------------------ 发布
    def publish(
        self,
        rule_id: int,
        *,
        expected_version: int,
        idempotency_key: str,
        cycle_days: int,
        weather_level: int,
        risk_level: int,
    ) -> tuple[dict[str, Any] | None, str]:
        """创建发布批次：幂等键拦截重复发布，版本锁防止基于过期规则发文。"""
        with self._lock:
            rule = store.find(RULE_MODULE, rule_id)
            if rule is None:
                return None, f"阈值规则 {rule_id} 不存在"
            if rule.get("适用范围") != "普通路段":
                return None, "项目专用阈值以批准方案为准，不能在模拟器里发布"
            for batch in store.rows(BATCH_MODULE):
                if batch.get("幂等键") == idempotency_key:
                    return self._public_batch(batch), "重复发布已被拦截：同一幂等键只生效一次"
            current_version = int(rule.get("版本", 0))
            if current_version != expected_version:
                return None, f"规则版本已变化（当前 V{current_version}），请刷新后按最新版本发布"
            for batch in store.rows(BATCH_MODULE):
                if batch.get("规则ID") == rule_id and batch.get("status") == "处理中":
                    return None, f"批次 {batch.get('批次号')} 正在处理中，请先从批次游标续做完成"
            batch_no = f"PUB-{datetime.now():%Y%m%d%H%M%S}-R{rule_id}V{current_version + 1}"
            items, traced, skipped_current = self._build_work_plan(
                cycle_days=cycle_days,
                weather_level=weather_level,
                risk_level=risk_level,
                next_version=current_version + 1,
            )
            batch = {
                "id": _next_id(BATCH_MODULE),
                "status": "处理中",
                "pending": True,
                "abnormal": False,
                "批次号": batch_no,
                "规则ID": rule_id,
                "规则名称": rule.get("规则名称"),
                "幂等键": idempotency_key,
                "锁定版本": current_version,
                "巡查周期": cycle_days,
                "天气等级": weather_level,
                "路段风险": risk_level,
                "游标": 0,
                "已处理": 0,
                "总量": len(items),
                "跳过当前月": skipped_current,
                "留痕旧巡查": traced,
                "已生效": {"督办": 0, "病害": 0, "排班": 0, "调整": 0},
                "工作计划": items,
                "结果": {},
                "错误": "",
                "创建时间": datetime.now().isoformat(timespec="seconds"),
                "完成时间": "",
            }
            store.rows(BATCH_MODULE).append(batch)
            if not items:
                self._finalize(batch, rule, _StepTransaction())
                return self._public_batch(batch), f"发布批次 {batch_no} 无需处理，已直接完成"
            return self._public_batch(batch), f"发布批次 {batch_no} 已创建，共 {len(items)} 项待处理"

    def resume(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """从批次游标续做：每步一个事务，连接断开后重调本接口即可接着推进。"""
        with self._lock:
            batch = store.find(BATCH_MODULE, batch_id)
            if batch is None:
                return None, f"发布批次 {batch_id} 不存在或已清理"
            if batch.get("status") == "已完成":
                return self._public_batch(batch), "批次已完成，重复续做不会重复生效"
            if batch.get("status") == "失败":
                return None, f"批次已失败：{batch.get('错误')}"
            rule = store.find(RULE_MODULE, int(batch.get("规则ID", 0)))
            if rule is None:
                return None, "批次关联的阈值规则不存在，无法续做"
            if int(rule.get("版本", 0)) != int(batch.get("锁定版本", 0)):
                batch["status"] = "失败"
                batch["pending"] = False
                batch["abnormal"] = True
                batch["错误"] = "规则版本在处理期间被修改，版本锁已中止该批次"
                return None, str(batch["错误"])
            items: list[dict[str, Any]] = batch.get("工作计划") or []
            cursor = int(batch.get("游标", 0))
            step = items[cursor:cursor + STEP_SIZE]
            tx = _StepTransaction()
            try:
                for item in step:
                    self._apply_item(tx, batch, item)
                batch["游标"] = cursor + len(step)
                batch["已处理"] = batch["游标"]
                if batch["游标"] >= len(items):
                    self._finalize(batch, rule, tx)
            except Exception as exc:  # noqa: BLE001 - 事务兜底：任何一步失败都整体回滚
                tx.rollback()
                batch["status"] = "失败"
                batch["pending"] = False
                batch["abnormal"] = True
                batch["错误"] = f"第 {cursor + 1} 项起处理失败，本步已整体回滚：{exc}"
                return None, str(batch["错误"])
            return self._public_batch(batch), f"批次游标推进到 {batch['游标']}/{len(items)}"

    # ---------------------------------------------------------------- 内部实现
    def _project_plans(self) -> dict[str, dict[str, Any]]:
        """项目专用阈值：以批准方案为准，按覆盖路段索引。"""
        plans: dict[str, dict[str, Any]] = {}
        for rule in store.rows(RULE_MODULE):
            if rule.get("适用范围") != "项目专用" or rule.get("status") != "已发布":
                continue
            section = str(rule.get("覆盖路段") or "").strip()
            if section and section not in ("—", "全部普通路段"):
                plans[section] = rule
        return plans

    def _resolve_cycle(
        self,
        section: str,
        plans: dict[str, dict[str, Any]],
        cycle_days: int,
        weather_level: int,
        risk_level: int,
    ) -> tuple[int, str]:
        plan = plans.get(section)
        if plan is not None:
            return int(plan.get("巡查周期") or 7), f"批准方案 {plan.get('批准方案号')}"
        return _effective_cycle(cycle_days, weather_level, risk_level), "既有周期"

    def _build_work_plan(
        self,
        *,
        cycle_days: int,
        weather_level: int,
        risk_level: int,
        next_version: int,
    ) -> tuple[list[dict[str, Any]], list[int], int]:
        """生成确定性工作计划：督办、病害、旧排班调整、未来排班回填；当前月历只计数不落项。"""
        today = _today()
        current_month = _month_key(today)
        plans = self._project_plans()
        items: list[dict[str, Any]] = []
        patrols = sorted(store.rows(PATROL_MODULE), key=lambda row: int(row.get("id", 0)))
        for patrol in patrols:
            if str(patrol.get("status") or "") not in OPEN_STATUSES:
                continue
            section = str(patrol.get("巡查路段") or "")
            effective, source = self._resolve_cycle(section, plans, cycle_days, weather_level, risk_level)
            patrol_date = _parse_date(patrol.get("巡查日期"))
            elapsed = (today - patrol_date).days if patrol_date else 0
            overdue = elapsed - effective
            if overdue <= 0:
                continue
            patrol_id = int(patrol.get("id", 0))
            items.append({
                "kind": "督办",
                "patrol_id": patrol_id,
                "逾期天数": overdue,
                "适用阈值": f"{source}·{effective}天",
            })
            problem = str(patrol.get("发现问题") or "").strip()
            if problem and problem != "无":
                items.append({
                    "kind": "病害",
                    "patrol_id": patrol_id,
                    "病害编号": f"PAVE-P{patrol_id:04d}",
                    "所属路段": section,
                    "病害类型": problem,
                })
        # 未来排班重排：先算新排班的内容键，旧排班里键不变的保留、其余标记调整；
        # 当前月历只计数不落项（不能集中处理当前月历）。
        vehicles = [str(v.get("车牌号") or v.get("车辆编号")) for v in store.rows(VEHICLE_MODULE)] or ["待派车"]
        sections = sorted({str(p.get("巡查路段") or "") for p in patrols if p.get("巡查路段")} | set(plans))
        skipped_current = 0
        vehicle_seq = 0
        schedule_items: list[dict[str, Any]] = []
        new_keys: set[str] = set()
        for offset in range(FUTURE_MONTHS + 1):
            month = _shift_month(current_month, offset)
            for section_index, section in enumerate(sections):
                effective, source = self._resolve_cycle(section, plans, cycle_days, weather_level, risk_level)
                count = max(1, 28 // effective)
                for seq in range(count):
                    if offset == 0:
                        skipped_current += 1  # 当前月历不纳入集中处理
                        continue
                    vehicle = vehicles[vehicle_seq % len(vehicles)]
                    vehicle_seq += 1
                    key = f"SCH-{month}-{section_index:02d}-{seq:02d}-C{effective}"
                    new_keys.add(key)
                    schedule_items.append({
                        "kind": "排班",
                        "排班编号": key,
                        "巡查路段": section,
                        "计划日期": f"{month}-{1 + seq * effective:02d}",
                        "计划月份": month,
                        "巡查车辆": vehicle,
                        "规则来源": source,
                        "计划版本": f"V{next_version}",
                    })
        for schedule in store.rows(SCHEDULE_MODULE):
            if schedule.get("status") != "待巡查" or str(schedule.get("计划月份")) <= current_month:
                continue
            if str(schedule.get("排班编号")) in new_keys:
                continue  # 键不变的排班保留，重复发布不会产生任何净变化
            items.append({"kind": "调整", "schedule_id": int(schedule.get("id", 0))})
        items.extend(schedule_items)
        traced = [int(p.get("id", 0)) for p in patrols if str(p.get("status") or "") in CLOSED_STATUSES]
        return items, traced, skipped_current

    def _apply_item(self, tx: _StepTransaction, batch: dict[str, Any], item: dict[str, Any]) -> None:
        """应用单个工作项；内容键兜底幂等，同一步重放也不会落重复数据。"""
        kind = item.get("kind")
        applied: dict[str, int] = batch.setdefault("已生效", {"督办": 0, "病害": 0, "排班": 0, "调整": 0})
        if kind == "督办":
            patrol = store.find(PATROL_MODULE, int(item.get("patrol_id", 0)))
            if patrol is None or patrol.get("督办"):
                return
            tx.snapshot(PATROL_MODULE, patrol)
            patrol["督办"] = True
            patrol["abnormal"] = True
            patrol["逾期天数"] = item.get("逾期天数")
            patrol["适用阈值"] = item.get("适用阈值")
            patrol["阈值批次"] = batch.get("批次号")
            applied["督办"] += 1
        elif kind == "病害":
            key = str(item.get("病害编号"))
            if any(row.get("病害编号") == key for row in store.rows(PAVEMENT_MODULE)):
                return
            tx.insert(PAVEMENT_MODULE, {
                "id": _next_id(PAVEMENT_MODULE),
                "status": "待修复",
                "pending": True,
                "abnormal": False,
                "病害编号": key,
                "所属路段": item.get("所属路段"),
                "病害类型": item.get("病害类型"),
                "严重程度": "一般",
                "起止桩号": "—",
                "面积": "—",
                "发现日期": _today().isoformat(),
                "病害状态": "待修复",
                "来源批次": batch.get("批次号"),
            })
            applied["病害"] += 1
        elif kind == "调整":
            schedule = store.find(SCHEDULE_MODULE, int(item.get("schedule_id", 0)))
            if schedule is None or schedule.get("status") != "待巡查":
                return
            tx.snapshot(SCHEDULE_MODULE, schedule)
            schedule["status"] = "已调整"
            schedule["pending"] = False
            schedule["调整批次"] = batch.get("批次号")
            applied["调整"] += 1
        elif kind == "排班":
            key = str(item.get("排班编号"))
            if any(row.get("排班编号") == key for row in store.rows(SCHEDULE_MODULE)):
                return
            tx.insert(SCHEDULE_MODULE, {
                "id": _next_id(SCHEDULE_MODULE),
                "status": "待巡查",
                "pending": True,
                "abnormal": False,
                "排班编号": key,
                "巡查路段": item.get("巡查路段"),
                "计划日期": item.get("计划日期"),
                "计划月份": item.get("计划月份"),
                "巡查车辆": item.get("巡查车辆"),
                "规则来源": item.get("规则来源"),
                "计划版本": item.get("计划版本"),
                "来源批次": batch.get("批次号"),
            })
            applied["排班"] += 1

    def _finalize(self, batch: dict[str, Any], rule: dict[str, Any], tx: _StepTransaction) -> None:
        """批次收尾：规则升版生效，批次汇总结果；与最后一步同事务提交。"""
        tx.snapshot(RULE_MODULE, rule)
        rule["巡查周期"] = batch.get("巡查周期")
        rule["天气等级"] = batch.get("天气等级")
        rule["路段风险"] = batch.get("路段风险")
        rule["版本"] = int(rule.get("版本", 0)) + 1
        rule["status"] = "已发布"
        rule["pending"] = False
        rule["发布批次"] = batch.get("批次号")
        rule["生效月份"] = _shift_month(_month_key(_today()), 1)
        items: list[dict[str, Any]] = batch.get("工作计划") or []
        applied: dict[str, int] = batch.get("已生效") or {}
        batch["结果"] = {
            "转督办": int(applied.get("督办", 0)),
            "病害登记": int(applied.get("病害", 0)),
            "排班回填": int(applied.get("排班", 0)),
            "旧排班调整": int(applied.get("调整", 0)),
            "留痕旧巡查": len(batch.get("留痕旧巡查") or []),
            "跳过当前月": int(batch.get("跳过当前月") or 0),
            "工作计划": len(items),
        }
        batch["status"] = "已完成"
        batch["pending"] = False
        batch["完成时间"] = datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _vehicle_summary(schedules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """车辆排班汇总：按车辆聚合排班次数、覆盖路段与状态分布。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in schedules:
            grouped.setdefault(str(row.get("巡查车辆") or "待派车"), []).append(row)
        summary = []
        for vehicle, rows in sorted(grouped.items()):
            summary.append({
                "巡查车辆": vehicle,
                "排班次数": len(rows),
                "待巡查": sum(1 for row in rows if row.get("status") == "待巡查"),
                "已调整": sum(1 for row in rows if row.get("status") == "已调整"),
                "覆盖路段": len({str(row.get("巡查路段")) for row in rows}),
                "覆盖月份": "、".join(sorted({str(row.get("计划月份")) for row in rows})),
                "最近计划日期": max(str(row.get("计划日期")) for row in rows),
            })
        return summary

    @staticmethod
    def _public_batch(batch: dict[str, Any] | None) -> dict[str, Any]:
        """对外视图：工作计划体积大，只暴露游标与汇总，不随接口返回。"""
        if batch is None:
            return {}
        view = {key: value for key, value in batch.items() if key != "工作计划"}
        view["留痕旧巡查"] = len(batch.get("留痕旧巡查") or [])
        return view
