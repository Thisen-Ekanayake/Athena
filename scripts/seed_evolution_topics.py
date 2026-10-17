"""
Seed the curated research-evolution topics.

Each topic starts from a few anchor papers. Seeds are resolved to OpenAlex
records through free DOI lookups (arXiv papers have DOIs 10.48550/arxiv.ID).
The titles and years here are trusted over OpenAlex's, which can be wrong
(LoRA's record carries another paper's title).

Seeds are kept few on purpose: the milestone evaluation
(scripts/evolution_bench/eval_milestones.py) checks whether the build finds
the field's other milestones on its own, so they must not be seeds.

Usage:
    python3 scripts/seed_evolution_topics.py
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import init_db  # noqa: E402
from athena.database.evolution import upsert_topic  # noqa: E402
from athena.evolution.config import TopicConfig  # noqa: E402
from athena.evolution.corpus import title_key  # noqa: E402
from athena.core.openalex import OpenAlexClient  # noqa: E402

TOPICS = [
    {
        "slug": "peft",
        "name": "Parameter-efficient fine-tuning",
        "aliases": ["parameter efficient fine tuning", "peft", "lora", "low-rank adaptation", "adapter tuning",
                    "adapters", "prompt tuning", "prefix tuning", "efficient fine-tuning"],
        "description": "Adapting large pretrained models by training a small number of extra or selected "
                       "parameters instead of all of them.",
        "seeds": [
            {"arxiv_id": "1902.00751", "title": "Parameter-Efficient Transfer Learning for NLP", "year": 2019},
            {"arxiv_id": "2106.09685", "title": "LoRA: Low-Rank Adaptation of Large Language Models", "year": 2021},
            {"arxiv_id": "2110.04366", "title": "Towards a Unified View of Parameter-Efficient Transfer Learning",
             "year": 2021},
        ],
        # Specific to PEFT on purpose: "fine-tun" on its own made R-CNN, T5, PaLM and ControlNet
        # milestones, since their abstracts mention fine-tuning.
        "config": {"keywords": ["parameter-efficient", "parameter efficient", "efficient fine-tun",
                                "efficient finetun", "adapter", "low-rank adaptation", "low rank adaptation", "lora",
                                "prompt tuning", "prompt-tuning", "prefix-tuning", "prefix tuning", "p-tuning",
                                "soft prompt", "delta tuning", "peft", "bitfit", "side-tuning", "side tuning"]},
    },
    {
        "slug": "object-detection",
        "name": "Object detection",
        "aliases": ["object detection", "object detector", "object detectors", "r-cnn", "yolo", "detr",
                    "detection transformer", "region proposal"],
        "description": "Locating and classifying objects in images, from hand-crafted features to "
                       "region-based CNNs, single-stage detectors and transformers.",
        "seeds": [
            {"arxiv_id": "1311.2524",
             "title": "Rich feature hierarchies for accurate object detection and semantic segmentation",
             "year": 2013},
            {"arxiv_id": "1506.02640", "title": "You Only Look Once: Unified, Real-Time Object Detection",
             "year": 2015},
            {"arxiv_id": "2005.12872", "title": "End-to-End Object Detection with Transformers", "year": 2020},
        ],
        "config": {"keywords": ["detect", "region proposal", "object proposal", "bounding box", "yolo", "r-cnn"]},
    },
    {
        "slug": "diffusion-models",
        "name": "Diffusion models",
        "aliases": ["diffusion models", "denoising diffusion", "score-based generative models", "ddpm",
                    "stable diffusion", "latent diffusion", "text-to-image diffusion"],
        "description": "Generative models that learn to reverse a gradual noising process, from the first "
                       "thermodynamics-inspired formulation to score-based SDEs, latent and text-to-image diffusion.",
        "seeds": [
            {"arxiv_id": "1503.03585", "title": "Deep Unsupervised Learning using Nonequilibrium Thermodynamics",
             "year": 2015},
            {"arxiv_id": "2006.11239", "title": "Denoising Diffusion Probabilistic Models", "year": 2020},
            {"arxiv_id": "2011.13456",
             "title": "Score-Based Generative Modeling through Stochastic Differential Equations", "year": 2020},
        ],
        # "diffusion" alone would also match information diffusion in networks and diffusion MRI.
        "config": {"keywords": ["diffusion model", "diffusion probabilistic", "denoising diffusion", "score-based",
                                "score matching", "latent diffusion", "diffusion-based", "text-to-image", "ddpm",
                                "ddim", "classifier-free guidance", "consistency model", "flow matching"]},
    },
    {
        "slug": "retrieval-augmented-generation",
        "name": "Retrieval-augmented generation",
        "aliases": ["retrieval-augmented generation", "retrieval augmented generation", "rag", "dense retrieval",
                    "open-domain question answering", "retrieval-augmented language models"],
        "description": "Language models that retrieve passages from an external corpus and condition on them, "
                       "from open-domain question answering and dense retrievers to retrieval-augmented LLMs.",
        "seeds": [
            {"arxiv_id": "2005.11401", "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
             "year": 2020},
            {"arxiv_id": "2002.08909", "title": "REALM: Retrieval-Augmented Language Model Pre-Training",
             "year": 2020},
            {"arxiv_id": "2004.04906", "title": "Dense Passage Retrieval for Open-Domain Question Answering",
             "year": 2020},
        ],
        "config": {"keywords": ["retrieval-augmented", "retrieval augmented", "retrieval-enhanced", "dense retrieval",
                                "dense passage", "passage retrieval", "open-domain question", "open domain question",
                                "retriever", "knowledge-intensive", "retrieval-based"]},
    },
]


def resolve_seeds(client: OpenAlexClient, seeds: list[dict]) -> list[dict]:
    """Find every OpenAlex record of each seed; the most-cited becomes the seed, the rest alt_ids.

    The arXiv DOI often resolves to a minor preprint record (R-CNN's has 514 citations, its CVPR
    record 32,121), so a title search ($0.001) looks for the main record too.
    """
    resolved = []
    for seed in seeds:
        records = {}
        by_doi = client.get_work(f"doi:10.48550/arxiv.{seed['arxiv_id']}")
        if by_doi:
            records[by_doi.openalex_id] = by_doi
        for work in client.search_title(seed["title"]):
            if title_key(work.title) == title_key(seed["title"]):
                records.setdefault(work.openalex_id, work)
        if not records:
            print(f"   ! not found in OpenAlex: {seed['title']}")
            continue
        ranked = sorted(records.values(), key=lambda w: w.cited_by_count, reverse=True)
        main = ranked[0]
        flag = "" if title_key(main.title) == title_key(seed["title"]) else f"   (OpenAlex title: {main.title!r})"
        alts = ", ".join(f"{w.openalex_id} ({w.cited_by_count})" for w in ranked[1:])
        print(f"   {main.openalex_id:12s} {main.cited_by_count:>7} citations  {seed['title'][:60]}{flag}"
              + (f"\n{'':16s}other records: {alts}" if alts else ""))
        resolved.append({"openalex_id": main.openalex_id, "alt_ids": [w.openalex_id for w in ranked[1:]], **seed})
    return resolved


def main():
    init_db()
    client = OpenAlexClient()
    for topic in TOPICS:
        print(f"\n{topic['name']} ({topic['slug']})")
        seeds = resolve_seeds(client, topic["seeds"])
        TopicConfig.from_dict(topic["config"])  # fail fast on a malformed config
        # Store only this topic's overrides, so later changes to the defaults still apply.
        upsert_topic(topic["slug"], topic["name"], topic["aliases"], topic["description"], seeds, topic["config"])
    print(f"\nSeeded {len(TOPICS)} topics. Build one with: python3 scripts/build_evolution_topic.py <slug>")


if __name__ == "__main__":
    main()
