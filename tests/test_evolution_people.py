"""People view (E8): key authors and labs per era, and who introduced each milestone."""
from athena.evolution.openalex import parse_authorships
from athena.evolution.people import PeoplePaper, author_key, key_people, milestone_people, people_by_era

MIT = {"id": "I1", "name": "MIT", "country": "US"}
CMU = {"id": "I2", "name": "CMU", "country": "US"}


def person(pid, name, *labs):
    return {"id": pid, "name": name, "institutions": list(labs)}


def paper(pid, year, score, milestone, *people, authors=()):
    return PeoplePaper(id=pid, title=f"Paper {pid}", year=year, milestone_score=score, is_milestone=milestone,
                       authorships=list(people), authors=list(authors))


ERAS = [(2000, 2009), (2010, 2019)]


def test_milestone_authors_come_before_prolific_ones():
    papers = [paper("m", 2015, 0.9, True, person("A1", "Ada", MIT))]
    papers += [paper(f"f{i}", 2016, 0.5, False, person("A2", "Bob", CMU)) for i in range(8)]
    era = people_by_era(papers, ERAS)[0]
    assert (era["start"], era["end"], era["papers"]) == (2010, 2019, 9)
    assert [a["name"] for a in era["authors"]] == ["Ada", "Bob"]
    assert era["authors"][1]["papers"] == 8 and era["authors"][0]["best_paper"]["id"] == "m"


def test_squared_scores_favour_one_strong_paper_among_equals():
    papers = [paper("strong", 2012, 0.8, False, person("A1", "Ada")),
              paper("w1", 2012, 0.45, False, person("A2", "Bob")), paper("w2", 2013, 0.45, False, person("A2", "Bob"))]
    assert [a["name"] for a in people_by_era(papers, ERAS)[0]["authors"]] == ["Ada", "Bob"]


def test_a_lab_counts_once_per_paper():
    papers = [paper("p", 2005, 0.7, True, person("A1", "Ada", MIT), person("A2", "Bob", MIT), person("A3", "Cy", CMU))]
    labs = people_by_era(papers, ERAS)[0]["labs"]
    assert [(lab["name"], lab["papers"]) for lab in labs] == [("CMU", 1), ("MIT", 1)]


def test_names_stand_in_for_missing_ids():
    papers = [paper("a", 2005, 0.7, True, authors=["José Núñez"]), paper("b", 2006, 0.6, False, authors=["Jose Nunez"])]
    authors = key_people(papers)["authors"]
    assert len(authors) == 1 and authors[0]["papers"] == 2
    assert author_key({"id": None, "name": "J. Smith"}) == "name:j smith"


def test_eras_without_papers_are_left_out():
    assert [e["start"] for e in people_by_era([paper("a", 2015, 0.5, False, person("A", "Ada"))], ERAS)] == [2010]


def test_milestone_people_oldest_first():
    papers = [paper("late", 2018, 0.9, True, person("A1", "Ada", MIT)),
              paper("early", 2004, 0.8, True, person("A2", "Bob", CMU)),
              paper("no", 2010, 0.9, False, person("A3", "Cy"))]
    out = milestone_people(papers)
    assert [m["id"] for m in out] == ["early", "late"]
    assert out[0]["authors"] == [{"id": "A2", "name": "Bob", "institutions": ["CMU"]}]


def test_parse_authorships():
    raw = [{"author": {"id": "https://openalex.org/A5", "display_name": "Ross Girshick"},
            "institutions": [{"id": "https://openalex.org/I95457486", "display_name": "UC Berkeley",
                              "country_code": "US"}, {"display_name": None}]}]
    assert parse_authorships(raw) == [{"id": "A5", "name": "Ross Girshick",
                                       "institutions": [{"id": "I95457486", "name": "UC Berkeley", "country": "US"}]}]
