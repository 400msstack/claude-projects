#!/usr/bin/env python3
"""
Council Web App — Flask版 v2
"""

import os
import json
import queue
import threading
import glob
import re
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify, send_from_directory
from openai import OpenAI
import requests as http_requests
from bs4 import BeautifulSoup

# .envがあれば読み込む
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── 設定 ───────────────────────────────────────────────
LLM_BASE_URL     = os.getenv("LLM_BASE_URL", "http://192.168.123.100:1234/v1")
LLM_MODEL        = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
OUTPUT_DIR       = os.getenv("OUTPUT_DIR", "./output")
CUSTOM_SETS_FILE = os.getenv("CUSTOM_SETS_FILE", "./custom_sets.json")

client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")
app = Flask(__name__)

# ─── 専門家セット ────────────────────────────────────────
EXPERT_SETS = {
    "1": {
        "name": "ビジネス",
        "experts": [
            {"name": "経営戦略家",    "role": "CEO・経営コンサルタント",     "focus": "ビジネス戦略・競争優位性・ROI"},
            {"name": "マーケター",    "role": "マーケティングディレクター",   "focus": "市場動向・顧客心理・ブランド戦略"},
            {"name": "財務アナリスト","role": "CFO・投資アナリスト",         "focus": "財務リスク・コスト構造・投資対効果"},
            {"name": "法律家",        "role": "企業法務弁護士",               "focus": "法的リスク・規制・コンプライアンス"},
        ],
    },
    "2": {
        "name": "テクノロジー",
        "experts": [
            {"name": "ソフトウェアエンジニア", "role": "シニアエンジニア",       "focus": "技術実装・スケーラビリティ・開発コスト"},
            {"name": "データサイエンティスト", "role": "AIリサーチャー",         "focus": "データ分析・AI活用・定量的根拠"},
            {"name": "セキュリティ専門家",     "role": "CISOレベルの専門家",     "focus": "セキュリティリスク・プライバシー・脆弱性"},
            {"name": "UXデザイナー",           "role": "プロダクトデザイナー",   "focus": "ユーザー体験・使いやすさ・人間中心設計"},
        ],
    },
    "3": {
        "name": "社会・人文",
        "experts": [
            {"name": "社会学者", "role": "社会学教授",       "focus": "社会構造・格差・コミュニティへの影響"},
            {"name": "心理学者", "role": "臨床心理士",       "focus": "人間行動・認知バイアス・メンタルヘルス"},
            {"name": "経済学者", "role": "マクロ経済学者",   "focus": "経済効果・市場メカニズム・政策影響"},
            {"name": "倫理学者", "role": "哲学・倫理学教授", "focus": "倫理的側面・価値観・長期的影響"},
        ],
    },
    "4": {
        "name": "未来・イノベーション",
        "experts": [
            {"name": "フューチャリスト", "role": "未来学者",                       "focus": "長期トレンド・シナリオプランニング"},
            {"name": "起業家",           "role": "シリアルアントレプレナー",       "focus": "イノベーション・機会発見・リスクテイク"},
            {"name": "環境専門家",       "role": "サステナビリティコンサルタント", "focus": "環境負荷・持続可能性・ESG"},
            {"name": "教育者",           "role": "教育改革研究者",                 "focus": "人材育成・学習・知識伝達"},
        ],
    },
    "5": {
        "name": "哲学・思想",
        "experts": [
            {"name": "ソクラテス", "role": "古代ギリシャの哲学者",   "focus": "問答法・無知の知・魂の本質への問い"},
            {"name": "ニーチェ",   "role": "19世紀ドイツの哲学者",   "focus": "力への意志・ニヒリズム・価値の転換"},
            {"name": "老子",       "role": "古代中国の思想家",       "focus": "道（タオ）・無為自然・流れに従う知恵"},
            {"name": "カント",     "role": "18世紀ドイツの哲学者",   "focus": "理性・義務論・人間の尊厳と自律"},
        ],
    },
}

DEPTH_OPTIONS = {
    "1": {"name": "ライト",       "rounds": 1, "desc": "各専門家が1回発言"},
    "2": {"name": "スタンダード", "rounds": 2, "desc": "初回発言＋他の意見への反応"},
    "3": {"name": "ディープ",     "rounds": 3, "desc": "深い議論・反論・統合"},
}

