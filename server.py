"""
记账软件 API 服务端
启动方式: uvicorn server:app --host 0.0.0.0 --port 8000
环境变量:
  TURSO_DATABASE_URL - Turso 数据库 URL (如 libsql://xxx.turso.io)
  TURSO_AUTH_TOKEN   - Turso 认证 token
"""

import os
from datetime import datetime

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

app = FastAPI(title="记账本 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 数据库 ====================

def get_conn():
    if TURSO_URL and TURSO_TOKEN:
        import libsql_experimental as libsql
        return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    else:
        import sqlite3
        db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "accounting.db"))
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('income','expense'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            type       TEXT NOT NULL CHECK(type IN ('income','expense')),
            amount     REAL NOT NULL,
            category   TEXT NOT NULL,
            necessity  TEXT DEFAULT '',
            date       TEXT NOT NULL,
            note       TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    try:
        cols = [row[1] for row in c.execute("PRAGMA table_info(transactions)").fetchall()]
        if "necessity" not in cols:
            c.execute("ALTER TABLE transactions ADD COLUMN necessity TEXT DEFAULT ''")
    except Exception:
        pass
    if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        defaults = [
            ("工资", "income"), ("奖金", "income"), ("投资收益", "income"),
            ("兼职", "income"), ("红包", "income"), ("其他收入", "income"),
            ("餐饮", "expense"), ("交通", "expense"), ("购物", "expense"),
            ("住房", "expense"), ("娱乐", "expense"), ("医疗", "expense"),
            ("教育", "expense"), ("通讯", "expense"), ("水电", "expense"),
            ("其他支出", "expense"),
        ]
        c.executemany("INSERT INTO categories (name, type) VALUES (?, ?)", defaults)
    conn.commit()
    conn.close()


init_db()


# ==================== Models ====================

class TransactionIn(BaseModel):
    type: str
    amount: float
    category: str
    necessity: str = ""
    date: str
    note: str = ""


class CategoryIn(BaseModel):
    name: str
    type: str


# ==================== Transactions ====================

@app.get("/api/transactions")
def list_transactions(
    ttype: str | None = Query(None),
    year: int | None = Query(None),
    month: int | None = Query(None),
):
    conn = get_conn()
    sql = "SELECT id, type, amount, category, necessity, date, note, created_at FROM transactions WHERE 1=1"
    params: list = []
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
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [
        {"id": r[0], "type": r[1], "amount": r[2], "category": r[3],
         "necessity": r[4], "date": r[5], "note": r[6], "created_at": r[7]}
        for r in rows
    ]


@app.post("/api/transactions", status_code=201)
def create_transaction(txn: TransactionIn):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO transactions (type, amount, category, necessity, date, note, created_at) VALUES (?,?,?,?,?,?,?)",
        (txn.type, txn.amount, txn.category, txn.necessity, txn.date, txn.note, datetime.now().isoformat()),
    )
    txn_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {"id": txn_id}


@app.delete("/api/transactions/{txn_id}")
def delete_transaction(txn_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/transactions/import")
def import_transactions(transactions: list[TransactionIn]):
    conn = get_conn()
    added = 0
    for t in transactions:
        conn.execute(
            "INSERT INTO transactions (type, amount, category, necessity, date, note, created_at) VALUES (?,?,?,?,?,?,?)",
            (t.type, t.amount, t.category, t.necessity, t.date, t.note, datetime.now().isoformat()),
        )
        added += 1
    conn.commit()
    conn.close()
    return {"added": added}


@app.get("/api/transactions/export")
def export_transactions():
    conn = get_conn()
    rows = conn.execute(
        "SELECT type, amount, category, necessity, date, note FROM transactions ORDER BY date, id"
    ).fetchall()
    conn.close()
    return [
        {"类型": r[0], "金额": r[1], "分类": r[2], "必要性": r[3], "日期": r[4], "备注": r[5]}
        for r in rows
    ]


# ==================== Categories ====================

@app.get("/api/categories")
def list_categories(ttype: str | None = Query(None)):
    conn = get_conn()
    if ttype:
        rows = conn.execute("SELECT name, type FROM categories WHERE type=? ORDER BY id", (ttype,)).fetchall()
    else:
        rows = conn.execute("SELECT name, type FROM categories ORDER BY type, id").fetchall()
    conn.close()
    return [{"name": r[0], "type": r[1]} for r in rows]


@app.post("/api/categories", status_code=201)
def create_category(cat: CategoryIn):
    conn = get_conn()
    conn.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (cat.name, cat.type))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/categories")
def delete_category(name: str = Query(...), ttype: str = Query(...)):
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE name=? AND type=?", (name, ttype))
    conn.commit()
    conn.close()
    return {"ok": True}


# ==================== 统计 ====================

@app.get("/api/summary")
def get_summary(year: int, month: int):
    conn = get_conn()
    ym_prefix = f"{year}-{month:02d}"
    income = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date LIKE ?",
        (ym_prefix + "%",),
    ).fetchone()[0]
    expense = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date LIKE ?",
        (ym_prefix + "%",),
    ).fetchone()[0]
    cat_rows = conn.execute(
        "SELECT category, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? GROUP BY category ORDER BY SUM(amount) DESC",
        (ym_prefix + "%",),
    ).fetchall()
    nec_rows = conn.execute(
        "SELECT necessity, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? AND necessity != '' GROUP BY necessity ORDER BY SUM(amount) DESC",
        (ym_prefix + "%",),
    ).fetchall()
    conn.close()
    return {
        "income": income,
        "expense": expense,
        "categories": [{"category": r[0], "amount": r[1]} for r in cat_rows],
        "necessity": [{"necessity": r[0], "amount": r[1]} for r in nec_rows],
    }


@app.get("/api/assets")
def get_assets():
    conn = get_conn()
    income, expense = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0), "
        "COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) FROM transactions"
    ).fetchone()
    conn.close()
    return {"assets": income - expense}


@app.get("/api/years")
def get_years():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT strftime('%Y', date) FROM transactions ORDER BY date DESC"
    ).fetchall()
    conn.close()
    return [int(r[0]) for r in rows if r[0]]
