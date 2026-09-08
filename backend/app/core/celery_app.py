from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.ping", "app.workers.transcribe", "app.workers.translate"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
