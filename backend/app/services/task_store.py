"""
Task store for background job status tracking.
Simple in-memory storage (use Redis for production).
"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import threading

_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def create_task(task_id: str) -> None:
    """Create a new task entry"""
    with _lock:
        _tasks[task_id] = {
            "status": "pending",
            "progress": 0,
            "message": "Starting...",
            "result": None,
            "created_at": datetime.utcnow().isoformat()
        }


def update_task(task_id: str, **kwargs) -> None:
    """Update task status"""
    with _lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Get task status"""
    with _lock:
        return _tasks.get(task_id)


def cleanup_old_tasks(max_age_minutes: int = 30) -> int:
    """Remove tasks older than max_age_minutes"""
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    removed = 0
    with _lock:
        to_remove = []
        for task_id, task in _tasks.items():
            created = datetime.fromisoformat(task["created_at"])
            if created < cutoff:
                to_remove.append(task_id)
        for task_id in to_remove:
            del _tasks[task_id]
            removed += 1
    return removed
