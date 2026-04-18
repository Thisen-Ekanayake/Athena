import os
import numpy as np
from typing import List
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import select, update
import umap
import mlflow
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from datetime import datetime
from uuid import UUID

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, Cluster, ItemLink, ClusterRunLog
from athena.pipeline.celery_app import celery_app

# Config
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "athena_content"
STABILITY_THRESHOLD = 0.85
# How many neighbour queries to send Qdrant in a single round-trip.
LINK_QUERY_BATCH = 64
# How many neighbours (including self) to ask for per item.
LINK_TOPK = 6


@celery_app.task
def run_clustering():
    """
    Main clustering job:
    1. Fetch all embeddings from Qdrant
    2. Reduce dimensionality with UMAP
    3. Group with HDBSCAN
    4. Label with TF-IDF
    5. Handle stability/re-assignment
    6. Persist results to DB
    """
    logger.info("Starting clustering run...")

    mlflow.set_experiment("athena-clustering")
    with mlflow.start_run(run_name="run_clustering"):
        mlflow.log_params({
            "umap_n_neighbors": 15,
            "umap_n_components": 50,
            "umap_metric": "cosine",
            "stability_threshold": STABILITY_THRESHOLD,
        })

        qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

        # 1. Fetch all points from Qdrant
        # For now, fetch ALL. In production, we might want to fetch only semi-recent ones.
        collections = [c.name for c in qdrant.get_collections().collections]
        if COLLECTION_NAME not in collections:
            logger.warning(f"Qdrant collection '{COLLECTION_NAME}' does not exist yet. Skipping clustering.")
            return

        offset = None
        all_points = []
        while True:
            points, next_offset = qdrant.scroll(
                collection_name=COLLECTION_NAME,
                limit=1000,
                with_vectors=True,
                offset=offset
            )
            all_points.extend(points)
            if not next_offset:
                break
            offset = next_offset

        if not all_points:
            logger.warning("No points found in Qdrant for clustering.")
            return

        vectors = np.array([p.vector for p in all_points])

        # 2. UMAP dimensionality reduction
        reducer = umap.UMAP(n_neighbors=15, n_components=50, metric='cosine', random_state=42)
        reduced_vectors = reducer.fit_transform(vectors)

        # 3. Topics Clustering (K-Means)
        num_items = len(all_points)
        k = max(5, min(20, num_items // 10))
        mlflow.log_param("kmeans_k", k)
        clusterer = KMeans(n_clusters=k, random_state=42, n_init='auto')
        cluster_labels = clusterer.fit_predict(reduced_vectors)

        unique_labels = set(cluster_labels)
        noise_count = list(cluster_labels).count(-1)

        mlflow.log_metrics({
            "total_items": len(all_points),
            "num_clusters": len(unique_labels),
            "noise_count": noise_count,
            "kmeans_inertia": float(clusterer.inertia_),
        })

        logger.info(f"Found {len(unique_labels)} topic clusters and {noise_count} noise points.")

        # 4. Process clusters (with run log)
        with SessionLocal() as session:
            run_log = ClusterRunLog(
                total_items=len(all_points),
                num_clusters=len(unique_labels),
                noise_items=list(cluster_labels).count(-1),
                umap_dims=50,
                hdbscan_min_cluster_size=5,
            )
            session.add(run_log)
            session.flush()
            try:
                stats = process_clusters(
                    all_points, cluster_labels, vectors, session
                )
                run_log.new_clusters = stats.get('new', 0)
                run_log.merged_clusters = stats.get('merged', 0)
                run_log.deactivated_clusters = stats.get('deactivated', 0)
                run_log.finished_at = datetime.utcnow()
                run_log.status = "success"
                session.commit()
                mlflow.log_metrics({
                    "new_clusters": stats.get('new', 0),
                    "merged_clusters": stats.get('merged', 0),
                    "deactivated_clusters": stats.get('deactivated', 0),
                })
            except Exception as e:
                run_log.finished_at = datetime.utcnow()
                run_log.status = "failed"
                run_log.error_message = str(e)[:500]
                session.commit()
                mlflow.set_tag("error", str(e)[:200])
                raise


def process_clusters(points, labels, raw_vectors, session):
    label_to_points = {}
    for i, label in enumerate(labels):
        if label == -1:
            continue
        if label not in label_to_points:
            label_to_points[label] = []
        label_to_points[label].append(i)

    # Fetch existing clusters for stability matching
    existing_clusters = session.execute(select(Cluster).where(Cluster.is_active .is_(True))).scalars().all()

    clusters_to_label = set()
    stats = {'new': 0, 'merged': 0, 'deactivated': 0}

    for label, point_indices in label_to_points.items():
        cluster_vectors = raw_vectors[point_indices]
        centroid = np.mean(cluster_vectors, axis=0)

        # Stability matching
        matched_cluster_id = None
        if existing_clusters:
            valid_clusters = [c for c in existing_clusters if c.centroid]
            similarities = [
                np.dot(centroid, np.array(c.centroid)) / (np.linalg.norm(centroid) * np.linalg.norm(c.centroid))
                for c in valid_clusters
            ]
            if similarities and max(similarities) >= STABILITY_THRESHOLD:
                max_idx = np.argmax(similarities)
                matched_cluster_id = valid_clusters[max_idx].id
                stats['merged'] += 1

        # Label with TF-IDF
        cluster_points = [points[i] for i in point_indices]
        cluster_titles = [p.payload.get("title", "") for p in cluster_points]
        cluster_label = generate_tfidf_label(cluster_titles)

        if matched_cluster_id:
            # Update existing
            session.execute(
                update(Cluster).where(Cluster.id == matched_cluster_id).values(
                    label=cluster_label,
                    centroid=centroid.tolist(),
                    updated_at=datetime.utcnow()
                )
            )
            cluster_id = matched_cluster_id
        else:
            # Create new
            new_cluster = Cluster(
                label=cluster_label,
                centroid=centroid.tolist(),
                is_active=True
            )
            session.add(new_cluster)
            session.flush()  # Get ID
            cluster_id = new_cluster.id
            stats['new'] += 1

        # Assign items to cluster with distance
        for idx in point_indices:
            item_uuid = points[idx].id
            item_vec = raw_vectors[idx]
            dist = float(np.linalg.norm(item_vec - centroid))
            session.execute(
                update(ContentItem)
                .where(ContentItem.id == item_uuid)
                .values(cluster_id=cluster_id, cluster_distance=dist)
            )

        clusters_to_label.add(cluster_id)

    session.commit()
    logger.info("Clustering results persisted to database.")

    import athena.pipeline.summarisation_tasks
    for c_id in clusters_to_label:
        athena.pipeline.summarisation_tasks.label_cluster_worker.apply_async(
            args=[str(c_id)], queue='summary_cluster')
    logger.info(f"Triggered label generation for {len(clusters_to_label)} clusters.")
    return stats


def generate_tfidf_label(texts: List[str]) -> str:
    if not texts:
        return "Unknown Cluster"
    try:
        vectorizer = TfidfVectorizer(stop_words='english', max_features=5)
        vectorizer.fit_transform(texts)
        terms = vectorizer.get_feature_names_out()
        return " ".join(terms)
    except BaseException:
        return texts[0][:50] if texts else "Unknown Cluster"


@celery_app.task
def compute_item_links():
    """Populate ``item_links`` using Qdrant ANN search.

    Previous implementation issued two Qdrant round-trips per item (retrieve
    + query_points), turning a 10k-item run into ~20k RPCs. We now:

    1. Scroll all embedded points once (payload-free, vectors included).
    2. Fire neighbour queries in batches of ``LINK_QUERY_BATCH`` via
       ``query_batch_points`` so each network round-trip resolves many items.
    """
    logger.info("Computing nearest neighbour links...")
    qdrant = QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"))

    # Guard: collection may not exist yet on a fresh install.
    collections = {c.name for c in qdrant.get_collections().collections}
    if COLLECTION_NAME not in collections:
        logger.warning(
            f"Qdrant collection '{COLLECTION_NAME}' does not exist yet. "
            "Skipping link computation."
        )
        return

    # 1. Scroll every point (with vectors) in one pass.
    all_ids: List[str] = []
    id_to_vector: dict = {}
    offset = None
    while True:
        points, next_offset = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            limit=1000,
            with_vectors=True,
            with_payload=False,
            offset=offset,
        )
        for p in points:
            pid = str(p.id)
            all_ids.append(pid)
            id_to_vector[pid] = p.vector
        if not next_offset:
            break
        offset = next_offset

    if not all_ids:
        logger.warning("No embedded points found — nothing to link.")
        return

    with SessionLocal() as session:
        # Fetch only the columns we need (id + cluster_id) and restrict to the
        # ids that actually exist in Qdrant.
        rows = session.execute(
            select(ContentItem.id, ContentItem.cluster_id)
            .where(ContentItem.embedding_id.isnot(None))
        ).all()
        item_cluster_map = {str(r.id): r.cluster_id for r in rows}

        # Filter to items that have both a DB row AND a Qdrant vector.
        target_ids = [pid for pid in all_ids if pid in item_cluster_map]
        logger.info(
            f"Batch-querying Qdrant for {len(target_ids)} items "
            f"({LINK_QUERY_BATCH} per round-trip)."
        )

        total_links = 0
        for batch_start in range(0, len(target_ids), LINK_QUERY_BATCH):
            batch_ids = target_ids[batch_start:batch_start + LINK_QUERY_BATCH]
            requests = [
                qmodels.QueryRequest(
                    query=id_to_vector[pid],
                    limit=LINK_TOPK,
                    with_payload=False,
                )
                for pid in batch_ids
            ]
            responses = qdrant.query_batch_points(
                collection_name=COLLECTION_NAME,
                requests=requests,
            )

            for source_pid, response in zip(batch_ids, responses):
                source_uuid = UUID(source_pid)
                source_cluster = item_cluster_map.get(source_pid)

                for res in response.points:
                    target_pid = str(res.id)
                    if target_pid == source_pid:
                        continue

                    target_cluster = item_cluster_map.get(target_pid)
                    if (
                        source_cluster
                        and target_cluster
                        and source_cluster != target_cluster
                    ):
                        link_type = 'cross_cluster'
                    else:
                        link_type = 'nearest_neighbour'

                    session.add(ItemLink(
                        source_item_id=source_uuid,
                        target_item_id=UUID(target_pid),
                        similarity_score=res.score,
                        link_type=link_type,
                    ))
                    total_links += 1

            # Commit per batch so long runs don't hold a single huge transaction.
            session.commit()

    logger.info(f"Item links updated — {total_links} rows written.")
