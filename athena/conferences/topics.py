"""
The fixed topic list conference papers are sorted into, and the sorting.

The list starts as the areas ACL Rolling Review asks submissions to pick (``SEED``); an admin can rename, describe,
add and remove topics (Settings → Conferences). Each topic's name and description are embedded as a query, each
paper's title and abstract as a document, and a paper goes to its nearest topic. Editing the list only re-sorts the
vectors already stored, which takes seconds; nothing is embedded again but the topics.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from athena.core import llm
from athena.core.models import ConfPaper, ConfTopic

INSTRUCT = "Given the name and description of a research area in natural language processing, retrieve papers in it"

SEED: list[tuple[str, str]] = [
    ("Language modeling", "Pretraining, scaling and architectures of language models, tokenization, long context, "
                          "in-context learning, instruction tuning"),
    ("Reasoning", "Mathematical, logical, symbolic and commonsense reasoning, chain of thought, planning"),
    ("LLM agents and tool use", "Language agents, tool use, web and computer agents, multi-agent systems"),
    ("Safety and alignment", "Alignment, RLHF and preference learning, jailbreaks, red teaming, hallucination, "
                             "factuality, trustworthiness"),
    ("Retrieval-augmented generation", "Retrieval-augmented language models, knowledge-intensive NLP, "
                                       "grounding generation in retrieved documents"),
    ("Code and structured data", "Code generation, semantic parsing, text-to-SQL, tables and structured data"),
    ("Efficient methods", "Efficient training and inference, compression, quantization, distillation, "
                          "parameter-efficient fine-tuning, low-resource methods"),
    ("Machine learning for NLP", "Learning algorithms for NLP, representation learning, optimization, "
                                 "robustness, domain adaptation, continual learning"),
    ("Interpretability and analysis", "How models work inside: probing their representations, attribution, "
                                      "mechanistic interpretability, explaining their predictions"),
    ("Ethics, bias and fairness", "Social bias, fairness, ethics, privacy and harms of NLP systems"),
    ("Dialogue and interactive systems", "Dialogue systems, conversational agents, task-oriented dialogue, chatbots"),
    ("Discourse and pragmatics", "Discourse structure, coherence, coreference, pragmatics"),
    ("Generation", "Natural language generation, decoding, controllable generation, data-to-text, story generation"),
    ("Summarization", "Text summarization, abstractive and extractive summaries"),
    ("Machine translation", "Machine translation, speech translation, translation evaluation"),
    ("Multilinguality and language diversity", "Multilingual and cross-lingual models, low-resource and "
                                               "under-represented languages, language diversity"),
    ("Question answering", "Question answering, reading comprehension, open-domain QA"),
    ("Information extraction", "Named entities, relation and event extraction, knowledge graphs, entity linking"),
    ("Information retrieval and text mining", "Search, ranking, dense retrieval, text classification, "
                                              "topic models, text mining"),
    ("Sentiment, style and argument mining", "Sentiment analysis, emotion, stylistic analysis, argument mining, "
                                             "opinion"),
    ("Semantics", "Lexical semantics, word senses, sentence semantics, textual entailment, semantic similarity"),
    ("Syntax and parsing", "Syntax, tagging, chunking, constituency and dependency parsing, grammar"),
    ("Phonology, morphology and word segmentation", "Phonology, morphology, morphological analysis, word "
                                                    "segmentation, transliteration"),
    ("Linguistic theory and psycholinguistics", "Linguistic theories, cognitive modelling, psycholinguistics, "
                                                "language acquisition"),
    ("Multimodality and grounding", "Vision and language, multimodal models, images, video, grounding, robotics"),
    ("Speech and spoken language", "Speech recognition, text-to-speech, spoken language understanding"),
    ("Resources and evaluation", "New datasets, corpora and benchmarks, annotation, evaluating what models can "
                                 "do, evaluation methods and metrics"),
    ("Computational social science", "Computational social science, cultural analytics, social media, "
                                     "misinformation, NLP for social good"),
    ("Clinical, biomedical and scientific text", "Clinical and biomedical NLP, scientific documents, legal and "
                                                 "financial text"),
    ("Human-centered NLP and applications", "NLP applications, human-centered NLP, education, user studies, "
                                            "writing assistance"),
]


def ensure_seeded(session: Session) -> bool:
    """Write the seed list when there is no topic yet; whether it did."""
    if session.execute(select(func.count()).select_from(ConfTopic)).scalar():
        return False
    session.add_all(ConfTopic(name=n, description=d, position=i) for i, (n, d) in enumerate(SEED))
    session.commit()
    return True


def topic_text(topic: ConfTopic) -> str:
    return f"{topic.name}: {topic.description}" if topic.description else topic.name


def topic_matrix(session: Session, model: str | None = None) -> tuple[list[int], np.ndarray | None]:
    """The topics' ids and unit vectors (one row each), embedding those without a vector from ``model``."""
    model = model or llm.embed_model()
    topics = list(session.execute(select(ConfTopic).order_by(ConfTopic.position, ConfTopic.id)).scalars())
    if not topics:
        return [], None
    stale = [t for t in topics if not t.vector or t.vector_model != model]
    if stale:
        vectors = llm.embed([topic_text(t) for t in stale], instruct=INSTRUCT, feature="conf_embed")
        for t, v in zip(stale, vectors):
            t.vector, t.vector_model = [float(x) for x in v], model
        session.commit()
    return [t.id for t in topics], np.asarray([t.vector for t in topics], dtype=np.float32)


def nearest(paper_vectors: np.ndarray, topic_ids: list[int], topics: np.ndarray) -> list[tuple[int, float]]:
    """Each paper's nearest topic and its cosine (the vectors are unit length)."""
    sims = paper_vectors @ topics.T
    best = sims.argmax(axis=1)
    return [(topic_ids[b], float(sims[i, b])) for i, b in enumerate(best)]


def reassign_all(session: Session) -> int:
    """Sort every embedded paper again, from the vectors in Qdrant: after the topic list changed."""
    from athena.conferences import embed
    topic_ids, topics = topic_matrix(session)
    if topics is None:
        session.execute(update(ConfPaper).values(topic_id=None, topic_score=None))
        session.commit()
        return 0
    done = 0
    for ids, vectors in embed.scroll_vectors():
        for pid, (tid, score) in zip(ids, nearest(vectors, topic_ids, topics)):
            session.execute(update(ConfPaper).where(ConfPaper.id == pid).values(topic_id=tid, topic_score=score))
        session.commit()
        done += len(ids)
    logger.info(f"Conference topics: {done} papers sorted again into {len(topic_ids)} topics")
    return done


def touch(topic: ConfTopic) -> None:
    """After an edit: its vector is made again on the next sort."""
    topic.vector, topic.vector_model = None, None
    topic.updated_at = datetime.now(timezone.utc)
