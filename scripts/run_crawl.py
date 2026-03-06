import sys
import os
import asyncio

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.pipeline.tasks import crawl_all_sources

def run():
    print("Triggering crawl for all sources...")
    # Since we don't want to start a full worker for a quick test, 
    # we can call the function directly (it will run in the main process)
    # But crawl_all_sources calls .delay(), so we should call the inner logic or wait for worker.
    
    # Let's import the actual logic to run synchronously for verification
    from athena.database.operations import get_active_sources
    from athena.pipeline.tasks import _crawl_source_async
    
    async def main():
        sources = get_active_sources()
        print(f"Found {len(sources)} active sources.")
        for source in sources:
            print(f"Crawling {source.name}...")
            await _crawl_source_async(str(source.id))
            
    asyncio.run(main())
    print("Crawl Complete.")

if __name__ == "__main__":
    run()