STYLE_OPTIONS = {
    "balanced":       {"name": "バランス",  "desc": "中立的・客観的な議論"},
    "constructive":   {"name": "建設的",    "desc": "共通点を見つけ協力的に深める"},
    "confrontational":{"name": "対立的",    "desc": "反論・批判で議論を鋭くする"},
}

STYLE_INSTRUCTIONS = {
    "constructive":    "他の専門家の意見の優れた点を積極的に認め、それを土台に発展させる形で建設的・協力的に意見を述べてください。",
    "balanced":        "",
    "confrontational": "他の専門家の意見の問題点や矛盾を鋭く指摘し、自分の立場を強く主張してください。対立軸を明確にし、安易な妥協は避けてください。",
}


# ─── カスタムセット管理 ──────────────────────────────────
def load_custom_sets() -> dict:
    if os.path.exists(CUSTOM_SETS_FILE):
        with open(CUSTOM_SETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_custom_sets(sets: dict):
    with open(CUSTOM_SETS_FILE, "w", encoding="utf-8") as f:
        json.dump(sets, f, ensure_ascii=False, indent=2)


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
        temperature=0.7,
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


def run_council(theme: str, experts: list, rounds: int,
                references: list, style: str, expert_set_name: str, q: queue.Queue):
    ref_context = build_reference_context(references)
    style_instr = STYLE_INSTRUCTIONS.get(style, "")

    def send(event: str, data: dict):
        q.put({"event": event, "data": data})

    all_statements = []

    for round_num in range(1, rounds + 1):
        round_labels = {
            1: "ラウンド1 — 初期見解",
            2: "ラウンド2 — 他の意見への反応",
            3: "ラウンド3 — 最終提言",
        }
        send("round_start", {"round": round_num, "label": round_labels[round_num]})

        for expert in experts:
            send("thinking", {"name": expert["name"]})

            if round_num == 1:
                system = (
                    f"あなたは{expert['role']}の{expert['name']}です。"
                    f"{expert['focus']}の観点から、専門的かつ簡潔に意見を述べてください。"
                    "回答は日本語で300字以内にまとめてください。"
                )
                user = f"テーマ「{theme}」について、あなたの専門的見地から初期見解を述べてください。"
                if ref_context:
                    user += f"\n\n{ref_context}"
            elif round_num == 2:
                summary = "\n".join(
                    f"- {s['expert']['name']}: {s['text']}" for s in all_statements
                )
                system = (
                    f"あなたは{expert['role']}の{expert['name']}です。"
                    f"{expert['focus']}の観点を持ちます。"
                    f"{style_instr}"
                    "日本語300字以内で述べてください。"
                )
                user = (
                    f"テーマ「{theme}」に関する他の専門家の見解:\n{summary}\n\n"
                    "これらを踏まえ、あなたの意見を述べてください。"
                )
            else:
                summary = "\n".join(
                    f"- [{s['expert']['name']} R{s['round']}]: {s['text']}"
                    for s in all_statements
                )
                system = (
                    f"あなたは{expert['role']}の{expert['name']}です。"
                    f"{expert['focus']}の観点から、議論全体を踏まえた最終的な提言を"
                    f"{style_instr}"
                    "日本語300字以内で述べてください。"
                )
                user = (
                    f"テーマ「{theme}」に関するここまでの議論:\n{summary}\n\n"
                    "この議論全体を踏まえた、あなたの最終的な提言を述べてください。"
                )

            text = chat(system, user)
            all_statements.append({"expert": expert, "round": round_num, "text": text})
            send("statement", {
                "round": round_num,
                "name": expert["name"],
                "role": expert["role"],
                "text": text,
            })

    # レポート生成
    send("report_start", {})
    full_discussion = "\n".join(
        f"[{s['expert']['name']} / ラウンド{s['round']}]\n{s['text']}\n"
        for s in all_statements
    )
    system = (
        "あなたは優秀な会議ファシリテーターです。"
        "複数の専門家による議論を整理し、日本語で構造化されたレポートを作成してください。"
    )
    user = (
        f"テーマ: {theme}\n"
        f"専門家セット: {expert_set_name}\n"
        f"参加専門家: {', '.join(e['name'] for e in experts)}\n\n"
        f"議論の全内容:\n{full_discussion}\n\n"
        "以下の構成でレポートを作成してください:\n"
        "1. エグゼクティブサマリー（200字程度）\n"
        "2. 各専門家の主要な論点（表形式）\n"
        "3. 主要な合意点\n"
        "4. 主要な対立点・課題\n"
        "5. 総合的な提言・結論\n"
    )
    report_text = chat(system, user)

    # 可視化スコアリング
    send("viz_start", {})
    viz_data = analyze_stances(theme, experts, all_statements)

    md = build_markdown(theme, expert_set_name, experts, all_statements, report_text, references, style)
    path = resolve_output_path()
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)

    send("visualization", viz_data)
    send("done", {"report": report_text, "path": path})
    q.put(None)


