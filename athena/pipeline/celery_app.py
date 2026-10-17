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
        # Topic builds run on their own single-concurrency worker (run_native.sh starts it).
        'athena.evolution.tasks.build_topic': {'queue': 'evolution'},
        'athena.evolution.tasks.build_search_topic': {'queue': 'evolution'},
        'athena.evolution.tasks.refine_proposal': {'queue': 'evolution'},
        'athena.evolution.tasks.process_full_text': {'queue': 'evolution'},
        'athena.evolution.tasks.run_gpu_lane': {'queue': 'evolution'},
        # Map refreshes (athena.evolution.refresh): every step but the method-name fetch needs the evolution worker.
        'athena.evolution.tasks.refresh_build': {'queue': 'evolution'},
        'athena.evolution.tasks.refresh_full_text': {'queue': 'evolution'},
        'athena.evolution.tasks.refresh_gpu_lane': {'queue': 'evolution'},
        'athena.evolution.tasks.snapshot_topic': {'queue': 'evolution'},
    }
)
