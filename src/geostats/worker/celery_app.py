# Async queue: Celery app with Redis broker and result backend
from celery import Celery

from geostats.config import get_settings

celery_app = Celery(
    "geostats",
    broker=get_settings().redis_url,
    backend=get_settings().redis_url,
    include=["geostats.worker.tasks"],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_expires = 3600
