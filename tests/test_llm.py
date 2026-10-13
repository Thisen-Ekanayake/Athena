"""The shared model client: settings fallbacks, llama.cpp extras, embeddings and the embedding-space guard."""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from athena.core import llm


@pytest.fixture
def settings(monkeypatch):
    values: dict[str, str] = {}
    monkeypatch.setattr(llm, "get_setting", lambda key, default="": values.get(key, default))
    return values


class TestSettings:
    def test_defaults_are_the_local_router(self, settings):
        assert llm.chat_base_url() == llm.DEFAULT_BASE_URL
        assert llm.embed_base_url() == llm.DEFAULT_BASE_URL
        assert llm.chat_model() == "qwen3.5-9b" and llm.embed_model() == "qwen3-embedding-8b"
        assert llm.chat_api_key() == "local"
        assert llm.is_llama_cpp()

    def test_task_models_override_the_shared_one(self, settings):
        settings.update(LLM_CHAT_MODEL="big", LLM_QA_MODEL="fast")
        assert llm.chat_model("qa") == "fast"
        assert llm.chat_model("summary") == "big"

    def test_openai_key_only_goes_to_openai(self, settings):
        settings.update(OPENAI_API_KEY="sk-old")
        assert llm.chat_api_key() == "local"  # the local router never sees it
        settings.update(LLM_BASE_URL="https://api.openai.com/v1/")
        assert llm.chat_api_key() == "sk-old"
        assert llm.chat_base_url() == "https://api.openai.com/v1"
        assert not llm.is_llama_cpp()
        assert llm.chat_extra() == {}

    def test_embeddings_follow_chat_unless_set(self, settings):
        settings.update(LLM_BASE_URL="https://api.openai.com/v1", LLM_API_KEY="sk-chat")
        assert llm.embed_base_url() == "https://api.openai.com/v1" and llm.embed_api_key() == "sk-chat"
        settings.update(EMBED_BASE_URL="http://gpu-box:8080/v1")
        assert llm.embed_api_key() == "local"

    def test_server_type_can_be_forced(self, settings):
        settings.update(LLM_SERVER="other")
        assert not llm.is_llama_cpp()
        settings.update(LLM_SERVER="llama.cpp", LLM_BASE_URL="https://api.openai.com/v1")
        assert llm.is_llama_cpp()

    def test_thinking_switch_is_sent_to_llama_cpp(self, settings):
        assert llm.chat_extra() == {"chat_template_kwargs": {"enable_thinking": False}}
        assert llm.chat_extra(think=True) == {"chat_template_kwargs": {"enable_thinking": True}}

    def test_server_root_drops_v1(self):
        assert llm.server_root("http://127.0.0.1:8080/v1/") == "http://127.0.0.1:8080"
        assert llm.server_root("http://127.0.0.1:8080") == "http://127.0.0.1:8080"

    def test_cost_is_zero_unless_priced(self, settings):
        assert llm.cost(1000, 1000) == 0
        settings.update(LLM_PRICE_IN_PER_M="0.15", LLM_PRICE_OUT_PER_M="0.60")
        assert llm.cost(1_000_000, 1_000_000) == pytest.approx(0.75)
        settings.update(LLM_PRICE_IN_PER_M="cheap")
        assert llm.cost(1_000_000, 1_000_000) == pytest.approx(0.60)


class FakeOpenAI:
    calls: list[dict] = []
    size = 4096

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.embeddings = SimpleNamespace(create=self.create)

    def create(self, input, model, **kwargs):
        FakeOpenAI.calls.append({"input": input, "model": model, **kwargs, "client": self.kwargs})
        # Reversed order: results must be put back by index.
        data = [SimpleNamespace(index=i, embedding=[float(i + 1)] * FakeOpenAI.size) for i in range(len(input))]
        return SimpleNamespace(data=list(reversed(data)))


class TestEmbed:
    @pytest.fixture(autouse=True)
    def fake_openai(self, monkeypatch):
        FakeOpenAI.calls, FakeOpenAI.size = [], 4096
        monkeypatch.setattr(llm, "OpenAI", FakeOpenAI)

    def tokenizer(self, monkeypatch, tokens_per_word: int = 1):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append((str(request.url), body["model"]))
            return httpx.Response(200, json={"tokens": [0] * len(body["content"].split()) * tokens_per_word})

        real = httpx.Client
        monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
        return seen

    def test_queries_get_the_instruction_and_vectors_are_cut_to_1024(self, settings, monkeypatch):
        seen = self.tokenizer(monkeypatch)
        vecs = llm.embed(["a", "b"], instruct="Find papers")
        assert vecs.shape == (2, 1024)
        assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0)
        assert FakeOpenAI.calls[0]["input"] == ["Instruct: Find papers\nQuery: a", "Instruct: Find papers\nQuery: b"]
        assert FakeOpenAI.calls[0]["model"] == "qwen3-embedding-8b"
        # The router needs the model name to pick the tokenizer.
        assert seen[0] == ("http://127.0.0.1:8080/tokenize", "qwen3-embedding-8b")

    def test_long_text_is_trimmed_to_fit_the_embedder(self, settings, monkeypatch):
        self.tokenizer(monkeypatch, tokens_per_word=2)
        llm.embed(["word " * 2000])
        sent = FakeOpenAI.calls[0]["input"][0]
        assert 2 * len(sent.split()) <= llm.EMBED_MAX_TOKENS

    def test_hosted_models_get_dimensions_and_no_tokenizer(self, settings, monkeypatch):
        settings.update(EMBED_BASE_URL="https://api.openai.com/v1", EMBED_API_KEY="sk-e", EMBED_DIMENSIONS="1024",
                        EMBED_MODEL="text-embedding-3-large")
        monkeypatch.setattr(llm.httpx, "Client", lambda **kw: pytest.fail("no /tokenize on hosted APIs"))
        FakeOpenAI.size = 1024
        llm.embed(["doc"])
        call = FakeOpenAI.calls[0]
        assert call["dimensions"] == 1024 and call["input"] == ["doc"]
        assert call["client"]["api_key"] == "sk-e" and call["client"]["base_url"] == "https://api.openai.com/v1"

    def test_short_vectors_are_refused(self, settings):
        settings.update(LLM_SERVER="other")
        FakeOpenAI.size = 768
        with pytest.raises(ValueError, match="768 dimensions"):
            llm.embed(["doc"])


class TestEmbedSpace:
    @pytest.fixture
    def stored(self, settings, monkeypatch):
        import athena.core.config_store as store
        monkeypatch.setattr(store, "set_setting", lambda key, value: settings.__setitem__(key, value))
        return settings

    def test_first_use_records_the_model_and_a_switch_is_refused(self, stored):
        llm.check_embed_space("feed", collection_dim=1024)
        assert stored["EMBED_SPACE_FEED"] == "qwen3-embedding-8b"
        llm.check_embed_space("feed", collection_dim=1024)
        stored["EMBED_MODEL"] = "text-embedding-3-large"
        with pytest.raises(llm.EmbedSpaceMismatch, match="made by qwen3-embedding-8b"):
            llm.check_embed_space("feed")

    def test_an_old_openai_collection_is_refused(self, stored):
        with pytest.raises(llm.EmbedSpaceMismatch, match="1536 dimensions"):
            llm.check_embed_space("feed", collection_dim=1536)
        assert "EMBED_SPACE_FEED" not in stored
