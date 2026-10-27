"""桌面客户端：不装浏览器也能用「记忆文档」。

为什么用它：Web 页面适合看长文档，但「随手问一句 → 存成笔记」这件事在浏览器里
要切标签、等页面、怕清缓存。桌面端直接用同一套本地 HTTP 接口，窗口常驻，
关掉浏览器也不影响数据（数据本来就在存储区里）。

只依赖标准库 Tkinter，与项目「零第三方依赖」的约定一致。
界面只做四件事：问答、记忆（笔记编辑）、会话、存储（备份/恢复）。
知识库上传与版本审批仍留在 Web 页——那是有审核流程的操作，不适合塞进小窗口。
"""
from __future__ import annotations

import argparse
import sys
import threading

from .client_api import DEFAULT_BASE, Client, ClientError

try:  # Tkinter 在部分精简发行版里要单独装（python3-tk），缺了要给出人话提示
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError:  # pragma: no cover - 只在缺 tk 的环境触发
    tk = None
    ttk = None
    messagebox = None


class App:
    def __init__(self, root, client: Client):
        self.root = root
        self.client = client
        self.session_id = None
        self.last_qa: tuple[str, str] | None = None
        self.current_note: dict | None = None
        self.notes_index: list[dict] = []
        self.threads_index: list[dict] = []
        self.store_chat = True          # 服务端「储存对话内容」开关，存笔记前会用到

        root.title("记忆文档 · 桌面客户端")
        root.geometry("1020x700")
        root.minsize(820, 560)

        self._build_header()
        self._build_tabs()
        self._build_status()
        self.refresh_health()
        self.refresh_notes()
        self.refresh_threads()
        self.refresh_backups()

    # ---------------- 布局 ----------------
    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        bar.pack(fill="x")
        ttk.Label(bar, text="记忆文档", font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        self.state_label = ttk.Label(bar, text="连接中…", foreground="#666")
        self.state_label.pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="刷新状态", command=self.refresh_health).pack(side="right")
        ttk.Label(bar, text=self.client.base, foreground="#888").pack(side="right", padx=(0, 10))

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=6)
        self._build_ask_tab()
        self._build_notes_tab()
        self._build_threads_tab()
        self._build_storage_tab()

    def _build_ask_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="问答")
        ttk.Label(tab, text="问题").pack(anchor="w")
        self.question = tk.Text(tab, height=3, wrap="word", font=("Microsoft YaHei UI", 10))
        self.question.pack(fill="x", pady=(2, 6))
        row = ttk.Frame(tab)
        row.pack(fill="x")
        self.ask_btn = ttk.Button(row, text="提问（Ctrl+Enter）", command=self.do_ask)
        self.ask_btn.pack(side="left")
        ttk.Button(row, text="清空", command=self.clear_ask).pack(side="left", padx=6)
        self.save_note_btn = ttk.Button(row, text="存为笔记", command=self.save_note, state="disabled")
        self.save_note_btn.pack(side="left")
        self.ask_meta = ttk.Label(row, text="", foreground="#666")
        self.ask_meta.pack(side="right")

        ttk.Label(tab, text="回答").pack(anchor="w", pady=(10, 0))
        self.answer = tk.Text(tab, wrap="word", font=("Microsoft YaHei UI", 10), state="disabled")
        self.answer.pack(fill="both", expand=True, pady=(2, 6))
        ttk.Label(tab, text="引用").pack(anchor="w")
        self.citations = tk.Listbox(tab, height=4, activestyle="none")
        self.citations.pack(fill="x")
        self.question.bind("<Control-Return>", lambda _event: self.do_ask())

    def _build_notes_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="记忆")
        pane = ttk.Panedwindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, width=280)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)

        ttk.Label(left, text="笔记（按更新时间）").pack(anchor="w")
        self.note_list = tk.Listbox(left, activestyle="none")
        self.note_list.pack(fill="both", expand=True, pady=(2, 6))
        self.note_list.bind("<<ListboxSelect>>", lambda _event: self.open_note())
        ttk.Button(left, text="刷新", command=self.refresh_notes).pack(fill="x")

        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.note_title = ttk.Label(right, text="未选择", font=("Microsoft YaHei UI", 10, "bold"))
        self.note_title.pack(anchor="w")
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(2, 4))
        ttk.Button(buttons, text="保存（Ctrl+S）", command=self.save_file).pack(side="left")
        ttk.Button(buttons, text="用系统编辑器打开", command=self.open_external).pack(side="left", padx=6)
        self.note_meta = ttk.Label(buttons, text="", foreground="#666")
        self.note_meta.pack(side="right")
        self.editor = tk.Text(right, wrap="word", undo=True, font=("Consolas", 10))
        self.editor.pack(fill="both", expand=True)
        self.editor.bind("<Control-s>", lambda _event: self.save_file())

    def _build_threads_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="会话")
        pane = ttk.Panedwindow(tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, width=280)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        ttk.Label(left, text="历史问答").pack(anchor="w")
        self.thread_list = tk.Listbox(left, activestyle="none")
        self.thread_list.pack(fill="both", expand=True, pady=(2, 6))
        self.thread_list.bind("<<ListboxSelect>>", lambda _event: self.open_thread())
        ttk.Button(left, text="刷新", command=self.refresh_threads).pack(fill="x")
        self.thread_view = tk.Text(right, wrap="word", state="disabled", font=("Microsoft YaHei UI", 10))
        self.thread_view.pack(fill="both", expand=True)

    def _build_storage_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(tab, text="存储")
        self.storage_info = ttk.Label(tab, text="读取中…", justify="left")
        self.storage_info.pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="打开存储区", command=self.open_folder).pack(side="left")
        ttk.Button(row, text="立即备份", command=self.do_backup).pack(side="left", padx=6)
        ttk.Button(row, text="恢复选中", command=self.do_restore).pack(side="left")
        ttk.Button(row, text="刷新", command=self.refresh_backups).pack(side="left", padx=6)
        self.warn_label = ttk.Label(tab, text="", foreground="#a15c00", wraplength=900)
        self.warn_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(tab, text="备份包（存在 <存储区>/exports/backups）").pack(anchor="w")
        self.backup_list = tk.Listbox(tab, activestyle="none")
        self.backup_list.pack(fill="both", expand=True, pady=(2, 0))

    def _build_status(self) -> None:
        self.status = ttk.Label(self.root, text="就绪", anchor="w", padding=(12, 4))
        self.status.pack(fill="x", side="bottom")

    # ---------------- 通用 ----------------
    def _say(self, text: str) -> None:
        self.status.config(text=text)

    def _error(self, exc: Exception) -> None:
        message = str(exc)
        if isinstance(exc, ClientError) and exc.status == 401:
            message += "\n\n服务端已启用 API Key：启动时加 --key <你的 Key>。"
        self._say("出错：" + message.splitlines()[0])
        messagebox.showerror("操作失败", message, parent=self.root)

    def _run(self, work, ok, label: str = "") -> None:
        """网络请求放后台线程，界面只从主线程更新——Tk 不接受跨线程改控件。"""
        if label:
            self._say(label)

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 —— 统一在界面层提示
                self.root.after(0, lambda exc=exc: self._error(exc))
                return
            self.root.after(0, lambda result=result: ok(result))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _set_text(widget, text: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")

    # ---------------- 状态 ----------------
    def refresh_health(self) -> None:
        def ok(data: dict) -> None:
            model = data.get("model") or "-"
            mode = "在线模型" if data.get("llm_ready") else "离线抽取"
            self.state_label.config(text=f"{mode} · {model} · 索引 {data.get('chunks', 0)} 块",
                                    foreground="#2f6f5e")
            warnings = ((data.get("runtime") or {}).get("warnings") or [])
            self.warn_label.config(text="；".join(warnings))
            self._say("已连接 " + self.client.base)

        self._run(self.client.health, ok)
        self._run(self.client.settings, self._sync_flags)

    def _sync_flags(self, payload: dict) -> None:
        notes = payload.get("notes") or {}
        self.store_chat = bool(notes.get("store_chat", True))

    # ---------------- 问答 ----------------
    def _paint(self, text: str) -> None:
        """流式增量刷新回答区；保持只读态，但内容随生成变化。"""
        self._set_text(self.answer, text)
        self.answer.see("end")
        self.ask_meta.config(text=f"生成中… {len(text)} 字")

    def do_ask(self) -> None:
        query = self.question.get("1.0", "end").strip()
        if not query:
            return
        self.ask_btn.config(state="disabled")
        self.ask_meta.config(text="查询中…")
        self._set_text(self.answer, "")
        self.citations.delete(0, "end")
        self.save_note_btn.config(state="disabled")
        self.last_qa = None

        def finish(result: dict) -> None:
            self.ask_btn.config(state="normal")
            answer = str(result.get("answer") or "")
            self._set_text(self.answer, answer)
            self.citations.delete(0, "end")
            for item in result.get("citations") or []:
                title = item.get("title") or ""
                section = item.get("section") or ""
                self.citations.insert("end", f"[{item.get('ref')}] {title} · {section}")
            meta = result.get("mode") or ""
            if result.get("degraded"):
                meta += f"（降级：{result.get('degrade_reason') or '未知'}）"
            rate = result.get("citation_support_rate")
            if rate is not None and rate < 1.0:
                meta += f" · 引用支持率 {rate:.0%}"
            self.ask_meta.config(text=meta)
            self.last_qa = (query, answer)
            self.save_note_btn.config(state="normal" if answer else "disabled")
            self._say(f"完成 · {result.get('latency_ms', 0)} ms")

        def worker() -> None:
            """流式优先；一个字都没收到时退回一次性请求，服务端不支持也不丢功能。"""
            buffer = ""
            final = None
            try:
                for event, payload in self.client.ask_stream(query, self.session_id):
                    if event == "delta":
                        buffer += str(payload.get("text") or "")
                        self.root.after(0, lambda text=buffer: self._paint(text))
                    elif event == "replace":
                        buffer = str(payload.get("text") or "")
                        self.root.after(0, lambda text=buffer: self._paint(text))
                    elif event == "final":
                        final = payload
            except Exception as exc:  # noqa: BLE001 —— 已渲染的部分内容不丢
                if buffer or final is not None:
                    self.root.after(0, lambda exc=exc: self._error(exc))
                    return
                try:
                    final = self.client.ask(query, self.session_id)
                except Exception:  # noqa: BLE001
                    self.root.after(0, lambda exc=exc: self._error(exc))
                    return
            if final is None:
                self.root.after(0, lambda: self._error(
                    ClientError("流式回答没有返回结果", 0, "stream")))
                return
            self.root.after(0, lambda: finish(final))

        threading.Thread(target=worker, daemon=True).start()

    def clear_ask(self) -> None:
        self.question.delete("1.0", "end")
        self._set_text(self.answer, "")
        self.citations.delete(0, "end")
        self.ask_meta.config(text="")
        self.save_note_btn.config(state="disabled")
        self.last_qa = None

    def save_note(self) -> None:
        if not self.last_qa:
            return
        question, answer = self.last_qa

        def ok(result: dict) -> None:
            if result.get("duplicate_of"):
                self._say("已有相同内容，未重复保存")
            else:
                self._say(f"已存为笔记 {result.get('id')}")
            self.refresh_notes()

        def work():
            if not self.store_chat:
                # 开关默认是关的：先征得同意再开，不能替用户决定要不要留对话
                self.client.update_settings({"notes": {"store_chat": True}})
                self.store_chat = True
            return self.client.save_note(question, answer)

        if not self.store_chat and not messagebox.askyesno(
                "需要先开启", "当前关闭了「储存对话内容」，问答不会被保存。\n"
                              "要开启并保存这一条吗？（之后可在设置里关掉）", parent=self.root):
            return
        self._run(work, ok, "正在整理成笔记…")

    # ---------------- 笔记 ----------------
    def refresh_notes(self) -> None:
        def ok(items: list) -> None:
            self.notes_index = items
            self.note_list.delete(0, "end")
            for item in items:
                title = item.get("title") or "(无标题)"
                status = item.get("status") or ""
                self.note_list.insert("end", f"{title}" + (f"  · {status}" if status else ""))

        self._run(self.client.notes, ok)

    def open_note(self) -> None:
        selection = self.note_list.curselection()
        if not selection:
            return
        item = self.notes_index[selection[0]]

        def work():
            note = self.client.note(item["id"])
            raw = self.client.read_file(note["path"])
            return note, raw

        def ok(result) -> None:
            note, raw = result
            self.current_note = {"id": note["id"], "path": note["path"], "rev": raw["rev"]}
            self.note_title.config(text=note.get("title") or "(无标题)")
            self.note_meta.config(text=f"{note.get('status') or ''} · rev {raw['rev'][:8]}")
            self.editor.delete("1.0", "end")
            self.editor.insert("1.0", raw["content"])
            self._say(f"已打开 {note['path']}")

        self._run(work, ok, "读取笔记…")

    def save_file(self) -> None:
        if not self.current_note:
            messagebox.showinfo("没有选中笔记", "先在左侧选择一篇笔记。", parent=self.root)
            return
        content = self.editor.get("1.0", "end-1c")
        note = dict(self.current_note)

        def ok(result: dict) -> None:
            self.current_note["rev"] = result["rev"]
            self.note_meta.config(text=f"已保存 · rev {result['rev'][:8]}")
            self._say("已写入磁盘")

        self._run(lambda: self.client.write_file(note["path"], content, note["rev"]), ok, "保存中…")

    def open_external(self) -> None:
        if not self.current_note:
            return
        path = self.current_note["path"]
        self._run(lambda: self.client.open_file(path),
                  lambda _r: self._say("已交给系统编辑器"), "打开中…")

    # ---------------- 会话 ----------------
    def refresh_threads(self) -> None:
        def ok(items: list) -> None:
            self.threads_index = items
            self.thread_list.delete(0, "end")
            for item in items:
                self.thread_list.insert("end", f"{item.get('title') or '新对话'} · {item.get('turns')} 轮")

        self._run(self.client.threads, ok)

    def open_thread(self) -> None:
        selection = self.thread_list.curselection()
        if not selection:
            return
        thread_id = self.threads_index[selection[0]]["id"]

        def ok(thread: dict) -> None:
            lines = []
            for turn in thread.get("turns") or []:
                lines.append("问：" + str(turn.get("q") or ""))
                answer = ((turn.get("d") or {}).get("answer")) or ""
                if answer:
                    lines.append("答：" + str(answer))
                lines.append("")
            self._set_text(self.thread_view, "\n".join(lines))
            self._say(f"已打开会话 {thread_id}")

        self._run(lambda: self.client.thread(thread_id), ok, "读取会话…")

    # ---------------- 存储 ----------------
    def refresh_backups(self) -> None:
        def ok(items: list) -> None:
            self.backup_list.delete(0, "end")
            for item in items:
                self.backup_list.insert("end", f"{item.get('name')} · {item.get('bytes', 0) // 1024} KB")

        self._run(self.client.backups, ok)
        self._run(self.client.settings, self._show_settings)

    def _show_settings(self, payload: dict) -> None:
        notes = payload.get("notes") or {}
        storage = payload.get("storage") or {}
        threads = storage.get("threads") or {}
        total = sum(int((item or {}).get("bytes") or 0)
                    for item in storage.values() if isinstance(item, dict))
        text = (
            f"存储区：{notes.get('home_effective') or '-'}\n"
            f"笔记 {notes.get('count', 0)} 篇 · 会话 {threads.get('files', 0)} 条 · "
            f"占用 {total // 1024} KB\n"
            f"模型：{(payload.get('llm') or {}).get('effective_model') or '-'} "
            f"· 对话存储：{'开' if notes.get('store_chat', True) else '关'}"
        )
        self.storage_info.config(text=text)

    def open_folder(self) -> None:
        self._run(self.client.open_folder, lambda _r: self._say("已打开存储区"), "打开中…")

    def do_backup(self) -> None:
        def ok(result: dict) -> None:
            self._say(f"已备份 {result.get('files')} 个文件 → {result.get('name')}")
            self.refresh_backups()

        self._run(lambda: self.client.backup("桌面客户端手动备份"), ok, "打包中…")

    def do_restore(self) -> None:
        selection = self.backup_list.curselection()
        if not selection:
            messagebox.showinfo("没有选中备份", "先在列表里选一个备份包。", parent=self.root)
            return
        name = self.backup_list.get(selection[0]).split(" · ")[0]
        if not messagebox.askyesno("确认恢复", f"用 {name} 覆盖当前笔记与会话？\n"
                                              "恢复前会自动再备份一次。", parent=self.root):
            return

        def work() -> dict:
            try:
                return self.client.restore(name, force=False)
            except ClientError as exc:
                if exc.status == 409:
                    return self.client.restore(name, force=True)
                raise

        def ok(result: dict) -> None:
            self._say(result.get("message") or "已恢复")
            self.refresh_notes()
            self.refresh_threads()
            self.refresh_backups()

        self._run(work, ok, "恢复中…")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="记忆文档 · 桌面客户端")
    parser.add_argument("--base", default=DEFAULT_BASE, help="服务地址，默认 http://127.0.0.1:8000")
    parser.add_argument("--key", default="", help="服务端启用 API_KEYS 时的访问密钥")
    args = parser.parse_args(argv)
    # 先解析参数再检查 Tk：否则 `--help` 会先报「没有 Tkinter」，连用法都看不到
    if tk is None:
        print("当前 Python 没有 Tkinter，图形界面起不来。\n"
              "Debian/Ubuntu：sudo apt install python3-tk；Windows 官方安装包默认自带。\n"
              "没有图形环境时可以直接用终端客户端：python -m src.client status",
              file=sys.stderr)
        return 2

    root = tk.Tk()
    App(root, Client(args.base, args.key))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
