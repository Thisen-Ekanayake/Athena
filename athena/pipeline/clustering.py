import os
import numpy as np
from typing import List, Dict, Any
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import select, update, insert
import umap
import hdbscan
from sklearn.feature_extraction.text import TfidfVectorizer

from athena.database.db import SessionLocal
from athena.core.models import ContentItem, Cluster, ItemLink
from athena.pipeline.tasks import celery_app

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
    point_ids = [p.id for p in all_points]
    
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
    
    # 4. Process clusters
    process_clusters(all_points, cluster_labels, vectors)

def process_clusters(points, labels, raw_vectors):
    label_to_points = {}
    for i, label in enumerate(labels):
        if label == -1: continue
        if label not in label_to_points: label_to_points[label] = []
        label_to_points[label].append(i)
        
    with SessionLocal() as session:
        # Fetch existing clusters for stability matching
        existing_clusters = session.execute(select(Cluster).where(Cluster.is_active == True)).scalars().all()
        
        new_cluster_data = []
        for label, point_indices in label_to_points.items():
            cluster_vectors = raw_vectors[point_indices]
            centroid = np.mean(cluster_vectors, axis=0)
            
            # Stability matching
            matched_cluster_id = None
            if existing_clusters:
                similarities = [
                    np.dot(centroid, np.array(c.centroid)) / (np.linalg.norm(centroid) * np.linalg.norm(c.centroid))
                    for c in existing_clusters if c.centroid
                ]
                if similarities and max(similarities) >= STABILITY_THRESHOLD:
                    max_idx = np.argmax(similarities)
                    matched_cluster_id = existing_clusters[max_idx].id
            
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
                session.flush() # Get ID
                cluster_id = new_cluster.id
            
            # Assign items to cluster
            item_uuids = [points[i].id for i in point_indices]
            session.execute(
                update(ContentItem).where(ContentItem.id.in_(item_uuids)).values(
                    cluster_id=cluster_id
                )
            )
            
        session.commit()
        logger.info("Clustering results persisted to database.")

def generate_tfidf_label(texts: List[str]) -> str:
    if not texts: return "Unknown Cluster"
    try:
        vectorizer = TfidfVectorizer(stop_words='english', max_features=5)
        X = vectorizer.fit_transform(texts)
        terms = vectorizer.get_feature_names_out()
        return " ".join(terms)
    except:
        return texts[0][:50] if texts else "Unknown Cluster"

@celery_app.task
def compute_item_links():
    """
    Populate item_links table using Qdrant ANN search.
    """
    logger.info("Computing nearest neighbour links...")
    with SessionLocal() as session:
        # Get all embedded items
        items = session.execute(
            select(ContentItem).where(ContentItem.embedding_id.isnot(None))
        ).scalars().all()
        
        for item in items:
            # Search Qdrant for top-6 (including self)
            results = qdrant.search(
                collection_name=COLLECTION_NAME,
                query_vector=qdrant.retrieve(COLLECTION_NAME, ids=[str(item.id)], with_vectors=True)[0].vector,
                limit=6
            )
            
            for res in results:
                if str(res.id) == str(item.id): continue
                
                # Check for existing link to avoid duplicates
                # In practice, we might want to clear and re-populate
                link = ItemLink(
                    source_item_id=item.id,
                    target_item_id=UUID(res.id),
                    similarity_score=res.score,
                    link_type='nearest_neighbour'
                )
                session.add(link)
            session.commit()
    logger.info("Item links updated.")
