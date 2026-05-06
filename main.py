"""
个人记账本 - 一个简单的小型个人记账软件
功能：记账录入、账目列表、分类管理、统计概览
数据存储在 Turso 云数据库，支持多设备共享
"""

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime, date
from urllib.request import Request, urlopen
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


TURSO_URL = ""
TURSO_TOKEN = ""


def _init_credentials():
    global TURSO_URL, TURSO_TOKEN
    cfg = _load_config()
    TURSO_URL = cfg.get("turso_url", "")
    TURSO_TOKEN = cfg.get("turso_token", "")


def _save_credentials(url, token):
    global TURSO_URL, TURSO_TOKEN
    TURSO_URL = url
    TURSO_TOKEN = token
    cfg = _load_config()
    cfg["turso_url"] = url
    cfg["turso_token"] = token
    _save_config(cfg)


# ==================== Turso HTTP API ====================

def _turso_api_url():
    if TURSO_URL.startswith("libsql://"):
        return "https://" + TURSO_URL[len("libsql://"):] + "/v2/pipeline"
    return TURSO_URL + "/v2/pipeline"


def _val(cell):
    if isinstance(cell, dict):
        return cell.get("value", cell)
    return cell


def turso_exec(sql, args=None):
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "text", "value": str(a)} for a in args]
    body = json.dumps({"requests": [{"type": "execute", "stmt": stmt}]}).encode()
    req = Request(_turso_api_url(), data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + TURSO_TOKEN,
    }, method="POST")
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    result = data["results"][0]
    if result.get("type") == "error":
        raise Exception(result["error"]["message"])
    r = result["response"]["result"]
    return {
        "rows": r.get("rows", []),
        "cols": [c["name"] for c in r.get("cols", [])],
        "affected": r.get("affected_row_count", 0),
        "last_id": r.get("last_insert_rowid"),
    }


def _test_connection():
    try:
        turso_exec("SELECT 1")
        return True
    except Exception:
        return False


# ==================== 数据层 ====================

