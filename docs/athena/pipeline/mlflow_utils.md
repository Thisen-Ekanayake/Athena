# Documentation for `athena/pipeline/mlflow_utils.py`

## Overview
Shared MLflow helpers.

MLflow is observability only — a tracking-server outage must never block the
data pipeline. These helpers make MLflow best-effort: tracking is used when the
server is reachable and silently skipped otherwise. Used by `clustering.py` and
`scoring.py`.

On import it sets `MLFLOW_HTTP_REQUEST_MAX_RETRIES=0` /
`MLFLOW_HTTP_REQUEST_TIMEOUT=3` so an unreachable tracking server fails in ~0.1s
instead of stalling for minutes on the default retry backoff.

## Functions
### `mlflow_run`
Context manager wrapping `set_experiment` + `start_run`. Degrades to a no-op
(logs a warning) if the tracking server is unreachable. Yields True when
tracking is active, False otherwise.

### `ml_log`
Call an `mlflow.log_*` / `set_tag` function, swallowing any failure so logging
never raises into the pipeline.
