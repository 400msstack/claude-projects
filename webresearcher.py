#!/usr/bin/env python3
"""
WebResearcher — DuckDuckGo + Gemma による Web情報収集ツール
Phase 1: Query Decomposition (Gemma)
Phase 2: Web Search (DuckDuckGo)
Phase 3: Top 3 Selection
Phase 4: Content Extraction (BeautifulSoup)
Phase 5: Summarization (Gemma)
Phase 6: Save to Obsidian + Index to LocalRAG
"""

import os
import re
import json
from pathlib import Path
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, Response, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── 設定 ───────────────────────────────────────────────
OLLAMA_BASE         = os.getenv("OLLAMA_BASE", "http://localhost:11434")
CHAT_MODEL          = os.getenv("CHAT_MODEL", "gemma3:27b")
DUCKDUCKGO_API_KEY  = os.getenv("DUCKDUCKGO_API_KEY", "")
OUTPUT_DIR          = os.getenv("OUTPUT_DIR", "./output")
RAG_SERVICE_URL     = os.getenv("RAG_SERVICE_URL", "http://localrag:5002")
TOP_PAGES           = 3
SEARCH_PER_KW       = 5

app = Flask(__name__, template_folder="templates")


# ─── Ollama ──────────────────────────────────────────────
def chat(system: str, user: str) -> str:
    res = requests.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": False,
        },
        timeout=120,
    )
    return res.json().get("message", {}).get("content", "")


# ─── Phase 1: Query Decomposition ────────────────────────
def decompose_question(question: str) -> list[str]:
    text = chat(
        "あなたは検索クエリ設計の専門家です。ユーザーの質問を、Web検索に適した具体的なキーワード・フレーズ3つに分解してください。JSONのみを返してください。説明文は不要です。",
        f"質問: {question}\n\n"
        '{"keywords": ["キーワード1", "キーワード2", "キーワード3"]}',
    )
    try:
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            data = json.loads(match.group())
            return data.get("keywords", [question])
    except Exception:
        pass
    return [question]


# ─── Phase 2: Web Search ─────────────────────────────────
def search_duckduckgo(keyword: str, max_results: int = SEARCH_PER_KW) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(keyword, max_results=max_results))
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        print(f"DuckDuckGo error [{keyword}]: {e}")
        return []


def collect_search_results(keywords: list[str]) -> list[dict]:
    """複数キーワードで検索、重複除去して返却"""
    seen_urls = set()
    all_results = []
    for kw in keywords:
        for r in search_duckduckgo(kw):
            url = r["url"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["keyword"] = kw
                all_results.append(r)
    return all_results


# ─── Phase 3: Top N Selection ────────────────────────────
def select_top_pages(results: list[dict], n: int = TOP_PAGES) -> list[dict]:
    return results[:n]


# ─── Phase 4: Content Extraction ─────────────────────────
def fetch_page(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; WebResearcher/1.0)"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if l.strip()]
        return "\n".join(lines[:200])
    except Exception as e:
        print(f"Fetch error [{url}]: {e}")
        return ""


# ─── Phase 5: Summarization ──────────────────────────────
def summarize_page(title: str, content: str, query: str) -> str:
    if not content.strip():
        return "（ページの取得に失敗しました）"
    return chat(
        "あなたは情報要約の専門家です。提供されたWebページの内容を、ユーザーの質問に関連する部分を中心に150〜200字で日本語要約してください。",
        f"質問: {query}\nページタイトル: {title}\n\nページ内容:\n{content[:3000]}\n\n要約:",
    )


# ─── Phase 6: Save & Index ───────────────────────────────
def save_to_obsidian(query: str, keywords: list[str], results: list[dict]) -> str:
    date = datetime.now().strftime("%Y%m%d")
    safe_name = re.sub(r'[^\w\u3000-\u9fff]', '_', query)[:40]
    filename = f"{safe_name}-{date}.md"
    folder = os.path.join(OUTPUT_DIR, "WebResearch")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)

    lines = [
        f"# {query}",
        f"",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Keywords**: {', '.join(keywords)}",
        f"**Source**: WebResearcher (DuckDuckGo + Gemma)",
        "",
        "---",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines += [
            f"## [{i}] {r.get('title', 'No title')}",
            f"",
            f"**URL**: {r.get('url', '')}",
            f"**Keyword**: {r.get('keyword', '')}",
            "",
            r.get("summary", ""),
            "",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def index_to_rag(file_path: str) -> bool:
    """LocalRAGの /index-files エンドポイントを呼び出してインデックス追加"""
    try:
        params = {"paths": json.dumps([file_path])}
        res = requests.get(
            f"{RAG_SERVICE_URL}/index-files",
            params=params,
            stream=True,
            timeout=120,
        )
        for line in res.iter_lines():
            if line and b'"event":"done"' in line:
                return True
        return True
    except Exception as e:
        print(f"RAG index error: {e}")
        return False


# ─── Flask ルート ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("webresearcher.html", chat_model=CHAT_MODEL)


@app.route("/research", methods=["GET"])
def research():
    query         = request.args.get("q", "").strip()
    save_obsidian = request.args.get("save", "true").lower() != "false"
    do_index_rag  = request.args.get("rag", "true").lower() != "false"

    if not query:
        return Response(
            'data: {"event":"error","data":{"msg":"質問を入力してください"}}\n\n',
            mimetype="text/event-stream",
        )

    def generate():
        def ev(event, data):
            return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"

        # Phase 1
        yield ev("phase", {"phase": 1, "msg": "質問をキーワードに分解中..."})
        keywords = decompose_question(query)
        yield ev("keywords", {"keywords": keywords})

        # Phase 2
        yield ev("phase", {"phase": 2, "msg": f"{len(keywords)}個のキーワードでDuckDuckGo検索中..."})
        all_results = collect_search_results(keywords)
        yield ev("search_results", {
            "count": len(all_results),
            "results": [{"title": r["title"], "url": r["url"]} for r in all_results[:10]],
        })

        if not all_results:
            yield ev("error", {"msg": "検索結果が見つかりませんでした"})
            return

        # Phase 3
        top_pages = select_top_pages(all_results)
        yield ev("phase", {"phase": 3, "msg": f"上位 {len(top_pages)} ページを選択"})

        # Phase 4 & 5
        yield ev("phase", {"phase": 4, "msg": "ページ内容を取得・要約中..."})
        for r in top_pages:
            yield ev("extracting", {"url": r["url"], "title": r["title"]})
            content = fetch_page(r["url"])
            summary = summarize_page(r["title"], content, query)
            r["summary"] = summary
            yield ev("summarized", {
                "title": r["title"],
                "url":   r["url"],
                "summary": summary,
            })

        # Phase 6
        saved_path = None
        indexed    = False
        if save_obsidian:
            yield ev("phase", {"phase": 6, "msg": "Obsidianに保存中..."})
            saved_path = save_to_obsidian(query, keywords, top_pages)
            yield ev("saved", {"path": saved_path})

        if do_index_rag and saved_path:
            yield ev("phase", {"phase": 6, "msg": "LocalRAGにインデックス中..."})
            indexed = index_to_rag(saved_path)
            yield ev("indexed", {"success": indexed})

        yield ev("done", {
            "query":      query,
            "keywords":   keywords,
            "results":    top_pages,
            "saved_path": saved_path,
            "indexed":    indexed,
        })

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5003, threaded=True)
