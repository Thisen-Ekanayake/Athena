"""Tests for TEI parsing, chunking, reference resolution and the classifier client (no network, no GPU)."""
from __future__ import annotations

import json
from uuid import uuid4

import httpx

from athena.evolution.classify import Classifier
from athena.evolution.fulltext import (
    KnownPaper, PaperIndex, chunk_id, chunk_sentences, contexts_from_parse, cue_words, s2_marked,
    sections_and_chunks,
)
from athena.evolution.names import detect_method_name
from athena.evolution.tei import (
    classify_heading, is_junk_heading, is_junk_sentence, mention_before, parse_tei,
)

TEI_NS = 'xmlns="http://www.tei-c.org/ns/1.0"'


def tei(body: str, bib: str = "", abstract: str = "") -> str:
    return (f'<TEI {TEI_NS}><teiHeader><fileDesc><titleStmt><title>QLoRA: Efficient Finetuning</title>'
            f'</titleStmt></fileDesc><profileDesc><abstract><div><p>{abstract}</p></div></abstract></profileDesc>'
            f'</teiHeader><text><body>{body}</body><back><listBibl>{bib}</listBibl></back></text></TEI>')


def div(head: str, *sentences: str, n: str | None = None) -> str:
    number = f' n="{n}"' if n else ""
    return f"<div><head{number}>{head}</head><p>{''.join(f'<s>{s}</s>' for s in sentences)}</p></div>"


LORA_BIB = ('<biblStruct xml:id="b27"><analytic><title>LoRA: Low-Rank Adaptation of Large Language Models</title>'
            '<author><persName><surname>Hu</surname></persName></author></analytic>'
            '<monogr><imprint><date when="2021"/></imprint></monogr><note>arXiv:2106.09685</note></biblStruct>')
PROSE = "This is an ordinary sentence of prose about the method we propose here."


class TestTei:
    def test_heading_rules(self):
        assert classify_heading("Conclusion and Future Work") == "conclusion"
        assert classify_heading("Error Analysis") == "results"
        assert classify_heading("Low-rank Adapters") is None

    def test_junk(self):
        assert is_junk_sentence("Table 3: Results on GLUE for all models we trained.")
        assert is_junk_sentence("Answer: [Yes] Justification: see section 5 of the paper.")
        assert is_junk_sentence("27.41 33.2 0.5 1.2 9.9 +0.3 -1.1 2.0")
        assert not is_junk_sentence(PROSE)
        assert is_junk_heading("27.41") and is_junk_heading("Guanaco:") and is_junk_heading("Q L o R A -A ll")
        assert not is_junk_heading("Double Quantization")

    def test_mention_before(self):
        assert mention_before("adds Low-rank Adapter weights like LoRA [") == "weights like LoRA"
        assert mention_before("as in LoRA (") == "as in LoRA"
        assert mention_before("few-shot results of GPT-3 [") == "results of GPT-3"
        assert mention_before("compared with Faster R-CNN ") == "with Faster R-CNN"  # at most three words
        assert mention_before("Low-Rank Adaptation (LoRA) ") == "LoRA"
        assert mention_before("variants such as LoRA+ [") == "such as LoRA+"
        assert mention_before("") is None

    def test_later_references_in_a_group_get_no_mention(self):
        # "R-CNN [12, 34]": the words name reference 12, not 34.
        assert mention_before("detectors like R-CNN [12, ") is None
        assert mention_before("such as R-CNN [12] [") is None
        assert mention_before("such as R-CNN [") == "such as R-CNN"

    def test_citations_mentions_and_marking(self):
        body = div("Introduction", 'Adapters such as LoRA <ref type="bibr" target="#b27">[28]</ref> are slow to '
                                   'train on long inputs, as shown in the experiments.', n="1")
        parsed = parse_tei(tei(body, LORA_BIB))
        [section] = [s for s in parsed.sections if s.section_type == "intro"]
        [sentence] = section.sentences
        assert sentence.refs == ["b27"]
        assert sentence.mentions["b27"] == "such as LoRA"
        assert "LoRA [[[28]]] are slow" in sentence.marked["b27"]
        assert parsed.bib["b27"].arxiv_id == "2106.09685"

    def test_author_year_fallback(self):
        body = div("Related Work", 'This was shown before by <ref type="bibr">Hu et al., 2021</ref> in a study '
                                   'of adapters for language models.', n="2")
        parsed = parse_tei(tei(body, LORA_BIB))
        assert parsed.sections[-1].sentences[0].refs == ["b27"]
        assert parsed.fallback_links == 1

    def test_section_typing(self):
        body = "".join([
            div("Introduction", PROSE, n="1"),
            div("Low-rank Adapters", PROSE),                       # untyped, between intro and experiments
            "<div><head n=\"4\">Experiments</head></div>",          # empty, but its subsections inherit
            div("Datasets we use", PROSE, n="4.1"),
            div("27.41", PROSE),                                    # junk heading: folded into 4.1
            div("QLoRA versus everything", PROSE, n="5"),           # names the paper's own method
            div("NeurIPS Paper Checklist", PROSE),
            div("Limitations", "Answer: [Yes] Justification: we discuss them in the paper."),
        ])
        parsed = parse_tei(tei(body, abstract=PROSE), method_name="QLoRA")
        types = [(s.heading, s.section_type) for s in parsed.sections]
        assert types == [("Abstract", "abstract"), ("Introduction", "intro"), ("Low-rank Adapters", "method"),
                         ("Datasets we use", "results"), ("QLoRA versus everything", "method")]
        assert len(parsed.sections[3].sentences) == 2  # the junk heading's text joined section 4.1


