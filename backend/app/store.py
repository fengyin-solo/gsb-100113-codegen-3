"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
表级事务用「快照 + 回滚」模拟：集中处理重排一个批次内的写入要么全部生效，
要么抛出异常后整批回到事务前的状态。
"""
from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.seed import SEED_ROWS
from app.threshold_seed import SIMULATOR_TABLES, build_patrol_rows


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 逾期阈值模拟器的专用表；模拟巡查记录并入既有 patrol 表。
        for name, rows in SIMULATOR_TABLES.items():
            self._tables[name] = [dict(row) for row in rows]
        patrol_rows = self._tables.setdefault("patrol", [])
        for row in build_patrol_rows():
            new_row = {"id": self.next_id("patrol", has_lock=False)}
            new_row.update(row)
            patrol_rows.append(new_row)
        # 集中处理（发布重排 / 模拟处置）的全局事务锁，串行化所有写批次。
        self._tx_lock = threading.RLock()

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str, *, has_lock: bool = True) -> int:
        """分配表内自增主键；已在事务锁内时用 has_lock=False 避免重入死锁。"""
        def _value() -> int:
            return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

        if has_lock:
            with self._tx_lock:
                return _value()
        return _value()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """表级事务：正常退出提交快照，异常时把涉及的表整体回滚。

        内存库没有真正的 MVCC，这里以「深拷贝全部表 + RLock」等价实现：
        版本锁检查、批次游标推进、回填写行必须落在同一事务里，保证中途
        异常（含连接中断重算）不会留下半截重排结果。
        """
        with self._tx_lock:
            snapshot = copy.deepcopy(self._tables)
            try:
                yield
            except Exception:
                self._tables = snapshot
                raise

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
