"""
Windows版 セッションログ保存スクリプト
ダブルクリックで起動 → ダイアログでテーマと内容を入力 → MDファイルに保存
保存先: Z:\Obsidian\note\Insights
"""

import tkinter as tk
from tkinter import messagebox, scrolledtext
from datetime import datetime
import os

SAVE_DIR = r"Z:\Obsidian\note\Insights"


def save_session(theme: str, content: str):
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    time_str = now.strftime("%H:%M")
    filename = f"{date_str}_Notes.md"
    filepath = os.path.join(SAVE_DIR, filename)

    os.makedirs(SAVE_DIR, exist_ok=True)

    if not os.path.exists(filepath):
        header = f"""---
date: {now.strftime('%Y-%m-%d')}
type: notes
tags: [notes]
---

# ノート — {now.strftime('%Y-%m-%d')}

"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(header)

    entry = f"""---

## {theme} — {time_str}

{content}

"""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(entry)

    return filepath, time_str


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("セッション保存")
        self.resizable(False, False)
        self._build()
        self._center()

    def _build(self):
        pad = {"padx": 12, "pady": 6}

        tk.Label(self, text="テーマ", anchor="w").grid(row=0, column=0, sticky="w", **pad)
        self.theme_var = tk.StringVar()
        tk.Entry(self, textvariable=self.theme_var, width=50).grid(row=0, column=1, **pad)

        tk.Label(self, text="内容", anchor="nw").grid(row=1, column=0, sticky="nw", **pad)
        self.content_box = scrolledtext.ScrolledText(self, width=50, height=15, wrap=tk.WORD)
        self.content_box.grid(row=1, column=1, **pad)

        tk.Button(self, text="保存", width=20, command=self._on_save).grid(
            row=2, column=0, columnspan=2, pady=10
        )

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _on_save(self):
        theme = self.theme_var.get().strip()
        content = self.content_box.get("1.0", tk.END).strip()

        if not theme:
            messagebox.showwarning("入力エラー", "テーマを入力してください")
            return
        if not content:
            messagebox.showwarning("入力エラー", "内容を入力してください")
            return

        try:
            filepath, time_str = save_session(theme, content)
            messagebox.showinfo("保存完了", f"保存しました\n{filepath}\n{time_str}")
            self.theme_var.set("")
            self.content_box.delete("1.0", tk.END)
        except Exception as e:
            messagebox.showerror("エラー", str(e))


if __name__ == "__main__":
    app = App()
    app.mainloop()
