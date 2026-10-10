"""
Phase 1 — how many known milestones a topic build finds on its own.

Reference lists exclude each topic's seeds, otherwise recall would be circular.

- object-detection: the milestone detectors on the roadmap in Zou et al.,
  "Object Detection in 20 Years: A Survey" (Figure 2), as recalled; check
  the list against the paper before quoting the numbers.
- peft: widely recognised parameter-efficient fine-tuning methods. Not one
  survey's figure, so treat it as a sanity check rather than ground truth.
- diffusion-models, retrieval-augmented-generation: the same kind of sanity
  check, written when the topics were added and before their first build.

For each reference paper this reports whether it is in the corpus, its score
rank among on-topic method papers, and whether it was picked as a milestone.

Usage:
    python -m scripts.evolution_bench.eval_milestones object-detection
    python -m scripts.evolution_bench.eval_milestones --all
"""
import argparse

from athena.database import evolution as db
from athena.database.db import SessionLocal
from athena.evolution.corpus import title_key

REFERENCE = {
    "object-detection": {
        "Viola-Jones": ["Rapid object detection using a boosted cascade of simple features",
                        "Robust Real-Time Face Detection"],
        "HOG": ["Histograms of Oriented Gradients for Human Detection"],
        "DPM": ["Object Detection with Discriminatively Trained Part-Based Models",
                "A discriminatively trained, multiscale, deformable part model"],
        "SPPNet": ["Spatial Pyramid Pooling in Deep Convolutional Networks for Visual Recognition"],
        "Fast R-CNN": ["Fast R-CNN"],
        "Faster R-CNN": ["Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks"],
        "FPN": ["Feature Pyramid Networks for Object Detection"],
        "SSD": ["SSD: Single Shot MultiBox Detector"],
        "RetinaNet": ["Focal Loss for Dense Object Detection"],
        "CornerNet": ["CornerNet: Detecting Objects as Paired Keypoints"],
        "CenterNet": ["Objects as Points", "CenterNet: Keypoint Triplets for Object Detection"],
    },
    "peft": {
        "Prefix-Tuning": ["Prefix-Tuning: Optimizing Continuous Prompts for Generation"],
        "Prompt Tuning": ["The Power of Scale for Parameter-Efficient Prompt Tuning"],
        "P-Tuning": ["GPT Understands, Too"],
        "P-Tuning v2": ["P-Tuning v2: Prompt Tuning Can Be Comparable to Fine-tuning Universally Across "
                        "Scales and Tasks"],
        "BitFit": ["BitFit: Simple Parameter-efficient Fine-tuning for Transformer-based Masked Language-models"],
        "Compacter": ["Compacter: Efficient Low-Rank Hypercomplex Adapter Layers"],
        "(IA)3": ["Few-Shot Parameter-Efficient Fine-Tuning is Better and Cheaper than In-Context Learning"],
        "AdaLoRA": ["Adaptive Budget Allocation for Parameter-Efficient Fine-Tuning"],
        "QLoRA": ["QLoRA: Efficient Finetuning of Quantized LLMs"],
        "DoRA": ["DoRA: Weight-Decomposed Low-Rank Adaptation"],
        "VeRA": ["VeRA: Vector-based Random Matrix Adaptation"],
        "PiSSA": ["PiSSA: Principal Singular Values and Singular Vectors Adaptation of Large Language Models"],
    },
    "diffusion-models": {
        "NCSN": ["Generative Modeling by Estimating Gradients of the Data Distribution"],
        "DDIM": ["Denoising Diffusion Implicit Models"],
        "Improved DDPM": ["Improved Denoising Diffusion Probabilistic Models"],
        "ADM": ["Diffusion Models Beat GANs on Image Synthesis"],
        "Classifier-free guidance": ["Classifier-Free Diffusion Guidance"],
        "GLIDE": ["GLIDE: Towards Photorealistic Image Generation and Editing with Text-Guided Diffusion Models"],
        "Latent diffusion": ["High-Resolution Image Synthesis with Latent Diffusion Models"],
        "DALL-E 2": ["Hierarchical Text-Conditional Image Generation with CLIP Latents"],
        "Imagen": ["Photorealistic Text-to-Image Diffusion Models with Deep Language Understanding"],
        "EDM": ["Elucidating the Design Space of Diffusion-Based Generative Models"],
        "DiT": ["Scalable Diffusion Models with Transformers"],
        "Consistency models": ["Consistency Models"],
    },
    "retrieval-augmented-generation": {
        "ORQA": ["Latent Retrieval for Weakly Supervised Open Domain Question Answering"],
        "kNN-LM": ["Generalization through Memorization: Nearest Neighbor Language Models"],
        "ColBERT": ["ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT"],
        "FiD": ["Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering"],
        "RETRO": ["Improving language models by retrieving from trillions of tokens"],
        "Contriever": ["Unsupervised Dense Information Retrieval with Contrastive Learning"],
        "Atlas": ["Atlas: Few-shot Learning with Retrieval Augmented Language Models"],
        "REPLUG": ["REPLUG: Retrieval-Augmented Black-Box Language Models"],
        "In-Context RALM": ["In-Context Retrieval-Augmented Language Models"],
        "Self-RAG": ["Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection"],
    },
}


def _matches(reference: str, title: str) -> bool:
    ref, got = title_key(reference), title_key(title)
    return ref == got or f" {ref} " in f" {got} "


def evaluate(slug: str):
    with SessionLocal() as session:
        topic = db.get_topic(session, slug)
        if topic is None:
            print(f"{slug}: not seeded")
            return
        nodes = db.topic_graph(session, topic, limit=100_000)["nodes"]
    ranked = sorted((n for n in nodes if n["kind"] == "method" and n["score_detail"].get("relevance", 1) > 0),
                    key=lambda n: n["milestone_score"], reverse=True)
    rank = {n["id"]: i + 1 for i, n in enumerate(ranked)}
    milestones = sum(n["is_milestone"] for n in nodes)

    print(f"\n{topic.name}: {len(nodes)} papers, {len(ranked)} on-topic methods, {milestones} milestones")
    print(f"  {'reference':14s} {'found':6s} {'year':5s} {'rank':>5s} {'score':>6s}  milestone  main path")
    found = picked = 0
    for name, titles in REFERENCE[slug].items():
        hits = [n for n in nodes if any(_matches(t, n["title"]) for t in titles)]
        if not hits:
            print(f"  {name:14s} {'no':6s}")
            continue
        n = max(hits, key=lambda h: h["milestone_score"])
        found += 1
        picked += n["is_milestone"]
        print(f"  {name:14s} {'yes':6s} {n['year'] or '':<5} {rank.get(n['id'], '-'):>5} {n['milestone_score']:6.3f}  "
              f"{'yes' if n['is_milestone'] else 'no':9s}  {'yes' if n['on_main_path'] else 'no'}")
    total = len(REFERENCE[slug])
    print(f"  in corpus: {found}/{total}   picked as milestone: {picked}/{total}   "
          f"precision proxy: {picked}/{milestones} milestones are reference papers")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    for slug in (list(REFERENCE) if args.all else args.slugs):
        evaluate(slug)


if __name__ == "__main__":
    main()
