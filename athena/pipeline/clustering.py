import os
import numpy as np
from typing import List
from loguru import logger
from qdrant_client import QdrantClient
from sqlalchemy import select, update
import umap
import hdbscan
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

qdrant = QdrantClient(url=QDRANT_URL)


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

    # 1. Fetch all points from Qdrant
    # For now, fetch ALL. In production, we might want to fetch only semi-recent ones.
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
    [p.id for p in all_points]

    # 2. UMAP dimensionality reduction
    reducer = umap.UMAP(n_neighbors=15, n_components=50, metric='cosine', random_state=42)
    reduced_vectors = reducer.fit_transform(vectors)

    # 3. HDBSCAN clustering
    clusterer = hdbscan.HDBSCAN(min_cluster_size=5, min_samples=3, metric='euclidean', prediction_data=True)
    cluster_labels = clusterer.fit_predict(reduced_vectors)

    # -1 is noise
    unique_labels = set(cluster_labels)
    unique_labels.discard(-1)

    logger.info(f"Found {len(unique_labels)} clusters and {list(cluster_labels).count(-1)} noise points.")

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
        except Exception as e:
            run_log.finished_at = datetime.utcnow()
            run_log.status = "failed"
            run_log.error_message = str(e)[:500]
            session.commit()
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
    """
    Populate item_links table using Qdrant ANN search.
    Detects cross_cluster vs nearest_neighbour link types.
    """
    logger.info("Computing nearest neighbour links...")
    with SessionLocal() as session:
        # Get all embedded items with their cluster assignments
        items = session.execute(
            select(ContentItem).where(ContentItem.embedding_id.isnot(None))
        ).scalars().all()

        # Build a cluster_id lookup for cross-cluster detection
        item_cluster_map = {
            str(item.id): item.cluster_id for item in items
        }

        for item in items:
            # Search Qdrant for top-6 (including self)
            results = qdrant.search(
                collection_name=COLLECTION_NAME,
                query_vector=qdrant.retrieve(COLLECTION_NAME, ids=[str(item.id)], with_vectors=True)[0].vector,
                limit=6
            )

            for res in results:
                if str(res.id) == str(item.id):
                    continue

                # Determine link type: cross_cluster if clusters differ
                target_cluster = item_cluster_map.get(str(res.id))
                if (
                    item.cluster_id
                    and target_cluster
                    and item.cluster_id != target_cluster
                ):
                    link_type = 'cross_cluster'
                else:
                    link_type = 'nearest_neighbour'

                link = ItemLink(
                    source_item_id=item.id,
                    target_item_id=UUID(res.id),
                    similarity_score=res.score,
                    link_type=link_type
                )
                session.add(link)
            session.commit()
    logger.info("Item links updated.")

