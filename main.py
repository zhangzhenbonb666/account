"""
个人记账本 - 一个简单的小型个人记账软件
功能：记账录入、账目列表、分类管理、统计概览
客户端模式：通过 HTTP API 与服务端通信
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime, date
from urllib.request import Request, urlopen
from urllib.error import URLError
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


# ==================== 配置 ====================

def _load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_server_url():
    cfg = _load_config()
    return cfg.get("server_url", "")


def set_server_url(url):
    cfg = _load_config()
    cfg["server_url"] = url.rstrip("/")
    _save_config(cfg)


# ==================== API 客户端 ====================

def api_get(path, params=None):
    url = get_server_url() + path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += "?" + qs
    req = Request(url)
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_post(path, data):
    url = get_server_url() + path
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def api_delete(path, params=None):
    url = get_server_url() + path
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url += "?" + qs
    req = Request(url, method="DELETE")
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


# ==================== 数据层 ====================

def add_transaction(ttype, amount, category, txn_date, note, necessity=""):
    api_post("/api/transactions", {
        "type": ttype, "amount": amount, "category": category,
        "necessity": necessity, "date": txn_date, "note": note,
    })


def delete_transaction(txn_id):
    api_delete(f"/api/transactions/{txn_id}")


def query_transactions(ttype=None, year=None, month=None):
    params = {}
    if ttype:
        params["ttype"] = ttype
    if year:
        params["year"] = year
    if month:
        params["month"] = month
    rows = api_get("/api/transactions", params)
    return [(r["id"], r["type"], r["amount"], r["category"], r["necessity"], r["date"], r["note"]) for r in rows]


def get_categories(ttype=None):
    params = {"ttype": ttype} if ttype else {}
    rows = api_get("/api/categories", params)
    if ttype:
        return [r["name"] for r in rows]
    return [(r["name"], r["type"]) for r in rows]


def add_category(name, ttype):
    api_post("/api/categories", {"name": name, "type": ttype})


def delete_category(name, ttype):
    api_delete("/api/categories", {"name": name, "ttype": ttype})


def get_summary(year, month):
    r = api_get("/api/summary", {"year": year, "month": month})
    return (
        r["income"],
        r["expense"],
        [(c["category"], c["amount"]) for c in r["categories"]],
        [(n["necessity"], n["amount"]) for n in r["necessity"]],
    )


def get_total_assets():
    return api_get("/api/assets")["assets"]


def get_available_years():
    return api_get("/api/years")


# ==================== GUI 层 ====================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("个人记账本")
        self.geometry("780x520")
        self.minsize(680, 420)
        self.resizable(True, True)

        self._apply_style()

        # 检查服务端连接
        server_url = get_server_url()
        if not server_url:
            self._prompt_server_url(first_time=True)
        else:
            try:
                api_get("/api/assets")
            except Exception:
                if not self._prompt_server_url(first_time=False):
                    self.destroy()
                    return

        self._build_toolbar()
        self._build_filter_bar()
        self._build_treeview()
        self._build_statusbar()

        self._refresh_list()

    # ---------- 样式 ----------
    def _apply_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=28, font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("AssetLabel.TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("AssetValue.TLabel", font=("Microsoft YaHei UI", 12, "bold"), foreground="#1565c0")
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    # ---------- 服务端地址 ----------
    def _prompt_server_url(self, first_time=True):
        title = "设置服务端地址" if not first_time else "欢迎使用记账本"
        msg = "请输入服务端地址:" if first_time else "无法连接服务端，请输入正确的地址:"
        url = simpledialog.askstring(title, msg, parent=self, initialvalue=get_server_url())
        if url:
            url = url.strip().rstrip("/")
            set_server_url(url)
            try:
                api_get("/api/assets")
                return True
            except Exception:
                messagebox.showerror("连接失败", f"无法连接到: {url}\n请检查地址是否正确、服务端是否已启动。", parent=self)
                return self._prompt_server_url(first_time=False)
        return False

    # ---------- 顶部标题栏 ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="个人记账本", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(bar, text="+ 记账", style="Accent.TButton", command=self._on_add).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="分类管理", command=self._on_manage_categories).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="服务端", command=self._on_change_server).pack(side=tk.RIGHT, padx=4)
        self.asset_var = tk.StringVar(value="¥0.00")
        asset_frame = ttk.Frame(bar)
        asset_frame.pack(side=tk.RIGHT, padx=(0, 16))
        ttk.Label(asset_frame, text="总资产", style="AssetLabel.TLabel").pack(side=tk.LEFT)
        ttk.Label(asset_frame, textvariable=self.asset_var, style="AssetValue.TLabel").pack(side=tk.LEFT, padx=(6, 0))

    # ---------- 筛选栏 ----------
    def _build_filter_bar(self):
        bar = ttk.Frame(self, padding=(10, 4))
        bar.pack(fill=tk.X)

        self.filter_type = tk.StringVar(value="all")
        for val, label in [("all", "全部"), ("income", "收入"), ("expense", "支出")]:
            ttk.Radiobutton(bar, text=label, variable=self.filter_type, value=val, command=self._refresh_list).pack(side=tk.LEFT, padx=4)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # 年月筛选
        years = ["全部"] + [str(y) for y in sorted((get_available_years() or [date.today().year]), reverse=True)]
        ttk.Label(bar, text="年份:").pack(side=tk.LEFT, padx=(4, 2))
        self.filter_year = ttk.Combobox(bar, values=years, width=6, state="readonly")
        self.filter_year.set(str(date.today().year))
        self.filter_year.pack(side=tk.LEFT)
        self.filter_year.bind("<<ComboboxSelected>>", lambda e: self._on_year_change())

        ttk.Label(bar, text="月份:").pack(side=tk.LEFT, padx=(8, 2))
        months = ["全部"] + [f"{i}月" for i in range(1, 13)]
        self.filter_month = ttk.Combobox(bar, values=months, width=6, state="readonly")
        self.filter_month.set(f"{date.today().month}月")
        self.filter_month.pack(side=tk.LEFT)
        self.filter_month.bind("<<ComboboxSelected>>", lambda e: self._refresh_list())

        ttk.Button(bar, text="统计", command=self._on_summary).pack(side=tk.RIGHT, padx=4)

    def _on_year_change(self):
        self._refresh_year_options()
        self._refresh_list()

    def _refresh_year_options(self):
        years = ["全部"] + [str(y) for y in sorted((get_available_years() or [date.today().year]), reverse=True)]
        self.filter_year["values"] = years

    # ---------- 表格 ----------
    def _build_treeview(self):
        frame = ttk.Frame(self, padding=(10, 4))
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ("date", "type", "category", "necessity", "amount", "note")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("date", text="日期")
        self.tree.heading("type", text="类型")
        self.tree.heading("category", text="分类")
        self.tree.heading("necessity", text="必要性")
        self.tree.heading("amount", text="金额")
        self.tree.heading("note", text="备注")

        self.tree.column("date", width=90, anchor=tk.CENTER)
        self.tree.column("type", width=50, anchor=tk.CENTER)
        self.tree.column("category", width=70, anchor=tk.CENTER)
        self.tree.column("necessity", width=60, anchor=tk.CENTER)
        self.tree.column("amount", width=100, anchor=tk.E)
        self.tree.column("note", width=340, anchor=tk.W)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 右键菜单
        self.ctx_menu = tk.Menu(self, tearoff=0)
        self.ctx_menu.add_command(label="删除记录", command=self._on_delete)
        self.tree.bind("<Button-3>", self._show_ctx_menu)

    def _show_ctx_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.ctx_menu.tk_popup(event.x_root, event.y_root)

    # ---------- 底部状态栏 ----------
    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="当前筛选: 收入 ¥0.00  |  支出 ¥0.00  |  结余 ¥0.00")
        bar = ttk.Frame(self, padding=(10, 6))
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status_var, style="Status.TLabel").pack(side=tk.LEFT)

    # ---------- 刷新列表 ----------
    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        ttype = self.filter_type.get()
        if ttype == "all":
            ttype = None

        year_str = self.filter_year.get()
        if year_str == "全部":
            year = None
            month = None
        else:
            try:
                year = int(year_str)
            except ValueError:
                year = date.today().year

            month_str = self.filter_month.get()
            if month_str == "全部":
                month = None
            else:
                month = int(month_str.replace("月", ""))

        try:
            rows = query_transactions(ttype, year, month)
        except Exception as e:
            messagebox.showerror("错误", f"获取数据失败: {e}")
            return

        total_income = 0.0
        total_expense = 0.0

        for txn_id, tp, amount, cat, nec, txn_date, note in rows:
            tag = "income" if tp == "income" else "expense"
            type_label = "收入" if tp == "income" else "支出"
            amount_display = f"+{amount:,.2f}" if tp == "income" else f"-{amount:,.2f}"
            nec_display = nec if tp == "expense" else ""
            self.tree.insert("", tk.END, iid=str(txn_id), values=(txn_date, type_label, cat, nec_display, amount_display, note), tags=(tag,))
            if tp == "income":
                total_income += amount
            else:
                total_expense += amount

        self.tree.tag_configure("income", foreground="#2e7d32")
        self.tree.tag_configure("expense", foreground="#c62828")

        balance = total_income - total_expense
        try:
            self.asset_var.set(f"¥{get_total_assets():,.2f}")
        except Exception:
            self.asset_var.set("¥--")
        self.status_var.set(
            f"当前筛选: 收入 ¥{total_income:,.2f}  |  支出 ¥{total_expense:,.2f}  |  结余 ¥{balance:,.2f}"
        )

    # ---------- 添加记录 ----------
    def _on_add(self):
        AddDialog(self, on_save=self._refresh_list)

    # ---------- 删除记录 ----------
    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("确认删除", "确定要删除这条记录吗？"):
            delete_transaction(int(sel[0]))
            self._refresh_list()

    # ---------- 统计 ----------
    def _on_summary(self):
        year_str = self.filter_year.get()
        if year_str == "全部":
            year = simpledialog.askinteger("选择年份", "请输入年份:", minvalue=2000, maxvalue=2100)
            if not year:
                return
        else:
            try:
                year = int(year_str)
            except ValueError:
                year = date.today().year
        month_str = self.filter_month.get()
        if month_str == "全部":
            month = simpledialog.askinteger("选择月份", "请输入月份 (1-12):", minvalue=1, maxvalue=12)
            if not month:
                return
        else:
            month = int(month_str.replace("月", ""))

        income, expense, cat_rows, nec_rows = get_summary(year, month)
        SummaryDialog(self, year, month, income, expense, cat_rows, nec_rows)

    # ---------- 分类管理 ----------
    def _on_manage_categories(self):
        CategoryDialog(self)

    # ---------- 更改服务端 ----------
    def _on_change_server(self):
        url = simpledialog.askstring("服务端地址", "请输入服务端地址:", parent=self, initialvalue=get_server_url())
        if url:
            url = url.strip().rstrip("/")
            set_server_url(url)
            try:
                api_get("/api/assets")
                messagebox.showinfo("连接成功", f"已连接到: {url}")
                self._refresh_list()
            except Exception:
                messagebox.showerror("连接失败", f"无法连接到: {url}")


# ==================== 对话框 ====================

class AddDialog(tk.Toplevel):
    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.title("记账")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save
        self.result = None

        self._build()
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        pad = {"padx": 10, "pady": 6}
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # 类型
        ttk.Label(frame, text="类型:").grid(row=0, column=0, sticky=tk.W, **pad)
        self.type_var = tk.StringVar(value="expense")
        tf = ttk.Frame(frame)
        tf.grid(row=0, column=1, sticky=tk.W, **pad)
        ttk.Radiobutton(tf, text="支出", variable=self.type_var, value="expense", command=self._on_type_change).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(tf, text="收入", variable=self.type_var, value="income", command=self._on_type_change).pack(side=tk.LEFT, padx=4)

        # 金额
        ttk.Label(frame, text="金额 (元):").grid(row=1, column=0, sticky=tk.W, **pad)
        self.amount_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.amount_var, width=20).grid(row=1, column=1, sticky=tk.W, **pad)

        # 分类
        ttk.Label(frame, text="分类:").grid(row=2, column=0, sticky=tk.W, **pad)
        self.cat_var = tk.StringVar()
        self.cat_combo = ttk.Combobox(frame, textvariable=self.cat_var, width=18, state="readonly")
        self.cat_combo.grid(row=2, column=1, sticky=tk.W, **pad)
        self._refresh_categories()

        # 必要性（仅支出）
        self.nec_label = ttk.Label(frame, text="必要性:")
        self.nec_label.grid(row=3, column=0, sticky=tk.W, **pad)
        self.nec_var = tk.StringVar(value="必须")
        self.nec_frame = ttk.Frame(frame)
        self.nec_frame.grid(row=3, column=1, sticky=tk.W, **pad)
        ttk.Radiobutton(self.nec_frame, text="必须", variable=self.nec_var, value="必须").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(self.nec_frame, text="非必须", variable=self.nec_var, value="非必须").pack(side=tk.LEFT, padx=4)

        # 日期
        ttk.Label(frame, text="日期:").grid(row=4, column=0, sticky=tk.W, **pad)
        self.date_var = tk.StringVar(value=date.today().isoformat())
        df = ttk.Frame(frame)
        df.grid(row=4, column=1, sticky=tk.W, **pad)
        ttk.Entry(df, textvariable=self.date_var, width=14).pack(side=tk.LEFT)
        ttk.Label(df, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=4)

        # 备注
        ttk.Label(frame, text="备注:").grid(row=5, column=0, sticky=tk.W, **pad)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(row=5, column=1, sticky=tk.W, **pad)

        # 按钮
        bf = ttk.Frame(frame)
        bf.grid(row=6, column=0, columnspan=2, pady=(16, 0))
        ttk.Button(bf, text="保存", command=self._on_ok).pack(side=tk.LEFT, padx=10)
        ttk.Button(bf, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)

    def _on_type_change(self):
        self._refresh_categories()
        if self.type_var.get() == "expense":
            self.nec_label.grid()
            self.nec_frame.grid()
        else:
            self.nec_label.grid_remove()
            self.nec_frame.grid_remove()

    def _refresh_categories(self):
        try:
            cats = get_categories(self.type_var.get())
        except Exception:
            cats = []
        self.cat_combo["values"] = cats
        if cats:
            self.cat_combo.set(cats[0])

    def _on_ok(self):
        amount_str = self.amount_var.get().strip()
        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("错误", "请输入正确的正数金额", parent=self)
            return

        txn_date = self.date_var.get().strip()
        try:
            datetime.strptime(txn_date, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("错误", "日期格式不正确，请使用 YYYY-MM-DD", parent=self)
            return

        category = self.cat_var.get()
        if not category:
            messagebox.showerror("错误", "请选择分类", parent=self)
            return

        necessity = self.nec_var.get() if self.type_var.get() == "expense" else ""
        add_transaction(self.type_var.get(), amount, category, txn_date, self.note_var.get().strip(), necessity)
        if self.on_save:
            self.on_save()
        self.destroy()


class SummaryDialog(tk.Toplevel):
    def __init__(self, parent, year, month, income, expense, cat_rows, nec_rows):
        super().__init__(parent)
        self.title(f"{year}年{month}月 收支统计")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build(year, month, income, expense, cat_rows, nec_rows)
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self, year, month, income, expense, cat_rows, nec_rows):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"{year}年{month}月 收支概览", font=("Microsoft YaHei UI", 13, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 12))

        balance = income - expense
        items = [
            ("总收入:", f"¥{income:,.2f}", "#2e7d32"),
            ("总支出:", f"¥{expense:,.2f}", "#c62828"),
            ("结余:", f"¥{balance:,.2f}", "#1565c0" if balance >= 0 else "#c62828"),
        ]
        for i, (label, value, color) in enumerate(items):
            ttk.Label(frame, text=label, font=("Microsoft YaHei UI", 11)).grid(row=i + 1, column=0, sticky=tk.W, padx=10, pady=3)
            lbl = ttk.Label(frame, text=value, font=("Microsoft YaHei UI", 11, "bold"))
            lbl.grid(row=i + 1, column=1, sticky=tk.W, padx=10, pady=3)
            lbl.configure(foreground=color)

        row_offset = 4

        # 必须/非必须明细
        if nec_rows:
            ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=row_offset, column=0, columnspan=2, sticky=tk.EW, pady=12)
            row_offset += 1
            ttk.Label(frame, text="必要性分析", font=("Microsoft YaHei UI", 11, "bold")).grid(row=row_offset, column=0, columnspan=2, pady=(0, 6))
            row_offset += 1

            cols = ("necessity", "amount", "percent")
            nec_tree = ttk.Treeview(frame, columns=cols, show="headings", height=min(len(nec_rows), 4))
            nec_tree.heading("necessity", text="必要性")
            nec_tree.heading("amount", text="金额")
            nec_tree.heading("percent", text="占比")
            nec_tree.column("necessity", width=100, anchor=tk.CENTER)
            nec_tree.column("amount", width=100, anchor=tk.E)
            nec_tree.column("percent", width=80, anchor=tk.CENTER)
            nec_tree.grid(row=row_offset, column=0, columnspan=2, sticky=tk.EW)
            row_offset += 1

            total_exp = sum(r[1] for r in nec_rows)
            for nec, amt in nec_rows:
                pct = (amt / total_exp * 100) if total_exp else 0
                nec_tree.insert("", tk.END, values=(nec, f"¥{amt:,.2f}", f"{pct:.1f}%"))

        # 分类明细
        if cat_rows:
            ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=row_offset, column=0, columnspan=2, sticky=tk.EW, pady=12)
            row_offset += 1
            ttk.Label(frame, text="支出分类明细", font=("Microsoft YaHei UI", 11, "bold")).grid(row=row_offset, column=0, columnspan=2, pady=(0, 6))
            row_offset += 1

            cols = ("category", "amount", "percent")
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=min(len(cat_rows), 10))
            tree.heading("category", text="分类")
            tree.heading("amount", text="金额")
            tree.heading("percent", text="占比")
            tree.column("category", width=100, anchor=tk.CENTER)
            tree.column("amount", width=100, anchor=tk.E)
            tree.column("percent", width=80, anchor=tk.CENTER)
            tree.grid(row=row_offset, column=0, columnspan=2, sticky=tk.EW)
            row_offset += 1

            total_cat = sum(r[1] for r in cat_rows)
            for cat, amt in cat_rows:
                pct = (amt / total_cat * 100) if total_cat else 0
                tree.insert("", tk.END, values=(cat, f"¥{amt:,.2f}", f"{pct:.1f}%"))

        # 关闭按钮
        ttk.Button(frame, text="关闭", command=self.destroy).grid(row=row_offset, column=0, columnspan=2, pady=(16, 0))


class CategoryDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("分类管理")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build()
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="支出分类", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, sticky=tk.W, pady=(0, 6))
        self.exp_list = tk.Listbox(frame, height=8, width=20, font=("Microsoft YaHei UI", 10))
        self.exp_list.grid(row=1, column=0, padx=(0, 10))

        ttk.Label(frame, text="收入分类", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=1, sticky=tk.W, pady=(0, 6))
        self.inc_list = tk.Listbox(frame, height=8, width=20, font=("Microsoft YaHei UI", 10))
        self.inc_list.grid(row=1, column=1, padx=(10, 0))

        self._refresh_lists()

        # 添加/删除
        af = ttk.Frame(frame)
        af.grid(row=2, column=0, columnspan=2, pady=(12, 0))

        ttk.Label(af, text="类型:").pack(side=tk.LEFT, padx=4)
        self.new_type = tk.StringVar(value="expense")
        ttk.Radiobutton(af, text="支出", variable=self.new_type, value="expense").pack(side=tk.LEFT)
        ttk.Radiobutton(af, text="收入", variable=self.new_type, value="income").pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(af, text="名称:").pack(side=tk.LEFT, padx=4)
        self.new_name = tk.StringVar()
        ttk.Entry(af, textvariable=self.new_name, width=12).pack(side=tk.LEFT, padx=4)
        ttk.Button(af, text="添加", command=self._on_add).pack(side=tk.LEFT, padx=4)
        ttk.Button(af, text="删除选中", command=self._on_delete).pack(side=tk.LEFT, padx=4)

        ttk.Button(frame, text="关闭", command=self.destroy).grid(row=3, column=0, columnspan=2, pady=(12, 0))

    def _refresh_lists(self):
        self.exp_list.delete(0, tk.END)
        self.inc_list.delete(0, tk.END)
        try:
            for name, ttype in get_categories():
                if ttype == "expense":
                    self.exp_list.insert(tk.END, name)
                else:
                    self.inc_list.insert(tk.END, name)
        except Exception:
            pass

    def _on_add(self):
        name = self.new_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请输入分类名称", parent=self)
            return
        add_category(name, self.new_type.get())
        self.new_name.set("")
        self._refresh_lists()

    def _on_delete(self):
        ttype = self.new_type.get()
        if ttype == "expense":
            sel = self.exp_list.curselection()
            if sel:
                name = self.exp_list.get(sel[0])
                if messagebox.askyesno("确认", f"确定删除分类「{name}」？", parent=self):
                    delete_category(name, ttype)
                    self._refresh_lists()
        else:
            sel = self.inc_list.curselection()
            if sel:
                name = self.inc_list.get(sel[0])
                if messagebox.askyesno("确认", f"确定删除分类「{name}」？", parent=self):
                    delete_category(name, ttype)
                    self._refresh_lists()


# ==================== 启动 ====================

if __name__ == "__main__":
    app = App()
    app.mainloop()
