"""The Celery app the API queues tasks on."""
import threading

from athena.pipeline.celery_app import celery_app


def test_shared_tasks_use_the_athena_app_from_any_thread():
    """Sync routes run in worker threads, where Celery's current app is its own default (amqp on :5672)."""
    from athena.pipeline.scoring import score_all_items
    from athena.pipeline.summarisation_tasks import summarise_item_worker

    seen = {}

    def look():
        seen["summary"] = summarise_item_worker.app
        seen["scoring"] = score_all_items.app

    thread = threading.Thread(target=look)
    thread.start()
    thread.join()
    assert seen == {"summary": celery_app, "scoring": celery_app}
