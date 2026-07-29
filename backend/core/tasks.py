"""
内存任务池：跟踪入库任务的执行状态。

设计说明：
- 毕设单机部署场景，不引入 Celery/Redis
- 任务状态存内存 + JSON 文件持久化，进程重启后自动恢复历史
- 同时只允许一个入库任务运行（_running_lock 互斥）
"""
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 持久化文件路径（与 app.db 同目录）
_TASKS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tasks_history.json")


# 任务状态枚举
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 流水线步骤名（convert 仅对 .log 等非 CSV 文件生效，CSV 文件会标记为 skipped）
STEPS = ["convert", "parse", "clean", "import", "vectorize"]


@dataclass
class StepProgress:
    """单步骤进度"""
    status: str = "pending"  # pending / running / done / failed / skipped
    detail: Dict = field(default_factory=dict)  # 各步骤自定义字段
    duration_sec: Optional[float] = None


@dataclass
class TaskState:
    """任务整体状态"""
    task_id: str
    task_type: str  # generate / upload
    status: str = STATUS_PENDING
    current_step: Optional[str] = None
    steps: Dict[str, StepProgress] = field(default_factory=dict)
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    # 关联文件（上传文件路径 / 失败日志路径等）
    artifacts: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转成可 JSON 序列化的字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "current_step": self.current_step,
            "steps": {
                name: {
                    "status": sp.status,
                    "detail": sp.detail,
                    "duration_sec": sp.duration_sec,
                }
                for name, sp in self.steps.items()
            },
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "artifacts": self.artifacts,
        }


