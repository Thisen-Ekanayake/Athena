import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.db import init_db  # noqa: E402
from athena.api.migrations.add_users import run_migration as add_users  # noqa: E402
from athena.api.migrations.add_evolution_tools import run_migration as add_evolution_tools  # noqa: E402
from athena.api.migrations.add_inbox_watches import run_migration as add_inbox_watches  # noqa: E402
from athena.api.migrations.add_release import run_migration as add_release  # noqa: E402
from athena.api.migrations.add_reading import run_migration as add_reading  # noqa: E402
from scripts.seed_prompts import seed_prompts  # noqa: E402
from athena.database.operations import upsert_source  # noqa: E402
from athena.core.schemas import SourceCreate  # noqa: E402
from athena.core.models import SourceType, SourceCategory  # noqa: E402


def setup():
    print("Initializing Database...")
    init_db()
    add_users()  # accounts on databases made before them
    add_evolution_tools()  # reading paths, idea checks, map questions, snapshots, cross-map links
    add_inbox_watches()  # follows, what they caught, inbox settings; existing users follow the built maps once
    add_release()  # usage log, map share links, the setup guide's flag (existing accounts skip the guide)
    add_reading()  # citation momentum
    seed_prompts()  # summaries and cluster labels need their prompt templates; does nothing once seeded

    print("Seeding Initial Sources...")

    # ArXiv Source
    upsert_source(SourceCreate(
        name="ArXiv AI",
        url="https://export.arxiv.org/api/query",
        type=SourceType.API,
        category=SourceCategory.PAPER,
        fetch_config={"query": "cat:cs.AI OR cat:cs.LG", "max_results": 20}
    ))

    # OpenAI Blog
    upsert_source(SourceCreate(
        name="OpenAI News",
        url="https://openai.com/news/rss.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Google DeepMind Blog
    upsert_source(SourceCreate(
        name="Google DeepMind Blog",
        url="https://deepmind.google/blog/rss.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Meta AI RSS
    upsert_source(SourceCreate(
        name="Meta AI Blog",
        url="https://ai.meta.com/blog/rss/",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Microsoft Research
    upsert_source(SourceCreate(
        name="Microsoft Research Blog",
        url="https://www.microsoft.com/en-us/research/feed/",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Hugging Face Blog
    upsert_source(SourceCreate(
        name="Hugging Face Blog",
        url="https://huggingface.co/blog/feed.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Anthropic News
    upsert_source(SourceCreate(
        name="Anthropic News",
        url="https://www.anthropic.com/feed.xml",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # NVIDIA Blog
    upsert_source(SourceCreate(
        name="NVIDIA Blog",
        url="https://blogs.nvidia.com/feed/",
        type=SourceType.RSS,
        category=SourceCategory.COMPANY
    ))

    # Community Blogs (Playwright Headless Scraping)
    upsert_source(SourceCreate(
        name="The Gradient",
        url="https://thegradient.pub/rss/",
        type=SourceType.SCRAPE,
        category=SourceCategory.BLOG,
        fetch_config={"use_playwright": True}
    ))

    upsert_source(SourceCreate(
        name="Towards Data Science",
        url="https://towardsdatascience.com/feed",
        type=SourceType.SCRAPE,
        category=SourceCategory.BLOG,
        fetch_config={"use_playwright": True}
    ))

    upsert_source(SourceCreate(
        name="LessWrong",
        url="https://www.lesswrong.com/feed.xml",
        type=SourceType.SCRAPE,
        category=SourceCategory.BLOG,
        fetch_config={"use_playwright": True}
    ))

    print("Setup Complete.")


if __name__ == "__main__":
    setup()
