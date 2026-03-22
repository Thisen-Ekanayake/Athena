import sys
import os
import asyncio

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.database.operations import get_active_sources  # noqa: E402
from athena.pipeline.tasks import _crawl_source_async  # noqa: E402


def run():
    print("Triggering crawl for all sources...")
    # Since we don't want to start a full worker for a quick test,
    # we can call the function directly (it will run in the main process)
    # But crawl_all_sources calls .delay(), so we should call the inner logic or wait for worker.

    async def main():
        sources = get_active_sources()
        print(f"Found {len(sources)} active sources.")
        for source in sources:
            print(f"Crawling {source.name}...")
            try:
                await _crawl_source_async(str(source.id))
            except Exception as e:
                print(f"Failed to crawl {source.name}: {e}")

    asyncio.run(main())
    print("Crawl Complete.")


if __name__ == "__main__":
    run()
