#!/usr/bin/env python3
"""
RAG 夜間差分インデックスバッチ
毎晩1時にlaunchdから実行される
前回実行時刻より新しいファイルだけをインデックス化する
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
import requests
import chromadb

# ─── 設定 ───────────────────────────────────────────────
OLLAMA_BASE   = "http://localhost:11434"
EMBED_MODEL   = "nomic-embed-text"
CHROMA_DIR    = "/Users/yamaosa/claude-projects/rag_db"
WATCH_FOLDER  = "/Users/yamaosa/Documents/Obsidian/note"
STATE_FILE    = "/Users/yamaosa/claude-projects/rag_reindex_state.json"
LOG_FILE      = "/Users/yamaosa/claude-projects/rag_reindex.log"
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 50

# ─── ログ設定 ────────────────────────────────────────────
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ─── 状態管理 ────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"last_run": 0}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ─── Ollama ─────────────────────────────────────────────
def embed(text: str) -> list[float]:
    res = requests.post(f"{OLLAMA_BASE}/api/embeddings",
                        json={"model": EMBED_MODEL, "prompt": text})
    return res.json()["embedding"]


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
    start, idx = 0, 0
    while start < len(text):
        chunk = text[start:start + CHUNK_SIZE]
        if chunk.strip():
            chunks.append({"id": f"{source}_{idx}", "text": chunk, "source": source})
            idx += 1
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── メイン ─────────────────────────────────────────────
def main():
    log.info("=== 夜間インデックス開始 ===")
    state = load_state()
    last_run = state["last_run"]
    now = datetime.now().timestamp()

    # 対象ファイルを収集（前回実行以降に更新されたもの）
    target_files = []
    for ext in ("*.md", "*.txt", "*.pdf"):
        for p in Path(WATCH_FOLDER).rglob(ext):
            if ".obsidian" in p.parts:
                continue
            if p.stat().st_mtime > last_run:
                target_files.append(str(p))

    if not target_files:
        log.info("更新ファイルなし — スキップ")
        save_state({"last_run": now})
        return

    log.info(f"対象ファイル数: {len(target_files)}")

    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    collection = chroma_client.get_or_create_collection("documents")

    success, skip, error = 0, 0, 0

    for path in target_files:
        filename = os.path.basename(path)
        try:
            text = read_file(path)
            if not text.strip():
                log.info(f"スキップ（空）: {filename}")
                skip += 1
                continue

            chunks = split_chunks(text, filename)
            for chunk in chunks:
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
            log.info(f"完了: {filename} ({len(chunks)}チャンク)")
            success += 1
        except Exception as e:
            log.error(f"エラー: {filename} — {e}")
            error += 1

    save_state({"last_run": now})
    log.info(f"=== 完了 — 成功:{success} スキップ:{skip} エラー:{error} 総チャンク:{collection.count()} ===")


if __name__ == "__main__":
    main()
