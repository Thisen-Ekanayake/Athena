"""
Database reads and writes for the research evolution feature, one module per part of a map.

Kept free of the graph libraries (igraph) so the API image, which installs
only requirements.api.txt, can import it.
Callers use the package (``from athena.database import evolution as db``), which re-exports every name;
a test that patches a helper called inside the package patches the module that calls it.
"""
from athena.database.evolution.topics import (  # noqa: F401
    OVERRIDE_ACTIONS, LOOSE_MIN_SCORE, LIMITATION_LABELS, _BATCH, effective_milestone, _chunks, upsert_topic, get_topic,
    set_topic_status, delete_topic, active_search_builds, slug_taken, find_topic, _overrides, _topic_rows, list_topics,
    topic_summary, _merge_paper, save_topic_build, labels_version, method_names, topic_eras, maps_version, set_override,
    milestone_ids, save_cited_name, cited_names_fetched_since, latest_changes,
)
from athena.database.evolution.graph import (  # noqa: F401
    _node, _strict, _evidence, topic_graph, topic_timeline, topic_links, _paper_url, export_papers, paper_detail,
    _citations_by_year, topic_rising,
)
from athena.database.evolution.gaps import (  # noqa: F401
    gap_export_rows, sync_citing_gaps, pending_gap_candidates, save_gap_labels, pending_gap_vectors, mark_gaps,
    pending_loose, save_loose_links, topic_gap_rows, save_themes, topic_gaps, themes_to_label, save_theme_label,
)
from athena.database.evolution.reading import (  # noqa: F401
    NOTE_WHY, current_notes, save_note, read_papers, set_read, reading_path, note_context,
)
from athena.database.evolution.people import (  # noqa: F401
    topic_people,
)
from athena.database.evolution.ask import (  # noqa: F401
    _idea_check, save_idea_check, list_idea_checks, get_idea_check, delete_idea_check, save_map_question, map_questions,
    delete_map_question,
)
from athena.database.evolution.feed import (  # noqa: F401
    map_membership, feed_place, new_feed_papers,
)
from athena.database.evolution.changes import (  # noqa: F401
    snapshot_state, take_snapshot, _announce, topic_changes, due_for_refresh,
)
from athena.database.evolution.lane import (  # noqa: F401
    tier2_ids, _PARSE_ERRORS, needs_full_text, tier2_papers, known_papers, save_full_text, _save_own_gaps,
    pending_chunks, mark_embedded, paper_topics, pending_contexts, unconfirmed_strict, save_labels, all_tier2_ids,
    cited_by, pending_abstracts, mark_abstracts, forget_vectors,
)
