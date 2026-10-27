"""The model registry: reading GGUF headers, presets per context and router, where a model loads, speed
estimates, the chat's choice of preset, load progress, chats going first, and the admin routes."""
from __future__ import annotations

import struct

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from athena.api.deps import get_db
from athena.api.main import app
from athena.core import llm
from athena.core.models import AppSetting, LlmBenchmark, LlmModel
from athena.database import model_registry as db
from athena.model_server import files, gguf, gpu, lane, loading, presets, registry, speed, stats

REAL_SNAPSHOT = registry.snapshot


def write_gguf(path, kv: dict, padding: int = 4096):
    """A GGUF file with ``kv`` in its header and no tensors."""
    def string(s: str) -> bytes:
        b = s.encode()
        return struct.pack("<Q", len(b)) + b

    parts = [b"GGUF", struct.pack("<I", 3), struct.pack("<Q", 0), struct.pack("<Q", len(kv))]
    for key, value in kv.items():
        parts.append(string(key))
        if isinstance(value, bool):
            parts += [struct.pack("<I", 7), struct.pack("<?", value)]
        elif isinstance(value, int):
            parts += [struct.pack("<I", 4), struct.pack("<I", value)]
        elif isinstance(value, str):
            parts += [struct.pack("<I", 8), string(value)]
        elif isinstance(value, list):
            parts += [struct.pack("<I", 9), struct.pack("<I", 8), struct.pack("<Q", len(value))]
            parts += [string(v) for v in value]
    path.write_bytes(b"".join(parts) + b"\0" * padding)
    return path


def qwen_header(**extra) -> dict:
    return {"general.architecture": "qwen35", "general.name": "Qwen3.5-9B", "general.file_type": 15,
            "general.size_label": "9B", "qwen35.block_count": 32, "qwen35.context_length": 262144,
            "qwen35.embedding_length": 4096, "qwen35.attention.head_count": 16, "qwen35.attention.head_count_kv": 4,
            "qwen35.attention.key_length": 256, "qwen35.full_attention_interval": 4,
            "tokenizer.ggml.tokens": [f"t{i}" for i in range(300)],
            "tokenizer.chat_template": "{% if tools %}...{% endif %}<think>{{ enable_thinking }}"} | extra


# ── GGUF headers ─────────────────────────────────────────────────────


def test_a_header_says_what_the_model_is(tmp_path):
    path = write_gguf(tmp_path / "Qwen3.5-9B-Q4_K_M.gguf", qwen_header())
    info = gguf.describe(str(path))
    assert info["kind"] == "model" and info["architecture"] == "qwen35" and info["quant"] == "Q4_K_M"
    assert info["layers"] == 32 and info["context_train"] == 262144 and info["params"] == "9B"
    assert info["thinks"] and info["tools"] and info["role"] == "chat"
    assert gguf.suggested_name(info) == "qwen3.5-9b"


def test_projectors_and_embedders_are_told_apart(tmp_path):
    proj = write_gguf(tmp_path / "mmproj-F16.gguf", {"general.architecture": "clip", "general.name": "Qwen3.5-9B",
                                                     "clip.has_vision_encoder": True})
    assert gguf.describe(str(proj))["kind"] == "mmproj"
    emb = write_gguf(tmp_path / "Qwen3-Embedding-8B-Q4_K_M.gguf",
                     {"general.architecture": "qwen3", "qwen3.block_count": 36, "qwen3.pooling_type": 3})
    assert gguf.describe(str(emb))["role"] == "embed"
    model = write_gguf(tmp_path / "Qwen3.5-9B-Q4_K_M.gguf", qwen_header())
    found = files.projectors_for(str(model), gguf.describe(str(model)))
    assert [p["filename"] for p in found] == ["mmproj-F16.gguf"] and found[0]["match"]


def test_other_files_are_refused(tmp_path):
    (tmp_path / "x.gguf").write_bytes(b"not a model")
    with pytest.raises(gguf.NotGGUF):
        gguf.describe(str(tmp_path / "x.gguf"))


# ── presets ──────────────────────────────────────────────────────────


def test_each_context_is_a_preset_and_the_default_keeps_the_name():
    assert presets.preset_name("qwen3.5-9b", 20480, 20480) == "qwen3.5-9b"
    assert presets.preset_name("qwen3.5-9b", 32768, 20480) == "qwen3.5-9b@32k"
    assert presets.preset_name("qwen3.5-9b", 20480, 20480, vision=True) == "qwen3.5-9b-vision"
    assert presets.preset_name("qwen3.5-9b", 12000, 20480, vision=True) == "qwen3.5-9b@12000-vision"


