#!/usr/bin/env python3
import argparse, json, re, sys
from dataclasses import dataclass, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

@dataclass
class Post:
    blog_id: str
    log_no: str
    url: str
    title: Optional[str] = None
    text: Optional[str] = None
    method: Optional[str] = None


def postview_url(blog_id: str, log_no: str) -> str:
    return (
        "https://m.blog.naver.com/PostView.naver"
        f"?blogId={blog_id}&logNo={log_no}&proxyReferer=&noTrackingCode=true"
    )


def clean_text(s: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in s.splitlines()]
    lines = [x for x in lines if x]
    return "\n".join(lines)


def extract_from_html(html: str) -> tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")

    title = None
    for sel in [
        "h3.se_textarea",
        ".se-title-text",
        ".pcol1 .se_textarea",
        "meta[property='og:title']",
        "title",
    ]:
        node = soup.select_one(sel)
        if not node:
            continue
        title = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
        if title:
            break

    candidates = [
        ".se-main-container",      # SmartEditor ONE
        "#postViewArea",          # older mobile/legacy
        ".post-view",             # alternate layouts
        ".se_component_wrap",
    ]

    body = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            txt = clean_text(node.get_text("\n", strip=True))
            if len(txt) >= 100:
                body = txt
                break

    return title, body


def fetch_requests(blog_id: str, log_no: str, timeout: int = 20) -> Post:
    url = postview_url(blog_id, log_no)
    r = requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"https://m.blog.naver.com/{blog_id}/{log_no}",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    title, text = extract_from_html(r.text)
    if not text:
        raise RuntimeError("HTTP 응답은 받았지만 본문 DOM을 찾지 못했습니다.")
    return Post(blog_id, log_no, url, title, text, "requests")


def fetch_playwright(blog_id: str, log_no: str, timeout_ms: int = 30000) -> Post:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright가 설치되어 있지 않습니다. pip install playwright && playwright install chromium") from e

    url = postview_url(blog_id, log_no)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            locale="ko-KR",
            viewport={"width": 390, "height": 844},
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # Give dynamic editor blocks a moment to render.
        page.wait_for_timeout(1200)
        html = page.content()
        title, text = extract_from_html(html)

        # Direct DOM fallback for SmartEditor blocks.
        if not text:
            for sel in [".se-main-container", "#postViewArea", ".post-view"]:
                loc = page.locator(sel)
                if loc.count():
                    txt = clean_text(loc.first.inner_text())
                    if len(txt) >= 100:
                        text = txt
                        break

        browser.close()

    if not text:
        raise RuntimeError("브라우저 렌더링 후에도 본문을 찾지 못했습니다.")
    return Post(blog_id, log_no, url, title, text, "playwright")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blog-id", default="ranto28")
    ap.add_argument("--log-no", default="224417472652")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    errors = []
    post = None

    try:
        post = fetch_requests(args.blog_id, args.log_no)
    except Exception as e:
        errors.append(f"requests: {e}")

    if post is None:
        try:
            post = fetch_playwright(args.blog_id, args.log_no)
        except Exception as e:
            errors.append(f"playwright: {e}")

    if post is None:
        print("수집 실패", file=sys.stderr)
        for e in errors:
            print("-", e, file=sys.stderr)
        sys.exit(2)

    if args.json:
        print(json.dumps(asdict(post), ensure_ascii=False, indent=2))
    else:
        print(f"[method] {post.method}")
        print(f"[title] {post.title or ''}")
        print(f"[url] {post.url}")
        print("\n--- BODY ---\n")
        print(post.text)


if __name__ == "__main__":
    main()
