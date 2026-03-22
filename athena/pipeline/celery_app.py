from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "athena",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

# Celery config: enable dead-letter queue via task_routes
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        'athena.pipeline.summarisation_tasks.summarise_item_worker': {'queue': 'summary_standard'},
        'athena.pipeline.summarisation_tasks.label_cluster_worker': {'queue': 'summary_cluster'},
        'athena.pipeline.summarisation_tasks.generate_trending_brief_worker': {'queue': 'summary_trend'}
    }
)
