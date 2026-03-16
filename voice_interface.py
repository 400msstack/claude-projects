#!/usr/bin/env python3
"""
VoiceInterface — ブラウザから音声でClaudeと会話
ブラウザ: マイク録音（MediaRecorder） → POST → Whisper → Claude → TTS → 音声再生

使用法: python3 voice_interface.py
アクセス: http://localhost:5006
"""

import os
import re
import json
import uuid
import asyncio
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

import edge_tts
from flask import Flask, render_template, request, Response, send_file, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ─── 設定 ───────────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
CLAUDE_MODEL  = os.getenv("CLAUDE_MODEL", "claude-opus-4-6")
VOICE         = "ja-JP-NanamiNeural"
AUDIO_DIR     = "/tmp/voice_interface"
os.makedirs(AUDIO_DIR, exist_ok=True)

app = Flask(__name__, template_folder="templates")

# セッションごとの会話履歴
sessions: dict[str, list[str]] = {}


# ─── Whisper 文字起こし ───────────────────────────────
def transcribe(audio_path: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            ["whisper", audio_path,
             "--model", WHISPER_MODEL,
             "--language", "ja",
             "--output_format", "txt",
             "--output_dir", tmpdir],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return ""
        txt_files = list(Path(tmpdir).glob("*.txt"))
        if not txt_files:
            return ""
        return txt_files[0].read_text(encoding="utf-8").strip()


# ─── Claude 応答 ─────────────────────────────────────
def ask_claude(user_input: str, history: list[str]) -> str:
    history.append(f"User: {user_input}")
    context = "\n".join(history[-10:])
    prompt = (
        "あなたは音声会話アシスタントです。返答は簡潔に、話し言葉で答えてください。"
        "箇条書きや記号は避け、自然な日本語の会話文で答えてください。\n\n"
        f"{context}\nAssistant:"
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", CLAUDE_MODEL],
        capture_output=True, text=True, timeout=60
    )
    reply = result.stdout.strip() if result.returncode == 0 else "すみません、エラーが発生しました。"
    history.append(f"Assistant: {reply}")
    return reply


# ─── TTS 生成 ────────────────────────────────────────
async def generate_tts(text: str, filename: str) -> str:
    path = os.path.join(AUDIO_DIR, filename)
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(path)
    return path


# ─── Flask ルート ────────────────────────────────────
@app.route("/")
def index():
    return render_template("voice_interface.html", claude_model=CLAUDE_MODEL)


@app.route("/chat", methods=["POST"])
def chat():
    """音声ファイル受取 → 文字起こし → Claude → TTS → SSEストリーム"""
    session_id = request.form.get("session_id", "default")
    if session_id not in sessions:
        sessions[session_id] = []
    history = sessions[session_id]

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"error": "音声ファイルがありません"}), 400

    # 音声ファイルを一時保存
    suffix = Path(audio_file.filename or "audio.webm").suffix or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    audio_file.save(tmp.name)
    tmp.close()

    def generate():
        def ev(event, data):
            return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"

        try:
            # Step 1: 文字起こし
            yield ev("status", {"msg": "音声を認識中..."})
            transcript = transcribe(tmp.name)
            os.unlink(tmp.name)

            if not transcript:
                yield ev("error", {"msg": "音声を認識できませんでした"})
                return

            yield ev("transcript", {"text": transcript})

            # Step 2: Claude 応答
            yield ev("status", {"msg": "考え中..."})
            reply = ask_claude(transcript, history)
            yield ev("reply", {"text": reply})

            # Step 3: TTS 生成
            yield ev("status", {"msg": "音声を生成中..."})
            audio_filename = f"{uuid.uuid4().hex}.wav"
            asyncio.run(generate_tts(reply, audio_filename))
            yield ev("audio_ready", {"url": f"/audio/{audio_filename}"})

            yield ev("done", {})

        except Exception as e:
            yield ev("error", {"msg": str(e)})

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/clear", methods=["POST"])
def clear():
    session_id = request.get_json(silent=True, force=True) or {}
    sid = session_id.get("session_id", "default")
    sessions.pop(sid, None)
    return jsonify({"ok": True})


@app.route("/audio/<filename>")
def serve_audio(filename):
    path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path, mimetype="audio/wav")


if __name__ == "__main__":
    print("🎤 VoiceInterface 起動中... http://localhost:5006")
    app.run(host="0.0.0.0", port=5006, debug=False, threaded=True)