def analyze_stances(theme: str, experts: list, all_statements: list) -> dict:
    discussion = "\n".join(
        f"[{s['expert']['name']} / R{s['round']}]: {s['text']}"
        for s in all_statements
    )
    system = (
        "あなたは議論分析の専門家です。"
        "以下の議論を分析し、指定されたJSON形式のみで返してください。説明文は不要です。"
    )
    user = (
        f"テーマ: {theme}\n\n"
        f"議論:\n{discussion}\n\n"
        "各専門家を以下のJSON形式で評価してください（スコアはすべて0〜10の整数）:\n"
        '{"experts":[{"name":"専門家名","risk":7,"urgency":6,"optimism":4,"consensus":8,"stance":2}]}\n\n'
        "各軸の意味:\n"
        "risk: リスク認識の高さ (0=ほぼ無視, 10=非常に高い)\n"
        "urgency: 行動の緊急性 (0=様子見, 10=即時対応)\n"
        "optimism: 将来への楽観度 (0=悲観的, 10=楽観的)\n"
        "consensus: 他者との合意度 (0=強く対立, 10=強く合意)\n"
        "stance: 総合スタンス (-5=強い懸念, 0=中立, 5=強い楽観)\n\n"
        f"対象専門家: {', '.join(e['name'] for e in experts)}"
    )
    try:
        text = chat(system, user)
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {"experts": []}


def build_markdown(theme, expert_set_name, experts, all_statements, report_text, references, style):
    now = datetime.now()
    style_name = STYLE_OPTIONS.get(style, {}).get("name", style)
    lines = [
        "---",
        f"date: {now.strftime('%Y-%m-%d')}",
        f"time: {now.strftime('%H:%M')}",
        f'theme: "{theme}"',
        f"expert_set: {expert_set_name}",
        f"experts: [{', '.join(e['name'] for e in experts)}]",
        f"style: {style_name}",
        "tags: [council, AI, report]",
        "---",
        "",
        "# 専門家会議レポート",
        f"## テーマ: {theme}",
        "",
        f"> 開催日時: {now.strftime('%Y年%m月%d日 %H:%M')}  ",
        f"> 専門家セット: **{expert_set_name}**  ",
        f"> 議論スタイル: {style_name}  ",
        f"> 参加者: {', '.join(e['name'] for e in experts)}",
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
        lines += [f"#### {s['expert']['name']} *（{s['expert']['role']}）*", "", s["text"], ""]

    lines += ["---", "", "## 総合レポート", "", report_text, ""]
    return "\n".join(lines)


def resolve_output_path():
    date_str = datetime.now().strftime("%Y%m%d")
    base = f"claude-council-{date_str}"
    path = os.path.join(OUTPUT_DIR, f"{base}.md")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(OUTPUT_DIR, f"{base}-{counter}.md")
        counter += 1
    return path


# ─── Flask ルート ────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html",
                           expert_sets=EXPERT_SETS,
                           depth_options=DEPTH_OPTIONS,
                           style_options=STYLE_OPTIONS)


