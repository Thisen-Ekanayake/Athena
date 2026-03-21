from athena.database.db import SessionLocal
from athena.core.models import PromptVersion, JobType


def seed_prompts():
    session = SessionLocal()
    try:
        if session.query(PromptVersion).first():
            print("Prompts already seeded.")
            return

        # 1. Item Summary
        sys_item = '''You are a senior AI researcher writing concise summaries for a research discovery tool.
Your audience is technical: ML engineers, researchers, and AI practitioners.
# Task
Given a research paper or blog post, produce two outputs:
1. summary: A 2-3 sentence summary. Cover what the work does, what makes it
   significant, and what the key result or contribution is. Be specific.
   Avoid vague phrases like 'the authors explore' or 'this paper discusses'.
2. takeaways: A JSON array of 3-5 key takeaway strings. Each takeaway is one
   punchy sentence. Focus on actionable insights or surprising findings.
# Format
Return ONLY valid JSON. No markdown, no preamble, no explanation.
{
  "summary": "string",
  "takeaways": ["string", "string", "string"]
}
# Rules
Do not begin the summary with the title or 'This paper'.
Do not use the word 'delve'.
If the content is a blog post, not a paper, adjust tone accordingly.
Always include at least one concrete number, result, or benchmark if present.'''

        user_item = '''Title: {title}
Authors: {authors}
Category: {category}
Source: {source_name}
Published: {published_at}

Content:
{preprocessed_text}'''

        p1 = PromptVersion(
            job_type=JobType.ITEM_SUMMARY,
            version=1,
            system_prompt=sys_item,
            user_prompt_tpl=user_item,
            is_active=True,
            notes="Initial seed"
        )

        # 2. Cluster Labelling
        sys_cluster = '''You are labelling a topic cluster for an AI research discovery tool.
A cluster is a group of related research papers and articles grouped by semantic similarity.
# Task
Given the titles and abstracts of the most representative items in a cluster,
produce a short label and a 2-sentence description that names the cluster's topic.
# Format
Return ONLY valid JSON. No markdown, no preamble.
{
  "label": "string (4-8 words, title case)",
  "description": "string (2 sentences, what this cluster covers and why it matters)"
}
# Rules
The label must be specific, not generic. 'Efficient LLM Fine-Tuning Methods' is good.
'Machine Learning Research' is too broad and unacceptable.
Do not use the word 'cluster' or 'group' in the label or description.'''

        user_cluster = '''Cluster contains {item_count} items. Here are the top 5 representative items:

{items_str}'''

        p2 = PromptVersion(
            job_type=JobType.CLUSTER_LABEL,
            version=1,
            system_prompt=sys_cluster,
            user_prompt_tpl=user_cluster,
            is_active=True,
            notes="Initial seed"
        )

        # 3. Trending Brief
        sys_trend = '''You are writing a daily trend digest for an AI research discovery platform.
# Task
Given the summaries of the top 5 trending items in a content category today,
write a 3-sentence digest that captures the overall trend or theme emerging.
Speak like a sharp, informed colleague, not a press release.
# Format
Return ONLY valid JSON.
{
  "brief": "string (3 sentences, present tense, specific)",
  "theme": "string (3-6 word theme label)"
}
If the items have no clear common theme, say so honestly in the brief.
Do not invent connections that are not there.'''

        user_trend = '''Top 5 trending items in {category} today:

{items_str}'''

        p3 = PromptVersion(
            job_type=JobType.TRENDING_BRIEF,
            version=1,
            system_prompt=sys_trend,
            user_prompt_tpl=user_trend,
            is_active=True,
            notes="Initial seed"
        )

        session.add_all([p1, p2, p3])
        session.commit()
        print("Successfully seeded prompts.")

    finally:
        session.close()


if __name__ == "__main__":
    seed_prompts()
