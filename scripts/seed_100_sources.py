"""
Seed script: ~100 verified RSS sources for Athena.
All URLs confirmed 200 OK before inclusion.
Run with: PYTHONPATH=/app python scripts/seed_100_sources.py
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.core.models import Source, SourceType, SourceCategory
from athena.database.db import SessionLocal

SOURCES = [
    # ── arXiv Paper Feeds ──────────────────────────────────────────────────
    {"name": "arXiv – Artificial Intelligence (cs.AI)",   "url": "https://arxiv.org/rss/cs.AI",    "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Machine Learning (cs.LG)",          "url": "https://arxiv.org/rss/cs.LG",    "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Computation & Language (cs.CL)",    "url": "https://arxiv.org/rss/cs.CL",    "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Computer Vision (cs.CV)",           "url": "https://arxiv.org/rss/cs.CV",    "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Neural & Evolutionary (cs.NE)",     "url": "https://arxiv.org/rss/cs.NE",    "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Robotics (cs.RO)",                  "url": "https://arxiv.org/rss/cs.RO",    "category": SourceCategory.PAPER,   "authority": 0.9},
    {"name": "arXiv – Statistics / Machine Learning",     "url": "https://arxiv.org/rss/stat.ML",  "category": SourceCategory.PAPER,   "authority": 1.0},
    {"name": "arXiv – Information Retrieval (cs.IR)",     "url": "https://arxiv.org/rss/cs.IR",    "category": SourceCategory.PAPER,   "authority": 0.9},
    {"name": "arXiv – Multi-Agent Systems (cs.MA)",       "url": "https://arxiv.org/rss/cs.MA",    "category": SourceCategory.PAPER,   "authority": 0.9},
    {"name": "Papers With Code – Latest",                 "url": "https://paperswithcode.com/latest/rss", "category": SourceCategory.PAPER, "authority": 0.9},

    # ── Company / Lab Research Blogs ──────────────────────────────────────
    {"name": "Microsoft Research",          "url": "https://www.microsoft.com/en-us/research/feed/",          "category": SourceCategory.COMPANY, "authority": 0.95},
    {"name": "Hugging Face Blog",           "url": "https://huggingface.co/blog/feed.xml",                    "category": SourceCategory.COMPANY, "authority": 0.95},
    {"name": "AWS Machine Learning Blog",   "url": "https://aws.amazon.com/blogs/machine-learning/feed/",     "category": SourceCategory.COMPANY, "authority": 0.9},
    {"name": "NVIDIA Deep Learning Blog",   "url": "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "category": SourceCategory.COMPANY, "authority": 0.9},
    {"name": "Weaviate Blog",               "url": "https://weaviate.io/blog/rss.xml",                        "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Databricks Blog",             "url": "https://www.databricks.com/feed",                         "category": SourceCategory.COMPANY, "authority": 0.85},
    {"name": "Cohere Blog",                 "url": "https://cohere.com/blog/rss",                             "category": SourceCategory.COMPANY, "authority": 0.85},
    {"name": "Replicate Blog",              "url": "https://replicate.com/blog/rss",                          "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Lightning AI Blog",           "url": "https://lightning.ai/blog/feed/",                         "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Weights & Biases Blog",       "url": "https://wandb.ai/fully-connected/feed.xml",               "category": SourceCategory.COMPANY, "authority": 0.85},
    {"name": "Scale AI Blog",               "url": "https://scale.com/blog/rss",                              "category": SourceCategory.COMPANY, "authority": 0.85},
    {"name": "Anyscale Blog",               "url": "https://www.anyscale.com/blog/rss",                       "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Vespa Blog",                  "url": "https://blog.vespa.ai/feed.xml",                          "category": SourceCategory.COMPANY, "authority": 0.75},
    {"name": "TensorFlow Blog",             "url": "https://blog.tensorflow.org/feeds/posts/default",         "category": SourceCategory.COMPANY, "authority": 0.9},
    {"name": "PyTorch Blog",                "url": "https://pytorch.org/blog/feed.xml",                       "category": SourceCategory.COMPANY, "authority": 0.9},
    {"name": "Medium – Hugging Face",       "url": "https://medium.com/feed/huggingface",                     "category": SourceCategory.COMPANY, "authority": 0.85},
    {"name": "Medium – TensorFlow",         "url": "https://medium.com/feed/tensorflow",                      "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Medium – PyTorch",            "url": "https://medium.com/feed/pytorch",                         "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Medium – NVIDIA AI",          "url": "https://medium.com/feed/nvidia-ai",                       "category": SourceCategory.COMPANY, "authority": 0.8},
    {"name": "Borealis AI (RBC)",           "url": "https://www.borealisai.com/feed/",                        "category": SourceCategory.COMPANY, "authority": 0.8},

    # ── Academic / Research Institutions ──────────────────────────────────
    {"name": "Stanford AI Lab Blog",        "url": "https://ai.stanford.edu/blog/feed.xml",          "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "CMU ML Blog",                 "url": "https://blog.ml.cmu.edu/feed/",                  "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "MIT News – AI",               "url": "https://news.mit.edu/rss/topic/artificial-intelligence2", "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "Harvard NLP",                 "url": "https://nlp.seas.harvard.edu/feed.xml",          "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "HAI Stanford",                "url": "https://hai.stanford.edu/news/rss.xml",          "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "CSET Georgetown",             "url": "https://cset.georgetown.edu/feed/",               "category": SourceCategory.BLOG, "authority": 0.85},

    # ── Researcher Personal Blogs ──────────────────────────────────────────
    {"name": "Lil'Log – Lilian Weng",       "url": "https://lilianweng.github.io/index.xml",         "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "Chip Huyen",                  "url": "https://huyenchip.com/feed.xml",                  "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Jay Alammar",                 "url": "https://jalammar.github.io/feed.xml",             "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Andrej Karpathy Blog",        "url": "https://karpathy.github.io/feed.xml",             "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "Ahead of AI – Raschka",       "url": "https://magazine.sebastianraschka.com/feed",      "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Sebastian Raschka",           "url": "https://sebastianraschka.com/rss_feed.xml",       "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Sebastian Ruder",             "url": "https://ruder.io/feed",                           "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Colah's Blog",                "url": "https://colah.github.io/rss.xml",                 "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Gregory Gundersen",           "url": "https://gregorygundersen.com/feed.xml",           "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Simon Willison",              "url": "https://simonwillison.net/atom/everything/",      "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "One Useful Thing – Mollick",  "url": "https://www.oneusefulthing.org/feed",             "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "Stephen Wolfram Writings",    "url": "https://writings.stephenwolfram.com/feed/",       "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "Louis Bouchard – AI",         "url": "https://www.louisbouchard.ai/feed/",              "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Scattered Thoughts",          "url": "https://www.scattered-thoughts.net/atom.xml",     "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Francesco Pochetti",          "url": "https://francescopochetti.com/feed/",             "category": SourceCategory.BLOG, "authority": 0.7},

    # ── AI Safety & Alignment ─────────────────────────────────────────────
    {"name": "AI Alignment Forum",          "url": "https://www.alignmentforum.org/feed.xml",         "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "LessWrong",                   "url": "https://www.lesswrong.com/feed.xml",               "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "AI Snake Oil",                "url": "https://aisnakeoil.substack.com/feed",             "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "Bounded Regret",              "url": "https://bounded-regret.ghost.io/rss/",             "category": SourceCategory.BLOG, "authority": 0.8},

    # ── Newsletters & Analysis ────────────────────────────────────────────
    {"name": "Import AI – Jack Clark",      "url": "https://jack-clark.net/feed/",                    "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Import AI Substack",          "url": "https://importai.substack.com/feed",              "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "Interconnects – Nathan Lambert", "url": "https://www.interconnects.ai/feed",            "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "The Gradient",                "url": "https://thegradient.pub/rss/",                    "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "SemiAnalysis",                "url": "https://www.semianalysis.com/feed",               "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "The Sequence",                "url": "https://thesequence.substack.com/feed",           "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "The Algorithmic Bridge",      "url": "https://thealgorithmicbridge.substack.com/feed",  "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Gradient Flow",               "url": "https://gradientflow.substack.com/feed",          "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Last Week in AI",             "url": "https://lastweekin.ai/feed",                      "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "Bens Bites",                  "url": "https://bensbites.com/feed",                      "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Every – Chain of Thought",    "url": "https://every.to/chain-of-thought/feed",          "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Jon Stokes",                  "url": "https://www.jonstokes.com/feed",                  "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "AI Weirdness",                "url": "https://www.aiweirdness.com/rss/",                 "category": SourceCategory.BLOG, "authority": 0.7},

    # ── General AI / ML Publications ─────────────────────────────────────
    {"name": "Towards Data Science",        "url": "https://towardsdatascience.com/feed",             "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Distill.pub",                 "url": "https://distill.pub/rss.xml",                     "category": SourceCategory.BLOG, "authority": 0.95},
    {"name": "Fast.ai Blog",                "url": "https://www.fast.ai/index.xml",                   "category": SourceCategory.BLOG, "authority": 0.9},
    {"name": "ML Mastery",                  "url": "https://machinelearningmastery.com/feed/",         "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "KDnuggets",                   "url": "https://www.kdnuggets.com/feed",                  "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Synced Review",               "url": "https://syncedreview.com/feed/",                  "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Medium – Synced Review",      "url": "https://medium.com/feed/syncedreview",            "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Medium – The Generator",      "url": "https://medium.com/feed/the-generator",           "category": SourceCategory.BLOG, "authority": 0.7},
    {"name": "Unite.AI",                    "url": "https://www.unite.ai/feed/",                      "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Marktechpost",                "url": "https://www.marktechpost.com/feed/",               "category": SourceCategory.BLOG, "authority": 0.7},
    {"name": "O'Reilly AI & ML Radar",      "url": "https://www.oreilly.com/radar/topics/ai-ml/feed/index.xml", "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Analytics India Magazine",    "url": "https://analyticsindiamag.com/feed/",             "category": SourceCategory.BLOG, "authority": 0.7},
    {"name": "AI Business",                 "url": "https://aibusiness.com/rss.xml",                  "category": SourceCategory.BLOG, "authority": 0.7},
    {"name": "Artificial Intelligence News","url": "https://www.artificialintelligence-news.com/feed/", "category": SourceCategory.BLOG, "authority": 0.7},

    # ── Tech News (AI Coverage) ───────────────────────────────────────────
    {"name": "TechCrunch – AI",             "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "VentureBeat – AI",            "url": "https://venturebeat.com/category/ai/feed/",      "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "MIT Technology Review – AI",  "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "IEEE Spectrum",               "url": "https://spectrum.ieee.org/rss/fulltext",          "category": SourceCategory.BLOG, "authority": 0.85},
    {"name": "Hacker News",                 "url": "https://news.ycombinator.com/rss",                "category": SourceCategory.BLOG, "authority": 0.8},

    # ── Podcasts / Community ──────────────────────────────────────────────
    {"name": "TWIML AI Podcast",            "url": "https://twimlai.com/feed/",                       "category": SourceCategory.BLOG, "authority": 0.8},
    {"name": "Lex Fridman Podcast",         "url": "https://lexfridman.com/feed/podcast/",            "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Practical AI Podcast",        "url": "https://changelog.com/practicalai/feed",          "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "Software Engineering Daily – ML", "url": "https://softwareengineeringdaily.com/category/machine-learning/feed/", "category": SourceCategory.BLOG, "authority": 0.75},
    {"name": "MLOps Community",             "url": "https://mlops.community/feed/",                   "category": SourceCategory.BLOG, "authority": 0.75},
]


def seed():
    db = SessionLocal()
    added = 0
    skipped = 0
    try:
        for s in SOURCES:
            exists = db.query(Source).filter(Source.url == s["url"]).first()
            if exists:
                skipped += 1
                continue
            src = Source(
                name=s["name"],
                url=s["url"],
                type=SourceType.RSS,
                category=s["category"],
                is_active=True,
                added_by="system",
                authority_score=s["authority"],
            )
            db.add(src)
            print(f"  + {s['name']}")
            added += 1

        db.commit()
        print(f"\nDone. Added {added} sources, skipped {skipped} duplicates.")
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding sources...")
    seed()
