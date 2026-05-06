"""
记账软件 API 服务端
启动方式: uvicorn server:app --host 0.0.0.0 --port 8000
环境变量:
  TURSO_DATABASE_URL - Turso 数据库 URL (如 libsql://xxx.turso.io)
  TURSO_AUTH_TOKEN   - Turso 认证 token
"""

import json
import os
from datetime import datetime
from urllib.request import Request, urlopen

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


# ==================== Turso HTTP API ====================

def _turso_api_url():
    if TURSO_URL.startswith("libsql://"):
        return "https://" + TURSO_URL[len("libsql://"):] + "/v2/pipeline"
    return TURSO_URL + "/v2/pipeline"


def turso_exec(sql, args=None):
    """通过 Turso HTTP API 执行 SQL，返回 rows 列表"""
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
    if int(r["rows"][0][0]["value"]) == 0:
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


# ==================== 行/值解析 ====================

def _val(cell):
    """从 Turso 单元格提取值"""
    if isinstance(cell, dict):
        return cell.get("value", cell)
    return cell


def _row(cells, cols):
    """将 Turso 行转为 dict"""
    return {col: _val(cell) for col, cell in zip(cols, cells)}


# ==================== Transactions ====================

@app.get("/api/transactions")
def list_transactions(
    ttype: str | None = Query(None),
    year: int | None = Query(None),
    month: int | None = Query(None),
):
    sql = "SELECT id, type, amount, category, necessity, date, note, created_at FROM transactions WHERE 1=1"
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
        result.append({
            "id": int(v[0]), "type": v[1], "amount": float(v[2]),
            "category": v[3], "necessity": v[4], "date": v[5],
            "note": v[6], "created_at": v[7],
        })
    return result


@app.post("/api/transactions", status_code=201)
def create_transaction(txn: TransactionIn):
    r = turso_exec(
        "INSERT INTO transactions (type, amount, category, necessity, date, note, created_at) VALUES (?,?,?,?,?,?,?)",
        [txn.type, txn.amount, txn.category, txn.necessity, txn.date, txn.note, datetime.now().isoformat()],
    )
    return {"id": int(r["last_id"] or 0)}


@app.delete("/api/transactions/{txn_id}")
def delete_transaction(txn_id: int):
    turso_exec("DELETE FROM transactions WHERE id=?", [txn_id])
    return {"ok": True}


@app.post("/api/transactions/import")
def import_transactions(transactions: list[TransactionIn]):
    added = 0
    for t in transactions:
        turso_exec(
            "INSERT INTO transactions (type, amount, category, necessity, date, note, created_at) VALUES (?,?,?,?,?,?,?)",
            [t.type, t.amount, t.category, t.necessity, t.date, t.note, datetime.now().isoformat()],
        )
        added += 1
    return {"added": added}


# ==================== Categories ====================

@app.get("/api/categories")
def list_categories(ttype: str | None = Query(None)):
    if ttype:
        r = turso_exec("SELECT name, type FROM categories WHERE type=? ORDER BY id", [ttype])
    else:
        r = turso_exec("SELECT name, type FROM categories ORDER BY type, id")
    return [{"name": _val(row[0]), "type": _val(row[1])} for row in r["rows"]]


@app.post("/api/categories", status_code=201)
def create_category(cat: CategoryIn):
    turso_exec("INSERT INTO categories (name, type) VALUES (?, ?)", [cat.name, cat.type])
    return {"ok": True}


@app.delete("/api/categories")
def delete_category(name: str = Query(...), ttype: str = Query(...)):
    turso_exec("DELETE FROM categories WHERE name=? AND type=?", [name, ttype])
    return {"ok": True}


# ==================== 统计 ====================

@app.get("/api/summary")
def get_summary(year: int, month: int):
    ym = f"{year}-{month:02d}"
    r = turso_exec(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='income' AND date LIKE ?",
        [ym + "%"],
    )
    income = float(_val(r["rows"][0][0]))
    r = turso_exec(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='expense' AND date LIKE ?",
        [ym + "%"],
    )
    expense = float(_val(r["rows"][0][0]))
    r = turso_exec(
        "SELECT category, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? GROUP BY category ORDER BY SUM(amount) DESC",
        [ym + "%"],
    )
    cats = [{"category": _val(row[0]), "amount": float(_val(row[1]))} for row in r["rows"]]
    r = turso_exec(
        "SELECT necessity, SUM(amount) FROM transactions WHERE type='expense' AND date LIKE ? AND necessity != '' GROUP BY necessity ORDER BY SUM(amount) DESC",
        [ym + "%"],
    )
    necs = [{"necessity": _val(row[0]), "amount": float(_val(row[1]))} for row in r["rows"]]
    return {"income": income, "expense": expense, "categories": cats, "necessity": necs}


@app.get("/api/assets")
def get_assets():
    r = turso_exec(
        "SELECT COALESCE(SUM(CASE WHEN type='income' THEN amount END), 0), "
        "COALESCE(SUM(CASE WHEN type='expense' THEN amount END), 0) FROM transactions"
    )
    income = float(_val(r["rows"][0][0]))
    expense = float(_val(r["rows"][0][1]))
    return {"assets": income - expense}


@app.get("/api/years")
def get_years():
    r = turso_exec("SELECT DISTINCT strftime('%Y', date) FROM transactions ORDER BY date DESC")
    return [int(_val(row[0])) for row in r["rows"] if _val(row[0])]
