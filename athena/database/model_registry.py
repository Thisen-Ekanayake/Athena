"""
Reads and writes for the model registry (athena.model_server): registered models and their measured speeds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from athena.core.models import LlmBenchmark, LlmModel

# A running average over this many turns, so the number follows a driver update but one odd turn barely moves it
SPEED_WINDOW = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def all_models(session: Session) -> list[LlmModel]:
    return list(session.execute(select(LlmModel).order_by(LlmModel.role, LlmModel.name)).scalars())


def get_model(session: Session, model_id: UUID) -> LlmModel | None:
    return session.get(LlmModel, model_id)


def by_name(session: Session, name: str) -> LlmModel | None:
    return session.execute(select(LlmModel).where(LlmModel.name == name)).scalar_one_or_none()


def add_model(session: Session, **fields) -> LlmModel:
    m = LlmModel(**fields, created_at=_now(), updated_at=_now())
    session.add(m)
    session.commit()
    return m


def update_model(session: Session, m: LlmModel, **fields) -> LlmModel:
    for key, value in fields.items():
        setattr(m, key, value)
    m.updated_at = _now()
    session.commit()
    return m


def remove_model(session: Session, m: LlmModel) -> None:
    session.execute(delete(LlmBenchmark).where(LlmBenchmark.model_id == m.id))
    session.delete(m)
    session.commit()


def benchmarks(session: Session, model_ids: list[UUID] | None = None) -> list[LlmBenchmark]:
    q = select(LlmBenchmark)
    if model_ids is not None:
        q = q.where(LlmBenchmark.model_id.in_(model_ids))
    return list(session.execute(q).scalars())


def record_speed(session: Session, model: LlmModel, device: str, context: int, *, gen_tps: float | None = None,
                 prompt_tps: float | None = None, load_seconds: float | None = None, gpu_layers: int | None = None,
                 source: str = "chats", replace: bool = False) -> LlmBenchmark:
    """Fold one measurement into the row for (model, file, device, context). ``replace`` (a benchmark run) starts
    the row again; chat turns are averaged into it."""
    row = session.execute(select(LlmBenchmark).where(
        LlmBenchmark.model_id == model.id, LlmBenchmark.fingerprint == model.fingerprint,
        LlmBenchmark.device == device, LlmBenchmark.context == context)).scalar_one_or_none()
    if row is None:
        row = LlmBenchmark(model_id=model.id, fingerprint=model.fingerprint, device=device, context=context,
                           samples=0, source=source)
        session.add(row)
    if replace:
        row.gen_tps, row.prompt_tps, row.samples, row.source = None, None, 0, source
    weight = 1 / min(row.samples + 1, SPEED_WINDOW)

    def blend(old: float | None, new: float | None) -> float | None:
        if new is None or new <= 0:
            return old
        return new if old is None else old + (new - old) * weight

    if gen_tps is not None or prompt_tps is not None:
        row.gen_tps = blend(row.gen_tps, gen_tps)
        row.prompt_tps = blend(row.prompt_tps, prompt_tps)
        row.samples = (row.samples or 0) + 1
    if load_seconds is not None and load_seconds > 0:
        row.load_seconds = load_seconds if row.load_seconds is None else row.load_seconds * 0.7 + load_seconds * 0.3
    if gpu_layers is not None:
        row.gpu_layers = gpu_layers
    row.updated_at = _now()
    session.commit()
    return row
