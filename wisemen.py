#!/usr/bin/env python3
"""
Wisemen Web App — 歴史上の偉人が議論するアプリ
"""

import os
import json
import queue
import threading
import re
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify
from openai import OpenAI
import requests as http_requests
from bs4 import BeautifulSoup

# ─── 設定 ───────────────────────────────────────────────
LLM_BASE_URL = "http://192.168.123.100:1234/v1"
LLM_MODEL    = "openai/gpt-oss-120b"
OUTPUT_DIR   = "/Users/yamaosa/Documents/Obsidian/note/Insights/WisemenLogs"

client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")
app = Flask(__name__, template_folder="templates")

# ─── 偉人セット ──────────────────────────────────────────
WISEMEN_SETS = {
    "1": {
        "name": "哲学・思想",
        "wisemen": [
            {"name": "ソクラテス",  "era": "古代ギリシャ BC470頃", "lens": "問答法・無知の知・魂の探求"},
            {"name": "ニーチェ",    "era": "19世紀ドイツ",         "lens": "力への意志・ニヒリズム・超人思想"},
            {"name": "老子",        "era": "古代中国 BC6世紀頃",   "lens": "道（タオ）・無為自然・陰陽の調和"},
            {"name": "カント",      "era": "18世紀ドイツ",         "lens": "理性・義務論・定言命法"},
        ],
    },
    "2": {
        "name": "戦略・リーダーシップ",
        "wisemen": [
            {"name": "孫子",        "era": "古代中国 BC6世紀",     "lens": "戦略・機略・戦わずして勝つ"},
            {"name": "マキャベリ",  "era": "15-16世紀イタリア",    "lens": "権力・現実主義・目的のための手段"},
            {"name": "チャーチル",  "era": "20世紀イギリス",       "lens": "不屈の意志・修辞・歴史的視座"},
            {"name": "ナポレオン",  "era": "18-19世紀フランス",    "lens": "決断力・スピード・中央集権的指揮"},
        ],
    },
    "3": {
        "name": "経済・経営",
        "wisemen": [
            {"name": "ドラッカー",        "era": "20世紀オーストリア・アメリカ", "lens": "マネジメント・知識労働・組織論"},
            {"name": "ケインズ",          "era": "20世紀イギリス",               "lens": "有効需要・政府介入・マクロ経済"},
            {"name": "アダム・スミス",    "era": "18世紀イギリス",               "lens": "見えざる手・自由市場・分業"},
            {"name": "シュンペーター",    "era": "20世紀オーストリア・アメリカ", "lens": "創造的破壊・イノベーション・起業家精神"},
        ],
    },
    "4": {
        "name": "革命・変革",
        "wisemen": [
            {"name": "マルクス",    "era": "19世紀ドイツ",         "lens": "階級闘争・資本主義批判・唯物史観"},
            {"name": "ガンジー",    "era": "19-20世紀インド",      "lens": "非暴力・真理・市民的不服従"},
            {"name": "ルソー",      "era": "18世紀フランス",       "lens": "社会契約・一般意志・自然への回帰"},
            {"name": "マルコムX",   "era": "20世紀アメリカ",       "lens": "自決・黒人の誇り・権力への直接対峙"},
        ],
    },
}

DEPTH_OPTIONS = {
    "1": {"name": "ライト",       "rounds": 1, "desc": "各偉人が1回発言"},
    "2": {"name": "スタンダード", "rounds": 2, "desc": "初回発言＋他の意見への反応"},
    "3": {"name": "ディープ",     "rounds": 3, "desc": "深い議論・反論・統合"},
}

STYLE_OPTIONS = {
    "balanced":        {"name": "バランス",  "desc": "中立的・客観的な議論"},
    "constructive":    {"name": "建設的",    "desc": "共通点を見つけ協力的に深める"},
    "confrontational": {"name": "対立的",    "desc": "反論・批判で議論を鋭くする"},
}