@app.route("/suggest-experts", methods=["POST"])
def suggest_experts():
    data = request.get_json()
    theme = data.get("theme", "").strip()
    if not theme:
        return jsonify({"error": "テーマを入力してください"}), 400
    system = (
        "あなたは議論設計の専門家です。"
        "与えられたテーマに最適な専門家パネルをJSON形式のみで返してください。説明文は不要です。"
    )
    user = (
        f"テーマ: {theme}\n\n"
        "このテーマを多角的に議論するために最適な専門家を4名提案してください。\n"
        "focusはこのテーマに特化した具体的な切り口にしてください。\n\n"
        '{"experts":[{"name":"名前","role":"役職","focus":"テーマに特化した具体的な視点"}]}'
    )
    try:
        text = chat(system, user)
        match = re.search(r'\{[\s\S]+\}', text)
        if match:
            return jsonify(json.loads(match.group()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"error": "提案の生成に失敗しました"}), 500


@app.route("/upload-file", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "ファイルがありません"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "ファイル名が空です"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in (".md", ".txt"):
        return jsonify({"error": "MD または TXT ファイルのみ対応しています"}), 400
    text = f.read().decode("utf-8", errors="replace")[:3000]
    return jsonify({"title": f.filename, "url": f"file://{f.filename}", "text": text})


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


@app.route("/start", methods=["GET"])
def start():
    theme     = request.args.get("theme", "")
    set_key   = request.args.get("set", "1")
    depth_key = request.args.get("depth", "2")
    refs_json = request.args.get("refs", "[]")
    style     = request.args.get("style", "balanced")
    custom_experts_json = request.args.get("custom_experts", "")

    if not theme:
        return Response('data: {"event":"error","data":{"msg":"テーマを入力してください"}}\n\n',
                        mimetype="text/event-stream")

    if set_key == "custom" and custom_experts_json:
        experts = json.loads(custom_experts_json)
        expert_set_name = "カスタム"
    else:
        chosen = EXPERT_SETS.get(set_key, EXPERT_SETS["1"])
        experts = chosen["experts"]
        expert_set_name = chosen["name"]

    rounds     = DEPTH_OPTIONS.get(depth_key, DEPTH_OPTIONS["2"])["rounds"]
    references = json.loads(refs_json)

    q = queue.Queue()
    thread = threading.Thread(
        target=run_council,
        args=(theme, experts, rounds, references, style, expert_set_name, q),
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


# ─── 履歴 ────────────────────────────────────────────────
@app.route("/history")
def history():
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "claude-council-*.md")), reverse=True)
    reports = []
    for f in files:
        filename = os.path.basename(f)
        try:
            with open(f, "r", encoding="utf-8") as fp:
                content = fp.read()
            theme_m    = re.search(r'theme:\s*"(.+)"', content)
            date_m     = re.search(r'^date:\s*(.+)$', content, re.MULTILINE)
            time_m     = re.search(r'^time:\s*(.+)$', content, re.MULTILINE)
            set_m      = re.search(r'^expert_set:\s*(.+)$', content, re.MULTILINE)
            experts_m  = re.search(r'^experts:\s*\[(.+)\]$', content, re.MULTILINE)
            reports.append({
                "filename":   filename,
                "theme":      theme_m.group(1) if theme_m else "不明",
                "date":       date_m.group(1).strip() if date_m else "",
                "time":       time_m.group(1).strip() if time_m else "",
                "expert_set": set_m.group(1).strip() if set_m else "",
                "experts":    experts_m.group(1).strip() if experts_m else "",
            })
        except Exception:
            pass
    return jsonify(reports)


@app.route("/report/<filename>")
def get_report(filename):
    if not re.match(r'^claude-council-[\w\-]+\.md$', filename):
        return jsonify({"error": "Invalid filename"}), 400
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Not found"}), 404
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content})


# ─── カスタムセット CRUD ─────────────────────────────────
@app.route("/custom-sets", methods=["GET"])
def get_custom_sets():
    return jsonify(load_custom_sets())


@app.route("/custom-sets", methods=["POST"])
def save_custom_set():
    data = request.get_json()
    name    = data.get("name", "").strip()
    experts = data.get("experts", [])
    if not name or len(experts) < 2:
        return jsonify({"error": "名前と専門家（2人以上）は必須です"}), 400
    sets = load_custom_sets()
    sets[name] = experts
    save_custom_sets(sets)
    return jsonify({"success": True})


@app.route("/custom-sets/<name>", methods=["DELETE"])
def delete_custom_set(name):
    sets = load_custom_sets()
    sets.pop(name, None)
    save_custom_sets(sets)
    return jsonify({"success": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True)
