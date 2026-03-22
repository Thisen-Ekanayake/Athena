from typing import List, Dict

SYSTEM_PROMPT = """You are Athena, an AI research assistant helping users understand a specific article.
You have been given the full text of the article the user is asking about.

# Behaviour
Answer questions using ONLY information found in the provided article text.
Never answer from your general training knowledge, even if you know the answer.
If the article does not contain enough information to answer the question, say:
  'The article does not cover this specifically. It does discuss: [brief list of what it does cover]'
Always cite the section or part of the article your answer comes from if identifiable.

# Format
Keep answers concise — 2-5 sentences for factual questions.
Use bullet points only if listing 3 or more distinct items.
Do not begin answers with 'Based on the article' or 'According to the article'.
Do not repeat the question back to the user.

# Limitations to state honestly
If the article text is marked as PARTIAL CONTENT, acknowledge this and note
that your answer may be incomplete due to limited article access.
Never fabricate citations, section numbers, or quotes not present in the text."""


def build_messages(
    article_text: str, question: str, history: List[Dict[str, str]],
    custom_sys_prompt: str | None = None
) -> List[Dict[str, str]]:
    sys_prompt = custom_sys_prompt if custom_sys_prompt else SYSTEM_PROMPT
    messages = [{"role": "system", "content": sys_prompt}]

    if not history:
        # Turn 1
        messages.append({
            "role": "user",
            "content": f"[ARTICLE CONTENT]\n\n{article_text}\n\n[QUESTION]\n{question}"
        })
    else:
        # Turn 2+
        # Article content was in the first user message. Reconstruct history.
        # We assume history contains all past turns:
        # [{'role': 'user', 'content': '...'}, {'role': 'assistant', 'content': '...'}]
        # Actually the frontend history might not include the article text in Turn 1, so we inject it.
        # Let's adjust Turn 1 in history to include article if it doesn't already, but since the
        # API is stateless, the frontend sends history as:
        # [{role: "user", content: "question1"}, {role: "assistant", content: "answer1"}, ...]
        # We need to prepend the article context to the FIRST user message in history.
        new_history = list(history)
        if new_history and new_history[0]["role"] == "user":
            original_q = new_history[0]["content"]
            # To avoid adding it multiple times if frontend already did (though frontend shouldn't)
            if "[ARTICLE CONTENT]" not in original_q:
                new_history[0]["content"] = f"[ARTICLE CONTENT]\n\n{article_text}\n\n[QUESTION]\n{original_q}"

        messages.extend(new_history)
        # Add current question
        messages.append({"role": "user", "content": question})

    return messages


def prune_history_if_needed(messages: List[Dict[str, str]], max_tokens: int = 8000) -> List[Dict[str, str]]:
    # Extremely naive token estimation
    def est_tokens(text):
        return len(text.split()) * 1.3

    current_tokens = sum(est_tokens(m["content"]) for m in messages)

    # Prune oldest turns from history (keep system prompt and turn 1 context if possible,
    # but actually we can't easily prune turn 1 without losing context)
    # The requirement: "Prune oldest turns from history before sending"
    # Wait, Turn 1 has the context. If we prune Turn 1, we lose context.
    # Usually we prune turns 2, 3.. and keep Turn 1 and the recent ones.
    if current_tokens > max_tokens and len(messages) > 3:
        # preserve system [0] and context [1]
        preserved = messages[:2]
        # preserve the latest question
        recent = messages[-1:]
        # try to keep as many recent history pairs as possible
        middle = messages[2:-1]

        while middle and current_tokens > max_tokens:
            # remove 2 messages at a time (user + assistant)
            removed = middle[:2]
            middle = middle[2:]
            current_tokens -= sum(est_tokens(m["content"]) for m in removed)

        return preserved + middle + recent

    return messages
