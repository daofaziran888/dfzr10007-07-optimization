"""拖拽可视化接口：维护可视化方案，覆盖发布方案、嵌入看板、归档方案等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, PublishBatchResult
from app.services.vizdrag import QUEUE_STATUSES, VizdragService

router = APIRouter(prefix="/api/vizdrag", tags=["拖拽可视化"])

service = VizdragService()

LIST_FIELDS = ["方案编号", "方案名称", "数据源绑定", "图表类型", "横轴字段", "纵轴字段", "分组字段", "方案状态"]
STATUSES = ["草稿", "已发布", "已嵌入", "已归档"]


@router.get("/publish-queue", response_model=PageResult[dict])
def list_publish_queue(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="待发布、发布中、已完成、失败"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """发布队列：每项都带失败原因与文件版本，断线恢复后从这里继续；没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if status and status not in QUEUE_STATUSES:
        raise HTTPException(status_code=400, detail=f"队列状态只能是：{'、'.join(QUEUE_STATUSES)}")
    items, total = service.list_queue(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/publish", response_model=PublishBatchResult)
def publish_schemes(payload: EntryPayload) -> PublishBatchResult:
    """连续发布：逐项给出回执；已发布过的方案沿用首次发布结果，不重复生成文件。"""
    codes = payload.values.get("方案编号")
    if isinstance(codes, str):
        codes = [code.strip() for code in codes.split(",") if code.strip()]
    if codes is not None and not isinstance(codes, list):
        raise HTTPException(status_code=400, detail="方案编号需要是字符串或字符串列表")
    return service.publish_schemes(codes=[str(code) for code in codes] if codes else None)


@router.post("/publish-queue/retry", response_model=PublishBatchResult)
def retry_publish_queue() -> PublishBatchResult:
    """断线恢复：只重试未完成项，已完成项保留首次发布结果。"""
    return service.retry_incomplete()


@router.get("/publish-queue/export")
def export_publish_files() -> dict[str, Any]:
    """发布结果导出文件：只含已完成项，异常项留在队列而不进入导出文件。"""
    return service.export_files()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号检索"),
    status: str | None = Query(default=None, description="草稿、已发布、已嵌入、已归档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号与状态过滤拖拽可视化列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条可视化方案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"可视化方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条可视化方案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="可视化方案已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条可视化方案执行发布方案、嵌入看板、归档方案；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出拖拽可视化清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "vizdrag", "total": total, "items": items}
