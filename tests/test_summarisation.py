import pytest
from datetime import datetime, timezone

from athena.core.models import ContentItem, JobType
from athena.pipeline.summarisation import (
    SummaryOutput,
    parse_and_validate,
    check_budget_before_call,
    today_date,
    redis
)
from athena.pipeline.summarisation_tasks import build_item_summary_prompt

def test_summary_output_validation():
    # Valid
    valid_data = {
        "summary": "This is a valid summary " * 5,  # 25 words
        "takeaways": ["Takeaway number one is good", "Takeaway number two is good", "Takeaway number three is good"]
    }
    obj = SummaryOutput(**valid_data)
    assert obj.summary == valid_data["summary"]

    # Invalid summary length (too short)
    with pytest.raises(ValueError, match="too short"):
        SummaryOutput(summary="Too short", takeaways=valid_data["takeaways"])

    # Invalid takeaways length (not enough)
    with pytest.raises(ValueError, match="at least 3"):
        SummaryOutput(summary=valid_data["summary"], takeaways=["Only one takeaway"])

    # Invalid takeaways string length
    with pytest.raises(ValueError, match="too short"):
        SummaryOutput(summary=valid_data["summary"], takeaways=["Short", "Takeaway two is fine", "Takeaway three is fine"])

def test_parse_and_validate():
    raw_str = '''```json
{
  "summary": "The authors introduce a new method for training large language models that significantly reduces memory overhead while maintaining performance across various benchmarks.",
  "takeaways": [
    "New training method reduces memory usage by 40%.",
    "Performance is maintained on MMLU and other benchmarks.",
    "The code is open source and available on GitHub."
  ]
}
```'''
    res = parse_and_validate(raw_str)
    assert isinstance(res, SummaryOutput)
    assert len(res.takeaways) == 3

def test_build_item_summary_prompt():
    from athena.core.models import Source, ContentCategory
    
    item = ContentItem(
        title="Test Paper",
        authors=["Alice", "Bob"],
        published_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
    )
    item.source = Source(name="Arxiv")
    item.category = ContentCategory.PAPER

    prompt_tpl = "Title: {title}\nCat: {category}\nText: {preprocessed_text}"
    text = "Some abstract text here."

    result = build_item_summary_prompt(item, text, prompt_tpl)
    assert "Title: Test Paper" in result
    assert "Cat: paper" in result
    assert "Text: Some abstract text here." in result

def test_redis_budgeting():
    # Clear the key first
    key = 'summary_spend:' + today_date()
    redis.delete(key)

    assert check_budget_before_call(JobType.ITEM_SUMMARY.value) is True

    # Simulate spending exactly budget limit
    # Default is 5.00
    redis.set(key, "5.01")
    assert check_budget_before_call(JobType.ITEM_SUMMARY.value) is False

    # Cleanup
    redis.delete(key)
