"""The once-a-minute runs that drain the embedding, scoring and enrichment queues."""
from unittest.mock import patch

from tests.fakes import FakeRedis


def test_a_minute_run_that_waited_too_long_is_dropped():
    """Runs that waited out a sync's backlog all ran at once, more of them than the database pool has connections."""
    from athena.pipeline import beat
    added = []

    class Sender:
        def add_periodic_task(self, schedule, sig, name=None, **options):
            added.append((schedule, sig.name, options))

    beat.setup_periodic_tasks(Sender())
    minute_runs = {task: options for schedule, task, options in added if schedule == 60.0}
    assert set(minute_runs) == {"athena.pipeline.embedding_worker.process_embedding_queue",
                                "athena.pipeline.scoring.process_scoring_queue",
                                "athena.pipeline.crawl.process_enrich_queue"}
    assert all(options == {"expires": beat.MINUTE_RUN_EXPIRES} for options in minute_runs.values())
    assert beat.MINUTE_RUN_EXPIRES < 60


def test_an_embedding_batch_that_cannot_start_goes_back_on_the_queue():
    from athena.pipeline import embedding_worker
    r = FakeRedis()
    r.rpush("athena:embedding_queue", b"a", b"b")
    with patch.object(embedding_worker, "init_qdrant"), patch.object(embedding_worker, "get_redis", return_value=r), \
            patch.object(embedding_worker, "process_batch", side_effect=TimeoutError("QueuePool limit reached")):
        embedding_worker.process_embedding_queue.run()
    assert r.lrange("athena:embedding_queue", 0, -1) == ["a", "b"]
