"""
A chat turn: the messages for the model, its streamed thinking and answer, and the tools it calls.

A turn in a project starts with the project's passages that best answer the question (athena.projects.index),
numbered so the answer cites them as [n]; tools can add more sources (athena.projects.tools). The system prompt
carries the project's instructions and what is in it. Files on the message go in as text, images to the vision
model. Everything is fitted into the model's context: the thinking budget and room for the answer first, then the
passages and files, then as many earlier turns as fit.

``run`` yields events for the page (server-sent events, athena.api.routers.chats):
    {"type": "sources", "sources": [...]}        the numbered sources so far
    {"type": "reasoning", "text": "..."}         thinking, as it streams
    {"type": "token", "text": "..."}             the answer, as it streams
    {"type": "tool", "step": {...}}              a tool call starting (status running) and finishing
    {"type": "artifact", "artifact": {...}}      an artifact written or changed
    {"type": "notice", "text": "..."}            something the user should know (no project search, a cut file)
    {"type": "done", "message": {...}}           the saved assistant message
    {"type": "error", "message": "..."}
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from loguru import logger

ANSWER_TOKENS = 4096        # the answer and any document written through a tool call
MIN_PROMPT_TOKENS = 3000    # thinking is cut back before the prompt gets smaller than this
MAX_STEPS = 4               # model calls that may use tools; one more answers without them
CHARS_PER_TOKEN = 3.0       # a cautious estimate (prose runs near 4)
HISTORY_TURNS = 20
TITLE_SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"],
                "additionalProperties": False}

SYSTEM = (
    "You are Athena, a research assistant for AI and machine learning research. Today is {today}.\n\n"
    "Answer clearly and concisely, in Markdown. When numbered sources are given, cite them for every claim that "
    "comes from them as [n]; never invent a citation, and say so plainly when the sources do not answer the "
    "question.\n\n"
    "Tools: search_papers finds papers (Athena's library, Semantic Scholar, arXiv); query_map asks one of Athena's "
    "research maps; write_artifact creates a document the user keeps (use it for drafts, sections, tables or notes "
    "they ask for, then say in one or two sentences what you wrote instead of repeating it); read_artifact and "
    "edit_artifact change an existing one. Only call a tool when it helps answer.")

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
    attachments: list[dict]          # [{id, filename, kind, text, path, mime, caption}]
    model: str
    effort: str
    first_turn: bool
    events: list[dict] = field(default_factory=list)


def system_prompt(turn: Turn) -> str:
    text = SYSTEM.format(today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if turn.project_id:
        catalog = "\n".join(turn.catalog[:60]) or "(nothing yet)"
        if len(turn.catalog) > 60:
            catalog += f"\n…and {len(turn.catalog) - 60} more"
        text += PROJECT.format(name=turn.project_name, catalog=catalog,
                               description=f" {turn.project_description}" if turn.project_description else "")
        if turn.instructions.strip():
            text += INSTRUCTIONS.format(instructions=turn.instructions.strip())
    if turn.artifacts:
        text += "\n\nArtifacts you can read or edit:\n" + "\n".join(
            f"- {a['title']} (id {a['id']}, {a['chars']} characters)" for a in turn.artifacts[:30])
    return text


def user_content(turn: Turn, passages: list[dict], budget: int, image_urls: dict[str, str]) -> tuple[object, list]:
    """The question with its passages and files, within ``budget`` tokens; returns (content, notices)."""
    notices, parts = [], []
    if passages:
        listed = "\n\n".join(f"[{p['n']}] {p['title']} ({p['kind']})\n{p['text']}" for p in passages)
        parts.append(f"Passages from the project:\n\n{listed}")
    used = tokens(turn.question) + sum(tokens(p) for p in parts)
    texts = [a for a in turn.attachments if a["kind"] != "image"]
    for i, a in enumerate(texts):
        share = max((budget - used) // max(len(texts) - i, 1), 200)
        body, cut = clip(a.get("text") or "(no text could be read from this file)", share)
        if cut:
            notices.append(f"{a['filename']} was too long for the model's context; it read the first part.")
        parts.append(f"Attached file {a['filename']}:\n\n{body}")
        used += tokens(body)
    parts.append(turn.question)
    text = "\n\n---\n\n".join(parts)
    images = [a for a in turn.attachments if a["kind"] == "image" and a["id"] in image_urls]
    if not images:
        return text, notices
    return [{"type": "image_url", "image_url": {"url": image_urls[a["id"]]}} for a in images] + \
        [{"type": "text", "text": text}], notices


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
    model = llm.vision_model() if has_images else turn.model
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
        system = system_prompt(turn)
        room = setup["prompt_budget"] - tokens(system) - 800 * len(image_urls)
        content, notices = user_content(turn, passages, int(room * 0.7), image_urls)
        for text in notices:
            yield {"type": "notice", "text": text}
        used = tokens(content if isinstance(content, str) else content[-1]["text"])
        messages = [{"role": "system", "content": system}] + fit_history(turn.history, room - used) + [
            {"role": "user", "content": content}]
        estimate = sum(tokens(m["content"] if isinstance(m["content"], str) else json.dumps(m["content"]))
                       for m in messages)

        client = client or llm.async_chat_client()
        for step in range(MAX_STEPS + 1):
            offer_tools = step < MAX_STEPS
            kwargs = {"tools": TOOLS} if offer_tools else {}
            stream = await client.chat.completions.create(
                model=setup["model"], messages=list(messages), max_tokens=setup["max_tokens"], stream=True,
                temperature=0.6 if setup["budget"] else 0.7, stream_options={"include_usage": True},
                extra_body=setup["extra"], **kwargs)
            calls: dict[int, dict] = {}
            text_parts: list[str] = []
            think_started = None
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    i, o = usage.tokens_of(chunk.usage)
                    counted_in, counted_out = counted_in + i, counted_out + o
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                thought = _delta_field(delta, "reasoning_content")
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
            if think_started:
                reasoning_ms += int((time.monotonic() - think_started) * 1000)
            text = "".join(text_parts)
            if text.strip():
                content_parts.append(text)
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
        yield {"type": "error", "message": error}
    finally:
        answer = "\n\n".join(content_parts)
        prompt_tokens = counted_in or estimate
        output_tokens = counted_out or tokens(answer + "".join(reasoning_parts))
        fields = {"content": answer, "reasoning": "".join(reasoning_parts) or None,
                  "reasoning_ms": reasoning_ms or None, "steps": steps, "sources": ctx.sources,
                  "artifacts": ctx.artifacts, "model": setup["model"], "effort": turn.effort, "status": status,
                  "error": error, "input_tokens": prompt_tokens, "output_tokens": output_tokens}
        if status == "stopped":  # the page went away: no awaiting here, the task is being cancelled
            save(fields)
            usage.add("chat", setup["model"], prompt_tokens, output_tokens, user_id=turn.user_id)
    saved = await run_in_threadpool(save, fields)
    await run_in_threadpool(usage.add, "chat", setup["model"], prompt_tokens, output_tokens, "chat", turn.user_id)
    yield {"type": "done", "message": saved}


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
