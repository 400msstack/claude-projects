#!/usr/bin/env python3
"""
LocalRAG — Ollamaを使ったローカル文書Q&Aアプリ
埋め込み: nomic-embed-text
回答生成: gemma3:27b
ベクトルDB: ChromaDB（ローカル保存）
"""

import os
import re
import json
import queue
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify
import chromadb
from chromadb.config import Settings
import requests

# .envがあれば読み込む
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── 設定 ───────────────────────────────────────────────
OLLAMA_BASE       = os.getenv("OLLAMA_BASE", "http://localhost:11434")
EMBED_MODEL       = os.getenv("EMBED_MODEL", "nomic-embed-text")
CHAT_MODEL        = os.getenv("CHAT_MODEL", "gemma3:27b")
CHROMA_DIR        = os.getenv("CHROMA_DIR", "./rag_db")
OUTPUT_DIR        = os.getenv("OUTPUT_DIR", "./output")
LANG_UI           = os.getenv("LANG_UI", "ja")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CHUNK_SIZE     = 500
CHUNK_OVERLAP  = 50
TOP_K          = 5

app = Flask(__name__, template_folder="templates")

# ChromaDB初期化
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)


# ─── Ollama呼び出し ──────────────────────────────────────
def embed(text: str) -> list[float]:
    res = requests.post(f"{OLLAMA_BASE}/api/embeddings",
                        json={"model": EMBED_MODEL, "prompt": text})
    return res.json()["embedding"]


def stream_chat(system: str, user: str):
    """ストリーミングでトークンを生成"""
    res = requests.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "stream": True,
        },
        stream=True,
    )
    for line in res.iter_lines():
        if line:
            data = json.loads(line)
            token = data.get("message", {}).get("content", "")
            if token:
                yield token
            if data.get("done"):
                break


# ─── テキスト処理 ────────────────────────────────────────
def read_file(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        import pymupdf
        doc = pymupdf.open(path)
        return "\n".join(page.get_text() for page in doc)
    elif ext in (".md", ".txt"):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


def split_chunks(text: str, source: str) -> list[dict]:
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append({
                "id":     f"{source}_{idx}",
                "text":   chunk,
                "source": source,
            })
            idx += 1
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── インデックス管理 ────────────────────────────────────
def get_or_create_collection(name: str = "documents"):
    return chroma_client.get_or_create_collection(name=name)


def index_files(paths: list[str], q: queue.Queue):
    def send(event, data):
        q.put({"event": event, "data": data})

    collection = get_or_create_collection()
    total = len(paths)

    for i, path in enumerate(paths):
        filename = os.path.basename(path)
        send("progress", {"msg": f"読み込み中: {filename}", "current": i, "total": total})

        text = read_file(path)
        if not text.strip():
            send("progress", {"msg": f"スキップ: {filename}（内容なし）", "current": i+1, "total": total})
            continue

        chunks = split_chunks(text, filename)
        send("progress", {"msg": f"ベクトル化中: {filename}（{len(chunks)}チャンク）", "current": i, "total": total})

        for chunk in chunks:
            # 既存のIDを上書き（再インデックス対応）
            try:
                collection.delete(ids=[chunk["id"]])
            except Exception:
                pass
            embedding = embed(chunk["text"])
            collection.add(
                ids=[chunk["id"]],
                embeddings=[embedding],
                documents=[chunk["text"]],
                metadatas=[{"source": chunk["source"]}],
            )

        send("progress", {"msg": f"完了: {filename}", "current": i+1, "total": total})

    # 統計
    count = collection.count()
    send("done", {"msg": f"インデックス完了 — 総チャンク数: {count}", "total_chunks": count})
    q.put(None)


# ─── Query Decomposition ────────────────────────────────
def decompose_question(question: str) -> list[str]:
    """漠然とした質問を検索キーワードに分解"""
    res = requests.post(
        f"{OLLAMA_BASE}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": (
                    "あなたは検索クエリ設計の専門家です。"
                    "ユーザーの質問を、ベクトル検索に適した具体的なキーワード・フレーズに分解してください。"
                    "JSONのみを返してください。説明文は不要です。"
                )},
                {"role": "user", "content": (
                    f"質問: {question}\n\n"
                    "この質問を検索に適した3〜5個のキーワードに分解してください。\n"
                    '{"keywords": ["キーワード1", "キーワード2", "キーワード3"]}'
                )},
            ],
            "stream": False,
        },
    )
    text = res.json().get("message", {}).get("content", "")
    try:
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            data = json.loads(match.group())
            return data.get("keywords", [question])
    except Exception:
        pass
    return [question]