def test_placement_decides_the_layers_and_the_projector_stays_on_the_cpu():
    auto = presets.section(name="m", path="m.gguf", context=8192, role="chat", placement="auto", device="gpu",
                           options={"reasoning-budget": 512}, mmproj="p.gguf")
    assert "n-gpu-layers" not in auto.values  # llama-server fits the layers itself
    assert auto.values["mmproj"] == "p.gguf" and auto.values["no-mmproj-offload"] == "true"
    assert auto.values["reasoning-budget"] == "512" and auto.values["jinja"] == "true"
    cpu = presets.section(name="m", path="m.gguf", context=8192, role="chat", placement="auto", device="cpu",
                          options={})
    assert cpu.values["device"] == "none" and cpu.values["n-gpu-layers"] == "0"
    pinned = presets.section(name="m", path="m.gguf", context=8192, role="chat", placement="gpu", device="split",
                             options={})
    assert pinned.values["n-gpu-layers"] == "99"


def test_preset_files_parse_back():
    sections = [presets.Section("*", {"parallel": "1"}), presets.Section("a@8k", {"ctx-size": "8192"})]
    top, sections = presets.parse(presets.render({"version": "1"}, sections, "a header"))
    assert top == {"version": "1"} and [s.name for s in sections] == ["*", "a@8k"]
    assert sections[1].values == {"ctx-size": "8192"}


# ── where a model loads ──────────────────────────────────────────────

CARD = {"name": "RTX", "total_mb": 8188, "used_mb": 800, "llama_mb": 0, "others_mb": 800, "available_mb": 6364}


def test_memory_is_read_off_the_line_through_two_contexts():
    points = [[8192, 5668, 1296], [65536, 7460, 1296]]
    full, zero = gpu.projection(points, 20480)
    assert abs(full - 6052) < 2 and zero == 1296
    assert gpu.projection(points, 131072)[0] > 7460  # past the end of the line
    assert gpu.projection([], 8192) is None


def test_a_model_goes_to_the_gpu_splits_or_stays_on_the_cpu():
    kw = {"layers": 33, "size_bytes": 5_680_000_000, "zero_mb": 1296, "info": CARD}
    assert gpu.plan(placement="auto", full_mb=6052, **kw)["device"] == "gpu"
    split = gpu.plan(placement="auto", full_mb=7460, **kw)
    assert split["device"] == "split" and 0 < split["gpu_layers"] < 33 and split["ram_mb"] > 0
    assert gpu.plan(placement="auto", full_mb=60000, **kw | {"zero_mb": 7000})["device"] == "cpu"
    assert gpu.plan(placement="cpu", full_mb=6052, **kw)["vram_mb"] == 0
    assert gpu.plan(placement="gpu", full_mb=9000, **kw)["fits"] is False
    assert gpu.plan(placement="auto", full_mb=6052, **kw | {"info": None})["device"] == "cpu"  # no GPU


# ── the registry ─────────────────────────────────────────────────────


