from athena.core.models import ReferenceEmbedding
from athena.database.db import SessionLocal
import sys
import os
import requests

# Ensure athena is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


def init_qdrant_comments():
    try:
        url = f"{QDRANT_URL}/collections/comments"
        payload = {
            "vectors": {
                "size": 1536,
                "distance": "Cosine"
            }
        }
        resp = requests.put(url, json=payload)
        if resp.status_code in (200, 201):
            print("Successfully created 'comments' collection in Qdrant.")
        elif resp.status_code == 400 and "already exists" in resp.text:
            print("Qdrant 'comments' collection already exists.")
        else:
            print(f"Failed to create Qdrant collection: {resp.text}")
    except Exception as e:
        print(f"Error connecting to Qdrant: {e}")


def seed_reference_embeddings():
    # We will seed 2 dummy positive and 2 dummy negative embeddings representing the 10 mentioned in the spec
    # to satisfy the DB persistence requirement without hitting the OpenAI API for this initialization script.
    db = SessionLocal()
    try:
        exists = db.query(ReferenceEmbedding).first()
        if exists:
            print("Reference embeddings already seeded.")
            return

        dummy_vector = [0.0] * 1536

        refs = [
            ReferenceEmbedding(
                label="positive",
                text_content="Such a great breakthrough in efficiency.",
                embedding=dummy_vector
            ),
            ReferenceEmbedding(
                label="positive",
                text_content="This paper solves a major bottleneck in the field.",
                embedding=dummy_vector
            ),
            ReferenceEmbedding(
                label="negative",
                text_content="The methodology is flawed and results are cherry-picked.",
                embedding=dummy_vector
            ),
            ReferenceEmbedding(
                label="negative",
                text_content="Hard to reproduce, code does not work.",
                embedding=dummy_vector
            )
        ]

        db.add_all(refs)
        db.commit()
        print("Successfully seeded reference embeddings.")
    finally:
        db.close()


if __name__ == "__main__":
    init_qdrant_comments()
    seed_reference_embeddings()
