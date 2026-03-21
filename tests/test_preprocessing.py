import pytest
from athena.pipeline.preprocessing import preprocess

def test_preprocess_basic():
    text = "<html><body><h1>Hello World</h1><p>This is a test.</p></body></html>"
    result = preprocess(text, title="Test Title")
    assert "Title: Test Title" in result
    assert "Hello World" in result
    assert "This is a test" in result
    assert "<html>" not in result

def test_preprocess_blocklist():
    text = "<div>Main content</div><nav>Navigation</nav><footer>Footer</footer>"
    result = preprocess(text)
    assert "Main content" in result
    assert "Navigation" not in result
    assert "Footer" not in result

def test_preprocess_url_normalization():
    text = "Check out https://www.google.com/search?q=test for more info."
    result = preprocess(text)
    assert "google.com" in result
    assert "https://" not in result

def test_preprocess_whitespace():
    text = "Multiple    spaces  and \n newlines."
    result = preprocess(text)
    assert "Multiple spaces and newlines." in result

def test_preprocess_truncation():
    text = "Word " * 10000
    result = preprocess(text, max_tokens=10)
    # tiktoken tokens are roughly 4 chars, so 10 tokens is about 40-50 chars
    assert len(result) < 200 # Should be well truncated
