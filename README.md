# Local AI Suite

A collection of three local LLM-powered apps that run entirely on your machine — no cloud API required.

## Apps

### 🌿 LocalRAG (port 5002)
Ask questions about your own documents. Drop PDFs, Markdown, or text files and chat with them.

- **Query Decomposition** — vague questions are automatically split into multiple search keywords for deeper answers
- Nightly auto-reindex via launchd (macOS)
- Powered by [Ollama](https://ollama.ai) + ChromaDB

### ⚡ Council (port 5000)
A panel of AI experts debates any topic and generates a structured report.

- 5 expert sets: Business / Technology / Social / Future / Philosophy
- Auto-suggest experts based on your topic
- Visualize stances with radar charts and stance bars
- Export reports as Obsidian-compatible Markdown

### 📜 Wisemen (port 5001)
Historical figures debate your topic — Socrates, Nietzsche, Laozi, Sun Tzu and more.

- 4 sets: Philosophy / Strategy / Economics / Revolution
- Auto-suggest historical figures based on your topic
- Same visualization and export as Council

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) running locally
- Required Ollama models:

```bash
ollama pull nomic-embed-text
ollama pull gemma3:27b   # or any model you prefer
```

## Installation

```bash
git clone https://github.com/400msstack/claude-projects
cd claude-projects
pip install flask openai requests beautifulsoup4 chromadb pymupdf
```

Copy and edit the environment file:

```bash
cp .env.example .env
```

Key settings in `.env`:

```
OLLAMA_BASE=http://localhost:11434
CHAT_MODEL=gemma3:27b
LANG_UI=ja   # ja or en
```

## Usage

Start all apps at once:

```bash
./start_all.sh
```

Or start individually:

```bash
python3 rag.py       # http://localhost:5002
python3 app.py       # http://localhost:5000
python3 wisemen.py   # http://localhost:5001
```

## Nightly Reindex (macOS)

To automatically reindex a folder every night at 1:00 AM:

1. Set `WATCH_FOLDER` in `.env`
2. Register with launchd:

```bash
cp com.localrag.reindex.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.localrag.reindex.plist
```

## Architecture

```
User question
    ↓
decompose_question()    ← gemma3 splits vague question into keywords
    ↓
multi_query_search()    ← ChromaDB vector search per keyword
    ↓
synthesize_results()    ← gemma3 generates unified answer
    ↓
Streamed to browser via SSE
```

Documents are chunked (500 chars, 50 overlap), embedded with `nomic-embed-text`, and stored in ChromaDB.

## License

MIT
