import re
import unicodedata
from bs4 import BeautifulSoup
import tiktoken
from typing import List


def preprocess(
    text: str,
    title: str = "",
    authors: List[str] = [],
    abstract: str = "",
    max_tokens: int = 8000,
    model_name: str = "text-embedding-3-small"
) -> str:
    """
    Athena Layer 2 Preprocessing:
    1. Strip HTML tags
    2. Remove navigation, footer, sidebar elements
    3. Normalize whitespace
    4. Normalize URLs (domain only)
    5. Normalize Unicode (NFKC)
    6. Structured prefixing
    7. Truncate to token limit
    """

    # 1. Strip HTML & 2. Blocklist-based removal
    soup = BeautifulSoup(text, "lxml")

    # Blocklist
    blocklist = ["nav", "footer", "sidebar", "cookie-banner", "header", "aside"]
    for tag in soup.find_all(True):
        if any(cls in tag.get("class", []) for cls in blocklist) or \
           any(id_ in tag.get("id", "") for id_ in blocklist) or \
           tag.name in blocklist:
            tag.decompose()

    clean_text = soup.get_text(separator=" ")

    # 4. Normalize URLs (replace with domain)
    # Simple regex for URLs
    url_pattern = re.compile(r'https?://(?:www\.)?([^/\s]+)[^\s]*')
    clean_text = url_pattern.sub(r'\1', clean_text)

    # 5. Unicode normalization (NFKC)
    clean_text = unicodedata.normalize("NFKC", clean_text)

    # 3. Normalize whitespace
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    # 6. Structured prefixing
    authors_str = ", ".join(authors) if authors else "Unknown"
    structured_text = f"Title: {title} | Authors: {authors_str} | Abstract: {abstract} | Body: {clean_text}"

    # 7. Truncate to token limit
    try:
        encoding = tiktoken.encoding_for_model(model_name)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")  # Fallback for text-embedding-3

    tokens = encoding.encode(structured_text)
    if len(tokens) > max_tokens:
        tokens = tokens[:max_tokens]
        structured_text = encoding.decode(tokens)

    return structured_text