STYLE_INSTRUCTIONS = {
    "constructive":    "他の偉人の意見の優れた点を積極的に認め、それを土台に発展させる形で建設的・協力的に意見を述べてください。",
    "balanced":        "",
    "confrontational": "他の偉人の意見の問題点や矛盾を鋭く指摘し、自分の立場を強く主張してください。対立軸を明確にし、安易な妥協は避けてください。",
}


# ─── Web資料取得 ─────────────────────────────────────────
def fetch_url_text(url: str, max_chars: int = 3000) -> str:
    try:
        resp = http_requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [l for l in text.splitlines() if len(l.strip()) > 20]
        return "\n".join(lines)[:max_chars]
    except Exception as e:
        return f"[取得エラー: {e}]"


# ─── LLM呼び出し ─────────────────────────────────────────
def chat(system_prompt: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.8,
    )
    return response.choices[0].message.content.strip()


# ─── 会議ロジック ────────────────────────────────────────
def build_reference_context(references: list) -> str:
    if not references:
        return ""
    parts = ["【参考資料】"]
    for r in references:
        parts.append(f"--- {r['title']} ({r['url']}) ---")
        parts.append(r["text"])
    return "\n".join(parts)


def run_council(theme: str, wisemen: list, rounds: int,
                references: list, style: str, set_name: str, q: queue.Queue):
    ref_context = build_reference_context(references)
    style_instr = STYLE_INSTRUCTIONS.get(style, "")

    def send(event: str, data: dict):
        q.put({"event": event, "data": data})

    all_statements = []
    round_labels = {
        1: "ラウンド1 — 初期見解",
        2: "ラウンド2 — 他の意見への反応",
        3: "ラウンド3 — 最終提言",
    }

    for round_num in range(1, rounds + 1):
        send("round_start", {"round": round_num, "label": round_labels[round_num]})

        for w in wisemen:
            send("thinking", {"name": w["name"]})

            if round_num == 1:
                system = (
                    f"あなたは{w['era']}の{w['name']}です。"
                    f"あなたの思想的特徴: {w['lens']}。"
                    "あなたの時代の言葉と思想で語りますが、現代のテーマにも適用します。"
                    "一人称で、あなたらしい語り口で日本語300字以内に述べてください。"
                    "自分の名前や時代を冒頭に名乗る必要はありません。"
                )
                user = f"テーマ「{theme}」について、あなたの思想的立場から見解を述べてください。"
                if ref_context:
                    user += f"\n\n{ref_context}"

            elif round_num == 2:
                summary = "\n".join(
                    f"- {s['wiseman']['name']}: {s['text']}" for s in all_statements
                )
                system = (
                    f"あなたは{w['era']}の{w['name']}です。"
                    f"あなたの思想的特徴: {w['lens']}。"
                    f"{style_instr}"
                    "あなたらしい語り口で日本語300字以内に述べてください。"
                )
                user = (
                    f"テーマ「{theme}」に関する他の偉人の見解:\n{summary}\n\n"
                    "これらを踏まえ、あなたの立場から意見を述べてください。"
                )

            else:
                summary = "\n".join(
                    f"- [{s['wiseman']['name']} R{s['round']}]: {s['text']}"
                    for s in all_statements
                )
                system = (
                    f"あなたは{w['era']}の{w['name']}です。"
                    f"あなたの思想的特徴: {w['lens']}。"
                    f"{style_instr}"
                    "議論全体を踏まえた最終的な提言を、あなたらしい語り口で日本語300字以内に述べてください。"
                )
                user = (
                    f"テーマ「{theme}」に関するここまでの議論:\n{summary}\n\n"
                    "この議論全体を踏まえた、あなたの最終的な言葉を述べてください。"
                )

            text = chat(system, user)
            all_statements.append({"wiseman": w, "round": round_num, "text": text})
            send("statement", {
                "round": round_num,
                "name": w["name"],
                "era": w["era"],
                "text": text,
            })

    # レポート生成
    send("report_start", {})
    full_discussion = "\n".join(
        f"[{s['wiseman']['name']} / ラウンド{s['round']}]\n{s['text']}\n"
        for s in all_statements
    )
    system = (
        "あなたは優秀な思想史家・ファシリテーターです。"
        "歴史上の偉人による議論を整理し、日本語で構造化されたレポートを作成してください。"
    )
    user = (
        f"テーマ: {theme}\n"
        f"参加者: {', '.join(w['name'] for w in wisemen)}\n\n"
        f"議論の全内容:\n{full_discussion}\n\n"
        "以下の構成でレポートを作成してください:\n"
        "1. エグゼクティブサマリー（200字程度）\n"
        "2. 各偉人の主要な論点（表形式）\n"
        "3. 思想的な共鳴・合意点\n"
        "4. 鋭い対立・相克\n"
        "5. 現代への示唆・総合的提言\n"
    )
    report_text = chat(system, user)

    # 可視化スコアリング
    send("viz_start", {})
    viz_data = analyze_stances(theme, wisemen, all_statements)

    # 保存
    md = build_markdown(theme, set_name, wisemen, all_statements, report_text, references, style)
    path = resolve_output_path()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    send("visualization", viz_data)
    send("done", {"report": report_text, "path": path})
    q.put(None)