@pytest.fixture
def store(monkeypatch, tmp_path):
    """A registry over an in-memory database, with its config folder and model files in ``tmp_path``."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (AppSetting, LlmModel, LlmBenchmark):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    import athena.database.db as dbmod
    monkeypatch.setattr(dbmod, "SessionLocal", Session)
    monkeypatch.setattr(registry, "snapshot", REAL_SNAPSHOT)
    monkeypatch.setattr(registry, "REPO", tmp_path)
    monkeypatch.setattr(registry, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(registry, "BASE_FILE", tmp_path / "config" / "llama-router.ini")
    monkeypatch.setattr(registry, "GPU_FILE", tmp_path / "config" / "llama-router.generated.ini")
    monkeypatch.setattr(registry, "CPU_FILE", tmp_path / "config" / "llama-router.cpu.ini")
    monkeypatch.setattr(registry, "reload_router", lambda url: True)
    monkeypatch.setattr(gpu, "gpu", lambda: CARD)
    monkeypatch.setattr(gpu, "fit_binary", lambda: None)
    monkeypatch.setattr(llm, "get_setting", lambda key, default="": "")
    monkeypatch.setattr(stats, "_cache", None)
    registry.invalidate()
    (tmp_path / "config").mkdir()
    (tmp_path / "models").mkdir()
    write_gguf(tmp_path / "models" / "Qwen3.5-9B-Q4_K_M.gguf", qwen_header())
    write_gguf(tmp_path / "models" / "mmproj-F16.gguf", {"general.architecture": "clip",
                                                         "general.name": "Qwen3.5-9B"})
    write_gguf(tmp_path / "models" / "emb.gguf", {"general.architecture": "qwen3", "qwen3.block_count": 36,
                                                  "qwen3.pooling_type": 3})
    (tmp_path / "config" / "llama-router.ini").write_text(
        "version = 1\n\n[*]\nn-gpu-layers = 99\nparallel = 1\n\n"
        "[qwen3.5-9b]\nmodel = models/Qwen3.5-9B-Q4_K_M.gguf\nctx-size = 20480\njinja = true\n"
        "reasoning-budget = 512\n\n"
        "[qwen3.5-9b-vision]\nmodel = models/Qwen3.5-9B-Q4_K_M.gguf\nmmproj = models/mmproj-F16.gguf\n"
        "no-mmproj-offload = true\nctx-size = 12288\njinja = true\n\n"
        "[qwen3-embedding-8b]\nmodel = models/emb.gguf\nembedding = true\npooling = last\nctx-size = 2048\n")
    yield Session
    registry.invalidate()


def test_the_hand_written_presets_are_taken_in(store):
    result = registry.write_presets()
    assert result["changed"]
    rows = {r["name"]: r for r in registry.snapshot()}
    assert set(rows) == {"qwen3.5-9b", "qwen3-embedding-8b"}
    qwen = rows["qwen3.5-9b"]
    assert qwen["vision"] and qwen["reasoning"] and qwen["default_context"] == 20480
    assert [c["context"] for c in qwen["contexts"]] == [8192, 16384, 20480, 32768, 65536]
    text = registry.GPU_FILE.read_text()
    assert "[qwen3.5-9b]" in text and "[qwen3.5-9b-vision]" in text and "[qwen3.5-9b@32k]" in text
    assert "[qwen3-embedding-8b]" in text and "pooling = last" in text
    assert "n-gpu-layers = 99" not in text  # auto placement: llama-server fits the layers
    assert registry.write_presets()["changed"] is False  # nothing new: the routers are not asked to reload


def test_a_cpu_model_goes_to_the_cpu_router(store):
    registry.write_presets()
    with store() as s:
        db.update_model(s, db.by_name(s, "qwen3.5-9b"), placement="cpu")
    registry.write_presets()
    assert "[qwen3.5-9b@8k]" in registry.CPU_FILE.read_text()
    assert "[qwen3.5-9b@8k]" not in registry.GPU_FILE.read_text()
    assert llm.base_url_for("qwen3.5-9b@8k") == registry.cpu_base_url()


def test_a_chat_turn_sends_the_preset_for_its_context(store):
    registry.write_presets()
    assert llm.chat_preset("qwen3.5-9b", 32768) == "qwen3.5-9b@32k"
    assert llm.chat_preset("qwen3.5-9b", None, images=True) == "qwen3.5-9b-vision"
    assert llm.chat_preset("qwen3.5-9b", 99999) == "qwen3.5-9b"  # not offered: the default
    assert llm.model_context("qwen3.5-9b@32k") == 32768
    with store() as s:
        db.update_model(s, db.by_name(s, "qwen3.5-9b"), mmproj_path=None)
    registry.invalidate()
    with pytest.raises(llm.TextOnlyModel):
        llm.chat_preset("qwen3.5-9b", None, images=True)
    assert llm.chat_preset("other-model", None, images=True) == llm.vision_model()  # not registered


def test_the_picker_lists_contexts_with_device_and_speed(store, monkeypatch):
    registry.write_presets()
    monkeypatch.setattr(llm, "_server_models", lambda: [{"id": "qwen3.5-9b@16k", "status": {"value": "loaded"}}])
    monkeypatch.setattr(llm, "_cpu_models", lambda: [])
    models = {m["id"]: m for m in llm.chat_models()}
    assert set(models) == {"qwen3.5-9b"}  # not the embedder
    qwen = models["qwen3.5-9b"]
    assert qwen["vision"] and qwen["tools"] and qwen["loaded"] and qwen["loaded_context"] == 16384
    assert all(c["tps"] and c["speed_source"] == "estimate" for c in qwen["contexts"])
    assert {c["device"] for c in qwen["contexts"]} <= {"gpu", "split", "cpu"}


def test_a_measured_speed_wins_and_scales_to_other_contexts(store):
    registry.write_presets()
    with store() as s:
        m = db.by_name(s, "qwen3.5-9b")
        db.record_speed(s, m, "RTX", 8192, gen_tps=40.0, prompt_tps=900.0, source="benchmark", replace=True)
        db.record_speed(s, m, "RTX", 8192, gen_tps=30.0)  # a chat turn moves the average
    est = stats.estimates()["qwen3.5-9b"]
    assert est[8192]["source"] == "measured" and 30 < est[8192]["tps"] < 40
    assert est[20480]["source"] == "scaled"


def test_turn_speeds_are_kept_for_known_presets(store):
    registry.write_presets()
    out = stats.record_turn("qwen3.5-9b@8k", {"predicted_per_second": 41.5, "predicted_n": 200,
                                              "prompt_per_second": 1200.0, "prompt_n": 900})
    assert out["tps"] == 41.5 and out["context"] == 8192 and out["device"] in ("gpu", "split")
    with store() as s:
        assert s.query(LlmBenchmark).one().gen_tps == 41.5
    assert stats.record_turn("unknown", {"predicted_per_second": 10}) is None


# ── loading ──────────────────────────────────────────────────────────


def test_the_bar_follows_the_estimate_then_slows():
    assert loading.progress(0, 10) == 0
    assert abs(loading.progress(5, 10) - 0.45) < 1e-9
    assert 0.9 < loading.progress(15, 10) < loading.progress(60, 10) <= 0.99


def test_load_state_shows_the_model_being_swapped_out(store, monkeypatch):
    registry.write_presets()
    monkeypatch.setattr(loading, "router_models", lambda url: [
        {"id": "qwen3.5-9b@8k", "status": {"value": "loading"}},
        {"id": "qwen3-embedding-8b", "status": {"value": "unloaded"}}])
    from tests.fakes import FakeRedis
    monkeypatch.setattr(loading, "_redis", lambda: FakeRedis())
    state = loading.state("qwen3.5-9b", 8192)
    assert state["status"] == "loading" and state["preset"] == "qwen3.5-9b@8k"
    assert state["device"]["kind"] == "gpu" and state["stages"][-1]["label"] == "Ready"
    monkeypatch.setattr(loading, "router_models", lambda url: [
        {"id": "qwen3.5-9b@8k", "status": {"value": "unloaded"}},
        {"id": "qwen3-embedding-8b", "status": {"value": "loaded"}}])
    state = loading.state("qwen3.5-9b", 8192)
    assert state["other"] == "qwen3-embedding-8b" and state["stages"][0]["label"].endswith("qwen3-embedding-8b")
    assert loading.state("not-registered", None) is None


# ── chats go first ───────────────────────────────────────────────────


def test_background_work_waits_while_a_chat_holds_the_model(monkeypatch):
    monkeypatch.setattr(lane, "POLL", 0.01)
    assert lane.yield_to_chat() == 0
    lane.hold()
    assert lane.chat_active()
    assert lane.yield_to_chat(max_wait=0.05) >= 0.05  # gives up in the end
    lane.release()
    assert not lane.chat_active()


def test_minute_embedding_runs_skip_while_someone_chats(monkeypatch):
    from athena.pipeline import embedding_worker
    lane.hold()
    monkeypatch.setattr(embedding_worker, "init_qdrant", lambda: pytest.fail("ran during a chat"))
    embedding_worker.process_embedding_queue()


# ── admin routes ─────────────────────────────────────────────────────


@pytest.fixture
def api(store, monkeypatch):
    def session():
        s = store()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(registry, "prepare_soon", lambda model_id, benchmark=True: None)
    monkeypatch.setattr(loading, "router_models", lambda url: [])
    monkeypatch.setattr(files, "roots", lambda: [str(registry.REPO / "models")])
    registry.write_presets()
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_the_admin_sees_models_with_their_contexts(api):
    body = api.get("/api/v1/models").json()
    names = {m["name"]: m for m in body["models"]}
    assert names["qwen3.5-9b"]["contexts"][0]["tokens"] == 8192
    assert names["qwen3.5-9b"]["used_for"] == ["default chat model"]
    assert body["writable"] and body["gpu"]["name"] == "RTX"
    assert body["servers"]["gpu"]["online"] is False


def test_the_browser_stays_inside_the_allowed_folders(api, tmp_path):
    listed = api.get("/api/v1/models/browse", params={"path": str(tmp_path / "models")}).json()
    kinds = {e["name"]: e["kind"] for e in listed["entries"]}
    assert kinds == {"Qwen3.5-9B-Q4_K_M.gguf": "model", "mmproj-F16.gguf": "mmproj", "emb.gguf": "model"}
    assert api.get("/api/v1/models/browse", params={"path": "/etc"}).status_code == 403


def test_a_model_is_inspected_added_changed_and_removed(api, tmp_path):
    path = write_gguf(tmp_path / "models" / "gemma-3-4b-it-Q4_K_M.gguf", {
        "general.architecture": "gemma3", "general.name": "Gemma 3 4B", "general.file_type": 15,
        "gemma3.block_count": 34, "gemma3.context_length": 131072,
        "tokenizer.chat_template": "{{ messages }}"})
    seen = api.post("/api/v1/models/inspect", json={"path": str(path)}).json()
    assert seen["name"] == "gemma-3-4b-it" and not seen["reasoning"] and not seen["tools"]
    assert seen["default_context"] == 16384 and seen["preview"]
    made = api.post("/api/v1/models", json={"path": str(path), "name": seen["name"], "contexts": [8192, 16384],
                                            "default_context": 8192, "placement": "cpu"})
    assert made.status_code == 201, made.text
    m = made.json()
    assert m["placement"] == "cpu" and [c["tokens"] for c in m["contexts"]] == [8192, 16384]
    assert all(c["server"] == "cpu" for c in m["contexts"])
    assert "[gemma-3-4b-it]" in registry.CPU_FILE.read_text()
    assert api.post("/api/v1/models", json={"path": str(path), "name": "gemma-3-4b-it"}).status_code == 409
    changed = api.patch(f"/api/v1/models/{m['id']}", json={"placement": "auto", "contexts": [4096, 8192]}).json()
    assert [c["tokens"] for c in changed["contexts"]] == [4096, 8192]
    assert "[gemma-3-4b-it@4k]" in registry.GPU_FILE.read_text()
    assert api.delete(f"/api/v1/models/{m['id']}").status_code == 204
    assert "gemma" not in registry.GPU_FILE.read_text()


def test_models_in_use_cannot_be_removed_and_bad_input_is_refused(api, tmp_path):
    qwen = next(m for m in api.get("/api/v1/models").json()["models"] if m["name"] == "qwen3.5-9b")
    assert api.delete(f"/api/v1/models/{qwen['id']}").status_code == 409
    assert api.patch(f"/api/v1/models/{qwen['id']}", json={"contexts": [100]}).status_code == 422
    assert api.post("/api/v1/models", json={"path": "/etc/passwd"}).status_code == 404
    proj = str(tmp_path / "models" / "mmproj-F16.gguf")
    assert api.post("/api/v1/models", json={"path": proj}).status_code == 422
    other = str(tmp_path / "models" / "emb.gguf")
    assert api.post("/api/v1/models", json={"path": other, "name": "Bad Name!"}).status_code == 422


def test_docker_setups_see_the_registry_read_only(api, monkeypatch, tmp_path):
    monkeypatch.setattr(registry, "BASE_FILE", tmp_path / "nowhere.ini")
    body = api.get("/api/v1/models").json()
    assert not body["writable"] and "Docker" in body["read_only_reason"]
    path = str(tmp_path / "models" / "emb.gguf")
    assert api.post("/api/v1/models", json={"path": path, "name": "x"}).status_code == 409


def test_speed_formula_reads_the_whole_model_per_token():
    row = {"size_bytes": 6e9, "info": {}}
    on_gpu = speed.formula(row, {"device": "gpu", "gpu_layers": 33, "layers": 33}, 180e9, 30e9)
    half = speed.formula(row, {"device": "split", "gpu_layers": 16, "layers": 33}, 180e9, 30e9)
    on_cpu = speed.formula(row, {"device": "cpu", "gpu_layers": 0, "layers": 33}, 180e9, 30e9)
    assert abs(on_gpu - 30) < 0.01 and on_gpu > half > on_cpu and abs(on_cpu - 5) < 0.01
    moe = {"size_bytes": 6e9, "info": {"experts": 64, "experts_used": 8}}
    assert speed.formula(moe, {"device": "cpu", "gpu_layers": 0, "layers": 33}, 180e9, 30e9) > on_cpu
