from app.core.celery_app import celery_app


@celery_app.task(name="app.workers.ping.ping_task")
def ping_task(message: str) -> str:
    return f"pong: {message}"
