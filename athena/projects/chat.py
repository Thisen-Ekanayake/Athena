"""
A chat turn: the messages for the model, its streamed thinking and answer, and the tools it calls.

A turn in a project starts with the project's passages that best answer the question (athena.projects.index),
numbered so the answer cites them as [n]; tools can add more sources (athena.projects.tools). The system prompt
carries the project's instructions and what is in it, the research maps shared with the model as graphs
(athena.evolution.digest), and the chat's files: they stay with every turn, oldest first, so the start of the
prompt stays the same from turn to turn and llama.cpp reuses it. Images go to the vision model on their own turn
and as their caption after it. Everything is fitted into the model's context: the thinking budget and room for the
answer first, then the maps, files and passages, then as many earlier turns as fit.

``run`` yields events for the page (server-sent events, athena.api.routers.chats):
    {"type": "sources", "sources": [...]}        the numbered sources so far
    {"type": "reasoning", "text": "..."}         thinking, as it streams
    {"type": "token", "text": "..."}             the answer, as it streams
    {"type": "tool", "step": {...}}              a tool call starting (status running) and finishing
    {"type": "artifact", "artifact": {...}}      an artifact written or changed
    {"type": "notice", "text": "..."}            something the user should know (no project search, a cut file)
    {"type": "loading", "state": {...}}          the model is loading (athena.model_server.loading), every half second
    {"type": "done", "message": {...}}           the saved assistant message
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

ANSWER_TOKENS = 4096        # the answer and any document written through a tool call
MIN_PROMPT_TOKENS = 3000    # thinking is cut back before the prompt gets smaller than this
MAX_STEPS = 4               # model calls that may use tools; one more answers without them
LOAD_WAIT = 600             # seconds a turn waits for its model to load
CHARS_PER_TOKEN = 3.0       # a cautious estimate (prose runs near 4)
HISTORY_TURNS = 20
MAP_SHARE = 0.3             # of the prompt budget, at most, for the maps shared as graphs
FILES_SHARE = 0.5           # of what is left after the maps, at most, for the chat's files
TITLE_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"],
                "additionalProperties": False}

SYSTEM = (
    "You are Athena, a research assistant for AI and machine learning research. Today is {today}.\n\n"
    "Answer clearly and concisely, in Markdown. When numbered sources are given, cite them for every claim that "
    "comes from them as [n], at the end of the sentence or bullet it supports (not gathered at the end of the "
    "answer); never invent a citation, and say so plainly when the sources do not answer the question.\n\n"
    "Tools: search_papers finds papers (Athena's library, Semantic Scholar, arXiv); query_map asks one of Athena's "
    "research maps; write_artifact creates a document the user keeps (use it for drafts, sections, tables or notes "
    "they ask for, then say in one or two sentences what you wrote instead of repeating it); read_artifact and "
    "edit_artifact change an existing one.\n\n"
    "For a question about a research topic, field, method or paper, call a tool before you answer, without asking "
    "first: query_map when a map may cover it (it finds a map by its topic's name, and lists the maps when none "
    "matches), search_papers otherwise. Answer from what they return. Never answer a research question from "
    "memory alone; if the tools find nothing, say so and say that what follows is not drawn from sources. "
    "Greetings, questions about you and follow-ups the conversation already answers need no tool.")

PROJECT = """
You are working in the user's project "{name}".{description}

