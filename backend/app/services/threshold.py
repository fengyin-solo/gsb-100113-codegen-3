"""逾期阈值模拟器业务口径。

几条不能被滑块或发布动作改变的口径：
- 项目专用阈值以「已批准」方案为准：适用路段的生效周期完全不接收滑块；
  待批准草案不生效，路段暂按普通口径。
- 普通路段继续沿用既有周期：滑块只能加密（取最小值），不能把周期放松到既有值之上。
- 规则发布只回填未来排班：本月月历一律保留，旧巡查按原计划留痕（历史记录不改写）。
- 集中处理重排走事务 + 规则版本锁；重算连接断开后按批次游标续做；
  重复发布（相同参数指纹）只生效一次。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, timedelta
from typing import Any

from app.store import store
from app.threshold_seed import REFERENCE_DATE, RISK_LEVELS, WEATHER_LEVELS

MODULE = "threshold"

# 滑块取值边界（与前端滑块一致）。
CYCLE_MIN, CYCLE_MAX = 1, 14
WEATHER_MIN, WEATHER_MAX = 0, 4
RISK_MIN, RISK_MAX = 0, 2

# 天气等级、路段风险对普通路段生效周期的扣减天数（加密巡查）。
WEATHER_PENALTY = {0: 0, 1: 0, 2: 1, 3: 2, 4: 3}
RISK_PENALTY = {0: 0, 1: 1, 2: 2}
RISK_CODE = {"低": 0, "中": 1, "高": 2}

# 集中重排不触碰的月历：基准日所在月份；回填从下个月 1 号开始。
BACKFILL_HORIZON_DAYS = 30
BATCH_CHUNK = 8  # 每个重算批次处理 8 条工作项，方便演示「断线后续做」。

OPEN_STATUSES = {"待巡查", "巡查中"}
DRIVERS = {"VEHI-0001": "张伟", "VEHI-0002": "李娜", "VEHI-0003": "王强"}
SECTION_TABLE = "threshold_section"
PLAN_TABLE = "threshold_plan"
RULE_TABLE = "threshold_rule"
BATCH_TABLE = "threshold_batch"
SCHEDULE_TABLE = "threshold_schedule"
TODO_TABLE = "patrol_todo"
PATROL_TABLE = "patrol"
PAVEMENT_TABLE = "pavement"


def _parse(value: str) -> date:
    return date.fromisoformat(value)


def _ref_date(as_of: str | None) -> date:
    return _parse(as_of or REFERENCE_DATE)


class ThresholdService:
    # ---------- 基础数据 ----------
    def config(self) -> dict[str, Any]:
        return {
            "referenceDate": REFERENCE_DATE,
            "cycle": {"min": CYCLE_MIN, "max": CYCLE_MAX},
            "weather": {"min": WEATHER_MIN, "max": WEATHER_MAX, "levels": WEATHER_LEVELS},
            "risk": {"min": RISK_MIN, "max": RISK_MAX, "levels": RISK_LEVELS},
            "currentRule": self._current_rule(),
        }

    def list_sections(self) -> list[dict[str, Any]]:
        return store.rows(SECTION_TABLE)

    def list_plans(self) -> list[dict[str, Any]]:
        return store.rows(PLAN_TABLE)

    # ---------- 生效阈值 ----------
    def _approved_plan(self, section: dict[str, Any]) -> dict[str, Any] | None:
        code = section.get("适用方案")
        if not code:
            return None
        for plan in store.rows(PLAN_TABLE):
            if plan.get("方案编号") == code and plan.get("方案状态") == "已批准":
                return plan
        return None

    def effective_threshold(
        self, section: dict[str, Any], *, cycle: int, weather: int, risk: int
    ) -> dict[str, Any]:
        """计算单路段生效阈值。

        专项段（有已批准方案）：周期、天气、风险全部取方案值，滑块无效；
        普通路段：基础周期 = min(滑块草案周期, 既有周期)，再扣天气/风险扣减，
        最低 1 天——普通路段只能比既有口径更严，不会被放松。
        """
        plan = self._approved_plan(section)
        if plan is not None:
            return {
                "路段编号": section["路段编号"],
                "路段名称": section["路段名称"],
                "适用来源": "批准方案",
                "方案编号": plan["方案编号"],
                "既有周期": section["既有巡查周期"],
                "基础周期": plan["巡查周期"],
                "天气等级": plan["天气等级"],
                "风险等级": plan["风险等级"],
                "天气扣减": 0,
                "风险扣减": 0,
                "生效周期": plan["巡查周期"],
                "滑块是否生效": False,
            }

        existing = int(section["既有巡查周期"])
        base = max(CYCLE_MIN, min(int(cycle), existing))
        weather = max(WEATHER_MIN, min(int(weather), WEATHER_MAX))
        risk = max(RISK_MIN, min(int(risk), RISK_MAX))
        w_penalty = WEATHER_PENALTY[weather]
        r_penalty = RISK_PENALTY[risk]
        effective = max(1, base - w_penalty - r_penalty)
        return {
            "路段编号": section["路段编号"],
            "路段名称": section["路段名称"],
            "适用来源": "既有周期",
            "方案编号": None,
            "既有周期": existing,
            "基础周期": base,
            "天气等级": weather,
            "风险等级": risk,
            "天气扣减": w_penalty,
            "风险扣减": r_penalty,
            "生效周期": effective,
            "滑块是否生效": True,
        }

    def _thresholds_map(self, *, cycle: int, weather: int, risk: int) -> dict[str, dict[str, Any]]:
        return {
            section["路段编号"]: self.effective_threshold(
                section, cycle=cycle, weather=weather, risk=risk
            )
            for section in store.rows(SECTION_TABLE)
        }

    # ---------- 预览：哪些巡查会转督办 ----------
    def preview(self, *, cycle: int, weather: int, risk: int, as_of: str | None) -> dict[str, Any]:
        ref = _ref_date(as_of)
        thresholds = self._thresholds_map(cycle=cycle, weather=weather, risk=risk)

        overdue_rows: list[dict[str, Any]] = []
        retained_rows: list[dict[str, Any]] = []
        future_rows = 0
        for patrol in store.rows(PATROL_TABLE):
            code = patrol.get("路段编号")
            if not code or code not in thresholds:
                continue  # 骨架自带的演示巡查不参与模拟器
            info = thresholds[code]
            planned = _parse(patrol["计划日期"])
            due = planned + timedelta(days=info["生效周期"])
            row_view = {
                "巡查id": patrol["id"],
                "巡查编号": patrol["巡查编号"],
                "路段编号": code,
                "路段名称": info["路段名称"],
                "计划日期": patrol["计划日期"],
                "巡查状态": patrol["status"],
                "记录性质": patrol.get("记录性质"),
                "生效周期": info["生效周期"],
                "适用来源": info["适用来源"],
                "方案编号": info["方案编号"],
                "应完成日期": due.isoformat(),
                "督办状态": patrol.get("督办状态", "无"),
            }
            if patrol["status"] not in OPEN_STATUSES or patrol.get("记录性质") == "历史留痕":
                # 旧巡查按原计划留痕：只展示，不纳入督办候选。
                row_view["留痕原因"] = (
                    "历史记录按原计划留痕" if patrol.get("记录性质") == "历史留痕" else "记录已结案"
                )
                retained_rows.append(row_view)
                continue
            if planned > ref:
                future_rows += 1
                continue
            overdue_days = (ref - due).days
            row_view["逾期天数"] = overdue_days
            if overdue_days > 0:
                overdue_rows.append(row_view)
            else:
                retained_rows.append({**row_view, "留痕原因": "未超过生效阈值，暂不督办"})

        overdue_rows.sort(key=lambda item: int(item["逾期天数"]), reverse=True)
        return {
            "asOf": ref.isoformat(),
            "inputs": {"cycle": cycle, "weather": weather, "risk": risk},
            "thresholds": list(thresholds.values()),
            "overdue": overdue_rows,
            "retained": retained_rows,
            "summary": {
                "将转督办": len(overdue_rows),
                "留痕或暂不督办": len(retained_rows),
                "未来在办": future_rows,
            },
        }

    # ---------- 模拟处置：落到待办、路面病害清单、车辆排班汇总 ----------
    def apply_simulation(
        self, *, cycle: int, weather: int, risk: int, as_of: str | None
    ) -> dict[str, Any]:
        """把预览出的逾期记录一次性模拟处置。

        处置结果落三张业务表：巡查待办（patrol_todo）、路面病害清单（pavement，
        新增待排查病害）、车辆排班汇总页（threshold_schedule 增加本月督办派车）。
        本月月历本身不被集中处理——新增的督办派车是独立行，不重排任何既有排班。
        """
        preview = self.preview(cycle=cycle, weather=weather, risk=risk, as_of=as_of)
        candidates = preview["overdue"]
        with store.transaction():
            created_todos: list[dict[str, Any]] = []
            skipped: list[dict[str, Any]] = []
            for item in candidates:
                patrol = store.find(PATROL_TABLE, int(item["巡查id"]))
                if patrol is None:
                    continue
                if patrol.get("督办状态") == "已督办":
                    skipped.append({"巡查编号": patrol["巡查编号"], "原因": "重复模拟，已在督办中"})
                    continue

                section = next(
                    s for s in store.rows(SECTION_TABLE) if s["路段编号"] == item["路段编号"]
                )
                batch_no = f"SIM-{patrol['巡查编号']}"
                patrol["督办状态"] = "已督办"
                patrol["abnormal"] = True
                patrol["督办批次"] = batch_no

                todo_id = store.next_id(TODO_TABLE, has_lock=False)
                todo = {
                    "id": todo_id,
                    "待办编号": f"DB-{todo_id:04d}",
                    "来源巡查": patrol["巡查编号"],
                    "路段编号": item["路段编号"],
                    "路段名称": item["路段名称"],
                    "逾期天数": item["逾期天数"],
                    "生效周期": item["生效周期"],
                    "适用来源": item["适用来源"],
                    "下发日期": preview["asOf"],
                    "待办类型": "逾期督办",
                    "状态": "待处置",
                    "pending": True,
                    "批次号": batch_no,
                }
                store.rows(TODO_TABLE).append(todo)
                created_todos.append(todo)

                defect_id = store.next_id(PAVEMENT_TABLE, has_lock=False)
                defect = {
                    "id": defect_id,
                    "status": "待修复",
                    "pending": True,
                    "abnormal": True,
                    "病害编号": f"PAVE-SIM-{defect_id:03d}",
                    "所属路段": item["路段名称"],
                    "病害类型": "逾期巡查待排查病害",
                    "严重程度": "高" if int(item["逾期天数"]) >= 5 else "中",
                    "起止桩号": item["路段编号"],
                    "面积": "待量测",
                    "发现日期": preview["asOf"],
                    "病害状态": "待修复",
                    "来源": "阈值模拟处置",
                    "批次号": batch_no,
                }
                store.rows(PAVEMENT_TABLE).append(defect)

                # 派车行是本月新增的督办加班班次，不改动本月既有月历；
                # patrol 已在前面做过「已督办」幂等拦截，这里不会重复插入。
                schedule_id = store.next_id(SCHEDULE_TABLE, has_lock=False)
                dispatch = {
                    "id": schedule_id,
                    "排班编号": f"PS-DSP-{schedule_id:02d}",
                    "排班日期": preview["asOf"],
                    "路段编号": item["路段编号"],
                    "路段名称": item["路段名称"],
                    "车辆编号": section["默认车辆"],
                    "驾驶员": DRIVERS.get(section["默认车辆"], "待派"),
                    "班次": "督办加班",
                    "周期天数": item["生效周期"],
                    "来源": "模拟处置派车",
                    "规则版本": None,
                    "重排状态": "督办派车",
                    "幂等键": batch_no,
                    "关联巡查": patrol["巡查编号"],
                }
                store.rows(SCHEDULE_TABLE).append(dispatch)

        return {
            "ok": True,
            "message": f"模拟处置完成：新增督办待办 {len(created_todos)} 条，跳过 {len(skipped)} 条",
            "asOf": preview["asOf"],
            "todosCreated": len(created_todos),
            "defectsCreated": len(created_todos),
            "dispatchesCreated": len(created_todos),
            "skipped": skipped,
            "todos": created_todos,
        }

    # ---------- 规则版本 ----------
    def _current_rule(self) -> dict[str, Any] | None:
        published = [r for r in store.rows(RULE_TABLE) if r.get("状态") == "生效中"]
        return published[-1] if published else None

    def _fingerprint(self, *, cycle: int, weather: int, risk: int) -> str:
        # 已批准方案是阈值口径的一部分：方案变更后旧指纹失效，允许再发布一次。
        plans = [
            {k: p[k] for k in ("方案编号", "巡查周期", "天气等级", "风险等级", "方案状态")}
            for p in store.rows(PLAN_TABLE)
        ]
        payload = json.dumps(
            {"cycle": cycle, "weather": weather, "risk": risk, "plans": plans},
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def publish_rule(
        self, *, cycle: int, weather: int, risk: int, base_version: int | None, operator: str
    ) -> dict[str, Any]:
        """发布阈值规则并启动集中重排批次。

        - 版本锁：已有批次在跑时拒绝并发发布；前端必须回传当前生效版本，
          期间被别人发布过（版本对不上）直接 409。
        - 重复发布：参数指纹与当前生效规则一致时只返回既有版本，不重排第二次。
        - 重排在事务内按工作项批次推进，游标持久化到 threshold_batch。
        """
        cycle = max(CYCLE_MIN, min(int(cycle), CYCLE_MAX))
        weather = max(WEATHER_MIN, min(int(weather), WEATHER_MAX))
        risk = max(RISK_MIN, min(int(risk), RISK_MAX))

        running = next(
            (b for b in store.rows(BATCH_TABLE) if b["状态"] in ("进行中", "待续算")), None
        )
        if running is not None:
            return {
                "ok": False,
                "conflict": "batch-running",
                "message": f"批次 {running['批次号']} 正在重排，请先续算完成后再发布",
                "batchId": running["id"],
            }

        with store.transaction():
            current = self._current_rule()
            if base_version is not None and current is not None and int(base_version) != int(current["版本号"]):
                return {
                    "ok": False,
                    "conflict": "version-stale",
                    "message": f"规则版本已过期（当前 v{current['版本号']}），请刷新后基于最新版本发布",
                    "currentVersion": current["版本号"],
                }
            fingerprint = self._fingerprint(cycle=cycle, weather=weather, risk=risk)
            if current is not None and current.get("指纹") == fingerprint:
                return {
                    "ok": True,
                    "idempotent": True,
                    "message": f"相同规则已发布（v{current['版本号']}），本次发布不重复生效",
                    "rule": current,
                    "batch": None,
                }

            work_items = self._build_work_items(cycle=cycle, weather=weather, risk=risk)
            # 版本锁检查、规则落库、批次建立与首批推进在同一事务：首批失败则整体回滚，
            # 不会留下「规则生效但没有批次/游标」的半成品状态。
            with store.transaction():
                version_no = store.next_id(RULE_TABLE, has_lock=False)
                rule = {
                    "id": version_no,
                    "版本号": version_no,
                    "参数": {"cycle": cycle, "weather": weather, "risk": risk},
                    "指纹": fingerprint,
                    "状态": "生效中",
                    "发布人": operator,
                    "发布时间": f"{REFERENCE_DATE}T09:00",
                }
                # 旧规则退位，保证任意时刻只有一条生效规则（版本锁）。
                for old in store.rows(RULE_TABLE):
                    if old.get("状态") == "生效中":
                        old["状态"] = "已归档"
                store.rows(RULE_TABLE).append(rule)

                batch_id = store.next_id(BATCH_TABLE, has_lock=False)
                batch_no = f"RB-v{version_no}-{uuid.uuid4().hex[:6]}"
                batch = {
                    "id": batch_id,
                    "批次号": batch_no,
                    "规则版本": version_no,
                    "指纹": fingerprint,
                    "状态": "进行中",
                    "游标": 0,
                    "总数": len(work_items),
                    "已处理": 0,
                    "工作项": work_items,
                    "创建时间": f"{REFERENCE_DATE}T09:00",
                }
                store.rows(BATCH_TABLE).append(batch)
                result = self._advance_batch(batch_id, join_transaction=True)
            return {"ok": True, "idempotent": False, "rule": rule, "batch": result}

    def _build_work_items(self, *, cycle: int, weather: int, risk: int) -> list[dict[str, Any]]:
        """汇总重排工作项：本月排班只保留不重排，未来排班回填。

        两类工作项：
        - retain：基准日当月的既有排班 -> 标记「本月保留」，不改日期/周期；
        - backfill：下月 1 号起 horizon 天内，按各路段生效周期生成的新排班，
          幂等键为 (路段, 日期)，重复续算不会重复插入。
        """
        ref = _parse(REFERENCE_DATE)
        thresholds = self._thresholds_map(cycle=cycle, weather=weather, risk=risk)
        items: list[dict[str, Any]] = []

        for sched in store.rows(SCHEDULE_TABLE):
            planned = _parse(sched["排班日期"])
            if sched["来源"] == "原计划" and planned.strftime("%Y-%m") == ref.strftime("%Y-%m"):
                items.append({"类型": "retain", "排班id": sched["id"]})

        horizon_start = date(ref.year + (ref.month // 12), (ref.month % 12) + 1, 1)
        for section in store.rows(SECTION_TABLE):
            info = thresholds[section["路段编号"]]
            step = int(info["生效周期"])
            day = horizon_start
            end = horizon_start + timedelta(days=BACKFILL_HORIZON_DAYS)
            while day < end:
                items.append({
                    "类型": "backfill",
                    "路段编号": section["路段编号"],
                    "日期": day.isoformat(),
                    "生效周期": step,
                    "幂等键": f"{section['路段编号']}@{day.isoformat()}",
                })
                day += timedelta(days=step)
        return items

    def resume_batch(self, batch_id: int) -> dict[str, Any]:
        """连接断开后重算：从批次游标继续，已完成工作项靠幂等键跳过。"""
        batch = store.find(BATCH_TABLE, batch_id)
        if batch is None:
            return {"ok": False, "message": f"批次 {batch_id} 不存在"}
        if batch["状态"] == "已完成":
            return {"ok": True, "finished": True, "batch": self._batch_view(batch)}
        return self._advance_batch(batch_id)

    def _advance_batch(self, batch_id: int, *, join_transaction: bool = False) -> dict[str, Any]:
        def _work() -> dict[str, Any]:
            batch = store.find(BATCH_TABLE, batch_id)
            if batch is None:
                return {"ok": False, "message": f"批次 {batch_id} 不存在"}
            items: list[dict[str, Any]] = batch["工作项"]
            cursor = int(batch["游标"])
            end = min(cursor + BATCH_CHUNK, len(items))
            affected_keys: set[str] = set()
            for idx in range(cursor, end):
                self._apply_work_item(items[idx], int(batch["规则版本"]), batch["批次号"], affected_keys)
            batch["游标"] = end
            batch["已处理"] = end
            batch["状态"] = "已完成" if end >= len(items) else "待续算"
            return {"ok": True, "finished": end >= len(items), "batch": self._batch_view(batch)}

        # 发布首块已在外层事务里（要和规则落库同生共死）；断线续算自己开事务。
        if join_transaction:
            return _work()
        with store.transaction():
            return _work()

    def _apply_work_item(
        self, item: dict[str, Any], version: int, batch_no: str, affected_keys: set[str]
    ) -> None:
        if item["类型"] == "retain":
            sched = store.find(SCHEDULE_TABLE, int(item["排班id"]))
            if sched is not None and sched["重排状态"] == "待重排":
                sched["重排状态"] = "本月保留"
            return

        key = item["幂等键"]
        ref = _parse(REFERENCE_DATE)
        horizon_start = date(ref.year + (ref.month // 12), (ref.month % 12) + 1, 1)
        # 幂等：续算时同一（路段, 日期）已有回填行就跳过，重复发布只生效一次。
        for sched in store.rows(SCHEDULE_TABLE):
            if sched.get("幂等键") == key and sched["来源"] == "规则回填":
                affected_keys.add(key)
                return
        for sched in store.rows(SCHEDULE_TABLE):
            if (
                sched["来源"] == "原计划"
                and sched["重排状态"] == "待重排"
                and sched["路段编号"] == item["路段编号"]
                and _parse(sched["排班日期"]) >= horizon_start
            ):
                sched["重排状态"] = "已重排"
                sched["规则版本"] = version
                sched["周期天数"] = item["生效周期"]

        section = next(s for s in store.rows(SECTION_TABLE) if s["路段编号"] == item["路段编号"])
        new_id = store.next_id(SCHEDULE_TABLE, has_lock=False)
        store.rows(SCHEDULE_TABLE).append({
            "id": new_id,
            "排班编号": f"PS-RB-v{version}-{new_id:02d}",
            "排班日期": item["日期"],
            "路段编号": item["路段编号"],
            "路段名称": section["路段名称"],
            "车辆编号": section["默认车辆"],
            "驾驶员": DRIVERS.get(section["默认车辆"], "待派"),
            "班次": "日班",
            "周期天数": item["生效周期"],
            "来源": "规则回填",
            "规则版本": version,
            "重排状态": "回填",
            "幂等键": key,
            "关联巡查": None,
            "_批次": batch_no,
        })
        affected_keys.add(key)

    def _batch_view(self, batch: dict[str, Any]) -> dict[str, Any]:
        view = {k: v for k, v in batch.items() if k != "工作项"}
        view["剩余"] = batch["总数"] - batch["已处理"]
        return view

    def list_batches(self) -> list[dict[str, Any]]:
        return [self._batch_view(b) for b in store.rows(BATCH_TABLE)]

    # ---------- 方案批复 ----------
    def approve_plan(self, plan_id: int) -> dict[str, Any]:
        plan = store.find(PLAN_TABLE, plan_id)
        if plan is None:
            return {"ok": False, "message": f"方案 {plan_id} 不存在"}
        if plan["方案状态"] == "已批准":
            return {"ok": True, "idempotent": True, "message": "方案已处于已批准状态", "plan": plan}
        with store.transaction():
            plan["方案状态"] = "已批准"
            plan["批准日期"] = REFERENCE_DATE
            section = next(
                (s for s in store.rows(SECTION_TABLE) if s["路段编号"] == plan["路段编号"]), None
            )
            if section is not None:
                section["适用方案"] = plan["方案编号"]
        return {"ok": True, "message": f"方案 {plan['方案编号']} 已批准，专项阈值即刻以方案为准", "plan": plan}

    # ---------- 落库结果：待办、病害、排班汇总 ----------
    def landing_stats(self) -> dict[str, Any]:
        todos = store.rows(TODO_TABLE)
        defects = [d for d in store.rows(PAVEMENT_TABLE) if d.get("来源") == "阈值模拟处置"]
        schedules = store.rows(SCHEDULE_TABLE)
        return {
            "patrolTodoCount": len(todos),
            "patrolTodoPending": sum(1 for t in todos if t.get("pending")),
            "defectCount": len(defects),
            "dispatchCount": sum(1 for s in schedules if s.get("来源") == "模拟处置派车"),
            "backfillCount": sum(1 for s in schedules if s.get("来源") == "规则回填"),
            "retainedCount": sum(1 for s in schedules if s.get("重排状态") == "本月保留"),
        }

    def list_todos(self, status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(TODO_TABLE)
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        return rows

    def vehicle_schedule_summary(self) -> dict[str, Any]:
        """车辆排班汇总页：按车辆聚合原计划、本月保留、督办派车、规则回填的班次数。"""
        vehicles: dict[str, dict[str, Any]] = {}
        for sched in store.rows(SCHEDULE_TABLE):
            code = sched["车辆编号"]
            bucket = vehicles.setdefault(code, {
                "车辆编号": code,
                "驾驶员": sched.get("驾驶员") or "待派",
                "原计划": 0,
                "本月保留": 0,
                "督办派车": 0,
                "规则回填": 0,
                "已重排": 0,
                "班次明细": [],
            })
            source = sched["来源"]
            if source == "原计划":
                bucket["原计划"] += 1
                if sched.get("重排状态") == "本月保留":
                    bucket["本月保留"] += 1
                if sched.get("重排状态") == "已重排":
                    bucket["已重排"] += 1
            else:
                bucket_key = "督办派车" if source == "模拟处置派车" else source
                bucket[bucket_key] += 1
            bucket["班次明细"].append({
                "排班编号": sched["排班编号"],
                "排班日期": sched["排班日期"],
                "路段": sched["路段名称"],
                "来源": source,
                "状态": sched.get("重排状态"),
            })
        rows = sorted(vehicles.values(), key=lambda item: item["车辆编号"])
        return {"asOf": REFERENCE_DATE, "vehicles": rows}


threshold_service = ThresholdService()
