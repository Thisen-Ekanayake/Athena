"""
Qdrant collection ``paper_chunks``: Tier 2 section chunks, embedded by Qwen3-Embedding-8B.

Derived from PostgreSQL (``evo_chunks``), so it can be dropped and rebuilt.
Vectors are the first 1024 of the model's 4096 dimensions, renormalised
(Phase 0: no recall loss), stored with int8 scalar quantization. Each point
carries ``paper_id``, ``topic_ids``, ``year`` and ``section_type`` as payload
so searches can filter, e.g. limitation chunks from before 2018. Athena's
``athena_content`` collection is not touched.
"""
from __future__ import annotations

import os
from uuid import UUID

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

COLLECTION = "paper_chunks"
DIM = 1024


def client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


def ensure_collection(qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    if qdrant.collection_exists(COLLECTION):
        return
    qdrant.create_collection(
        COLLECTION,
        vectors_config=qm.VectorParams(size=DIM, distance=qm.Distance.COSINE, on_disk=True),
        quantization_config=qm.ScalarQuantization(
            scalar=qm.ScalarQuantizationConfig(type=qm.ScalarType.INT8, always_ram=True)),
    )
    for field, schema in [("paper_id", qm.PayloadSchemaType.KEYWORD), ("topic_ids", qm.PayloadSchemaType.KEYWORD),
                          ("section_type", qm.PayloadSchemaType.KEYWORD), ("year", qm.PayloadSchemaType.INTEGER)]:
        qdrant.create_payload_index(COLLECTION, field, field_schema=schema)


def truncate(vectors: np.ndarray, dim: int = DIM) -> np.ndarray:
    """Keep the first ``dim`` dimensions (Qwen3-Embedding is trained for this) and renormalise."""
    cut = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(cut, axis=1, keepdims=True)
    return cut / np.where(norms == 0, 1, norms)


def upsert(points: list[tuple[UUID, np.ndarray, dict]], qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    qdrant.upsert(COLLECTION, points=[qm.PointStruct(id=str(pid), vector=vec.tolist(), payload=payload)
                                      for pid, vec, payload in points])


def delete_points(ids: list[UUID], qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    if ids and qdrant.collection_exists(COLLECTION):
        qdrant.delete(COLLECTION, points_selector=qm.PointIdsList(points=[str(i) for i in ids]))