The project contains:
{catalog}"""

INSTRUCTIONS = """
The user's instructions for this project (follow them):
{instructions}"""


def tokens(text: str) -> int:
    return int(len(text or "") / CHARS_PER_TOKEN) + 4


def clip(text: str, max_tokens: int) -> tuple[str, bool]:
    limit = int(max_tokens * CHARS_PER_TOKEN)
    return (text, False) if len(text) <= limit else (text[:max(limit, 0)].rstrip() + "\n[…cut to fit]", True)


@dataclass
class Turn:
    """Everything a turn needs, read from the database before the stream starts."""
    user_id: UUID
    conversation_id: UUID
    message_id: UUID                 # the assistant message, saved as "streaming" before the model starts
    project_id: UUID | None
    project_name: str | None
    project_description: str
    instructions: str
    catalog: list[str]               # one line per thing in the project
    artifacts: list[dict]            # [{id, title, chars}] in this project or chat
    history: list[dict]              # earlier turns: [{role, content}]
    question: str
    attachments: list[dict]          # this message's files: [{id, filename, kind, text, path, mime, caption}]
    model: str
    effort: str
    first_turn: bool
    context: int | None = None       # the context size picked; the model's default when None
    files: list[dict] = field(default_factory=list)        # the chat's files still in it, oldest first
    shared_maps: list[dict] = field(default_factory=list)  # [{key, data}]: maps the model gets as graphs
    open_maps: list[str] = field(default_factory=list)     # maps only the user sees: "Name (slug)"
    events: list[dict] = field(default_factory=list)


def map_share(prompt_budget: int, maps: int) -> int:
    """Tokens each shared map may take."""
    return int(prompt_budget * MAP_SHARE) // max(maps, 1)


def pick_level(levels: dict[str, str], share: int) -> str:
    """The most detailed level that fits ``share`` tokens; the smallest when none does."""
    from athena.evolution import digest
    return next((level for level in digest.LEVELS if tokens(levels[level]) <= share), digest.MINIMAL)


def maps_block(turn: Turn, prompt_budget: int | None = None) -> str:
    """The shared maps as graphs, each at the most detail its share of the prompt allows, and the maps only the
    user has open."""
    from athena.evolution import digest
    parts = []
    if turn.shared_maps:
        share = map_share(prompt_budget, len(turn.shared_maps)) if prompt_budget else None
        graphs = []
        for m in turn.shared_maps:
            levels = {level: digest.render(m["data"], m["key"], level) for level in digest.LEVELS}
            text = levels[pick_level(levels, share)] if share else levels[digest.FULL]
            graphs.append(clip(text, share)[0] if share else text)
        parts.append(digest.LEGEND + "\n\n" + "\n\n".join(graphs))
    if turn.open_maps:
        parts.append("The user has these maps open beside the chat; you were not given them, and query_map reads "
                     "them if the user asks about them: " + "; ".join(turn.open_maps) + ".")
    return "\n\n".join(parts)


def map_refs(turn: Turn) -> dict[str, dict]:
    """Every paper id the shared maps name (A3), for linking the answer's mentions."""
    from athena.evolution import digest
    known: dict[str, dict] = {}
    for m in turn.shared_maps:
        known |= digest.refs(m["data"], m["key"])
    return known


