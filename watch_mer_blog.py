#!/usr/bin/env python3
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BLOG_ID = "ranto28"
STATE_FILE = Path("last_seen.txt")
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

def clean_text(s: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in s.splitlines()]
    return "\n".join(x for x in lines if x)

def postview_url(log_no: str) -> str:
    return (
        "https://m.blog.naver.com/PostView.naver"
        f"?blogId={BLOG_ID}&logNo={log_no}&proxyReferer=&noTrackingCode=true"
    )

def get_latest_log_no() -> str:
    """
    Try several public mobile endpoints and locate the newest visible post id.
    We intentionally do not infer article content from search results.
    """
    endpoints = [
        f"https://m.blog.naver.com/{BLOG_ID}",
        f"https://m.blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0&listStyle=post",
        f"https://blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0",
    ]

    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    found = []
    for url in endpoints:
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            html = r.text

            patterns = [
                rf"/{re.escape(BLOG_ID)}/(\d{{8,}})",
                r"logNo=(\d{8,})",
                r'"logNo"\s*:\s*"?(\d{8,})"?',
            ]
            for pat in patterns:
                found.extend(re.findall(pat, html))
        except Exception:
            continue

    if not found:
        raise RuntimeError("최신 글 번호를 찾지 못했습니다.")

    # Naver blog logNo values are effectively increasing identifiers for this blog.
    return max(found, key=int)

def fetch_post(log_no: str):
    url = postview_url(log_no)
    r = requests.get(
        url,
        headers={
            "User-Agent": UA,
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"https://m.blog.naver.com/{BLOG_ID}/{log_no}",
        },
        timeout=20,
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = ""
    for sel in [
        "h3.se_textarea",
        ".se-title-text",
        ".pcol1 .se_textarea",
        "meta[property='og:title']",
        "title",
    ]:
        node = soup.select_one(sel)
        if node:
            title = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
            if title:
                break

    body = ""
    for sel in [".se-main-container", "#postViewArea", ".post-view", ".se_component_wrap"]:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node.get_text("\n", strip=True))
            if len(text) >= 100:
                body = text
                break

    if not body:
        raise RuntimeError(f"글 {log_no}의 본문을 찾지 못했습니다.")

    return title, body, url

def main():
    latest = get_latest_log_no()
    previous = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else ""

    print(f"[previous] {previous or '(none)'}")
    print(f"[latest]   {latest}")

    if previous == latest:
        print("NO_NEW_POST")
        return 0

    # First run: establish baseline only.
    if not previous:
        STATE_FILE.write_text(latest + "\n", encoding="utf-8")
        print("BASELINE_CREATED")
        return 0

    title, body, url = fetch_post(latest)

    Path("latest_post.txt").write_text(
        f"{title}\n{url}\n\n{body}\n",
        encoding="utf-8",
    )
    STATE_FILE.write_text(latest + "\n", encoding="utf-8")

    print("NEW_POST")
    print(f"[title] {title}")
    print(f"[url] {url}")
    print("\n--- BODY ---\n")
    print(body)
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
