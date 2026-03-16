#!/usr/bin/env python3
"""
Council - ローカルLLMを使った専門家会議＆レポート生成アプリ
"""

import os
import sys
from datetime import datetime
from openai import OpenAI

# ─── 設定 ───────────────────────────────────────────────
LLM_BASE_URL = "http://192.168.123.100:1234/v1"
LLM_MODEL    = "openai/gpt-oss-120b"
OUTPUT_DIR   = "/Users/yamaosa/Documents/Obsidian/note/Insights/CouncilLogs"

client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")

# ─── 専門家セット ────────────────────────────────────────
EXPERT_SETS = {
    "1": {
        "name": "ビジネス",
        "experts": [
            {"name": "経営戦略家",   "role": "CEO・経営コンサルタント",       "focus": "ビジネス戦略・競争優位性・ROI"},
            {"name": "マーケター",   "role": "マーケティングディレクター",     "focus": "市場動向・顧客心理・ブランド戦略"},
            {"name": "財務アナリスト","role": "CFO・投資アナリスト",           "focus": "財務リスク・コスト構造・投資対効果"},
            {"name": "法律家",       "role": "企業法務弁護士",                 "focus": "法的リスク・規制・コンプライアンス"},
        ],
    },
    "2": {
        "name": "テクノロジー",
        "experts": [
            {"name": "ソフトウェアエンジニア", "role": "シニアエンジニア",         "focus": "技術実装・スケーラビリティ・開発コスト"},
            {"name": "データサイエンティスト", "role": "AIリサーチャー",           "focus": "データ分析・AI活用・定量的根拠"},
            {"name": "セキュリティ専門家",     "role": "CISOレベルの専門家",       "focus": "セキュリティリスク・プライバシー・脆弱性"},
            {"name": "UXデザイナー",           "role": "プロダクトデザイナー",     "focus": "ユーザー体験・使いやすさ・人間中心設計"},
        ],
    },
    "3": {
        "name": "社会・人文",
        "experts": [
            {"name": "社会学者",   "role": "社会学教授",         "focus": "社会構造・格差・コミュニティへの影響"},
            {"name": "心理学者",   "role": "臨床心理士",         "focus": "人間行動・認知バイアス・メンタルヘルス"},
            {"name": "経済学者",   "role": "マクロ経済学者",     "focus": "経済効果・市場メカニズム・政策影響"},
            {"name": "倫理学者",   "role": "哲学・倫理学教授",   "focus": "倫理的側面・価値観・長期的影響"},
        ],
    },
    "4": {
        "name": "未来・イノベーション",
        "experts": [
            {"name": "フューチャリスト", "role": "未来学者",                         "focus": "長期トレンド・シナリオプランニング"},
            {"name": "起業家",           "role": "シリアルアントレプレナー",         "focus": "イノベーション・機会発見・リスクテイク"},
            {"name": "環境専門家",       "role": "サステナビリティコンサルタント",   "focus": "環境負荷・持続可能性・ESG"},
            {"name": "教育者",           "role": "教育改革研究者",                   "focus": "人材育成・学習・知識伝達"},
        ],
    },
}

# ─── 議論の深さ ──────────────────────────────────────────
DEPTH_OPTIONS = {
    "1": {"name": "ライト",       "rounds": 1, "desc": "各専門家が1回発言（手軽）"},
    "2": {"name": "スタンダード", "rounds": 2, "desc": "初回発言＋他の意見への反応"},
    "3": {"name": "ディープ",     "rounds": 3, "desc": "深い議論・反論・統合"},
}


# ─── ヘルパー ────────────────────────────────────────────
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


def print_separator(char="─", width=60):
    print(char * width)


def select_menu(title: str, options: dict) -> str:
    print(f"\n{title}")
    print_separator()
    for key, val in options.items():
        if isinstance(val, dict) and "name" in val:
            extra = val.get("desc", val.get("description", ""))
            print(f"  [{key}] {val['name']}  — {extra}")
        else:
            print(f"  [{key}] {val}")
    print_separator()
    while True:
        choice = input("番号を入力してください: ").strip()
        if choice in options:
            return choice
        print("  ※ 正しい番号を入力してください")


def resolve_output_path() -> str:
    date_str = datetime.now().strftime("%Y%m%d")
    base = f"claude-council-{date_str}"
    path = os.path.join(OUTPUT_DIR, f"{base}.md")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(OUTPUT_DIR, f"{base}-{counter}.md")
        counter += 1
    return path


# ─── 会議ロジック ────────────────────────────────────────
def run_round_1(theme: str, experts: list) -> list[dict]:
    """ラウンド1: 各専門家の初期見解"""
    print("\n【ラウンド1】初期見解")
    print_separator()
    statements = []
    for expert in experts:
        print(f"\n  {expert['name']} ({expert['role']}) が発言中...", end="", flush=True)
        system = (
            f"あなたは{expert['role']}の{expert['name']}です。"
            f"{expert['focus']}の観点から、専門的かつ簡潔に意見を述べてください。"
            "回答は日本語で300字以内にまとめてください。"
        )
        user = f"テーマ「{theme}」について、あなたの専門的見地から初期見解を述べてください。"
        text = chat(system, user)
        print(" 完了")
        print(f"\n  ▶ {expert['name']}: {text}\n")
        statements.append({"expert": expert, "round": 1, "text": text})
    return statements


