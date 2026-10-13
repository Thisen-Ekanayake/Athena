"""Exports (E6): BibTeX, RIS, Markdown and the gap CSV."""
import csv
import io

from athena.evolution import export

FASTER = {"title": "Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks", "year": 2015,
          "authors": ["Shaoqing Ren", "Kaiming He", "Ross Girshick", "Jian Sun"],
          "venue": "IEEE Transactions on Pattern Analysis and Machine Intelligence",
          "doi": "10.1109/tpami.2016.2577031",
          "arxiv_id": "1506.01497", "url": "https://arxiv.org/abs/1506.01497", "named_method": "Faster R-CNN",
          "why": "It introduced the Region Proposal Network."}
PREPRINT = {"title": "LoRA: Low-Rank Adaptation of Large Language Models", "year": 2021, "authors": ["Edward J. Hu"],
            "venue": "arXiv (Cornell University)", "doi": None, "arxiv_id": "2106.09685",
            "url": "https://arxiv.org/abs/2106.09685"}


def test_bibtex_entry_types_and_fields():
    text = export.bibtex([FASTER, PREPRINT, FASTER | {"venue": "2016 IEEE Conference on Computer Vision (CVPR)"},
                          FASTER | {"venue": "Proceedings of the IEEE"}])
    entries = text.split("\n\n")
    assert entries[0].startswith("@article{ren2015faster,")
    assert "author = {Shaoqing Ren and Kaiming He and Ross Girshick and Jian Sun}" in entries[0]
    assert "eprint = {1506.01497}" in entries[0] and "archivePrefix = {arXiv}" in entries[0]
    assert entries[1].startswith("@misc{hu2021lora,") and "journal" not in entries[1]
    assert entries[2].startswith("@inproceedings{ren2015fastera,") and "booktitle = " in entries[2]
    assert entries[3].startswith("@article{")  # a journal despite its name


def test_bibtex_escapes_latex_and_keeps_capitals():
    text = export.bibtex([PREPRINT | {"title": "50% Faster & Cheaper: A_B tests", "authors": ["José Núñez"]}])
    assert r"title = {{50\% Faster \& Cheaper: A\_B tests}}" in text
    assert text.startswith("@misc{nunez2021faster,")


def test_ris_record():
    record = export.ris([FASTER]).strip()
    lines = record.splitlines()
    assert lines[0] == "TY  - JOUR" and lines[-1] == "ER  -"
    assert "AU  - Kaiming He" in lines and "PY  - 2015" in lines and "N1  - arXiv:1506.01497" in lines


def test_markdown_path_marks_the_survey_and_keeps_the_notes():
    survey = PREPRINT | {"title": "A Survey", "why": "Covers the field."}
    text = export.markdown_path("Object detection", survey, [FASTER], "2026-10-12")
    assert text.startswith("# Reading path: Object detection")
    assert "1. **[A Survey](https://arxiv.org/abs/2106.09685)** (2021)" in text and "*(start here)*" in text
    assert "2. **[Faster R-CNN: Towards" in text and "   It introduced the Region Proposal Network." in text
    assert ".." not in text.replace("...", "")


def test_markdown_milestones_group_by_year():
    text = export.markdown_milestones("PEFT", [PREPRINT, FASTER], None)
    assert text.index("## 2015") < text.index("## 2021")


def test_gaps_csv():
    rows = [{"theme": "Small objects", "status": "persisting", "first_year": 2016, "last_year": 2024, "theme_size": 9,
             "statement": 'It misses small, "crowded" objects.', "origin": "own", "section": "limitations",
             "paper": "SSD", "paper_year": 2016, "stated_by": None, "stated_by_year": None}]
    parsed = list(csv.DictReader(io.StringIO(export.gaps_csv(rows))))
    assert parsed[0]["statement"] == 'It misses small, "crowded" objects.' and parsed[0]["stated_by"] == ""
    assert list(parsed[0]) == export.GAP_COLUMNS
