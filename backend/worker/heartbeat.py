"""Short-lived worker presence for API readiness; no private inquiry data."""

import logging
from datetime import datetime, timezone

from app.core.config import settings
from celery.signals import heartbeat_sent, worker_ready
from redis import Redis

logger = logging.getLogger(__name__)
WORKER_HEARTBEAT_KEY = "compliance:worker:heartbeat"


@worker_ready.connect
@heartbeat_sent.connect
def record_worker_heartbeat(**kwargs):
    try:
        with Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1) as db:
            db.setex(WORKER_HEARTBEAT_KEY, 15, datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.warning("Worker heartbeat unavailable (%s)", type(exc).__name__)