def multi_query_search(keywords: list[str], n: int = 3) -> list[dict]:
    """複数キーワードで検索し、重複除去して統合"""
    collection = get_or_create_collection()
    if collection.count() == 0:
        return []
    seen_ids = set()
    all_hits = []
    for kw in keywords:
        q_embed = embed(kw)
        results = collection.query(
            query_embeddings=[q_embed],
            n_results=min(n, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            key = doc[:80]  # 先頭80文字で重複判定
            if key not in seen_ids:
                seen_ids.add(key)
                all_hits.append({
                    "text": doc,
                    "source": meta.get("source", ""),
                    "score": round(1 - dist, 3),
                    "keyword": kw,
                })
    # スコア降順でソート
    return sorted(all_hits, key=lambda x: x["score"], reverse=True)


# ─── Web検索 ────────────────────────────────────────────
def web_search(query: str) -> list[dict]:
    """Anthropic web_search_20250305 toolで外部Web検索"""
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{
                "role": "user",
                "content": (
                    f"次のクエリについてWeb検索し、検索結果を以下のJSON形式のみで返してください（説明文不要）:\n"
                    f"クエリ: {query}\n\n"
                    '{"results": [{"title": "タイトル", "url": "URL", "snippet": "重要な内容の要約（100文字程度）"}]}'
                ),
            }],
        )
        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                match = re.search(r'\{[\s\S]+\}', block.text)
                if match:
                    data = json.loads(match.group())
                    results = data.get("results", [])
                    return [
                        {
                            "text": r.get("snippet", ""),
                            "source": r.get("url", r.get("title", "Web")),
                            "score": 0.75,
                            "type": "web",
                        }
                        for r in results if r.get("snippet")
                    ]
    except Exception as e:
        print(f"Web search error: {e}")
    return []


def web_search_keywords(keywords: list[str]) -> list[dict]:
    """複数キーワードを並行Web検索して統合"""
    all_results = []
    seen_urls = set()

    def _search(kw):
        results = web_search(kw)
        for r in results:
            r["keyword"] = kw
        return results

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_search, kw): kw for kw in keywords[:3]}
        for future in concurrent.futures.as_completed(futures):
            for r in future.result():
                url = r.get("source", "")
                if url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
    return all_results


def rank_and_merge(local_results: list, web_results: list) -> list:
    """LocalRAGとWeb検索結果を統合・スコアリング"""
    for r in local_results:
        r["type"] = "local"
    for r in web_results:
        r["type"] = "web"
        r["score"] = min(r.get("score", 0.75), 0.85)  # Web結果は信頼度で上限補正
    combined = local_results + web_results
    return sorted(combined, key=lambda x: x["score"], reverse=True)


