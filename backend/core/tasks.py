"""
内存任务池：跟踪入库任务的执行状态。

设计说明：
- 毕设单机部署场景，不引入 Celery/Redis
- 任务状态存内存，进程重启后丢失（可接受，入库任务频率低）
- 同时只允许一个入库任务运行（_running_lock 互斥）
"""
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


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
    """线程安全的内存任务池"""

    def __init__(self, max_history: int = 50):
        self._tasks: Dict[str, TaskState] = {}
        self._lock = threading.Lock()
        self._max_history = max_history
        # 同时只允许一个入库任务运行
        self._running_lock = threading.Lock()
        self._running_task_id: Optional[str] = None

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


# 全局单例
task_store = InMemoryTaskStore()
