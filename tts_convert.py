#!/usr/bin/env python3
"""
TTS変換スクリプト — テキストを音声に変換して再生
使用法: python3 tts_convert.py "変換したいテキスト"
"""

import edge_tts
import asyncio
import sys
import subprocess

VOICE = "ja-JP-NanamiNeural"
OUTPUT = "/tmp/response.wav"


async def main():
    if len(sys.argv) < 2:
        print("使用法: python3 tts_convert.py 'テキスト'")
        sys.exit(1)

    text = sys.argv[1]
    print(f"🎤 変換中: {text[:50]}{'...' if len(text) > 50 else ''}")

    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(OUTPUT)

    print(f"🎧 再生中...")
    subprocess.run(["afplay", OUTPUT])


if __name__ == "__main__":
    asyncio.run(main())
