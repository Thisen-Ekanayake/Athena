"""
Rebuild the optional Neo4j read-only copy of the research-evolution graph from PostgreSQL.

Usage:
    docker compose -f docker/docker-compose.yml --profile graph up -d neo4j
    python3 scripts/export_evolution_neo4j.py

Then try, in the Neo4j browser at http://localhost:7474 (neo4j / athena_graph):
    MATCH (a:Paper)-[s:STATES_LIMITATION_OF]->(b:Paper)-[:IN_TOPIC {milestone: true}]->(:Topic {slug: 'peft'})
    RETURN b.title, count(s) AS times ORDER BY times DESC LIMIT 10
"""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena.evolution.neo4j_export import export  # noqa: E402

if __name__ == "__main__":
    for key, value in export().items():
        print(f"  {key:14s} {value}")
