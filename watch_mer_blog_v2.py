#!/usr/bin/env python3
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BLOG_ID = "ranto28"
STATE_FILE = Path("last_seen.txt")
OUTPUT_FILE = Path("latest_post.txt")

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

def clean_text(s: str) -> str:
    lines = [re.sub(r"\s+", " ", x).strip() for x in s.splitlines()]
    return "\n".join(x for x in lines if x)

def postview_url(log_no: str) -> str:
    return (
        "https://m.blog.naver.com/PostView.naver"
        f"?blogId={BLOG_ID}&logNo={log_no}&proxyReferer=&noTrackingCode=true"
    )

def extract_log_nos(text: str):
    patterns = [
        rf"https?://(?:m\.)?blog\.naver\.com/{re.escape(BLOG_ID)}/(\d{{8,}})",
        r"logNo[=:\"']+\s*\"?(\d{8,})",
        r'"logNo"\s*:\s*"?(\d{8,})"?',
        rf"/{re.escape(BLOG_ID)}/(\d{{8,}})",
    ]
    found = []
    for pat in patterns:
        found.extend(re.findall(pat, text, flags=re.I))
    return found

def latest_from_rss(session):
    url = f"https://rss.blog.naver.com/{BLOG_ID}.xml"
    try:
        r = session.get(url, timeout=20)
        print(f"[check] RSS {r.status_code} {url}")
        r.raise_for_status()

        # First try XML parsing.
        try:
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                candidates = []
                for tag in ("link", "guid"):
                    node = item.find(tag)
                    if node is not None and node.text:
                        candidates += extract_log_nos(node.text)
                if candidates:
                    return candidates[0]
        except Exception as e:
            print(f"[debug] RSS XML parse failed: {e}")

        # Then regex the raw feed.
        ids = extract_log_nos(r.text)
        if ids:
            return ids[0]
    except Exception as e:
        print(f"[debug] RSS failed: {e}")
    return None

def latest_from_pages(session):
    urls = [
        f"https://m.blog.naver.com/{BLOG_ID}",
        f"https://m.blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0&currentPage=1",
        f"https://m.blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0&listStyle=post&currentPage=1",
        f"https://blog.naver.com/PostList.naver?blogId={BLOG_ID}&categoryNo=0&currentPage=1",
    ]

    all_ids = []
    for url in urls:
        try:
            r = session.get(url, timeout=20)
            print(f"[check] PAGE {r.status_code} {url} len={len(r.text)}")
            if r.status_code >= 400:
                continue

            ids = extract_log_nos(r.text)
            if ids:
                print(f"[debug] found ids: {ids[:5]}")
                all_ids.extend(ids)
            else:
                print("[debug] no logNo found on this page")
        except Exception as e:
            print(f"[debug] page failed: {e}")

    if not all_ids:
        return None

    # For this blog, larger logNo corresponds to newer posts.
    return max(set(all_ids), key=int)

def get_latest_log_no():
    session = requests.Session()
    session.headers.update(HEADERS)

    latest = latest_from_rss(session)
    if latest:
        print(f"[source] rss -> {latest}")
        return latest

    latest = latest_from_pages(session)
    if latest:
        print(f"[source] page -> {latest}")
        return latest

    raise RuntimeError("ìµì  ê¸ ë²í¸ë¥¼ RSSì ë¸ë¡ê·¸ ëª©ë¡ ëª¨ëìì ì°¾ì§ ëª»íìµëë¤.")

def fetch_post(log_no: str):
    url = postview_url(log_no)
    headers = dict(HEADERS)
    headers["Referer"] = f"https://m.blog.naver.com/{BLOG_ID}/{log_no}"

    r = requests.get(url, headers=headers, timeout=20)
    print(f"[fetch] post {r.status_code} len={len(r.text)}")
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
    for sel in [
        ".se-main-container",
        "#postViewArea",
        ".post-view",
        ".se_component_wrap",
    ]:
        node = soup.select_one(sel)
        if node:
            text = clean_text(node.get_text("\n", strip=True))
            if len(text) >= 100:
                body = text
                break

    if not body:
        raise RuntimeError(f"ê¸ {log_no}ì ë³¸ë¬¸ì ì°¾ì§ ëª»íìµëë¤.")

    return title, body, url

def main():
    latest = get_latest_log_no()
    previous = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else ""

    print(f"[previous] {previous or '(none)'}")
    print(f"[latest]   {latest}")

    if previous == latest:
        print("NO_NEW_POST")
        return 0

    if not previous:
        STATE_FILE.write_text(latest + "\n", encoding="utf-8")
        print("BASELINE_CREATED")
        return 0

    title, body, url = fetch_post(latest)

    OUTPUT_FILE.write_text(
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
