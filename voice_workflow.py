#!/usr/bin/env python3
"""
Voice Workflow — 音声でClaudeと会話
Bluetooth マイク → Whisper → Claude API → edge-tts → 再生

使用法:
  python3 voice_workflow.py          # 10秒録音
  python3 voice_workflow.py -t 15    # 15秒録音
  python3 voice_workflow.py --text "テキスト直接入力"  # 音声入力スキップ
"""

import os
import sys
import json
import asyncio
import argparse
import subprocess
import tempfile
from pathlib import Path

import edge_tts

# ─── 設定 ───────────────────────────────────────────────
VOICE          = "ja-JP-NanamiNeural"
WHISPER_MODEL  = "small"   # tiny/base/small/medium/large
AUDIO_DEVICE   = ":0"      # avfoundation audio device index
RECORD_SECONDS = 10
CLAUDE_MODEL   = "claude-opus-4-6"

conversation_history = []


# ─── Phase 1: 音声録音 ────────────────────────────────
def record_audio(seconds: int = RECORD_SECONDS) -> str:
    print(f"\n🎙️  {seconds}秒間話してください... (録音中)")
    output = tempfile.mktemp(suffix=".wav")
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "avfoundation",
        "-i", AUDIO_DEVICE,
        "-t", str(seconds),
        "-ar", "16000",
        "-ac", "1",
        output
    ], capture_output=True)
    if result.returncode != 0:
        print(f"❌ 録音エラー: {result.stderr.decode()[-200:]}")
        return ""
    print("✅ 録音完了")
    return output


# ─── Phase 2: 音声認識 ────────────────────────────────
def transcribe(audio_path: str) -> str:
    print("📝 音声を認識中...")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run([
            "whisper", audio_path,
            "--model", WHISPER_MODEL,
            "--language", "ja",
            "--output_format", "txt",
            "--output_dir", tmpdir,
        ], capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            print(f"❌ 認識エラー: {result.stderr[-200:]}")
            return ""

        txt_files = list(Path(tmpdir).glob("*.txt"))
        if not txt_files:
            return ""
        text = txt_files[0].read_text(encoding="utf-8").strip()
        return text


# ─── Phase 3: Claude CLI ─────────────────────────────
def ask_claude(user_input: str) -> str:
    conversation_history.append(f"User: {user_input}")

    # 会話履歴を含めたプロンプト
    context = "\n".join(conversation_history[-10:])  # 直近5往復
    prompt = (
        "あなたは音声会話アシスタントです。返答は簡潔に、話し言葉で答えてください。"
        "長い箇条書きや記号は避け、自然な日本語の会話文で答えてください。\n\n"
        f"{context}\nAssistant:"
    )

    result = subprocess.run(
        ["claude", "-p", prompt, "--model", CLAUDE_MODEL],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return f"エラーが発生しました: {result.stderr[:100]}"

    reply = result.stdout.strip()
    conversation_history.append(f"Assistant: {reply}")
    return reply


# ─── Phase 4: TTS + 再生 ──────────────────────────────
async def speak(text: str):
    output = "/tmp/voice_response.wav"
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(output)
    subprocess.run(["afplay", output])


# ─── メインループ ─────────────────────────────────────
async def voice_loop(record_seconds: int, direct_text: str = ""):
    print("\n🔊 Voice Workflow 起動")
    print(f"   モデル: claude-opus-4-6 × {VOICE}")
    print("   終了: Ctrl+C\n")

    while True:
        try:
            # 入力取得
            if direct_text:
                user_input = direct_text
                direct_text = ""  # 最初の1回だけ
            else:
                audio_path = record_audio(record_seconds)
                if not audio_path:
                    continue
                user_input = transcribe(audio_path)
                if audio_path and Path(audio_path).exists():
                    Path(audio_path).unlink()

            if not user_input.strip():
                print("⚠️  音声を認識できませんでした。もう一度試してください。")
                continue

            print(f"\n👤 あなた: {user_input}")

            # Claude に問い合わせ
            print("🤔 考え中...")
            reply = ask_claude(user_input)
            print(f"\n🤖 Claude: {reply}\n")

            # 音声で返答
            await speak(reply)

            # テキスト入力モードなら終了
            if "--text" in sys.argv:
                break

        except KeyboardInterrupt:
            print("\n\n👋 終了します")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Voice Workflow")
    parser.add_argument("-t", "--time", type=int, default=RECORD_SECONDS, help="録音秒数")
    parser.add_argument("--text", type=str, default="", help="テキスト直接入力（音声入力スキップ）")
    args = parser.parse_args()

    asyncio.run(voice_loop(args.time, args.text))
