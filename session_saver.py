#!/usr/bin/env python3
"""
Claude Code セッションログ保存スクリプト
使い方: python3 session_saver.py "テーマ" "内容"
差分保存: 既存ファイルの末尾に追記、重複なし
"""

import sys
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = "/Users/yamaosa/Documents/Obsidian/note/Log/ClaudeCode"

def save_session(theme: str, content: str):
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H:%M")
    filename = f"{date_str}_ClaudeCode.md"
    filepath = os.path.join(LOG_DIR, filename)

    # ファイルが存在しない場合は新規作成
    if not os.path.exists(filepath):
        header = f"""---
date: {now.strftime('%Y-%m-%d')}
type: claude-code-session
tags: [claude-code, dev-session]
---

# Claude Code セッションログ — {now.strftime('%Y-%m-%d')}

"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header)
        print(f"新規ファイル作成: {filepath}")

    # 追記（差分保存）
    entry = f"""---

## セッション更新 — {time_str}
**テーマ:** {theme}

{content}

"""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"保存完了: {filepath}")
    print(f"更新時刻: {time_str}")
    return filepath


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python3 session_saver.py 'テーマ' '内容'")
        sys.exit(1)
    theme = sys.argv[1]
    content = sys.argv[2]
    save_session(theme, content)
