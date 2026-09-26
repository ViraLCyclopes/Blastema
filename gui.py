"""Browse the engine-side prefabs in a JWE3 prefab dump.

    python gui.py

Opens the dump from the game root by default; File > Open picks another.
Tkinter so there is no dependency to install.
"""

from __future__ import annotations

import os
import random
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import emit, probe  # noqa: E402
from core.dump import Dump, default_dump_path  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JWE3 Engine-Side Prefabs")
        self.geometry("1040x620")
        self.dump: Dump | None = None
        self.rows: list[tuple[str, int]] = []
        self.schema = self._load_schema()
        self._build()
        self.after(100, lambda: self.load(default_dump_path()))

    @staticmethod
    def _load_schema():
        try:
            from core.schema import Schema
            return Schema()
        except Exception:
            return None

    # -- layout ----------------------------------------------------------
    def _build(self) -> None:
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="Open dump...", command=self.pick).pack(side="left")
        ttk.Label(bar, text="  filter ").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self.refresh())
        ttk.Entry(bar, textvariable=self.filter_var, width=28).pack(side="left")
        ttk.Label(bar, text="  min refs ").pack(side="left")
        self.min_var = tk.StringVar(value="1")
        self.min_var.trace_add("write", lambda *_: self.refresh())
        ttk.Spinbox(bar, from_=1, to=200, width=5,
                    textvariable=self.min_var).pack(side="left")
        self.status = ttk.Label(bar, text="loading...")
        self.status.pack(side="right")

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, columns=("refs",), show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="Engine-side prefab")
        self.tree.heading("refs", text="Refs")
        self.tree.column("#0", width=380)
        self.tree.column("refs", width=60, anchor="e")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show())
        panes.add(left, weight=3)

        right = ttk.Frame(panes)
        self.detail = tk.Text(right, wrap="word", height=10,
                              font=("Consolas", 9))
        self.detail.pack(fill="both", expand=True)
        actions = ttk.Frame(right, padding=(0, 6))
        actions.pack(fill="x")
        self.build_button = ttk.Button(actions, text="Reconstruct from running game",
                                       command=self.build, state="disabled")
        self.build_button.pack(side="left")
        ttk.Label(actions, text="  (needs the game loaded into a world)").pack(side="left")
        panes.add(right, weight=4)

    # -- data ------------------------------------------------------------
    def pick(self) -> None:
        path = filedialog.askopenfilename(
            title="Open a JWE3 prefab dump",
            filetypes=[("Prefab dump", "*.lua"), ("All files", "*.*")],
        )
        if path:
            self.load(path)

    def load(self, path: str) -> None:
        self.status.config(text="reading %s ..." % os.path.basename(path))
        self.update_idletasks()
        try:
            self.dump = Dump(path)
            self.rows = self.dump.engine_side_candidates()
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("Could not read the dump", str(error))
            self.status.config(text="failed")
            return
        self.title("JWE3 Engine-Side Prefabs - %s" % os.path.basename(path))
        self.refresh()

    def refresh(self) -> None:
        if self.dump is None:
            return
        needle = self.filter_var.get().strip().lower()
        try:
            minimum = int(self.min_var.get() or 1)
        except ValueError:
            minimum = 1
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for name, count in self.rows:
            if count < minimum or (needle and needle not in name.lower()):
                continue
            self.tree.insert("", "end", text=name, values=(count,))
            shown += 1
        self.status.config(
            text="%d shown of %d engine-side  (%d defined entries)"
                 % (shown, len(self.rows), len(self.dump.entry_names()))
        )

    def selected(self) -> str | None:
        item = self.tree.focus()
        return self.tree.item(item, "text") if item else None

    def show(self) -> None:
        name = self.selected()
        if not name or self.dump is None:
            return
        self.detail.delete("1.0", "end")
        refs = self.dump.reference_counts().get(name, 0)
        lines = ["%s\n%s\n" % (name, "=" * len(name)),
                 "referenced %d time(s), never defined at column 0.\n" % refs,
                 "A Lua prefab cannot inherit this: it compiles and spawns an\n"
                 "entity missing everything the base provided, and nothing is\n"
                 "logged. Reconstruct it instead.\n"]
        if self.schema is not None:
            if self.schema.component(name) is not None:
                lines.append("\nNOTE: a specdef exists for this name - it may be a\n"
                             "component rather than a prefab.\n")
        consumers = self.dump.consumers(name)
        lines.append("\nWhere its content can be read from (%d):\n" % len(consumers))
        for entry, child, size in consumers[:12]:
            where = ("child=%s" % child) if child else "(root inheritor)"
            lines.append("   %-44s %-24s %dB\n" % (entry, where, size))
        if not consumers:
            lines.append("   none - nothing inherits it, so there is nothing to read.\n")
        self.detail.insert("1.0", "".join(lines))
        self.build_button.config(state="normal" if consumers else "disabled")

    # -- build -----------------------------------------------------------
    def build(self) -> None:
        name = self.selected()
        if not name or self.dump is None:
            return
        self.build_button.config(state="disabled")
        self.detail.insert("end", "\nreading from the running game ...\n")
        self.detail.see("end")
        threading.Thread(target=self._build_worker, args=(name,), daemon=True).start()

    def _build_worker(self, name: str) -> None:
        try:
            rows = self.dump.consumers(name)[:3]
            sources = [(entry, child) for entry, child, _ in rows]
            body = probe.run(random.randint(900000, 998000), None, None,
                             sources=sources)
            if body.startswith("SOURCES"):
                body = body.partition("\n")[2]
            text = emit.render(name, body, rows[0][0], rows[0][1] or "(root)",
                               self.dump.reference_counts().get(name, 0))
            os.makedirs(OUT_DIR, exist_ok=True)
            path = os.path.join(OUT_DIR, name.lower() + ".lua")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            message = ("wrote %s (%d bytes)\n"
                       "NOT verified - compile it in game before shipping.\n"
                       % (path, len(text)))
        except Exception as error:  # noqa: BLE001
            message = "FAILED: %s\n" % error
        self.after(0, lambda: self._done(message))

    def _done(self, message: str) -> None:
        self.detail.insert("end", message)
        self.detail.see("end")
        self.build_button.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
