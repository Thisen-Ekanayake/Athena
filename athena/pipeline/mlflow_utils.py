"""
Shared MLflow helpers.

MLflow is observability only — a tracking-server outage must never block the
data pipeline. These helpers make MLflow best-effort: tracking is used when the
server is reachable and silently skipped otherwise.
"""
import os
from contextlib import contextmanager
from loguru import logger

# Fail fast when the tracking server is unreachable instead of stalling for
# minutes on the default retry backoff.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "3")


@contextmanager
def mlflow_run(experiment: str, run_name: str):
    """
    Best-effort MLflow run. If the tracking server is unreachable, this degrades
    to a no-op so the surrounding task still runs. Yields True when tracking is
    active, False otherwise.
    """
    import mlflow
    active = False
    try:
        mlflow.set_experiment(experiment)
        mlflow.start_run(run_name=run_name)
        active = True
    except Exception as e:
        logger.warning(f"MLflow tracking unavailable ({e}); continuing without it.")
    try:
        yield active
    finally:
        if active:
            try:
                mlflow.end_run()
            except Exception:
                pass


def ml_log(fn, *args, **kwargs):
    """Call an mlflow.log_* / set_tag function, swallowing any failure."""
    try:
        fn(*args, **kwargs)
    except Exception:
        pass
