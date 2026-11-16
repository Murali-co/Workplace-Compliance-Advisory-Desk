"""Celery application configuration."""

import worker.heartbeat  # noqa: F401 -- Register presence signals in the worker parent.
from app.core.config import settings
from celery import Celery

broker_url = settings.get_celery_broker_url()
backend_url = settings.get_celery_backend_url()

celery_app = Celery(
    "compliance_worker",
    broker=broker_url,
    backend=backend_url,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_default_queue="compliance_tasks",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
    task_publish_retry=False,
    beat_schedule={"outbox-reconcile": {"task": "worker.tasks.reconcile_outbox", "schedule": 15.0}},
    timezone="UTC",
    enable_utc=True,
)
