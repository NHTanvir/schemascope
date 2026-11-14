#!/usr/bin/env python3
"""Normalize a database schema from DDL, an ORM schema file, or a live SQLite file.

Emits a stable JSON document consumed by audit.py and render.py.
Standard library only -- no install step, no database drivers.
"""
from __future__ import annotations

import json
import os
import re
import sys

# --------------------------------------------------------------------------
# tokenizing helpers
# --------------------------------------------------------------------------

_QUOTE_PAIRS = {'"': '"', '`': '`', '[': ']'}


def strip_comments(sql: str) -> str:
    """Remove -- and /* */ comments without touching string literals."""
    out = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif c in ('"', '`'):
            close = c
            j = sql.find(close, i + 1)
            if j == -1:
                out.append(sql[i:])
                break
            out.append(sql[i : j + 1])
            i = j + 1
        elif c == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif c == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_statements(sql: str) -> list[str]:
    """Split on semicolons that sit at paren depth zero and outside quotes."""
    stmts, buf, depth = [], [], 0
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            buf.append(sql[i : j + 1])
            i = j + 1
            continue
        if c in ('"', '`'):
            j = sql.find(c, i + 1)
            if j == -1:
                j = n - 1
            buf.append(sql[i : j + 1])
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if c == ";" and depth == 0:
            stmts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if "".join(buf).strip():
        stmts.append("".join(buf))
    return [s.strip() for s in stmts if s.strip()]


