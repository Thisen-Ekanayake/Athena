import os
import re
import httpx
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup
import pdfplumber
from datetime import datetime
from typing import Optional
from loguru import logger
from playwright.async_api import async_playwright

from athena.core.models import ContentItem


class FetchResult:
    def __init__(self, text: str, method: str, word_count: int, partial: bool = False):
        self.text = text
        self.method = method
        self.word_count = word_count
        self.partial = partial


def is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf") or "arxiv.org/pdf" in url.lower()


def file_age_days(path: Path) -> float:
    age = datetime.utcnow().timestamp() - path.stat().st_mtime
    return age / (24 * 3600)


async def try_direct_fetch(url: str) -> Optional[FetchResult]:
    logger.info(f"Trying direct HTTP fetch for {url}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, 'html.parser')
            # remove scripts and styles
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            text = soup.get_text(separator=' ', strip=True)
            word_count = len(text.split())
            if word_count > 200:
                return FetchResult(text=text, method='http', word_count=word_count)
    except Exception as e:
        logger.warning(f"Direct fetch failed for {url}: {e}")
    return None


async def try_playwright_fetch(url: str) -> Optional[FetchResult]:
    logger.info(f"Trying playwright fetch for {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            html_content = await page.content()
            await browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            text = soup.get_text(separator=' ', strip=True)
            word_count = len(text.split())
            if word_count > 200:
                return FetchResult(text=text, method='playwright', word_count=word_count)
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
    return None


async def try_pdf_fetch(url: str) -> Optional[FetchResult]:
    logger.info(f"Trying PDF fetch for {url}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            if resp.status_code != 200:
                return None

            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            text = ""
            with pdfplumber.open(tmp_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
            os.remove(tmp_path)

            word_count = len(text.split())
            if word_count > 50:  # PDFs might be shorter if they are mostly images, but 50 is a safe lower bound
                return FetchResult(text=text, method='pdf', word_count=word_count)
    except Exception as e:
        logger.warning(f"PDF fetch failed for {url}: {e}")
    return None


async def fetch_article_content(item: ContentItem) -> FetchResult:
    # Tier 1: Staging file
    staging = Path(f'/tmp/athena/staging/{item.id}.txt')
    if staging.exists() and file_age_days(staging) < 7:
        text = staging.read_text(encoding='utf-8', errors='ignore')
        return FetchResult(text=text, method='staged', word_count=len(text.split()))

    url = item.url
    # For Arxiv URLs we can guess PDF link
    if "arxiv.org/abs/" in url:
        pdf_url = url.replace("/abs/", "/pdf/")
        if not pdf_url.endswith(".pdf"):
            pdf_url += ".pdf"
        url = pdf_url

    is_pdf = is_pdf_url(url)

    # Tier 2: Direct HTTP (only for non-pdf)
    if not is_pdf:
        result = await try_direct_fetch(url)
        if result:
            return result

    # Tier 3: Playwright (only for non-pdf, as PDF can't really be scraped this way directly easily)
    if not is_pdf:
        result = await try_playwright_fetch(url)
        if result:
            return result

    # Tier 4: PDF Extraction
    if is_pdf:
        result = await try_pdf_fetch(url)
        if result:
            return result

    # Fallback: Abstract only
    text_content = (
        f"Title: {item.title}\n"
        f"Abstract: {item.abstract or 'No abstract provided.'}\n\n"
        "Note: This is partial content generated from the metadata because "
        "the full article could not be accessed."
    )
    return FetchResult(text=text_content, method='abstract_only', word_count=len(text_content.split()), partial=True)


class Section:
    def __init__(self, heading: str, text: str):
        self.heading = heading
        self.text = text


def split_by_headings(text: str) -> list[Section]:
    lines = text.split('\n')
    sections = []
    current_heading = "introduction"
    current_text = []

    # naive heading split
    heading_pattern = re.compile(r'^(?:[0-9]+[\.\)])?\s*[A-Z][a-zA-Z\s]{2,40}$')

    for line in lines:
        sline = line.strip()
        if not sline:
            continue
        if heading_pattern.match(sline) and len(sline) < 60:
            sections.append(Section(heading=current_heading, text="\n".join(current_text)))
            current_heading = line.strip()
            current_text = []
        else:
            current_text.append(line)

    sections.append(Section(heading=current_heading, text="\n".join(current_text)))
    return [s for s in sections if s.text.strip()]


def truncate_to_token_limit(sections: list[Section], max_tokens: int) -> str:
    # Approx 1 token = 0.75 words. For simplicity max_words = max_tokens * 0.75
    max_words = int(max_tokens * 0.75)

    final_text = []
    current_words = 0
    for s in sections:
        section_text = f"{s.heading}\n{s.text}\n"
        words = section_text.split()
        if current_words + len(words) <= max_words:
            final_text.append(section_text)
            current_words += len(words)
        else:
            # truncate remaining part
            allowed = max_words - current_words
            if allowed > 0:
                final_text.append(" ".join(words[:allowed]))
            break

    return "\n".join(final_text)


def select_relevant_sections(text: str, question: str, max_tokens: int) -> str:
    sections = split_by_headings(text)
    must_include = ['abstract', 'introduction', 'conclusion', 'discussion']

    fixed = []
    rest = []
    for s in sections:
        if any(k in s.heading.lower() for k in must_include):
            fixed.append(s)
        else:
            rest.append(s)

    question_tokens = set(question.lower().split())

    scored = []
    for section in rest:
        overlap = len(question_tokens & set(section.text.lower().split()))
        scored.append((overlap, section))

    scored.sort(reverse=True, key=lambda x: x[0])
    selected = fixed + [s for _, s in scored]

    return truncate_to_token_limit(selected, max_tokens)