def files_block(turn: Turn, budget: int) -> tuple[str, list[str]]:
    """The chat's files within ``budget`` tokens, oldest first: text files as text (each cut to an equal share
    when they do not all fit), earlier images as their caption. This message's images go in as images."""
    notices, parts, used = [], [], 0
    current = {a["id"] for a in turn.attachments}
    texts = [f for f in turn.files if f["kind"] != "image"]
    for i, f in enumerate(texts):
        share = max((budget - used) // max(len(texts) - i, 1), 200)
        body, cut = clip(f.get("text") or "(no text could be read from this file)", share)
        if cut:
            notices.append(f"{f['filename']} was too long for the model's context; it read the first part. "
                           "A larger context (in the model menu) reads more of it.")
        parts.append(f"File {f['filename']}:\n\n{body}")
        used += tokens(body)
    for f in turn.files:
        if f["kind"] == "image" and f["id"] not in current:
            parts.append(f"Image {f['filename']} (as the vision model described it): {f['caption']}"
                         if f.get("caption") else
                         f"Image {f['filename']}: not described yet; ask the user to attach it again if it matters.")
    if not parts:
        return "", notices
    return ("Files the user attached in this chat (they stay with the conversation until removed):\n\n"
            + "\n\n---\n\n".join(parts)), notices


def system_prompt(turn: Turn, prompt_budget: int | None = None, files: str = "") -> str:
    """Instructions first, then what changes least to most (maps, files, artifacts), so turns share a prefix."""
    text = SYSTEM.format(today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if turn.project_id:
        catalog = "\n".join(turn.catalog[:60]) or "(nothing yet)"
        if len(turn.catalog) > 60:
            catalog += f"\n…and {len(turn.catalog) - 60} more"
        text += PROJECT.format(name=turn.project_name, catalog=catalog,
                               description=f" {turn.project_description}" if turn.project_description else "")
        if turn.instructions.strip():
            text += INSTRUCTIONS.format(instructions=turn.instructions.strip())
    if maps := maps_block(turn, prompt_budget):
        text += "\n\n" + maps
    if files:
        text += "\n\n" + files
    if turn.artifacts:
        text += "\n\nArtifacts you can read or edit:\n" + "\n".join(
            f"- {a['title']} (id {a['id']}, {a['chars']} characters)" for a in turn.artifacts[:30])
    return text


def user_content(turn: Turn, passages: list[dict], image_urls: dict[str, str]) -> object:
    """The question with the project's passages and this message's images (its other files are in the system
    prompt, files_block)."""
    parts = []
    if passages:
        listed = "\n\n".join(f"[{p['n']}] {p['title']} ({p['kind']})\n{p['text']}" for p in passages)
        parts.append(f"Passages from the project:\n\n{listed}")
    parts.append(turn.question)
    text = "\n\n---\n\n".join(parts)
    images = [a for a in turn.attachments if a["kind"] == "image" and a["id"] in image_urls]
    if not images:
        return text
    return [{"type": "image_url", "image_url": {"url": image_urls[a["id"]]}} for a in images] + \
        [{"type": "text", "text": text}]


CITATION = re.compile(r" ?\[(\d+)\](?![(:])")


def drop_unknown_citations(text: str, sources: int) -> str:
    """The answer without [n] markers that point at no source (the model made them up), outside code."""
    def clean(part: str) -> str:
        return CITATION.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= sources else "", part)
    parts = re.split(r"(```.*?```|`[^`\n]*`)", text, flags=re.S)
    return "".join(p if i % 2 else clean(p) for i, p in enumerate(parts))


def fit_history(history: list[dict], budget: int) -> list[dict]:
    """The latest turns that fit in ``budget`` tokens, oldest first, starting with a user turn."""
    kept, used = [], 0
    for m in reversed(history[-HISTORY_TURNS:]):
        cost = tokens(m["content"])
        if used + cost > budget:
            break
        kept.append(m)
        used += cost
    kept.reverse()
    while kept and kept[0]["role"] != "user":
        kept.pop(0)
    return kept


def plan(turn: Turn) -> dict:
    """The model to call, its extra body, the thinking budget and max_tokens, and the prompt's token budget."""
    from athena.core import llm
    has_images = any(a["kind"] == "image" for a in turn.attachments)
    model = llm.chat_preset(turn.model, turn.context, has_images)
    extra, budget = llm.effort_extra(turn.model, turn.effort)
    context = llm.model_context(model)
    room = context - ANSWER_TOKENS - 256
    if room - budget < MIN_PROMPT_TOKENS and budget:  # a small context: think less rather than forget the question
        budget = max(room - MIN_PROMPT_TOKENS, 0)
        extra, _ = llm.effort_extra(turn.model, turn.effort)
        if budget < 256:
            extra, budget = llm.effort_extra(turn.model, "off")
        elif "reasoning_budget_tokens" in extra:
            extra["reasoning_budget_tokens"] = budget
    return {"model": model, "extra": extra, "budget": budget, "max_tokens": budget + ANSWER_TOKENS,
            "prompt_budget": max(context - budget - ANSWER_TOKENS - 256, 1024)}


def _delta_field(delta, name: str):
    value = getattr(delta, name, None)
    if value is None and getattr(delta, "model_extra", None):
        value = delta.model_extra.get(name)
    return value


async def run(turn: Turn, retrieve, tool_runner, save, client=None):
    """Stream one turn as events. ``retrieve(question)`` returns the project's passages, ``tool_runner(ctx, name,
    args)`` runs a tool, ``save(fields)`` writes the assistant message and returns it; all three are synchronous
    and run in a thread. The message is saved however the turn ends: done, failed, or stopped by the user."""
    from fastapi.concurrency import run_in_threadpool

    from athena.core import llm, usage
    from athena.model_server import activity, lane, loading
    from athena.projects import files as uploads
    from athena.projects.tools import LABELS, TOOLS, Context

    ctx = Context(user_id=turn.user_id, project_id=turn.project_id, conversation_id=turn.conversation_id,
                  message_id=turn.message_id)
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    steps: list[dict] = []
    reasoning_ms = 0
    counted_in = counted_out = 0
    status, error = "stopped", None
    setup = plan(turn)
    estimate = tokens(turn.question)  # until the messages are built; the server's counts win
    timing = {"predicted_n": 0, "predicted_ms": 0.0, "prompt_n": 0, "prompt_ms": 0.0}
    kept = [0, 0]  # the last call's prompt and answer tokens: what the context holds after this turn
    asked_at = first_token_at = load_ms = None
    model_call = None  # the model call running now (athena.model_server.activity)
    lane.hold()

    try:
        passages: list[dict] = []
        if turn.project_id:
            try:
                found = await run_in_threadpool(retrieve, turn.question)
                for p in found:
                    n = ctx.add_source({"kind": p.kind, "title": p.title, "link": p.link, "excerpt": p.text[:400],
                                        "source": p.source, "score": p.score})
                    passages.append({"n": n, "title": p.title, "kind": p.kind, "text": p.text})
            except Exception as exc:  # no embedding model: answer without the project's passages
                logger.warning(f"Chat {turn.conversation_id}: project search failed: {exc}")
                yield {"type": "notice", "text": "The project could not be searched (is the embedding model "
                                                 "running?); this answer does not use its documents."}
        if ctx.sources:
            yield {"type": "sources", "sources": list(ctx.sources)}

        image_urls = {}
        for a in turn.attachments:
            if a["kind"] == "image":
                image_urls[a["id"]] = await run_in_threadpool(uploads.image_data_url, a["path"], a["mime"])
        system = system_prompt(turn, setup["prompt_budget"])
        content = user_content(turn, passages, image_urls)
        used = tokens(content if isinstance(content, str) else content[-1]["text"])
        room = setup["prompt_budget"] - tokens(system) - 800 * len(image_urls) - used
        files, notices = files_block(turn, int(max(room, 0) * FILES_SHARE))
        for text in notices:
            yield {"type": "notice", "text": text}
        if files:
            system = system_prompt(turn, setup["prompt_budget"], files)
            room -= tokens(files)
        messages = [{"role": "system", "content": system}] + fit_history(turn.history, room) + [
            {"role": "user", "content": content}]
        estimate = sum(tokens(m["content"] if isinstance(m["content"], str) else json.dumps(m["content"]))
                       for m in messages)

        target = await run_in_threadpool(loading.target_of, setup["model"])
        if target:  # load the model first, showing how far it has got
            state = await run_in_threadpool(loading.state_of, target)
            if state["status"] != "loaded":
                began = time.monotonic()
                loading.warm_target(target)
                while state["status"] not in ("loaded", "failed") and time.monotonic() - began < LOAD_WAIT:
                    yield {"type": "loading", "state": state}
                    await asyncio.sleep(0.5)
                    state = await run_in_threadpool(loading.state_of, target)
                yield {"type": "loading", "state": state}
                load_ms = int((time.monotonic() - began) * 1000)
                if state["status"] == "failed":
                    raise RuntimeError(f"{turn.model} failed to load. An admin can check it in Settings → Models "
                                       "and keys.")

        client = client or llm.async_chat_client(model=setup["model"])
        held = time.monotonic()
        for step in range(MAX_STEPS + 1):
            offer_tools = step < MAX_STEPS
            kwargs = {"tools": TOOLS} if offer_tools else {}
            model_call = activity.start("chat", setup["model"], user_id=turn.user_id)
            stream = await client.chat.completions.create(
                model=setup["model"], messages=list(messages), max_tokens=setup["max_tokens"], stream=True,
                temperature=0.6 if setup["budget"] else 0.7, stream_options={"include_usage": True},
                extra_body=setup["extra"], **kwargs)
            asked_at = asked_at or time.monotonic()
            calls: dict[int, dict] = {}
            text_parts: list[str] = []
            think_started = None
            step_timings = None
            async for chunk in stream:
                if time.monotonic() - held > 20:  # still answering: background work keeps waiting
                    lane.hold()
                    held = time.monotonic()
                step_timings = (getattr(chunk, "model_extra", None) or {}).get("timings") or step_timings
                if getattr(chunk, "usage", None):
                    i, o = usage.tokens_of(chunk.usage)
                    counted_in, counted_out = counted_in + i, counted_out + o
                    kept[:] = [i, o]
                    model_call.tokens(i, o)
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                thought = _delta_field(delta, "reasoning_content")
                if first_token_at is None and (thought or delta.content or delta.tool_calls):
                    first_token_at = time.monotonic()
                if thought:
                    think_started = think_started or time.monotonic()
                    reasoning_parts.append(thought)
                    yield {"type": "reasoning", "text": thought}
                if delta.content or delta.tool_calls:
                    if think_started:
                        reasoning_ms += int((time.monotonic() - think_started) * 1000)
                        think_started = None
                if delta.content:
                    text_parts.append(delta.content)
                    yield {"type": "token", "text": delta.content}
                for tc in delta.tool_calls or []:
                    call = calls.setdefault(tc.index or 0, {"id": None, "name": "", "arguments": ""})
                    call["id"] = tc.id or call["id"]
                    if tc.function and tc.function.name:
                        call["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        call["arguments"] += tc.function.arguments
            activity.finish(model_call)
            if think_started:
                reasoning_ms += int((time.monotonic() - think_started) * 1000)
            for key in timing:
                timing[key] += (step_timings or {}).get(key) or 0
            text = "".join(text_parts)
            if text.strip():
                content_parts.append(text.strip())
            if not calls:
                break
            messages.append({"role": "assistant", "content": text or None, "tool_calls": [
                {"id": c["id"] or f"call_{step}_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                for i, c in sorted(calls.items())]})
            for i, c in sorted(calls.items()):
                try:
                    args = json.loads(c["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                shown = {k: v for k, v in args.items() if k not in ("content", "edits")} if isinstance(args, dict) \
                    else {}
                step_info = {"id": c["id"] or f"call_{step}_{i}", "tool": c["name"],
                             "label": LABELS.get(c["name"], c["name"]), "args": shown, "status": "running"}
                yield {"type": "tool", "step": step_info}
                before_sources, before_artifacts = len(ctx.sources), list(ctx.artifacts)
                result, info = await run_in_threadpool(tool_runner, ctx, c["name"], c["arguments"])
                step_info = step_info | {"status": "done" if info.get("ok") else "failed"} | {
                    k: v for k, v in info.items() if k != "ok"}
                steps.append(step_info)
                yield {"type": "tool", "step": step_info}
                if len(ctx.sources) > before_sources:
                    yield {"type": "sources", "sources": list(ctx.sources)}
                for a in ctx.artifacts:
                    if a not in before_artifacts:
                        yield {"type": "artifact", "artifact": a}
                messages.append({"role": "tool", "tool_call_id": step_info["id"], "content": result})
        status = "done"
    except Exception as exc:
        logger.warning(f"Chat {turn.conversation_id}: the model failed: {exc}")
        status, error = "failed", f"The model did not answer: {str(exc)[:300]}"
        if model_call:
            activity.finish(model_call, exc)
        yield {"type": "error", "message": error}
    finally:
        if model_call:
            activity.finish(model_call, GeneratorExit())  # the page went away mid-answer; a no-op otherwise
        answer = drop_unknown_citations("\n\n".join(content_parts), len(ctx.sources))
        prompt_tokens = counted_in or estimate
        output_tokens = counted_out or tokens(answer + "".join(reasoning_parts))
        lane.hold(30)  # a follow-up usually comes soon
        fields = {"content": answer, "reasoning": "".join(reasoning_parts) or None,
                  "stats": turn_stats(setup["model"], timing, asked_at, first_token_at, load_ms,
                                      sum(kept) or None),
                  "reasoning_ms": reasoning_ms or None, "steps": steps, "sources": ctx.sources,
                  "artifacts": ctx.artifacts, "map_refs": digest_mentions(answer, turn) or None,
                  "model": setup["model"], "effort": turn.effort, "status": status,
                  "error": error, "input_tokens": prompt_tokens, "output_tokens": output_tokens}
        if status == "stopped":  # the page went away: no awaiting here, the task is being cancelled
            save(fields)
            usage.add("chat", setup["model"], prompt_tokens, output_tokens, user_id=turn.user_id)
    saved = await run_in_threadpool(save, fields)
    await run_in_threadpool(usage.add, "chat", setup["model"], prompt_tokens, output_tokens, "chat", turn.user_id)
    yield {"type": "done", "message": saved}


def digest_mentions(answer: str, turn: Turn) -> dict[str, dict]:
    """The shared maps' papers the answer names by id."""
    if not turn.shared_maps:
        return {}
    from athena.evolution import digest
    return digest.mentioned(answer, map_refs(turn))


def turn_stats(preset: str, timing: dict, asked_at: float | None, first_token_at: float | None,
               load_ms: int | None, context_used: int | None = None) -> dict | None:
    """How the answer ran, for the message ({tps, prompt_tps, ttft_ms, load_ms, device, gpu_layers, layers,
    context, context_used}); its speed also updates the model's measured speed (athena.model_server.stats).
    ``context_used`` is what the context held at the end (the last call's prompt and answer), which the chat box
    shows against the context size."""
    from athena.model_server import stats
    rates = {"predicted_n": timing["predicted_n"], "prompt_n": timing["prompt_n"]}
    if timing["predicted_ms"]:
        rates["predicted_per_second"] = timing["predicted_n"] / timing["predicted_ms"] * 1000
    if timing["prompt_ms"]:
        rates["prompt_per_second"] = timing["prompt_n"] / timing["prompt_ms"] * 1000
    try:
        out = stats.record_turn(preset, rates) or {}
    except Exception as exc:
        logger.debug(f"Turn stats not kept: {exc}")
        out = {}
    if not out and rates.get("predicted_per_second"):
        out = {"tps": round(rates["predicted_per_second"], 1)}
    if asked_at and first_token_at:
        out["ttft_ms"] = int((first_token_at - asked_at) * 1000)
    if load_ms:
        out["load_ms"] = load_ms
    if context_used:
        out["context_used"] = context_used
        out.setdefault("context", llm_context(preset))
    return out or None


def llm_context(preset: str) -> int | None:
    from athena.core import llm
    try:
        return llm.model_context(preset)
    except Exception:
        return None


def title_for(question: str, answer: str, model: str) -> str | None:
    """A short title for a new chat, by the model with thinking off; None when it does not answer."""
    from athena.core import llm
    prompt = (f"Write a title of at most six words for a conversation that starts like this. No quotes.\n\n"
              f"User: {question[:1500]}\n\nAssistant: {answer[:1500]}")
    try:
        result, _ = llm.chat_json(prompt, TITLE_SCHEMA, "chat_title", max_tokens=40, timeout=60, feature="chat")
    except Exception as exc:
        logger.info(f"Chat title not written: {exc}")
        return None
    title = ((result or {}).get("title") or "").strip().strip('"').strip()
    return title[:80] or None
