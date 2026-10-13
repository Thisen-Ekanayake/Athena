"""
Per-topic build settings.

Stored as JSON in ``evo_topics.config`` so a topic can be tuned without a
code change; anything missing falls back to the defaults here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields


@dataclass
class MilestoneWeights:
    """Each feature is in [0, 1]; magnitudes are log-scaled so the extreme tail stays distinct."""
    citations: float = 0.25    # global citations, relative to topic papers within two years
    in_degree: float = 0.25    # citations from inside the topic
    pagerank: float = 0.15     # importance inside the topic's citation graph
    flow: float = 0.15         # share of the topic's citation paths running through the paper
    relevance: float = 0.10    # topic keywords in the title (full) or only the abstract (half)
    specificity: float = 0.10  # share of the paper's citations that come from this topic
    # Introduced a named method: citing papers call it by a name ("LoRA [15]"), read from Semantic Scholar's
    # citing sentences for each topic's top candidates (athena.evolution.method_names). The earlier title
    # proxy ("LoRA: ...") penalised iconic papers whose titles do not follow the pattern (Fast R-CNN).
    # Evaluated 2026-10-13 (scripts/evolution_bench/eval_named_method.py, replayed on the four curated topics):
    # reference milestones picked at w = 0 / 0.05 / 0.10 / 0.15 were object detection 9/9/9/8 of 11, PEFT
    # 8/8/9/9 of 12, diffusion 7/6/5/4 of 12, RAG 7/6/5/1 of 10. A name is found for 55-75% of each topic's top
    # 150 candidates, so the feature mostly reshuffles them (RAG lost RETRO, Contriever and Active RAG to R3 and
    # BERTserini). No weight gains on a topic without losing on another, so it stays off.
    named_method: float = 0.0


@dataclass
class TopicConfig:
    # Corpus
    citers_per_seed: int = 600         # most-cited works citing each seed; each 200 costs one OpenAlex list call
    min_links: int = 2                 # a candidate must cite, or be cited by, this many accepted papers
    fields: list[str] = field(default_factory=lambda: ["Computer Science"])  # OpenAlex fields; empty = any
    year_min: int | None = None
    year_max: int | None = None
    max_papers: int = 1500
    # Semantic Scholar fills the reference lists OpenAlex lacks (most recent arXiv preprints) and
    # adds papers that pool papers cite but OpenAlex never linked to the seeds (QLoRA, DoRA).
    s2: bool = True
    # Papers matching the topic's name or aliases, most cited first. The seeds' citer lists cannot
    # reach them: OpenAlex lists only citers it has references for, and Semantic Scholar lists the
    # newest 10,000. Candidates found this way still need min_links links to join.
    s2_search_max: int = 1000
    s2_expand_min_citers: int = 3   # an outside paper needs this many pool papers citing it to be fetched
    s2_expand_max: int = 1500       # fetch at most this many, the most cited by the pool first
    # Without a working key, wait out the shared keyless pool (curated builds) or skip Semantic Scholar
    # (search-built topics, where someone is waiting for the map).
    s2_keyless: bool = True
    # The most-cited OpenAlex works matching the topic's name or aliases join the candidates, as the
    # Semantic Scholar search does; they still need min_links. Each 200 costs one search ($0.001).
    openalex_search_max: int = 0
    # Relevance: papers whose title (full weight) or abstract (half) mentions one of these are on-topic.
    # A keyword matches at the start of a word ("detect" finds "detector"); in double quotes ('"mot"') it
    # matches the whole word only.
    # Off-topic papers stay in the graph as context, but cannot be milestones or on the main path.
    # Empty means every paper is on-topic.
    keywords: list[str] = field(default_factory=list)
    # Decide on-topic papers from abstract embeddings too (athena.evolution.membership); keywords still
    # count for titles and for papers without a vector yet.
    semantic_membership: bool = True
    # Milestones
    weights: MilestoneWeights = field(default_factory=MilestoneWeights)
    eras: int = 8                      # eras hold equal numbers of papers, so busy years get more milestones
    max_era_years: int = 6             # but no era spans longer, so sparse early history is not one slot
    milestones_per_era: int = 3
    global_top: int = 12               # the highest-scoring papers are milestones whatever their era's quota
    milestone_min_score: float = 0.55  # no era pick below this, so sparse eras are not padded
    # Main-path papers at or above this score are milestones too. None: the main path is display only.
    # Membership is a yes/no that favoured mid-tier papers on long paths; the flow weight replaces it.
    main_path_min_score: float | None = None
    key_routes: int = 3                # top-SPC edges the key-route main path starts from
    # Tier 2 (full text): milestones, main-path papers and this many of each milestone's strongest citers
    tier2_successors: int = 8
    # Refresh (E4): rebuild, read new full text and run the GPU lane when the last build is this many days old.
    # 0 turns the scheduled refresh off for the topic.
    refresh_days: int = 30

    @classmethod
    def from_dict(cls, data: dict | None) -> "TopicConfig":
        data = dict(data or {})
        weights = MilestoneWeights(**{k: v for k, v in (data.pop("weights", None) or {}).items()
                                      if k in {f.name for f in fields(MilestoneWeights)}})
        known = {f.name for f in fields(cls)} - {"weights"}
        return cls(weights=weights, **{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)
