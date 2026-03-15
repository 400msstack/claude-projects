# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## アプリ構成

| ファイル | 役割 | ポート | 起動コマンド |
|---|---|---|---|
| `app.py` | Council — 専門家AI会議 | 5000 | `python3 app.py` |
| `wisemen.py` | Wisemen — 偉人AI会議 | 5001 | `python3 wisemen.py` |
| `rag.py` | LocalRAG — 文書Q&A | 5002 | `python3 rag.py` |
| `rag_reindex.py` | 夜間差分インデックスバッチ | — | `python3 rag_reindex.py`（手動実行可） |
| `session_saver.py` | セッションログをObsidianに保存 | — | `python3 session_saver.py "テーマ" "内容"` |
| `start_all.sh` | 3アプリ一括起動 | — | `./start_all.sh` |

全アプリ一括起動はデスクトップの `AI Apps.app` でも可能。

## LLM接続先

**EVO-X2（LM Studio）**
- URL: `http://192.168.123.100:1234/v1`
- モデル: `openai/gpt-oss-120b`
- 用途: Council・Wisemen の議論・レポート生成

**Mac Mini（Ollama）**
- URL: `http://localhost:11434`
- 埋め込み: `nomic-embed-text`
- 回答生成: `gemma3:27b`
- 用途: LocalRAG 完結

## パス

| 用途 | パス |
|---|---|
| テンプレート | `templates/` （index.html / wisemen.html / rag.html） |
| ChromaDB | `rag_db/` |
| Obsidian Vault | `/Users/yamaosa/Documents/Obsidian/note/` |
| Councilログ | `/Users/yamaosa/Documents/Obsidian/note/Insights/CouncilLogs/` |
| Wisemenログ | `/Users/yamaosa/Documents/Obsidian/note/Insights/WisemenLogs/` |
| セッションログ | `/Users/yamaosa/Documents/Obsidian/note/Log/ClaudeCode/` |
| Coworkログ | `/Users/yamaosa/Documents/Obsidian/note/Log/Cowork/` |

## アーキテクチャ

**Council / Wisemen** — 共通構造
- SSE（Server-Sent Events）でフロントにリアルタイム配信
- `queue.Queue` + `threading.Thread` で非同期処理
- LLMへのリクエストは `chat(system, user)` 経由
- 議論終了後、`analyze_stances()` でスコアリング → Chart.jsで可視化
- レポートはObsidianのMarkdown形式で自動保存

**LocalRAG** — RAGパイプライン
- `embed()` → `split_chunks()` → ChromaDB に保存
- 通常検索: `/ask` — 単一クエリ
- 高度検索: `/decompose_query` — LLMが質問を複数キーワードに分解 → 結果を統合
- 夜間バッチ（`rag_reindex.py`）は `rag_reindex_state.json` で前回実行時刻を管理し差分のみ処理
- launchdで毎晩1:00に自動実行（登録済み）

## ユーザーについて

- コードは書かない。会話で設計・判断し、実装はClaude Codeに任せるスタイル
- 「何を省くか」の判断が的確。過剰な機能追加は好まない
- Cowork（Claude Desktop）で設計 → Claude Code（ターミナル）で実装 → Obsidianで記録 → RAGで検索 というワークフローで運用中
- セッション終了時は `session_saver.py` で内容をObsidianに保存する
- 誕生日: 2026-03-14。Local AI Suiteを公開した翌日が誕生日だった