def run_round_2(theme: str, experts: list, prev_statements: list) -> list[dict]:
    """ラウンド2: 他の意見への反応"""
    print("\n【ラウンド2】他の意見への反応")
    print_separator()
    summary = "\n".join(
        f"- {s['expert']['name']}: {s['text']}" for s in prev_statements
    )
    statements = []
    for expert in experts:
        print(f"\n  {expert['name']} が反応中...", end="", flush=True)
        system = (
            f"あなたは{expert['role']}の{expert['name']}です。"
            f"{expert['focus']}の観点を持ちます。"
            "他の専門家の意見を踏まえ、同意・反論・補足を日本語300字以内で述べてください。"
        )
        user = (
            f"テーマ「{theme}」に関する他の専門家の見解:\n{summary}\n\n"
            "これらを踏まえ、あなたの意見を述べてください。"
        )
        text = chat(system, user)
        print(" 完了")
        print(f"\n  ▶ {expert['name']}: {text}\n")
        statements.append({"expert": expert, "round": 2, "text": text})
    return statements


def run_round_3(theme: str, experts: list, all_statements: list) -> list[dict]:
    """ラウンド3: 最終的な統合・提言"""
    print("\n【ラウンド3】最終提言")
    print_separator()
    summary = "\n".join(
        f"- [{s['expert']['name']} R{s['round']}]: {s['text']}" for s in all_statements
    )
    statements = []
    for expert in experts:
        print(f"\n  {expert['name']} が最終提言中...", end="", flush=True)
        system = (
            f"あなたは{expert['role']}の{expert['name']}です。"
            f"{expert['focus']}の観点から、議論全体を踏まえた最終的な提言を"
            "日本語300字以内で述べてください。"
        )
        user = (
            f"テーマ「{theme}」に関するここまでの議論:\n{summary}\n\n"
            "この議論全体を踏まえた、あなたの最終的な提言を述べてください。"
        )
        text = chat(system, user)
        print(" 完了")
        print(f"\n  ▶ {expert['name']}: {text}\n")
        statements.append({"expert": expert, "round": 3, "text": text})
    return statements


def generate_report(theme: str, expert_set_name: str, experts: list, all_statements: list) -> str:
    """全議論をまとめた最終レポートを生成"""
    print("\n【レポート生成中】...")
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
        "2. 各専門家の主要な論点（箇条書き）\n"
        "3. 主要な合意点\n"
        "4. 主要な対立点・課題\n"
        "5. 総合的な提言・結論\n"
    )
    return chat(system, user)


# ─── Obsidian マークダウン生成 ───────────────────────────
def build_markdown(theme: str, expert_set_name: str, experts: list,
                   all_statements: list, report_text: str) -> str:
    now = datetime.now()
    lines = []

    # フロントマター
    lines += [
        "---",
        f"date: {now.strftime('%Y-%m-%d')}",
        f"time: {now.strftime('%H:%M')}",
        f"theme: \"{theme}\"",
        f"expert_set: {expert_set_name}",
        f"experts: [{', '.join(e['name'] for e in experts)}]",
        "tags: [council, AI, report]",
        "---",
        "",
    ]

    # タイトル
    lines += [
        f"# 専門家会議レポート",
        f"## テーマ: {theme}",
        "",
        f"> 開催日時: {now.strftime('%Y年%m月%d日 %H:%M')}  ",
        f"> 専門家セット: **{expert_set_name}**  ",
        f"> 参加者: {', '.join(e['name'] for e in experts)}",
        "",
    ]

    # 議論ログ
    lines += ["---", "", "## 議論ログ", ""]
    current_round = 0
    for s in all_statements:
        if s["round"] != current_round:
            current_round = s["round"]
            round_labels = {1: "ラウンド1 — 初期見解", 2: "ラウンド2 — 他の意見への反応", 3: "ラウンド3 — 最終提言"}
            lines += ["", f"### {round_labels.get(current_round, f'ラウンド{current_round}')}", ""]
        lines += [
            f"#### {s['expert']['name']} *（{s['expert']['role']}）*",
            "",
            s["text"],
            "",
        ]

    # レポート
    lines += ["---", "", "## 総合レポート", "", report_text, ""]

    return "\n".join(lines)


# ─── メイン ──────────────────────────────────────────────
def main():
    print("\n" + "═" * 60)
    print("  Council — 専門家会議＆レポート生成")
    print("═" * 60)

    # テーマ入力
    print("\nテーマを入力してください（例: AIが雇用に与える影響）")
    theme = input("テーマ: ").strip()
    if not theme:
        print("テーマが入力されていません。終了します。")
        sys.exit(1)

    # 専門家セット選択
    set_key = select_menu("専門家セットを選んでください", EXPERT_SETS)
    chosen_set = EXPERT_SETS[set_key]
    experts = chosen_set["experts"]

    # 議論の深さ選択
    depth_key = select_menu("議論の深さを選んでください", DEPTH_OPTIONS)
    rounds = DEPTH_OPTIONS[depth_key]["rounds"]

    print(f"\n{'═'*60}")
    print(f"  テーマ     : {theme}")
    print(f"  専門家セット: {chosen_set['name']}")
    print(f"  議論の深さ : {DEPTH_OPTIONS[depth_key]['name']} ({rounds}ラウンド)")
    print(f"{'═'*60}")
    input("\nEnter キーで会議を開始します...")

    # 会議実行
    all_statements = []
    all_statements += run_round_1(theme, experts)
    if rounds >= 2:
        all_statements += run_round_2(theme, experts, all_statements)
    if rounds >= 3:
        all_statements += run_round_3(theme, experts, all_statements)

    # レポート生成
    report_text = generate_report(theme, chosen_set["name"], experts, all_statements)

    # ファイル保存
    output_path = resolve_output_path()
    md_content = build_markdown(theme, chosen_set["name"], experts, all_statements, report_text)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    print(f"\n{'═'*60}")
    print(f"  完了！レポートを保存しました")
    print(f"  {output_path}")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