def analyze_stances(theme: str, wisemen: list, all_statements: list) -> dict:
    discussion = "\n".join(
        f"[{s['wiseman']['name']} / R{s['round']}]: {s['text']}"
        for s in all_statements
    )
    system = (
        "あなたは議論分析の専門家です。"
        "以下の議論を分析し、指定されたJSON形式のみで返してください。説明文は不要です。"
    )
    user = (
        f"テーマ: {theme}\n\n"
        f"議論:\n{discussion}\n\n"
        "各偉人を以下のJSON形式で評価してください（スコアはすべて0〜10の整数）:\n"
        '{"experts":[{"name":"偉人名","risk":7,"urgency":6,"optimism":4,"consensus":8,"stance":2}]}\n\n'
        "各軸の意味:\n"
        "risk: リスク認識の高さ (0=ほぼ無視, 10=非常に高い)\n"
        "urgency: 行動の緊急性 (0=様子見, 10=即時対応)\n"
        "optimism: 将来への楽観度 (0=悲観的, 10=楽観的)\n"
        "consensus: 他者との合意度 (0=強く対立, 10=強く合意)\n"
        "stance: 総合スタンス (-5=強い懸念, 0=中立, 5=強い楽観)\n\n"
        f"対象: {', '.join(w['name'] for w in wisemen)}"
    )
    try:
        text = chat(system, user)
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"experts": []}


def build_markdown(theme, set_name, wisemen, all_statements, report_text, references, style):
    now = datetime.now()
    style_name = STYLE_OPTIONS.get(style, {}).get("name", style)
    lines = [
        "---",
        f"date: {now.strftime('%Y-%m-%d')}",
        f"time: {now.strftime('%H:%M')}",
        f'theme: "{theme}"',
        f"wisemen_set: {set_name}",
        f"wisemen: [{', '.join(w['name'] for w in wisemen)}]",
        f"style: {style_name}",
        "tags: [wisemen, AI, report]",
        "---",
        "",
        "# 偉人会議レポート",
        f"## テーマ: {theme}",
        "",
        f"> 開催日時: {now.strftime('%Y年%m月%d日 %H:%M')}  ",
        f"> 参加者: {', '.join(w['name'] for w in wisemen)}  ",
        f"> 議論スタイル: {style_name}",
        "",
    ]
    if references:
        lines += ["### 参考資料", ""]
        for r in references:
            lines.append(f"- [{r['title']}]({r['url']})")
        lines.append("")

    lines += ["---", "", "## 議論ログ", ""]
    current_round = 0
    round_labels = {1: "ラウンド1 — 初期見解", 2: "ラウンド2 — 他の意見への反応", 3: "ラウンド3 — 最終提言"}
    for s in all_statements:
        if s["round"] != current_round:
            current_round = s["round"]
            lines += ["", f"### {round_labels.get(current_round, f'ラウンド{current_round}')}", ""]
        lines += [
            f"#### {s['wiseman']['name']} *（{s['wiseman']['era']}）*",
            "",
            s["text"],
            "",
        ]

    lines += ["---", "", "## 総合レポート", "", report_text, ""]
    return "\n".join(lines)


