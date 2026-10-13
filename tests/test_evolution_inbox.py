"""The inbox: map updates, new maps and feed papers citing milestones become events; each user reads up to a point."""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from athena.api.deps import get_db
from athena.api.main import app
from athena.database import evolution as evo_db
from athena.evolution.snapshots import summary

TOPIC = SimpleNamespace(id=uuid4(), slug="peft", name="Parameter-efficient fine-tuning")
STATS = {"papers": 1189, "milestones": 18, "themes": 40, "open_themes": 14}


def changes(**kw):
    base = {"new_milestones": [], "dropped_milestones": [], "papers_added": 0, "papers_removed": 0,
            "top_new_papers": [], "new_gaps": [], "solved_gaps": [], "reopened_gaps": [], "faded_gaps": []}
    return base | kw


def test_summary_names_what_changed():
    milestones = [{"named_method": "DoRA", "title": "DoRA: ..."}, {"named_method": None, "title": "PiSSA"}]
    c = changes(new_milestones=milestones, solved_gaps=[{"label": "Memory cost"}], papers_added=37)
    assert summary(c) == ["2 new milestones (DoRA, PiSSA)", "1 gap solved (Memory cost)", "37 new papers"]


@pytest.mark.parametrize("reason,first,c,expected", [
    ("baseline", True, None, None),
    ("build", True, None, ("map_new", "New map: Parameter-efficient fine-tuning")),
    ("refresh", False, changes(papers_added=3), ("map_changes", "Parameter-efficient fine-tuning updated")),
    ("refresh", False, changes(), None),
])
def test_snapshots_announce_new_maps_and_changes(reason, first, c, expected):
    with patch("athena.database.inbox.add_event") as add:
        evo_db._announce(None, TOPIC, reason, c, STATS, first)
    if expected is None:
        add.assert_not_called()
    else:
        assert add.call_args.args[1:3] == expected
        assert add.call_args.args[4].startswith("/evolution/peft")


def test_feed_papers_citing_milestones_make_one_event():
    from athena.evolution.feedlink import announce
    items = [(SimpleNamespace(id=uuid4(), title=f"Paper {i}"),
              [{"named_method": "LoRA", "title": "LoRA", "topic_name": "PEFT"}]) for i in range(4)]
    with patch("athena.database.inbox.add_event") as add:
        announce(None, items)
    args = add.call_args.args
    assert args[1:3] == ("feed_citations", "4 new papers cite milestones in your maps")
    assert args[3] == "Paper 0; Paper 1; Paper 2; ..." and args[4] == "/evolution"
    assert args[6]["items"][0]["cites"] == ["LoRA"]


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_inbox_routes_are_per_user(client):
    with patch("athena.database.inbox.events_for", return_value={"events": [], "unread": 2}) as events, \
            patch("athena.database.inbox.unread_count", return_value=2), \
            patch("athena.database.inbox.mark_seen") as seen:
        assert client.get("/api/v1/inbox", params={"limit": 5}).json() == {"events": [], "unread": 2}
        assert client.get("/api/v1/inbox/unread").json() == {"unread": 2}
        assert client.post("/api/v1/inbox/seen").status_code == 204
    assert events.call_args.args[2] == 5
    assert seen.call_args.args[1].role == "admin"  # the logged-in user from conftest