class TestChunks:
    def test_chunks_never_cross_sections_and_ids_are_stable(self):
        body = div("Introduction", *[PROSE] * 30, n="1") + div("Method", PROSE, n="2")
        parsed = parse_tei(tei(body))
        pid = uuid4()
        sections, chunks = sections_and_chunks(pid, "QLoRA", parsed)
        assert [c["section_type"] for c in chunks] == ["intro", "intro", "method"]
        assert chunks[0]["n_words"] >= 300
        assert chunk_id(pid, 0, chunks[0]["text"]) == chunks[0]["id"]
        _, again = sections_and_chunks(pid, "QLoRA", parse_tei(tei(body)))
        assert [c["id"] for c in again] == [c["id"] for c in chunks]

    def test_chunk_sentences(self):
        assert chunk_sentences(["a b c", "d e", "f"], words=4) == ["a b c d e", "f"]


class TestResolution:
    def setup_method(self):
        self.lora = KnownPaper(id=uuid4(), title="LoRA: Low-Rank Adaptation of Large Language Models", year=2021,
                               arxiv_id="2106.09685", doi=None, s2_paper_id="pl")
        self.fast = KnownPaper(id=uuid4(), title="Fast R-CNN", year=2015, arxiv_id=None, doi=None)
        self.index = PaperIndex([self.lora, self.fast])

    def test_arxiv_then_title(self):
        assert self.index.find("2106.09685v2", None, "garbled title") == self.lora.id
        assert self.index.find(None, None, "LoRA - low-rank adaptation of large language models") == self.lora.id

    def test_short_titles_only_match_known_references(self):
        assert self.index.find(None, None, "Fast R-CNN") is None
        assert self.index.find(None, None, "Fast R-CNN", known_refs=[self.fast.id]) == self.fast.id

    def test_contexts_from_parse(self):
        body = div("Introduction", 'However, LoRA <ref type="bibr" target="#b27">[28]</ref> cannot merge '
                                   'quantized weights back into the base model.', n="1")
        parsed = parse_tei(tei(body, LORA_BIB))
        citing = uuid4()
        rows, new_refs, resolved = contexts_from_parse(citing, parsed, self.index, known_refs=[])
        [row] = rows
        assert row.cited_id == self.lora.id and row.mention == "LoRA" and row.section_type == "intro"
        assert "[[[28]]]" in row.marked
        assert new_refs == {self.lora.id} and resolved == 1
        assert "however" in cue_words(row.sentence) and "cannot" in cue_words(row.sentence)

    def test_s2_snippets_are_marked_only_with_one_marker(self):
        mention, marked = s2_marked("Unlike LoRA [12], our method merges weights.")
        assert mention == "Unlike LoRA" and marked == "Unlike LoRA [[[12]]], our method merges weights."
        assert s2_marked("LoRA [12] and adapters [7] both add parameters.") == (None, None)


class TestClassifier:
    def test_a_yes_to_attribution_is_confirmed_with_thinking(self):
        answers = iter([{"label": "criticises"}, {"attributed": True}, {"attributed": False}])
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(answers))}}]})

        clf = Classifier(base_url="http://llm", model="m", http=httpx.Client(transport=httpx.MockTransport(handler)),
                         local=True)
        v = clf.classify("QLoRA", "LoRA", "LoRA is slow.", marked="LoRA [[[5]]] is slow.")
        assert v.attributed is False and not v.strict
        assert [b["chat_template_kwargs"]["enable_thinking"] for b in seen] == [False, False, True]
        assert seen[2]["max_tokens"] > 64 and clf.model_tag == "m+think"

    def test_attribution_is_asked_only_for_limitation_labels(self):
        answers = iter([{"label": "criticises"}, {"attributed": True}, {"attributed": True}, {"label": "background"}])
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(answers))}}]})

        clf = Classifier(base_url="http://llm", model="m", http=httpx.Client(transport=httpx.MockTransport(handler)))
        v = clf.classify("QLoRA", "LoRA", "LoRA is slow.", marked="LoRA [[[5]]] is slow.")
        assert v.label == "criticises" and v.attributed is True and v.strict
        assert "[[like this]]" in seen[0]["messages"][1]["content"]
        assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
        v = clf.classify("QLoRA", "LoRA", "We build on LoRA.")
        assert v.label == "background" and v.attributed is None and not v.strict
        assert len(seen) == 4


