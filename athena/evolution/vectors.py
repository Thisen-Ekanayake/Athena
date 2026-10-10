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
GAP_COLLECTION = "gap_statements"   # Phase 3: one vector per gap statement, for themes and loose links
ABSTRACT_COLLECTION = "paper_abstracts"  # Tier 1: title and abstract of every topic paper, for topic search
DIM = 1024


def client() -> QdrantClient:
    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))


_PAYLOAD_INDEXES = {
    COLLECTION: [("paper_id", qm.PayloadSchemaType.KEYWORD), ("topic_ids", qm.PayloadSchemaType.KEYWORD),
                 ("section_type", qm.PayloadSchemaType.KEYWORD), ("year", qm.PayloadSchemaType.INTEGER)],
    GAP_COLLECTION: [("paper_id", qm.PayloadSchemaType.KEYWORD), ("origin", qm.PayloadSchemaType.KEYWORD),
                     ("year", qm.PayloadSchemaType.INTEGER)],
    ABSTRACT_COLLECTION: [("paper_id", qm.PayloadSchemaType.KEYWORD), ("year", qm.PayloadSchemaType.INTEGER)],
}


def ensure_collection(qdrant: QdrantClient | None = None, name: str = COLLECTION) -> None:
    qdrant = qdrant or client()
    if qdrant.collection_exists(name):
        return
    qdrant.create_collection(
        name,
        vectors_config=qm.VectorParams(size=DIM, distance=qm.Distance.COSINE, on_disk=True),
        quantization_config=qm.ScalarQuantization(
            scalar=qm.ScalarQuantizationConfig(type=qm.ScalarType.INT8, always_ram=True)),
    )
    for field, schema in _PAYLOAD_INDEXES[name]:
        qdrant.create_payload_index(name, field, field_schema=schema)


def truncate(vectors: np.ndarray, dim: int = DIM) -> np.ndarray:
    """Keep the first ``dim`` dimensions (Qwen3-Embedding is trained for this) and renormalise."""
    cut = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(cut, axis=1, keepdims=True)
    return cut / np.where(norms == 0, 1, norms)


def upsert(points: list[tuple[UUID, np.ndarray, dict]], qdrant: QdrantClient | None = None,
           name: str = COLLECTION) -> None:
    qdrant = qdrant or client()
    qdrant.upsert(name, points=[qm.PointStruct(id=str(pid), vector=vec.tolist(), payload=payload)
                                for pid, vec, payload in points])


def delete_points(ids: list[UUID], qdrant: QdrantClient | None = None) -> None:
    qdrant = qdrant or client()
    if ids and qdrant.collection_exists(COLLECTION):
        qdrant.delete(COLLECTION, points_selector=qm.PointIdsList(points=[str(i) for i in ids]))


def vectors_for(ids: list[UUID], name: str = GAP_COLLECTION,
                qdrant: QdrantClient | None = None) -> dict[UUID, np.ndarray]:
    qdrant = qdrant or client()
    out: dict[UUID, np.ndarray] = {}
    for start in range(0, len(ids), 256):
        for point in qdrant.retrieve(name, ids=[str(i) for i in ids[start:start + 256]], with_vectors=True):
            out[UUID(str(point.id))] = np.asarray(point.vector, dtype=np.float32)
    return out


def later_chunks(vector: np.ndarray, after_year: int | None, topics: list[str], exclude_papers: list[str],
                 section_types: list[str], limit: int, qdrant: QdrantClient | None = None) -> list:
    """Chunks of papers that appeared after ``after_year`` in the given topics, nearest first."""
    qdrant = qdrant or client()
    must = [qm.FieldCondition(key="section_type", match=qm.MatchAny(any=section_types)),
            qm.FieldCondition(key="topic_ids", match=qm.MatchAny(any=topics))]
    if after_year is not None:
        must.append(qm.FieldCondition(key="year", range=qm.Range(gt=after_year)))
    flt = qm.Filter(must=must, must_not=[qm.FieldCondition(key="paper_id", match=qm.MatchAny(any=exclude_papers))])
    return qdrant.query_points(COLLECTION, query=vector.tolist(), query_filter=flt, limit=limit,
                               with_payload=True).points