# ─── 検索・回答 ─────────────────────────────────────────
def search(query: str, n: int = TOP_K) -> list[dict]:
    collection = get_or_create_collection()
    if collection.count() == 0:
        return []
    q_embed = embed(query)
    results = collection.query(
        query_embeddings=[q_embed],
        n_results=min(n, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({"text": doc, "source": meta.get("source",""), "score": round(1 - dist, 3)})
    return hits


# ─── Flask ルート ────────────────────────────────────────
@app.route("/")
def index():
    collection = get_or_create_collection()
    chunk_count = collection.count()
    return render_template("rag.html", chunk_count=chunk_count, chat_model=CHAT_MODEL)


@app.route("/index-files", methods=["GET"])
def index_files_stream():
    paths_json = request.args.get("paths", "[]")
    paths = json.loads(paths_json)
    paths = [p for p in paths if os.path.exists(p)]

    if not paths:
        return Response('data: {"event":"error","data":{"msg":"有効なファイルがありません"}}\n\n',
                        mimetype="text/event-stream")

    q = queue.Queue()
    thread = threading.Thread(target=index_files, args=(paths, q), daemon=True)
    thread.start()

    def generate():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/upload-and-index", methods=["POST"])
def upload_and_index():
    """アップロードされたファイルを一時保存してパスを返す"""
    files = request.files.getlist("files")
    saved = []
    tmp_dir = "/tmp/rag_uploads"
    os.makedirs(tmp_dir, exist_ok=True)
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in (".md", ".txt", ".pdf"):
            continue
        path = os.path.join(tmp_dir, f.filename)
        f.save(path)
        saved.append(path)
    return jsonify({"paths": saved})


@app.route("/index-folder", methods=["POST"])
def index_folder():
    data = request.get_json()
    folder = data.get("folder", "").strip()
    if not os.path.isdir(folder):
        return jsonify({"error": f"フォルダが見つかりません: {folder}"}), 400
    paths = []
    for ext in ("*.md", "*.txt", "*.pdf"):
        paths += [
            str(p) for p in Path(folder).rglob(ext)
            if ".obsidian" not in p.parts
        ]
    return jsonify({"paths": paths, "count": len(paths)})


@app.route("/ask", methods=["GET"])
def ask():
    question = request.args.get("q", "").strip()
    if not question:
        return Response('data: {"event":"error","data":{"msg":"質問を入力してください"}}\n\n',
                        mimetype="text/event-stream")

    hits = search(question)
    if not hits:
        return Response('data: {"event":"error","data":{"msg":"インデックスが空です。先にファイルを追加してください。"}}\n\n',
                        mimetype="text/event-stream")

    context = "\n\n---\n\n".join(
        f"【出典: {h['source']}】\n{h['text']}" for h in hits
    )
    sources = list({h["source"] for h in hits})

    system = (
        "あなたは優秀なリサーチアシスタントです。"
        "以下の参考資料のみを根拠に質問に日本語で答えてください。"
        "資料に記載のない情報は「資料には記載がありません」と明示してください。"
    )
    user = f"参考資料:\n{context}\n\n質問: {question}"

    def generate():
        # まずソースを送信
        yield f"data: {json.dumps({'event': 'sources', 'data': {'sources': sources}}, ensure_ascii=False)}\n\n"
        # ストリーミングで回答
        for token in stream_chat(system, user):
            yield f"data: {json.dumps({'event': 'token', 'data': {'text': token}}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/decompose_query", methods=["GET"])
def decompose_query():
    question = request.args.get("q", "").strip()
    source   = request.args.get("source", "local")  # local | web | all
    if not question:
        return Response('data: {"event":"error","data":{"msg":"質問を入力してください"}}\n\n',
                        mimetype="text/event-stream")

    def generate():
        # Step1: 質問を分解
        yield f"data: {json.dumps({'event': 'decomposing', 'data': {'msg': '質問を分解中...'}}, ensure_ascii=False)}\n\n"
        keywords = decompose_question(question)
        yield f"data: {json.dumps({'event': 'keywords', 'data': {'keywords': keywords}}, ensure_ascii=False)}\n\n"

        # Step2: 検索（source指定に応じてLocal / Web / 両方）
        label = {"local": "Local", "web": "Web", "all": "Local + Web"}.get(source, "Local")
        yield f"data: {json.dumps({'event': 'searching', 'data': {'msg': f'{len(keywords)}個のキーワードで検索中（{label}）...'}}, ensure_ascii=False)}\n\n"

        local_hits, web_hits = [], []

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if source in ("local", "all"):
                futures["local"] = executor.submit(multi_query_search, keywords)
            if source in ("web", "all") and ANTHROPIC_API_KEY:
                futures["web"] = executor.submit(web_search_keywords, keywords)
            if "local" in futures:
                local_hits = futures["local"].result()
            if "web" in futures:
                web_hits = futures["web"].result()

        all_hits = rank_and_merge(local_hits, web_hits)

        if not all_hits:
            msg = "インデックスが空です" if source == "local" else "検索結果が見つかりませんでした"
            yield f"data: {json.dumps({'event': 'error', 'data': {'msg': msg}}, ensure_ascii=False)}\n\n"
            return

        local_sources = list({h["source"] for h in all_hits if h.get("type") != "web"})
        web_sources   = list({h["source"] for h in all_hits if h.get("type") == "web"})
        yield f"data: {json.dumps({'event': 'sources', 'data': {'sources': local_sources, 'web_sources': web_sources, 'hit_count': len(all_hits)}}, ensure_ascii=False)}\n\n"

        # Step3: 統合回答生成
        context = "\n\n---\n\n".join(
            f"【出典: {h['source']} / キーワード: {h.get('keyword', '')} / ソース: {'Web' if h.get('type') == 'web' else 'Local'}】\n{h['text']}"
            for h in all_hits[:10]
        )
        system = (
            "あなたは優秀なリサーチアシスタントです。"
            "複数の視点から収集した参考資料（ローカル文書・Web検索結果）を統合し、質問に対して包括的な日本語の回答を作成してください。"
            "資料に記載のない情報は「資料には記載がありません」と明示してください。"
        )
        user = (
            f"元の質問: {question}\n"
            f"検索に使ったキーワード: {', '.join(keywords)}\n\n"
            f"参考資料:\n{context}\n\n"
            "これらの情報を統合して、元の質問に答えてください。"
        )
        for token in stream_chat(system, user):
            yield f"data: {json.dumps({'event': 'token', 'data': {'text': token}}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'event': 'done', 'data': {}}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/stats")
def stats():
    collection = get_or_create_collection()
    count = collection.count()
    # ソース一覧を取得
    sources = set()
    if count > 0:
        results = collection.get(include=["metadatas"], limit=10000)
        for m in results["metadatas"]:
            sources.add(m.get("source", ""))
    return jsonify({"chunk_count": count, "sources": sorted(sources)})


@app.route("/clear", methods=["POST"])
def clear():
    chroma_client.delete_collection("documents")
    get_or_create_collection()
    return jsonify({"success": True})


if __name__ == "__main__":
    os.makedirs(CHROMA_DIR, exist_ok=True)
    app.run(host="0.0.0.0", debug=True, port=5002, threaded=True)