class TestMethodNames:
    @staticmethod
    def pairs(*phrases):
        return [(i, p) for i, p in enumerate(phrases)]

    def test_the_name_most_citing_papers_use_wins(self):
        mentions = self.pairs("such as LoRA", "with LoRA", "Unlike LoRA", "of LoRA", "et al", "many adapters")
        assert detect_method_name(mentions, "LoRA: Low-Rank Adaptation of Large Language Models", 6) == "LoRA"

    def test_multi_word_names(self):
        mentions = self.pairs("baseline Faster R-CNN", "with Faster R-CNN", "as Faster R-CNN", "of R-CNN")
        assert detect_method_name(mentions, "Towards Real-Time Object Detection", 4) == "Faster R-CNN"
        # Sentence openers are not part of a name.
        mentions = self.pairs("Unlike R-CNN", "Unlike R-CNN", "Unlike R-CNN")
        assert detect_method_name(mentions, "Rich feature hierarchies", 3) == "R-CNN"

    def test_a_title_word_counts_as_a_name(self):
        mentions = self.pairs("of Prefix-tuning", "with Prefix-tuning", "uses Prefix-tuning")
        assert detect_method_name(mentions, "Prefix-Tuning: Optimizing Continuous Prompts", 5) == "Prefix-tuning"

    def test_one_paper_counts_once(self):
        mentions = [("a", "with BitFit"), ("a", "as BitFit"), ("a", "of BitFit"), ("b", "BitFit")]
        assert detect_method_name(mentions, "BitFit: Simple Parameter-efficient Fine-tuning", 2) is None

    def test_generic_or_rare_words_are_not_names(self):
        assert detect_method_name(self.pairs(*["deep CNN"] * 30), "ImageNet Classification", 40) is None
        # Used by too small a share of the citing papers.
        assert detect_method_name(self.pairs(*["with YOLO"] * 4), "You Only Look Once", 30) is None


class TestExternalEndpoints:
    """Bring-your-own-model: any OpenAI-compatible service instead of the local llama-server."""

    def test_nothing_llama_specific_goes_to_an_external_chat_endpoint(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"label": "background"}'}}]})

        http = httpx.Client(headers={"Authorization": "Bearer k"}, transport=httpx.MockTransport(handler))
        Classifier(base_url="https://api.example.com", model="gpt-x", http=http, local=False).classify(
            "QLoRA", "LoRA", "We build on LoRA.")
        body = json.loads(seen[0].content)
        assert "chat_template_kwargs" not in body and body["model"] == "gpt-x"
        assert seen[0].url == "https://api.example.com/v1/chat/completions"
        assert seen[0].headers["authorization"] == "Bearer k"

    def test_embeddings_are_cut_to_1024_dimensions_and_short_ones_are_refused(self, monkeypatch):
        import numpy as np
        import pytest

        from athena.evolution import classify, gpu
        settings = {"EVOLUTION_EMBED_MODEL_NAME": "text-embedding-3-large", "EVOLUTION_EMBED_DIMENSIONS": "1024"}
        for module in (gpu, classify):
            monkeypatch.setattr(module, "get_setting", lambda key, default="": settings.get(key, default))
        sizes = iter([3072, 768])
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            n = next(sizes)
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * n}]})

        http = httpx.Client(transport=httpx.MockTransport(handler))
        vec = gpu._embed(http, "https://api.example.com", ["a gap"])
        assert vec.shape == (1, 1024) and np.isclose(np.linalg.norm(vec[0]), 1.0)
        assert bodies[0] == {"input": ["a gap"], "model": "text-embedding-3-large", "dimensions": 1024}
        with pytest.raises(ValueError, match="768 dimensions"):
            gpu._embed(http, "https://api.example.com", ["a gap"])

    def test_external_text_is_cut_by_words(self, monkeypatch):
        from athena.evolution import gpu
        monkeypatch.setattr(gpu, "is_local", lambda: False)
        text, cut = gpu._fit(None, "https://api.example.com", "word " * 700)
        assert cut and len(text.split()) == gpu.EXTERNAL_MAX_WORDS


def test_theme_labels_are_short_or_refused():
    answers = iter([{"label": "High cost of  full fine-tuning"}, {"label": " ".join(["word"] * 12)}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(answers))}}]})

    clf = Classifier(base_url="http://llm", model="m", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert clf.theme_label("PEFT", ["Full fine-tuning is costly."]) == "High cost of full fine-tuning"
    assert clf.theme_label("PEFT", ["Full fine-tuning is costly."]) is None
