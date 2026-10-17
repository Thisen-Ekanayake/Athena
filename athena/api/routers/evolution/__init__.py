"""
Research maps (evolution), one module per part of a map: topics, graph, gaps, people, reading, feed, ask, sharing.

GET  /api/v1/evolution/topics                                — topics (curated and search-built) and their status
GET  /api/v1/evolution/search?q=                             — match a query to a topic by alias or by its
                                                               papers' content, or say it is not covered
POST /api/v1/evolution/proposals                             — propose a topic for a query (anchors, keywords,
                                                               fields); the 9B refines it if the GPU is free
GET  /api/v1/evolution/proposals/{id}                        — a proposal, polled while the 9B works
POST /api/v1/evolution/topics                                — build a topic from a checked proposal
GET  /api/v1/evolution/topics/{slug}                         — one topic's status, uncached, for build progress
POST /api/v1/evolution/topics/{slug}/rebuild                 — rebuild a search-built topic
DELETE /api/v1/evolution/topics/{slug}                       — delete a search-built topic
GET  /api/v1/evolution/topics/{slug}/graph                   — papers and citation edges for the timeline graph
GET  /api/v1/evolution/topics/{slug}/timeline                — milestones by year, and notable papers without
                                                               openly available full text
GET  /api/v1/evolution/topics/{slug}/papers/{paper_id}       — one paper with what it builds on, what built on it,
                                                               and strict gap -> resolution links with evidence
GET  /api/v1/evolution/topics/{slug}/gaps                    — gap themes with yearly counts, persisting first
POST /api/v1/evolution/topics/{slug}/milestones/{paper_id}   — pin, unpin, or reset a milestone
GET  /api/v1/evolution/topics/{slug}/reading-path?n=10       — a survey, then milestones in order, each with a
                                                               model-written line on why it matters
PUT|DELETE /api/v1/evolution/papers/{paper_id}/read          — tick or untick a paper as read (per user)
GET  /api/v1/evolution/topics/{slug}/export?what=&format=    — milestones or the reading path as BibTeX, RIS or
                                                               Markdown; gap themes as CSV
GET  /api/v1/evolution/topics/{slug}/rising?limit=10         — papers gaining citations fastest (OpenAlex per year)
GET  /api/v1/evolution/topics/{slug}/people                  — key authors and labs per era, and who introduced
                                                               each milestone
GET  /api/v1/evolution/items/{item_id}                       — a feed item's place in the maps, and the
                                                               milestones it cites
GET  /api/v1/evolution/new-papers?days=30&topic=             — recent feed papers that cite map milestones
POST /api/v1/evolution/idea-checks                           — check an idea against every map: closest papers,
                                                               gap themes it touches, a short verdict
GET|DELETE /api/v1/evolution/idea-checks[/{id}]              — the user's saved checks
POST /api/v1/evolution/topics/{slug}/ask                     — a question answered from the map's papers, streamed,
                                                               citing paper and section
GET|DELETE /api/v1/evolution/topics/{slug}/questions         — the user's questions to a map
DELETE /api/v1/evolution/questions/{id}                      — one of them
GET  /api/v1/evolution/topics/{slug}/links                   — papers shared with other maps, and milestones
                                                               borrowed and lent
GET  /api/v1/evolution/topics/{slug}/changes                 — snapshots and what changed between them
POST /api/v1/evolution/topics/{slug}/refresh                 — rebuild, read new full text, GPU lane, snapshot (admin)
POST /api/v1/evolution/topics/{slug}/full-text               — read full text and run the GPU lane only (admin)
PATCH /api/v1/evolution/topics/{slug}/settings               — how often the map is refreshed (admin)
"""
from fastapi import APIRouter

from athena.api.routers.evolution import ask, feed, gaps, graph, people, reading, sharing, topics

router = APIRouter(prefix="/api/v1/evolution", tags=["Evolution"])
for part in (topics, graph, gaps, people, reading, feed, ask, sharing):
    router.include_router(part.router)