def split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on commas at paren depth zero."""
    parts, buf, depth = [], [], 0
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "'":
            j = i + 1
            while j < n:
                if body[j] == "'":
                    if j + 1 < n and body[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            buf.append(body[i : j + 1])
            i = j + 1
            continue
        if c in ('"', '`'):
            j = body.find(c, i + 1)
            if j == -1:
                j = n - 1
            buf.append(body[i : j + 1])
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if "".join(buf).strip():
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def unquote(ident: str) -> str:
    ident = ident.strip()
    if not ident:
        return ident
    first = ident[0]
    if first in _QUOTE_PAIRS and ident.endswith(_QUOTE_PAIRS[first]):
        return ident[1:-1]
    # strip schema qualifier: public.users -> users
    if "." in ident and not ident.startswith("("):
        tail = ident.rsplit(".", 1)[1]
        return unquote(tail)
    return ident


def ident_list(raw: str) -> list[str]:
    """Parse ( a, b, "c" ) into ['a','b','c']."""
    raw = raw.strip()
    if raw.startswith("("):
        raw = raw[1:]
    if raw.endswith(")"):
        raw = raw[:-1]
    cols = []
    for piece in split_top_level(raw):
        piece = piece.strip()
        # drop ASC/DESC and operator classes / prefix lengths
        piece = re.sub(r"\s+(asc|desc)$", "", piece, flags=re.I)
        piece = re.sub(r"\(\d+\)$", "", piece)
        if piece:
            cols.append(unquote(piece))
    return cols


def match_paren_group(text: str, start: int) -> tuple[str, int]:
    """Return the (...) group beginning at or after `start`, plus the index after it."""
    open_at = text.find("(", start)
    if open_at == -1:
        return "", len(text)
    depth, i, n = 0, open_at, len(text)
    while i < n:
        c = text[i]
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            continue
        if c in ('"', '`'):
            j = text.find(c, i + 1)
            i = (n if j == -1 else j) + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_at : i + 1], i + 1
        i += 1
    return text[open_at:], n


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

# Unambiguous constraint keywords: these can never begin a column definition.
_CONSTRAINT_KEYWORDS = re.compile(
    r"^\s*(constraint\b|primary\s+key\b|foreign\s+key\b|check\s*\(|exclude\b)", re.I
)
# Ambiguous ones. MySQL writes `KEY idx (col)` for an index, but `key` and
# `index` are also perfectly legal column names, so require a paren group
# before treating the item as a constraint rather than a column.
_AMBIGUOUS_KEYWORDS = re.compile(r"^\s*(unique|key|index|fulltext|spatial)\b", re.I)


def is_table_constraint(item: str) -> bool:
    if _CONSTRAINT_KEYWORDS.match(item):
        return True
    if _AMBIGUOUS_KEYWORDS.match(item):
        # `KEY idx_a (a)` / `UNIQUE (a)` -> constraint; `key TEXT` -> column.
        return "(" in item
    return False

_PART = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
IDENT = rf"(?:{_PART}(?:\.{_PART})*)"


def new_table(name: str) -> dict:
    return {
        "name": name,
        "columns": [],
        "primary_key": [],
        "foreign_keys": [],
        "indexes": [],
        "uniques": [],
        "checks": [],
    }


def parse_column(defn: str) -> dict | None:
    m = re.match(rf"^\s*({IDENT})\s+(.*)$", defn, re.S)
    if not m:
        return None
    name = unquote(m.group(1))
    rest = m.group(2).strip()
    if not name or not rest:
        return None

    # data type: leading words plus an optional (..) or [] suffix
    tm = re.match(
        r"^([A-Za-z_][\w]*(?:\s+(?:precision|varying|int|integer|key|unsigned|zerofill))*)"
        r"\s*(\([^)]*\))?\s*((?:\[\s*\d*\s*\])*)",
        rest,
    )
    if tm:
        base = " ".join(tm.group(1).split())
        dtype = base + (tm.group(2) or "") + (tm.group(3) or "")
        tail = rest[tm.end() :]
    else:
        dtype, tail = rest.split()[0], ""

    low = tail.lower()
    col = {
        "name": name,
        "type": dtype.strip(),
        "nullable": "not null" not in low,
        "pk": bool(re.search(r"\bprimary\s+key\b", low)),
        "unique": bool(re.search(r"\bunique\b", low)),
        "default": None,
        "identity": bool(
            re.search(r"\b(auto_increment|autoincrement|identity|serial)\b", low)
            or re.search(r"\b(serial|bigserial|smallserial)\b", dtype.lower())
        ),
        "comment": None,
    }
    dm = re.search(r"\bdefault\s+(.+?)(?=\s+(?:not\s+null|null|unique|primary|check|references|generated|comment|collate|on\s+update)\b|$)", tail, re.I | re.S)
    if dm:
        col["default"] = dm.group(1).strip().rstrip(",")
    cm = re.search(r"\bcomment\s+'((?:[^']|'')*)'", tail, re.I)
    if cm:
        col["comment"] = cm.group(1).replace("''", "'")
    return col


def parse_inline_reference(defn: str, col_name: str) -> dict | None:
    m = re.search(rf"\breferences\s+({IDENT})\s*(\([^)]*\))?", defn, re.I)
    if not m:
        return None
    ref_cols = ident_list(m.group(2)) if m.group(2) else []
    tail = defn[m.end() :]
    return {
        "name": None,
        "columns": [col_name],
        "ref_table": unquote(m.group(1)),
        "ref_columns": ref_cols,
        "on_delete": _action(tail, "delete"),
        "on_update": _action(tail, "update"),
    }


def _action(text: str, kind: str) -> str | None:
    m = re.search(
        rf"\bon\s+{kind}\s+(cascade|restrict|set\s+null|set\s+default|no\s+action)",
        text,
        re.I,
    )
    return " ".join(m.group(1).split()).lower() if m else None


def parse_table_constraint(item: str, table: dict) -> None:
    name = None
    m = re.match(rf"^\s*constraint\s+({IDENT})\s+(.*)$", item, re.I | re.S)
    if m:
        name, item = unquote(m.group(1)), m.group(2).strip()

    if re.match(r"^primary\s+key", item, re.I):
        grp, _ = match_paren_group(item, 0)
        table["primary_key"] = ident_list(grp)
        return

    if re.match(r"^foreign\s+key", item, re.I):
        grp, after = match_paren_group(item, 0)
        cols = ident_list(grp)
        rm = re.search(rf"\breferences\s+({IDENT})\s*(\([^)]*\))?", item[after - 1 :], re.I)
        if rm:
            tail = item[after - 1 + rm.end() :]
            table["foreign_keys"].append(
                {
                    "name": name,
                    "columns": cols,
                    "ref_table": unquote(rm.group(1)),
                    "ref_columns": ident_list(rm.group(2)) if rm.group(2) else [],
                    "on_delete": _action(tail, "delete"),
                    "on_update": _action(tail, "update"),
                }
            )
        return

    if re.match(r"^unique", item, re.I):
        grp, _ = match_paren_group(item, 0)
        cols = ident_list(grp)
        if cols:
            table["uniques"].append(cols)
        return

    if re.match(r"^check", item, re.I):
        grp, _ = match_paren_group(item, 0)
        table["checks"].append(grp.strip())
        return

    if re.match(r"^(key|index|fulltext|spatial)\b", item, re.I):
        km = re.match(rf"^(?:key|index|fulltext|spatial)(?:\s+(?!\()({IDENT}))?\s*", item, re.I)
        idx_name = unquote(km.group(1)) if km and km.group(1) else name
        grp, _ = match_paren_group(item, 0)
        cols = ident_list(grp)
        if cols:
            table["indexes"].append({"name": idx_name, "columns": cols, "unique": False})
        return


def parse_create_table(stmt: str, tables: dict) -> None:
    m = re.match(
        rf"^\s*create\s+(?:(?:global|local)\s+)?(?:temp(?:orary)?\s+)?(?:unlogged\s+)?"
        rf"table\s+(?:if\s+not\s+exists\s+)?({IDENT})",
        stmt,
        re.I,
    )
    if not m:
        return
    name = unquote(m.group(1))
    body, _ = match_paren_group(stmt, m.end())
    if not body:
        return
    table = tables.get(name) or new_table(name)
    tables[name] = table

    for item in split_top_level(body[1:-1]):
        if is_table_constraint(item):
            parse_table_constraint(item, table)
            continue
        col = parse_column(item)
        if not col:
            continue
        table["columns"].append(col)
        if col["pk"] and col["name"] not in table["primary_key"]:
            table["primary_key"].append(col["name"])
        if col["unique"]:
            table["uniques"].append([col["name"]])
        fk = parse_inline_reference(item, col["name"])
        if fk:
            table["foreign_keys"].append(fk)


def parse_alter_table(stmt: str, tables: dict) -> None:
    m = re.match(rf"^\s*alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?({IDENT})\s+(.*)$", stmt, re.I | re.S)
    if not m:
        return
    name = unquote(m.group(1))
    table = tables.get(name) or new_table(name)
    tables[name] = table
    for action in split_top_level(m.group(2)):
        am = re.match(rf"^\s*add\s+(?:constraint\s+({IDENT})\s+)?(.*)$", action, re.I | re.S)
        if am:
            cname, rest = (unquote(am.group(1)) if am.group(1) else None), am.group(2)
            parse_table_constraint(
                (f"CONSTRAINT {cname} " if cname else "") + rest, table
            )
            continue
        cm = re.match(rf"^\s*add\s+column\s+(.*)$", action, re.I | re.S)
        if cm:
            col = parse_column(cm.group(1))
            if col:
                table["columns"].append(col)


def parse_create_index(stmt: str, tables: dict) -> None:
    m = re.match(
        rf"^\s*create\s+(unique\s+)?index\s+(?:concurrently\s+)?"
        rf"(?:if\s+not\s+exists\s+)?({IDENT})?\s*on\s+({IDENT})",
        stmt,
        re.I,
    )
    if not m:
        return
    is_unique = bool(m.group(1))
    idx_name = unquote(m.group(2)) if m.group(2) else None
    tname = unquote(m.group(3))
    grp, _ = match_paren_group(stmt, m.end())
    cols = ident_list(grp) if grp else []
    if not cols:
        return
    table = tables.get(tname) or new_table(tname)
    tables[tname] = table
    table["indexes"].append({"name": idx_name, "columns": cols, "unique": is_unique})
    if is_unique:
        table["uniques"].append(cols)


def parse_sql(sql: str) -> dict:
    tables: dict[str, dict] = {}
    cleaned = strip_comments(sql)
    for stmt in split_statements(cleaned):
        head = stmt.lstrip()[:40].lower()
        if head.startswith("create") and re.search(r"\btable\b", head):
            parse_create_table(stmt, tables)
        elif head.startswith("alter"):
            parse_alter_table(stmt, tables)
        elif head.startswith("create") and re.search(r"\bindex\b", head):
            parse_create_index(stmt, tables)
    return {"tables": list(tables.values())}


def detect_dialect(sql: str) -> str:
    low = sql.lower()
    if "auto_increment" in low or "engine=" in low:
        return "mysql"
    if "autoincrement" in low and "serial" not in low:
        return "sqlite"
    if re.search(r"\b(bigserial|serial|::|tsvector|jsonb)\b", low):
        return "postgres"
    return "sql"


# --------------------------------------------------------------------------
# Prisma schema
# --------------------------------------------------------------------------

_PRISMA_SCALARS = {
    "String", "Boolean", "Int", "BigInt", "Float", "Decimal",
    "DateTime", "Json", "Bytes",
}


def parse_prisma(text: str) -> dict:
    tables: dict[str, dict] = {}
    enums = set(re.findall(r"^\s*enum\s+(\w+)\s*\{", text, re.M))
    models = re.findall(r"^\s*model\s+(\w+)\s*\{(.*?)^\s*\}", text, re.M | re.S)

    # pass 1: scalar fields
    relations: list[tuple[str, str, str, list[str], list[str]]] = []
    for model, body in models:
        table = new_table(model)
        mapped = re.search(r'@@map\(\s*"([^"]+)"\s*\)', body)
        if mapped:
            table["name"] = mapped.group(1)
        tables[model] = table

        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("//"):
                continue
            if line.startswith("@@"):
                im = re.match(r"@@(id|unique|index)\s*\(\s*\[([^\]]*)\]", line)
                if im:
                    cols = [c.strip() for c in im.group(2).split(",") if c.strip()]
                    kind = im.group(1)
                    if kind == "id":
                        table["primary_key"] = cols
                    elif kind == "unique":
                        table["uniques"].append(cols)
                    else:
                        table["indexes"].append({"name": None, "columns": cols, "unique": False})
                continue

            fm = re.match(r"^(\w+)\s+(\w+)(\[\])?(\?)?\s*(.*)$", line)
            if not fm:
                continue
            fname, ftype, is_list, optional, attrs = fm.groups()
            attrs = attrs or ""

            if ftype not in _PRISMA_SCALARS and ftype not in enums:
                rm = re.search(r"@relation\(([^)]*)\)", attrs)
                if rm and "fields:" in rm.group(1):
                    inner = rm.group(1)
                    f = re.search(r"fields:\s*\[([^\]]*)\]", inner)
                    r = re.search(r"references:\s*\[([^\]]*)\]", inner)
                    on_del = re.search(r"onDelete:\s*(\w+)", inner)
                    relations.append(
                        (
                            model,
                            ftype,
                            on_del.group(1) if on_del else "",
                            [c.strip() for c in f.group(1).split(",") if c.strip()] if f else [],
                            [c.strip() for c in r.group(1).split(",") if c.strip()] if r else [],
                        )
                    )
                continue  # relation navigation field, not a column

            dbname = re.search(r'@map\(\s*"([^"]+)"\s*\)', attrs)
            native = re.search(r"@db\.(\w+)(\([^)]*\))?", attrs)
            col = {
                "name": dbname.group(1) if dbname else fname,
                "type": (native.group(0).replace("@db.", "") if native else ftype)
                + ("[]" if is_list else ""),
                "nullable": bool(optional),
                "pk": "@id" in attrs,
                "unique": "@unique" in attrs,
                "default": None,
                "identity": "autoincrement()" in attrs,
                "comment": None,
            }
            dm = re.search(r"@default\(", attrs)
            if dm:
                grp, _ = match_paren_group(attrs, dm.start())
                col["default"] = grp[1:-1].strip() if grp else None
            table["columns"].append(col)
            if col["pk"]:
                table["primary_key"].append(col["name"])
            if col["unique"]:
                table["uniques"].append([col["name"]])

    # pass 2: relations, resolved to mapped table names
    for model, target, on_delete, fields, refs in relations:
        table = tables.get(model)
        if not table:
            continue
        ref_table = tables.get(target, {}).get("name", target)
        table["foreign_keys"].append(
            {
                "name": None,
                "columns": fields,
                "ref_table": ref_table,
                "ref_columns": refs,
                "on_delete": {
                    "Cascade": "cascade",
                    "SetNull": "set null",
                    "Restrict": "restrict",
                    "NoAction": "no action",
                    "SetDefault": "set default",
                }.get(on_delete),
                "on_update": None,
            }
        )
    return {"tables": list(tables.values())}


# --------------------------------------------------------------------------
# live SQLite (stdlib sqlite3)
# --------------------------------------------------------------------------

def introspect_sqlite(path: str) -> dict:
    import sqlite3

    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT name, sql FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    rows = cur.fetchall()
    tables: dict[str, dict] = {}

    for row in rows:
        tname = row["name"]
        table = new_table(tname)
        tables[tname] = table

        for c in cur.execute(f'PRAGMA table_info("{tname}")').fetchall():
            table["columns"].append(
                {
                    "name": c["name"],
                    "type": c["type"] or "",
                    "nullable": not c["notnull"],
                    "pk": bool(c["pk"]),
                    "unique": False,
                    "default": c["dflt_value"],
                    "identity": False,
                    "comment": None,
                }
            )
            if c["pk"]:
                table["primary_key"].append(c["name"])

        for f in cur.execute(f'PRAGMA foreign_key_list("{tname}")').fetchall():
            table["foreign_keys"].append(
                {
                    "name": None,
                    "columns": [f["from"]],
                    "ref_table": f["table"],
                    "ref_columns": [f["to"]] if f["to"] else [],
                    "on_delete": (f["on_delete"] or "").lower() or None,
                    "on_update": (f["on_update"] or "").lower() or None,
                }
            )

        for idx in cur.execute(f'PRAGMA index_list("{tname}")').fetchall():
            cols = [
                i["name"]
                for i in cur.execute(f'PRAGMA index_info("{idx["name"]}")').fetchall()
                if i["name"]
            ]
            if not cols:
                continue
            is_unique = bool(idx["unique"])
            table["indexes"].append(
                {"name": idx["name"], "columns": cols, "unique": is_unique}
            )
            if is_unique:
                table["uniques"].append(cols)

        # AUTOINCREMENT / INTEGER PRIMARY KEY rowid aliasing
        ddl = (row["sql"] or "").lower()
        for col in table["columns"]:
            if col["pk"] and (
                "autoincrement" in ddl or col["type"].strip().lower() == "integer"
            ):
                col["identity"] = True

    con.close()
    return {"tables": list(tables.values())}


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def load(path: str) -> dict:
    if path == "-":
        text = sys.stdin.read()
        doc = parse_sql(text)
        doc["source"] = "<stdin>"
        doc["dialect"] = detect_dialect(text)
        return doc

    ext = os.path.splitext(path)[1].lower()
    if ext in (".db", ".sqlite", ".sqlite3"):
        doc = introspect_sqlite(path)
        doc["source"] = path
        doc["dialect"] = "sqlite"
        return doc

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    if ext == ".prisma" or re.search(r"^\s*(model|datasource)\s+\w+\s*\{", text, re.M):
        doc = parse_prisma(text)
        doc["source"] = path
        doc["dialect"] = "prisma"
        return doc

    doc = parse_sql(text)
    doc["source"] = path
    doc["dialect"] = detect_dialect(text)
    return doc


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: introspect.py <schema.sql|schema.prisma|db.sqlite|->\n"
            "   or: pg_dump --schema-only mydb | introspect.py -",
            file=sys.stderr,
        )
        return 2
    doc = load(argv[1])
    doc["table_count"] = len(doc["tables"])
    json.dump(doc, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
