from app.core.celery_app import celery_app
from app.workers.ping import ping_task


def test_ping_task_is_registered_on_celery_app():
    assert "app.workers.ping.ping_task" in celery_app.tasks


def test_ping_task_runs_synchronously():
    result = ping_task.apply(args=["hello"])
    assert result.result == "pong: hello"