def resolve_output_path():
    date_str = datetime.now().strftime("%Y%m%d")
    base = f"wisemen-{date_str}"
    path = os.path.join(OUTPUT_DIR, f"{base}.md")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(OUTPUT_DIR, f"{base}-{counter}.md")
        counter += 1
    return path


# ─── Flask ルート ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("wisemen.html",
                           wisemen_sets=WISEMEN_SETS,
                           depth_options=DEPTH_OPTIONS,
                           style_options=STYLE_OPTIONS)


@app.route("/suggest-wisemen", methods=["POST"])
def suggest_wisemen():
    data = request.get_json()
    theme = data.get("theme", "").strip()
    if not theme:
        return jsonify({"error": "テーマを入力してください"}), 400
    system = (
        "あなたは歴史・思想の専門家です。"
        "与えられたテーマに最適な歴史上の偉人パネルをJSON形式のみで返してください。説明文は不要です。"
    )
    user = (
        f"テーマ: {theme}\n\n"
        "このテーマを多角的に議論するために最適な歴史上の偉人を4名提案してください。\n"
        "lensはこのテーマに特化した具体的な切り口にしてください。\n\n"
        '{"wisemen":[{"name":"偉人名","era":"時代・国","lens":"テーマに特化した思想的視点"}]}'
    )
    try:
        text = chat(system, user)
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            return jsonify(json.loads(match.group()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "提案の生成に失敗しました"}), 500


@app.route("/fetch-url", methods=["POST"])
def fetch_url():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URLが空です"}), 400
    text = fetch_url_text(url)
    try:
        resp = http_requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title else url
    except Exception:
        title = url
    return jsonify({"title": title, "url": url, "text": text[:3000]})


@app.route("/upload-file", methods=["POST"])
def upload_file():
    import os as _os
    if "file" not in request.files:
        return jsonify({"error": "ファイルがありません"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "ファイル名が空です"}), 400
    ext = _os.path.splitext(f.filename)[1].lower()
    if ext not in (".md", ".txt"):
        return jsonify({"error": "MD または TXT ファイルのみ対応しています"}), 400
    text = f.read().decode("utf-8", errors="replace")[:3000]
    return jsonify({"title": f.filename, "url": f"file://{f.filename}", "text": text})


@app.route("/start", methods=["GET"])
def start():
    theme     = request.args.get("theme", "")
    set_key   = request.args.get("set", "1")
    depth_key = request.args.get("depth", "2")
    refs_json = request.args.get("refs", "[]")
    style     = request.args.get("style", "balanced")
    custom_json = request.args.get("custom_wisemen", "")

    if not theme:
        return Response('data: {"event":"error","data":{"msg":"テーマを入力してください"}}\n\n',
                        mimetype="text/event-stream")

    if set_key == "custom" and custom_json:
        wisemen = json.loads(custom_json)
        set_name = "カスタム"
    else:
        chosen = WISEMEN_SETS.get(set_key, WISEMEN_SETS["1"])
        wisemen = chosen["wisemen"]
        set_name = chosen["name"]

    rounds     = DEPTH_OPTIONS.get(depth_key, DEPTH_OPTIONS["2"])["rounds"]
    references = json.loads(refs_json)

    q = queue.Queue()
    thread = threading.Thread(
        target=run_council,
        args=(theme, wisemen, rounds, references, style, set_name, q),
        daemon=True,
    )
    thread.start()

    def generate():
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


if __name__ == "__main__":
    app.run(debug=True, port=5001, threaded=True)