def init_db():
    turso_exec("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('income','expense'))
    )""")
    turso_exec("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL CHECK(type IN ('income','expense')),
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        necessity TEXT DEFAULT '',
        date TEXT NOT NULL,
        note TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    r = turso_exec("SELECT COUNT(*) FROM categories")
    if int(_val(r["rows"][0][0])) == 0:
        defaults = [
            ("工资", "income"), ("奖金", "income"), ("投资收益", "income"),
            ("兼职", "income"), ("红包", "income"), ("其他收入", "income"),
            ("餐饮", "expense"), ("交通", "expense"), ("购物", "expense"),
            ("住房", "expense"), ("娱乐", "expense"), ("医疗", "expense"),
            ("教育", "expense"), ("通讯", "expense"), ("水电", "expense"),
            ("其他支出", "expense"),
        ]
        for name, ttype in defaults:
            turso_exec("INSERT INTO categories (name, type) VALUES (?, ?)", [name, ttype])


def add_transaction(ttype, amount, category, txn_date, note, necessity=""):
    turso_exec(
        "INSERT INTO transactions (type, amount, category, necessity, date, note, created_at) VALUES (?,?,?,?,?,?,?)",
        [ttype, amount, category, necessity, txn_date, note, datetime.now().isoformat()],
    )


def delete_transaction(txn_id):
    turso_exec("DELETE FROM transactions WHERE id=?", [txn_id])


def query_transactions(ttype=None, year=None, month=None):
    sql = "SELECT id, type, amount, category, necessity, date, note FROM transactions WHERE 1=1"
    params = []
    if ttype:
        sql += " AND type=?"
        params.append(ttype)
    if year and month:
        sql += " AND strftime('%Y', date)=? AND strftime('%m', date)=?"
        params.extend([str(year), f"{month:02d}"])
    elif year:
        sql += " AND strftime('%Y', date)=?"
        params.append(str(year))
    sql += " ORDER BY date DESC, id DESC"
    r = turso_exec(sql, params)
    result = []
    for row in r["rows"]:
        v = [_val(c) for c in row]
        result.append((int(v[0]), v[1], float(v[2]), v[3], v[4], v[5], v[6]))
    return result


def get_categories(ttype=None):
    if ttype:
        r = turso_exec("SELECT name FROM categories WHERE type=? ORDER BY id", [ttype])
        return [_val(row[0]) for row in r["rows"]]
    else:
        r = turso_exec("SELECT name, type FROM categories ORDER BY type, id")
        return [(_val(row[0]), _val(row[1])) for row in r["rows"]]


def add_category(name, ttype):
    turso_exec("INSERT INTO categories (name, type) VALUES (?, ?)", [name, ttype])


def delete_category(name, ttype):
    turso_exec("DELETE FROM categories WHERE name=? AND type=?", [name, ttype])


def get_summary(year, month):
    ym = f"{year}-{month:02d}"
    r = turso_exec("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date LIKE ?", [ym + "%"])
    income = float(_val(r["rows"][0][0]))
    r = turso_exec("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date LIKE ?", [ym + "%"])
    expense = float(_val(r["rows"][0][0]))
    r = turso_exec("SELECT category, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? GROUP BY category ORDER BY SUM(amount) DESC", [ym + "%"])
    cat_rows = [(_val(row[0]), float(_val(row[1]))) for row in r["rows"]]
    r = turso_exec("SELECT necessity, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? AND necessity != '' GROUP BY necessity ORDER BY SUM(amount) DESC", [ym + "%"])
    nec_rows = [(_val(row[0]), float(_val(row[1]))) for row in r["rows"]]
    return income, expense, cat_rows, nec_rows


def get_total_assets():
    r = turso_exec("SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0), COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) FROM transactions")
    income = float(_val(r["rows"][0][0]))
    expense = float(_val(r["rows"][0][1]))
    return income - expense


def get_available_years():
    r = turso_exec("SELECT DISTINCT strftime('%Y', date) FROM transactions ORDER BY date DESC")
    return [int(_val(row[0])) for row in r["rows"] if _val(row[0])]


# ==================== GUI 层 ====================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("个人记账本")
        self.geometry("780x520")
        self.minsize(680, 420)
        self.resizable(True, True)

        self._apply_style()
        _init_credentials()

        # 检查连接
        if not TURSO_URL or not TURSO_TOKEN:
            if not self._prompt_credentials(first_time=True):
                self.destroy()
                return
        elif not _test_connection():
            if not self._prompt_credentials(first_time=False):
                self.destroy()
                return

        init_db()

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

    # ---------- 数据库凭证 ----------
    def _prompt_credentials(self, first_time=True):
        title = "连接云数据库" if first_time else "连接失败，请重新输入"
        dlg = CredentialDialog(self, title)
        self.wait_window(dlg)
        if dlg.result:
            url, token = dlg.result
            _save_credentials(url, token)
            if _test_connection():
                return True
            else:
                messagebox.showerror("连接失败", "无法连接数据库，请检查 URL 和 Token。", parent=self)
                return self._prompt_credentials(first_time=False)
        return False

    # ---------- 顶部标题栏 ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill=tk.X)
        ttk.Label(bar, text="个人记账本", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(bar, text="+ 记账", style="Accent.TButton", command=self._on_add).pack(side=tk.RIGHT, padx=4)
        ttk.Button(bar, text="分类管理", command=self._on_manage_categories).pack(side=tk.RIGHT, padx=4)
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

    def _on_add(self):
        AddDialog(self, on_save=self._refresh_list)

    def _on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("确认删除", "确定要删除这条记录吗？"):
            delete_transaction(int(sel[0]))
            self._refresh_list()

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

    def _on_manage_categories(self):
        CategoryDialog(self)


# ==================== 凭证输入对话框 ====================

class CredentialDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result = None

        self._build()
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        pad = {"padx": 10, "pady": 6}
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="连接 Turso 云数据库", font=("Microsoft YaHei UI", 11, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 12))

        ttk.Label(frame, text="Database URL:").grid(row=1, column=0, sticky=tk.W, **pad)
        self.url_var = tk.StringVar(value=TURSO_URL)
        ttk.Entry(frame, textvariable=self.url_var, width=40).grid(row=1, column=1, sticky=tk.W, **pad)

        ttk.Label(frame, text="Auth Token:").grid(row=2, column=0, sticky=tk.W, **pad)
        self.token_var = tk.StringVar(value=TURSO_TOKEN)
        ttk.Entry(frame, textvariable=self.token_var, width=40, show="*").grid(row=2, column=1, sticky=tk.W, **pad)

        bf = ttk.Frame(frame)
        bf.grid(row=3, column=0, columnspan=2, pady=(16, 0))
        ttk.Button(bf, text="连接", command=self._on_ok).pack(side=tk.LEFT, padx=10)
        ttk.Button(bf, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=10)

    def _on_ok(self):
        url = self.url_var.get().strip()
        token = self.token_var.get().strip()
        if not url or not token:
            messagebox.showwarning("提示", "请填写 URL 和 Token", parent=self)
            return
        self.result = (url, token)
        self.destroy()


# ==================== 对话框 ====================

class AddDialog(tk.Toplevel):
    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.title("记账")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.on_save = on_save

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

        ttk.Label(frame, text="类型:").grid(row=0, column=0, sticky=tk.W, **pad)
        self.type_var = tk.StringVar(value="expense")
        tf = ttk.Frame(frame)
        tf.grid(row=0, column=1, sticky=tk.W, **pad)
        ttk.Radiobutton(tf, text="支出", variable=self.type_var, value="expense", command=self._on_type_change).pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(tf, text="收入", variable=self.type_var, value="income", command=self._on_type_change).pack(side=tk.LEFT, padx=4)

        ttk.Label(frame, text="金额 (元):").grid(row=1, column=0, sticky=tk.W, **pad)
        self.amount_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.amount_var, width=20).grid(row=1, column=1, sticky=tk.W, **pad)

        ttk.Label(frame, text="分类:").grid(row=2, column=0, sticky=tk.W, **pad)
        self.cat_var = tk.StringVar()
        self.cat_combo = ttk.Combobox(frame, textvariable=self.cat_var, width=18, state="readonly")
        self.cat_combo.grid(row=2, column=1, sticky=tk.W, **pad)
        self._refresh_categories()

        self.nec_label = ttk.Label(frame, text="必要性:")
        self.nec_label.grid(row=3, column=0, sticky=tk.W, **pad)
        self.nec_var = tk.StringVar(value="必须")
        self.nec_frame = ttk.Frame(frame)
        self.nec_frame.grid(row=3, column=1, sticky=tk.W, **pad)
        ttk.Radiobutton(self.nec_frame, text="必须", variable=self.nec_var, value="必须").pack(side=tk.LEFT, padx=4)
        ttk.Radiobutton(self.nec_frame, text="非必须", variable=self.nec_var, value="非必须").pack(side=tk.LEFT, padx=4)

        ttk.Label(frame, text="日期:").grid(row=4, column=0, sticky=tk.W, **pad)
        self.date_var = tk.StringVar(value=date.today().isoformat())
        df = ttk.Frame(frame)
        df.grid(row=4, column=1, sticky=tk.W, **pad)
        ttk.Entry(df, textvariable=self.date_var, width=14).pack(side=tk.LEFT)
        ttk.Label(df, text="(YYYY-MM-DD)").pack(side=tk.LEFT, padx=4)

        ttk.Label(frame, text="备注:").grid(row=5, column=0, sticky=tk.W, **pad)
        self.note_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.note_var, width=30).grid(row=5, column=1, sticky=tk.W, **pad)

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