class InMemoryTaskStore:
    """线程安全的内存任务池（带 JSON 文件持久化）"""

    def __init__(self, max_history: int = 50):
        self._tasks: Dict[str, TaskState] = {}
        self._lock = threading.Lock()
        self._max_history = max_history
        # 同时只允许一个入库任务运行
        self._running_lock = threading.Lock()
        self._running_task_id: Optional[str] = None
        # 取消请求集合（协作式取消）
        self._cancel_requested: set = set()
        # 启动时从文件恢复历史
        self._load()

    # ---------- 持久化 ----------

    def _save(self):
        """将当前任务列表写入 JSON 文件（调用方需持有 _lock）"""
        try:
            data = [t.to_dict() for t in self._tasks.values()]
            with open(_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"任务历史持久化写入失败: {e}")

    def _load(self):
        """从 JSON 文件恢复任务历史"""
        if not os.path.exists(_TASKS_FILE):
            return
        try:
            with open(_TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                steps = {}
                for name, sp_data in (item.get("steps") or {}).items():
                    steps[name] = StepProgress(
                        status=sp_data.get("status", "pending"),
                        detail=sp_data.get("detail", {}),
                        duration_sec=sp_data.get("duration_sec"),
                    )
                task = TaskState(
                    task_id=item["task_id"],
                    task_type=item.get("task_type", "generate"),
                    status=item.get("status", "done"),
                    current_step=item.get("current_step"),
                    steps=steps,
                    started_at=item.get("started_at"),
                    updated_at=item.get("updated_at"),
                    finished_at=item.get("finished_at"),
                    error=item.get("error"),
                    artifacts=item.get("artifacts", {}),
                )
                # 进程重启后，之前 running/pending 的任务标记为 failed
                if task.status in (STATUS_RUNNING, STATUS_PENDING):
                    task.status = STATUS_FAILED
                    task.error = "服务重启，任务中断"
                    task.finished_at = datetime.now().isoformat(timespec="seconds")
                self._tasks[task.task_id] = task
            logger.info(f"从文件恢复 {len(self._tasks)} 条任务历史")
        except Exception as e:
            logger.warning(f"任务历史恢复失败: {e}")

    # ---------- 任务生命周期 ----------

    def create(self, task_id: str, task_type: str) -> TaskState:
        """创建新任务（不启动）"""
        with self._lock:
            task = TaskState(
                task_id=task_id,
                task_type=task_type,
                status=STATUS_PENDING,
                started_at=datetime.now().isoformat(timespec="seconds"),
                updated_at=datetime.now().isoformat(timespec="seconds"),
                steps={name: StepProgress() for name in STEPS},
            )
            self._tasks[task_id] = task
            self._evict_if_needed()
            self._save()
            return task

    def try_start(self, task_id: str) -> bool:
        """
        尝试占用运行锁。成功返回 True，已有任务在跑返回 False。
        """
        with self._lock:
            if self._running_task_id is not None and self._running_task_id != task_id:
                return False
            self._running_task_id = task_id
            task = self._tasks.get(task_id)
            if task:
                task.status = STATUS_RUNNING
                task.updated_at = datetime.now().isoformat(timespec="seconds")
            self._save()
            return True

    def update(self, task_id: str, **fields):
        """更新任务顶层字段"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            for k, v in fields.items():
                if hasattr(task, k):
                    setattr(task, k, v)
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            self._save()

    def update_step(self, task_id: str, step_name: str,
                    status: Optional[str] = None,
                    detail: Optional[Dict] = None,
                    duration_sec: Optional[float] = None,
                    merge_detail: bool = True):
        """更新某步骤的进度"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            sp = task.steps.get(step_name)
            if not sp:
                sp = StepProgress()
                task.steps[step_name] = sp
            if status is not None:
                sp.status = status
            if detail is not None:
                if merge_detail:
                    sp.detail.update(detail)
                else:
                    sp.detail = detail
            if duration_sec is not None:
                sp.duration_sec = duration_sec
            if status in ("running", "done", "failed") and task.current_step != step_name:
                task.current_step = step_name
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            self._save()

    def finish(self, task_id: str, success: bool, error: Optional[str] = None):
        """结束任务（成功或失败）"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = STATUS_DONE if success else STATUS_FAILED
            task.error = error
            task.finished_at = datetime.now().isoformat(timespec="seconds")
            task.updated_at = task.finished_at
            if self._running_task_id == task_id:
                self._running_task_id = None
            self._save()

    # ---------- 取消 ----------

    def request_cancel(self, task_id: str) -> bool:
        """请求取消任务（协作式：流水线循环检测后自行退出）"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.status not in (STATUS_RUNNING, STATUS_PENDING):
                return False
            self._cancel_requested.add(task_id)
            return True

    def is_cancel_requested(self, task_id: str) -> bool:
        """流水线内部调用：检测是否收到取消请求"""
        return task_id in self._cancel_requested

    def clear_cancel(self, task_id: str):
        """任务结束后清理取消标记"""
        self._cancel_requested.discard(task_id)

    # ---------- 查询 ----------

    def get(self, task_id: str) -> Optional[TaskState]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_recent(self, limit: int = 20) -> List[TaskState]:
        with self._lock:
            # 按开始时间倒序
            items = sorted(
                self._tasks.values(),
                key=lambda t: t.started_at or "",
                reverse=True,
            )
            return items[:limit]

    def is_busy(self) -> bool:
        """是否已有任务在运行"""
        with self._lock:
            return self._running_task_id is not None

    def running_task_id(self) -> Optional[str]:
        with self._lock:
            return self._running_task_id

    # ---------- 内部 ----------

    def _evict_if_needed(self):
        """超过 max_history 时淘汰最旧的任务（仅淘汰已完成/失败的）"""
        if len(self._tasks) <= self._max_history:
            return
        candidates = [
            t for t in self._tasks.values()
            if t.status in (STATUS_DONE, STATUS_FAILED)
        ]
        candidates.sort(key=lambda t: t.finished_at or "")
        excess = len(self._tasks) - self._max_history
        for t in candidates[:excess]:
            self._tasks.pop(t.task_id, None)
        # 注意：_evict_if_needed 仅在 create() 内调用，create() 末尾已统一 _save()


# 全局单例
task_store = InMemoryTaskStore()
