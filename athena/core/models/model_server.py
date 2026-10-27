"""
The model registry (Settings → Models and keys): GGUF files an admin registered, from which Athena writes the
llama-server router presets, and what each one measured on this machine (athena.model_server).
"""
from uuid import uuid4
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from athena.core.models.base import Base


class LlmModel(Base):
    """A model file the router serves under ``name`` (the name Athena sends), at each context in ``contexts``.

    ``info`` is what the GGUF header says (architecture, parameters, quantisation, layers, trained context);
    ``fingerprint`` (size and modification time) changes when the file does, which retires its benchmarks.
    ``placement`` is auto (llama.cpp fits the layers into free VRAM), gpu or cpu; ``plans`` keeps the memory
    llama-fit-params projected, from which each context's device is worked out.
    """
    __tablename__ = "llm_models"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False, unique=True)
    path = Column(String, nullable=False)
    mmproj_path = Column(String, nullable=True)       # a vision projector: the model takes images
    size_bytes = Column(BigInteger, nullable=False, default=0)
    mmproj_bytes = Column(BigInteger, nullable=True)
    fingerprint = Column(String, nullable=False, default="")
    info = Column(JSONB, nullable=False, default={})
    role = Column(String, nullable=False, default="chat")          # chat | embed
    reasoning = Column(Boolean, nullable=False, default=False)     # thinks: chats offer an effort
    tools = Column(Boolean, nullable=False, default=True)          # its template takes tool calls
    placement = Column(String, nullable=False, default="auto")     # auto | gpu | cpu
    contexts = Column(JSONB, nullable=False, default=[])           # the context sizes users may pick, smallest first
    default_context = Column(Integer, nullable=False, default=8192)
    options = Column(JSONB, nullable=False, default={})            # other preset keys (pooling, batch-size, ...)
    plans = Column(JSONB, nullable=False, default={})              # {fingerprint, points: [[ctx, full_mb, zero_mb]]}
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class LlmBenchmark(Base):
    """How fast a model ran at one context on one device: from the benchmark run when it was added, then kept
    current by real chat turns (a running average over ``samples``). ``device`` is the GPU's name, or cpu."""
    __tablename__ = "llm_benchmarks"
    __table_args__ = (UniqueConstraint("model_id", "fingerprint", "device", "context", name="uq_llm_benchmark"),)

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    model_id = Column(PG_UUID(as_uuid=True), ForeignKey("llm_models.id", ondelete="CASCADE"), nullable=False,
                      index=True)
    fingerprint = Column(String, nullable=False)
    device = Column(String, nullable=False)
    context = Column(Integer, nullable=False)
    gpu_layers = Column(Integer, nullable=True)
    gen_tps = Column(Float, nullable=True)          # answer tokens a second
    prompt_tps = Column(Float, nullable=True)       # prompt tokens read a second
    load_seconds = Column(Float, nullable=True)
    samples = Column(Integer, nullable=False, default=0)
    source = Column(String, nullable=False, default="benchmark")   # benchmark | chats
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
