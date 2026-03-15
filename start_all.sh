#!/bin/bash
# Council / Wisemen / RAG 一括起動スクリプト

cd /Users/yamaosa/claude-projects

# 既に起動していれば何もしない
pgrep -f "app.py" > /dev/null    || /opt/homebrew/bin/python3 app.py &
pgrep -f "wisemen.py" > /dev/null || /opt/homebrew/bin/python3 wisemen.py &
pgrep -f "rag.py" > /dev/null     || /opt/homebrew/bin/python3 rag.py &

# ブラウザで3つを開く
sleep 2
open "http://localhost:5000"
open "http://localhost:5001"
open "http://localhost:5002"
