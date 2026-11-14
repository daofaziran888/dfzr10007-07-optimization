"""拖拽可视化业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.schemas import PublishBatchResult, PublishReceipt
from app.store import store

MODULE = "vizdrag"
REQUIRED_FIELDS = ["方案编号", "方案名称", "数据源绑定"]
STATUS_ORDER = ["草稿", "已发布", "已嵌入", "已归档"]
ACTION_RULES = {"发布方案": "草稿", "嵌入看板": "已发布", "归档方案": "已嵌入"}
NEGATIVE_ACTIONS = []

QUEUE_MODULE = "vizqueue"
QUEUE_STATUSES = ["待发布", "发布中", "已完成", "失败"]
INCOMPLETE_STATUSES = ("待发布", "发布中", "失败")
# 发布校验顺序：数据源绑定、纵轴、分组；纵轴缺失对应 error=AXIS_MISSING
PUBLISH_CHECKS = [
    ("数据源绑定", "DATASOURCE_MISSING", "缺少数据源绑定"),
    ("纵轴字段", "AXIS_MISSING", "缺少纵轴字段"),
    ("分组字段", "GROUP_MISSING", "缺少分组字段"),
]


class VizdragService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"可视化方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于拖拽可视化可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"可视化方案已{action}"

    # ---------- 发布队列：可恢复、可重试、异常项不进导出 ----------

    def list_queue(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(QUEUE_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def publish_schemes(self, *, codes: list[str] | None = None) -> PublishBatchResult:
        """连续发布：逐项出回执；指定方案时按给定顺序处理，否则只处理未完成项。"""
        if codes:
            receipts: list[PublishReceipt] = []
            for code in codes:
                item = self._find_queue_item(str(code))
                if item is None:
                    receipts.append(PublishReceipt(
                        方案编号=str(code),
                        ok=False,
                        status="失败",
                        error="NOT_FOUND",
                        失败原因="方案不在发布队列",
                        message=f"{code} 不在发布队列，无法发布",
                    ))
                else:
                    receipts.append(self._publish_one(item))
            return self._batch_result(receipts)
        items = [row for row in store.rows(QUEUE_MODULE) if row.get("status") in INCOMPLETE_STATUSES]
        if not items:
            return PublishBatchResult(ok=True, message="暂无可发布方案", receipts=[])
        return self._batch_result([self._publish_one(item) for item in items])

    def retry_incomplete(self) -> PublishBatchResult:
        """断线恢复：只重试未完成项，已完成项保留首次发布结果不动。"""
        items = [row for row in store.rows(QUEUE_MODULE) if row.get("status") in INCOMPLETE_STATUSES]
        if not items:
            return PublishBatchResult(ok=True, message="没有待重试的未完成项", receipts=[])
        return self._batch_result([self._publish_one(item) for item in items])

    def export_files(self) -> dict[str, Any]:
        """发布结果导出文件：只含已完成项；异常项留在队列，不进入导出。"""
        queue = store.rows(QUEUE_MODULE)
        items = [row for row in queue if row.get("进入导出")]
        excluded = [
            {
                "方案编号": row.get("方案编号"),
                "error": row.get("error"),
                "失败原因": row.get("失败原因") or "尚未发布",
            }
            for row in queue
            if not row.get("进入导出")
        ]
        return {"module": "vizdrag-publish", "total": len(items), "items": items, "excluded": excluded}

    def _publish_one(self, item: dict[str, Any]) -> PublishReceipt:
        code = str(item.get("方案编号") or "")
        first = item.get("首次发布结果")
        if item.get("status") == "已完成" and first:
            # 幂等：同一方案再次触发时沿用首次发布结果，不重复生成文件
            reused = dict(first)
            reused["复用首次结果"] = True
            reused["message"] = f"{code} 已发布过，沿用首次发布结果（文件版本 {first.get('文件版本')}）"
            return PublishReceipt(**reused)
        entry = self._find_scheme(code)
        if entry is None:
            return self._fail(item, "NOT_FOUND", "方案不存在或已归档")
        for field, error, reason in PUBLISH_CHECKS:
            if not str(entry.get(field) or "").strip():
                return self._fail(item, error, f"{reason}，无法完成发布校验")
        version = self._next_version()
        file_name = f"exports/{code}-{version}.json"
        item["status"] = "已完成"
        item["error"] = None
        item["失败原因"] = None
        item["文件版本"] = version
        item["导出文件"] = file_name
        item["进入导出"] = True
        item["pending"] = False
        item["abnormal"] = False
        item["尝试次数"] = int(item.get("尝试次数") or 0) + 1
        entry["status"] = "已发布"
        entry["方案状态"] = "已发布"
        entry["pending"] = False
        entry["abnormal"] = False
        receipt = PublishReceipt(
            方案编号=code,
            ok=True,
            status="已完成",
            文件版本=version,
            导出文件=file_name,
            进入导出=True,
            message=f"{code} 发布成功，文件版本 {version}",
        )
        item["首次发布结果"] = receipt.model_dump()
        return receipt

    def _fail(self, item: dict[str, Any], error: str, reason: str) -> PublishReceipt:
        code = str(item.get("方案编号") or "")
        item["status"] = "失败"
        item["error"] = error
        item["失败原因"] = reason
        item["进入导出"] = False
        item["pending"] = True
        item["abnormal"] = True
        item["尝试次数"] = int(item.get("尝试次数") or 0) + 1
        entry = self._find_scheme(code)
        if entry is not None:
            entry["abnormal"] = True
        return PublishReceipt(
            方案编号=code,
            ok=False,
            status="失败",
            error=error,
            失败原因=reason,
            message=f"{code} 发布失败：{reason}（error={error}）",
        )

    @staticmethod
    def _find_queue_item(code: str) -> dict[str, Any] | None:
        for row in store.rows(QUEUE_MODULE):
            if str(row.get("方案编号", "")) == code:
                return row
        return None

    @staticmethod
    def _find_scheme(code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("方案编号", "")) == code:
                return row
        return None

    @staticmethod
    def _next_version() -> str:
        versions = []
        for row in store.rows(QUEUE_MODULE):
            tag = str(row.get("文件版本") or "")
            if tag.startswith("v") and tag[1:].isdigit():
                versions.append(int(tag[1:]))
        return f"v{max(versions, default=0) + 1}"

    @staticmethod
    def _batch_result(receipts: list[PublishReceipt]) -> PublishBatchResult:
        done = sum(1 for receipt in receipts if receipt.ok and not receipt.复用首次结果)
        reused = sum(1 for receipt in receipts if receipt.ok and receipt.复用首次结果)
        failed = sum(1 for receipt in receipts if not receipt.ok)
        return PublishBatchResult(
            ok=failed == 0,
            message=f"连续发布完成：成功 {done} 项，复用 {reused} 项，失败 {failed} 项",
            receipts=receipts,
            完成数=done,
            失败数=failed,
            复用数=reused,
        )
