#!/usr/bin/env python3
"""Audit a normalized schema document for design defects.

Reads the JSON emitted by introspect.py and reports ranked findings, each with
the DDL that fixes it. Standard library only.
"""
from __future__ import annotations

import json
import re
import sys

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# --------------------------------------------------------------------------
# type classification
# --------------------------------------------------------------------------

def base_type(t: str) -> str:
    return re.sub(r"\(.*", "", (t or "")).strip().lower()


def is_text(t: str) -> bool:
    return base_type(t) in {
        "text", "varchar", "char", "character", "character varying", "nvarchar",
        "nchar", "clob", "string", "longtext", "mediumtext", "tinytext", "citext",
        "varchar2",
    }


def is_int(t: str) -> bool:
    return base_type(t) in {
        "int", "integer", "bigint", "smallint", "tinyint", "mediumint", "serial",
        "bigserial", "smallserial", "int2", "int4", "int8", "number",
    }


def is_float(t: str) -> bool:
    return base_type(t) in {"float", "double", "double precision", "real", "float4", "float8"}


def is_exact_numeric(t: str) -> bool:
    return base_type(t) in {"decimal", "numeric", "money", "bigint", "int", "integer"}


def is_bool(t: str) -> bool:
    return base_type(t) in {"bool", "boolean", "bit", "tinyint"}


def is_temporal(t: str) -> bool:
    return base_type(t) in {
        "timestamp", "timestamptz", "datetime", "date", "time", "timetz",
        "timestamp with time zone", "timestamp without time zone", "datetime2",
    }


def is_json(t: str) -> bool:
    return base_type(t) in {"json", "jsonb"}


def has_length(t: str) -> bool:
    return bool(re.search(r"\(\s*\d+", t or ""))


# --------------------------------------------------------------------------
# name heuristics
# --------------------------------------------------------------------------

BOOL_NAME = re.compile(r"^(is|has|can|should|was|allow|enable|flag)_|_(flag|enabled|disabled)$|^(active|approved|deleted|published|verified|archived)$", re.I)
TIME_NAME = re.compile(r"(_at|_on|_date|_time|_timestamp)$|^(created|updated|deleted)$", re.I)
COUNT_NAME = re.compile(r"(_count|_total|_qty|_quantity|_num|_number|_views|_size|_bytes|_score|_rank|_position|_order|_index)$|^(count|total|quantity|amount|price|cost|balance|rate)$", re.I)
MONEY_NAME = re.compile(r"(price|amount|total|cost|balance|fee|salary|revenue|discount|subtotal|tax)", re.I)
ENUM_NAME = re.compile(r"^(status|state|role|type|kind|level|tier|visibility|mode|stage|severity|priority|currency|locale|provider)$|_(status|state|role|type|kind|level)$", re.I)
JSON_NAME = re.compile(r"^(metadata|meta|data|config|settings|payload|props|properties|options|attributes|extra|params)$|_(json|metadata|payload|config)$", re.I)
SECRET_NAME = re.compile(r"^(password|passwd|pwd|secret|api_key|apikey|token|private_key)$|_(password|secret|token|api_key)$", re.I)
UNIQUEISH_NAME = re.compile(r"^(email|slug|username|handle|uuid|guid|sku|isbn|barcode|code|permalink)$|_(slug|email|uuid|sku|code)$", re.I)
BOUNDED_NAME = re.compile(r"^(email|slug|username|handle|url|uri|phone|zip|postcode|country|currency|locale|ip|ip_address|timezone|title|name)$|_(email|slug|url|uri|phone|code)$", re.I)
RESERVED = {
    # words that genuinely require quoting on PostgreSQL and/or MySQL
    "key", "value", "order", "user", "table", "column", "index", "select",
    "from", "where", "group", "default", "check", "constraint", "primary",
    "references", "limit", "offset", "desc", "asc", "all", "and", "or", "not",
    "null", "case", "end", "join", "union", "having", "distinct", "unique",
    "foreign", "grant", "create", "drop", "alter", "into", "values",
}
TIMESTAMP_COLS = {"created_at", "createdat", "created", "inserted_at", "date_created"}
UPDATED_COLS = {"updated_at", "updatedat", "modified_at", "updated", "date_modified"}


def q(name: str) -> str:
    """Quote an identifier for the generated DDL when it needs it."""
    return f'"{name}"' if (name.lower() in RESERVED or not re.match(r"^[a-z_][a-z0-9_]*$", name)) else name


# --------------------------------------------------------------------------
# schema index
# --------------------------------------------------------------------------

class Schema:
    def __init__(self, doc: dict):
        self.doc = doc
        self.tables = doc.get("tables", [])
        self.by_name = {t["name"]: t for t in self.tables}
        self.by_lower = {t["name"].lower(): t for t in self.tables}

    def find(self, name: str) -> dict | None:
        return self.by_name.get(name) or self.by_lower.get((name or "").lower())

    @staticmethod
    def cols(table: dict) -> dict:
        return {c["name"]: c for c in table.get("columns", [])}

    @staticmethod
    def leading_indexed(table: dict) -> set[str]:
        """Columns that are the first column of some index, unique, or PK."""
        out: set[str] = set()
        pk = table.get("primary_key") or []
        if pk:
            out.add(pk[0])
        for idx in table.get("indexes", []):
            if idx.get("columns"):
                out.add(idx["columns"][0])
        for u in table.get("uniques", []):
            if u:
                out.add(u[0])
        return out

    @staticmethod
    def unique_sets(table: dict) -> list[set]:
        sets = [set(u) for u in table.get("uniques", []) if u]
        pk = table.get("primary_key") or []
        if pk:
            sets.append(set(pk))
        for idx in table.get("indexes", []):
            if idx.get("unique") and idx.get("columns"):
                sets.append(set(idx["columns"]))
        return sets

    def pk_type(self, table_name: str) -> str | None:
        t = self.find(table_name)
        if not t:
            return None
        pk = t.get("primary_key") or []
        if len(pk) != 1:
            return None
        col = self.cols(t).get(pk[0])
        return col["type"] if col else None


def finding(sev, rule, table, msg, why, fix, columns=None) -> dict:
    return {
        "severity": sev,
        "rule": rule,
        "table": table,
        "columns": columns or [],
        "message": msg,
        "why": why,
        "fix": fix,
    }


# --------------------------------------------------------------------------
# foreign-key target inference
# --------------------------------------------------------------------------

def singularize(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def pluralize(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


_FK_SUFFIX = re.compile(r"^(.+?)(_id|_uuid|_fk|_key|id|Id|ID)$")
_BY_SUFFIX = re.compile(r"^(.+?)_by$", re.I)
SELF_REF_STEMS = {"parent", "child", "next", "prev", "previous", "reply_to", "related"}


def guess_ref_table(col_name: str, table: dict, schema: Schema) -> str | None:
    """Infer which table a foreign-key-looking column points at."""
    if col_name in (table.get("primary_key") or []):
        return None

    m = _FK_SUFFIX.match(col_name)
    stem = None
    if m:
        stem = m.group(1).rstrip("_")
    else:
        bm = _BY_SUFFIX.match(col_name)
        if bm:
            # created_by / uploaded_by / owned_by conventionally reference users
            for cand in ("users", "user", "accounts", "account", "members"):
                if schema.find(cand):
                    return schema.find(cand)["name"]
            return None
    if not stem:
        return None

    low = stem.lower()
    if low in SELF_REF_STEMS:
        return table["name"]

    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()
    for cand in (
        stem, snake, pluralize(snake), singularize(snake),
        pluralize(singularize(snake)),
    ):
        hit = schema.find(cand)
        if hit and hit["name"] != table["name"]:
            return hit["name"]
        if hit and hit["name"] == table["name"]:
            return hit["name"]
    return None


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _is_join_table(table: dict) -> bool:
    """A pure link table: two FKs, and no payload beyond keys and timestamps."""
    fks = table.get("foreign_keys", [])
    fk_cols = [c for fk in fks for c in fk["columns"]]
    if len(fks) != 2 or len(fk_cols) != 2:
        return False
    pk = table.get("primary_key") or []
    payload = [
        c["name"] for c in table.get("columns", [])
        if c["name"] not in pk and c["name"] not in fk_cols
        and c["name"].lower() not in TIMESTAMP_COLS | UPDATED_COLS
    ]
    return not payload


def rule_table_level(table: dict, schema: Schema, out: list) -> None:
    name = table["name"]
    cols = table.get("columns", [])
    colmap = {c["name"]: c for c in cols}
    lower_names = {c["name"].lower() for c in cols}
    pk = table.get("primary_key") or []

    if not pk:
        first = cols[0]["name"] if cols else "id"
        out.append(finding(
            "critical", "no_primary_key", name,
            "Table has no primary key.",
            "Rows cannot be addressed, updated or deleted unambiguously. Replication, "
            "ORMs and most migration tools all require one.",
            f"ALTER TABLE {q(name)} ADD COLUMN id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY;\n"
            f"-- or, if {q(first)} is already unique:\n"
            f"ALTER TABLE {q(name)} ADD PRIMARY KEY ({q(first)});",
            [first],
        ))

    if not (lower_names & TIMESTAMP_COLS):
        out.append(finding(
            "medium", "missing_timestamps", name,
            "No creation timestamp.",
            "Without created_at you cannot order history, debug an incident, expire old "
            "rows or build any time-series view. It is unrecoverable retroactively.",
            f"ALTER TABLE {q(name)} ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();",
        ))
    elif not (lower_names & UPDATED_COLS) and not _is_join_table(table):
        out.append(finding(
            "low", "no_updated_at", name,
            "Has created_at but no updated_at.",
            "Caching, incremental sync and audit trails all need to know when a row last changed.",
            f"ALTER TABLE {q(name)} ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();",
        ))

    non_pk = [c for c in cols if c["name"] not in pk]
    nullable = [c for c in non_pk if c["nullable"]]
    if len(non_pk) >= 4 and len(nullable) / len(non_pk) >= 0.8:
        worst = ", ".join(c["name"] for c in nullable[:6])
        out.append(finding(
            "high", "nullable_everything", name,
            f"{len(nullable)} of {len(non_pk)} non-key columns are nullable.",
            "A schema where everything is optional enforces nothing. Every reader must "
            "handle NULL for fields that are in practice always present, and genuinely "
            "optional fields become indistinguishable from mistakes.",
            "\n".join(
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(c['name'])} SET NOT NULL;"
                for c in nullable[:6]
            ) + "\n-- backfill existing rows first; keep NOT NULL only where truly required.",
            [c["name"] for c in nullable],
        ))

    if len(cols) > 30:
        out.append(finding(
            "low", "wide_table", name,
            f"{len(cols)} columns in one table.",
            "Very wide tables usually hide several entities, force SELECT * to read cold "
            "data, and make row-level locking coarser than it needs to be.",
            f"-- review {q(name)} for columns that belong in a separate table or a jsonb payload.",
        ))

    # join table that permits duplicate relationships
    fks = table.get("foreign_keys", [])
    fk_cols = [c for fk in fks for c in fk["columns"]]
    if len(fks) == 2 and len(fk_cols) == 2:
        payload = [c for c in cols if c["name"] not in pk and c["name"] not in fk_cols]
        meaningful = [c for c in payload if c["name"].lower() not in TIMESTAMP_COLS | UPDATED_COLS]
        if not meaningful:
            pair = set(fk_cols)
            if not any(pair <= u for u in schema.unique_sets(table)):
                out.append(finding(
                    "medium", "duplicate_rows_possible", name,
                    f"Join table allows duplicate ({', '.join(fk_cols)}) pairs.",
                    "Nothing stops the same relationship being inserted twice. A retried "
                    "request silently creates a duplicate, and every join through this "
                    "table then multiplies rows.",
                    f"ALTER TABLE {q(name)} ADD CONSTRAINT uq_{name}_pair "
                    f"UNIQUE ({', '.join(q(c) for c in fk_cols)});\n"
                    f"-- a composite primary key on the pair is usually better than a surrogate id.",
                    fk_cols,
                ))

    snake = [c["name"] for c in cols if "_" in c["name"] and c["name"].islower()]
    camel = [c["name"] for c in cols if re.search(r"[a-z][A-Z]", c["name"])]
    if snake and camel:
        out.append(finding(
            "low", "inconsistent_naming", name,
            "Mixes snake_case and camelCase column names.",
            "Every query becomes a guess about quoting and casing, and in Postgres "
            "camelCase identifiers require double quotes forever.",
            f"-- settle on snake_case: {', '.join(camel[:4])}",
            camel,
        ))


def rule_column_level(table: dict, schema: Schema, out: list) -> None:
    name = table["name"]
    dialect = schema.doc.get("dialect", "sql")
    pk = table.get("primary_key") or []
    declared_fk_cols = {c for fk in table.get("foreign_keys", []) for c in fk["columns"]}
    unique_sets = schema.unique_sets(table)
    checks_blob = " ".join(table.get("checks", [])).lower()

    for col in table.get("columns", []):
        cname, ctype = col["name"], col["type"]

        # ---- undeclared foreign key
        if cname not in declared_fk_cols and cname not in pk:
            target = guess_ref_table(cname, table, schema)
            if target:
                ref_pk = (schema.find(target) or {}).get("primary_key") or ["id"]
                out.append(finding(
                    "critical", "fk_without_constraint", name,
                    f"{cname} looks like a reference to {target} but no foreign key enforces it.",
                    "The database will happily store an id that points at nothing. Orphans "
                    "accumulate silently, deletes leave dangling references, and the only "
                    "thing protecting integrity is application code that every new caller "
                    "has to remember.",
                    f"ALTER TABLE {q(name)} ADD CONSTRAINT fk_{name}_{cname}\n"
                    f"  FOREIGN KEY ({q(cname)}) REFERENCES {q(target)} ({q(ref_pk[0])})\n"
                    f"  ON DELETE RESTRICT;\n"
                    f"CREATE INDEX idx_{name}_{cname} ON {q(name)} ({q(cname)});",
                    [cname],
                ))

        # ---- secrets stored as plain text
        if SECRET_NAME.match(cname) and not re.search(r"(hash|digest|encrypted|_enc)", cname, re.I):
            out.append(finding(
                "critical", "plaintext_secret", name,
                f"{cname} appears to store a credential in a plain column.",
                "If this holds a raw password or token, a single read of the table or a "
                "leaked backup exposes every account. Credentials must be stored as a "
                "one-way hash; tokens must be hashed or encrypted at rest.",
                f"-- rename to make the intent explicit and store a hash, never the secret:\n"
                f"ALTER TABLE {q(name)} RENAME COLUMN {q(cname)} TO {cname}_hash;\n"
                f"-- then write only argon2id/bcrypt/scrypt output into it.",
                [cname],
            ))

        # ---- type mismatches
        if BOOL_NAME.search(cname) and is_text(ctype):
            out.append(finding(
                "high", "boolean_as_text", name,
                f"{cname} is a boolean stored as {ctype}.",
                "'true', 'True', 'TRUE', '1' and 'yes' all become distinct values. Every "
                "query needs string comparison, no index helps much, and the column cannot "
                "be trusted in a WHERE clause.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE boolean\n"
                f"  USING (lower({q(cname)}) IN ('true','t','1','yes'));\n"
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} SET NOT NULL;",
                [cname],
            ))

        if TIME_NAME.search(cname) and is_text(ctype):
            out.append(finding(
                "high", "timestamp_as_text", name,
                f"{cname} is a timestamp stored as {ctype}.",
                "Text timestamps sort lexicographically, not chronologically, cannot be "
                "compared across time zones, and make range queries unindexable. Mixed "
                "formats are undetectable until something breaks.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE timestamptz\n"
                f"  USING {q(cname)}::timestamptz;",
                [cname],
            ))
        elif TIME_NAME.search(cname) and base_type(ctype) in ("timestamp", "timestamp without time zone") and dialect == "postgres":
            out.append(finding(
                "medium", "timestamp_without_timezone", name,
                f"{cname} is `timestamp` without a time zone.",
                "The value records a wall-clock reading with no offset, so the same column "
                "means different instants depending on who wrote it. This is the most common "
                "source of off-by-hours bugs.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE timestamptz;",
                [cname],
            ))

        if COUNT_NAME.search(cname) and is_text(ctype):
            out.append(finding(
                "high", "numeric_as_text", name,
                f"{cname} is numeric but stored as {ctype}.",
                "Arithmetic, ordering and aggregation all require casting, '10' sorts below "
                "'9', and nothing prevents a non-numeric value being written.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE bigint "
                f"USING {q(cname)}::bigint;\n"
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} SET DEFAULT 0;",
                [cname],
            ))

        if MONEY_NAME.search(cname) and is_float(ctype):
            out.append(finding(
                "high", "money_as_float", name,
                f"{cname} holds money as {ctype}.",
                "Binary floating point cannot represent decimal fractions exactly, so sums "
                "drift by fractions of a cent and totals stop reconciling. This is a "
                "correctness bug in anything that bills.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE numeric(12,2);\n"
                f"-- or store minor units as a bigint (cents) and format on the way out.",
                [cname],
            ))

        if JSON_NAME.search(cname) and is_text(ctype):
            out.append(finding(
                "medium", "json_as_text", name,
                f"{cname} looks like structured data stored as {ctype}.",
                "As text it cannot be queried, indexed or validated. Malformed JSON is only "
                "discovered when something tries to parse it.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE jsonb "
                f"USING {q(cname)}::jsonb;",
                [cname],
            ))

        if ENUM_NAME.search(cname) and is_text(ctype) and cname.lower() not in checks_blob:
            default = (col.get("default") or "").strip("'\"") or "active"
            out.append(finding(
                "medium", "enum_as_free_text", name,
                f"{cname} is a free-text state column with no allowed-value constraint.",
                "Any string is accepted, so a typo in one code path creates a state no "
                "reader handles. The set of legal values exists only in someone's head.",
                f"ALTER TABLE {q(name)} ADD CONSTRAINT chk_{name}_{cname}\n"
                f"  CHECK ({q(cname)} IN ('{default}', ...));  -- list the real states",
                [cname],
            ))

        if UNIQUEISH_NAME.search(cname) and cname not in pk:
            if not any({cname} <= u for u in unique_sets):
                out.append(finding(
                    "high", "missing_unique", name,
                    f"{cname} is an identifier-like column with no unique constraint.",
                    "Duplicates are inevitable under concurrency: two requests check for "
                    "existence, both see nothing, and both insert. Only the database can "
                    "prevent this.",
                    f"ALTER TABLE {q(name)} ADD CONSTRAINT uq_{name}_{cname} "
                    f"UNIQUE ({q(cname)});",
                    [cname],
                ))

        if BOUNDED_NAME.search(cname) and is_text(ctype) and not has_length(ctype):
            sev = "low" if dialect == "postgres" else "medium"
            out.append(finding(
                sev, "unbounded_text", name,
                f"{cname} has no length bound.",
                "Nothing stops a megabyte being written into a field meant for an email "
                "address. On MySQL an unbounded text column also cannot be fully indexed.",
                f"ALTER TABLE {q(name)} ALTER COLUMN {q(cname)} TYPE varchar(255);\n"
                f"-- or add: CHECK (length({q(cname)}) <= 255)",
                [cname],
            ))

        if cname.lower() in RESERVED:
            out.append(finding(
                "low", "reserved_word_column", name,
                f"Column name `{cname}` is a reserved SQL word.",
                "Every reference to it must be quoted, forever, in every query and every "
                "ORM. One unquoted use is a syntax error that only appears at runtime.",
                f"ALTER TABLE {q(name)} RENAME COLUMN {q(cname)} TO {name.rstrip('s')}_{cname};",
                [cname],
            ))


def rule_fk_level(table: dict, schema: Schema, out: list) -> None:
    name = table["name"]
    indexed = schema.leading_indexed(table)
    colmap = schema.cols(table)

    for fk in table.get("foreign_keys", []):
        cols = fk.get("columns") or []
        if not cols:
            continue
        label = ", ".join(cols)

        if cols[0] not in indexed:
            out.append(finding(
                "high", "unindexed_fk", name,
                f"Foreign key ({label}) has no index.",
                "Every join through this key becomes a full table scan, and every delete on "
                f"{fk['ref_table']} must scan {name} to check the constraint. This is the most "
                "common performance defect in generated schemas and it degrades silently as "
                "the table grows.",
                f"CREATE INDEX idx_{name}_{'_'.join(cols)} ON {q(name)} "
                f"({', '.join(q(c) for c in cols)});",
                cols,
            ))

        if not fk.get("on_delete"):
            out.append(finding(
                "high", "no_cascade_rule", name,
                f"Foreign key ({label}) has no ON DELETE rule.",
                f"The default is NO ACTION, so deleting a row in {fk['ref_table']} fails with "
                "a constraint error instead of doing something defined. The intended behaviour "
                "has to be chosen deliberately, not inherited.",
                f"ALTER TABLE {q(name)} DROP CONSTRAINT "
                f"{fk.get('name') or f'fk_{name}_{cols[0]}'},\n"
                f"  ADD CONSTRAINT {fk.get('name') or f'fk_{name}_{cols[0]}'}\n"
                f"  FOREIGN KEY ({', '.join(q(c) for c in cols)}) "
                f"REFERENCES {q(fk['ref_table'])}\n"
                f"  ON DELETE CASCADE;  -- or RESTRICT / SET NULL, deliberately",
                cols,
            ))

        ref_type = schema.pk_type(fk["ref_table"])
        own = colmap.get(cols[0])
        if ref_type and own and len(cols) == 1:
            a, b = base_type(own["type"]), base_type(ref_type)
            norm = {"serial": "integer", "bigserial": "bigint", "int": "integer",
                    "int4": "integer", "int8": "bigint", "int2": "smallint"}
            a, b = norm.get(a, a), norm.get(b, b)
            if a != b and not (is_text(own["type"]) and is_text(ref_type)):
                out.append(finding(
                    "medium", "fk_type_mismatch", name,
                    f"{cols[0]} is {own['type']} but {fk['ref_table']} key is {ref_type}.",
                    "Mismatched key widths force an implicit cast on every join, which can "
                    "prevent index use entirely, and the narrower column will overflow before "
                    "the table it references does.",
                    f"ALTER TABLE {q(name)} ALTER COLUMN {q(cols[0])} TYPE {b};",
                    cols,
                ))


def rule_index_level(table: dict, out: list) -> None:
    name = table["name"]
    idxs = [i for i in table.get("indexes", []) if i.get("columns")]
    for i, a in enumerate(idxs):
        for j, b in enumerate(idxs):
            if i == j:
                continue
            ac, bc = a["columns"], b["columns"]
            if len(ac) < len(bc) and bc[: len(ac)] == ac and not a.get("unique"):
                out.append(finding(
                    "low", "redundant_index", name,
                    f"Index on ({', '.join(ac)}) is a prefix of ({', '.join(bc)}).",
                    "The wider index already serves every query the narrower one does. The "
                    "extra index costs write throughput and storage for no read benefit.",
                    f"DROP INDEX {a.get('name') or 'idx_' + '_'.join(ac)};",
                    ac,
                ))
                break


def audit(doc: dict) -> dict:
    schema = Schema(doc)
    out: list[dict] = []
    for table in schema.tables:
        rule_table_level(table, schema, out)
        rule_column_level(table, schema, out)
        rule_fk_level(table, schema, out)
        rule_index_level(table, out)

    out.sort(key=lambda f: (SEVERITY_ORDER[f["severity"]], f["table"], f["rule"]))
    counts: dict[str, int] = {}
    for f in out:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "source": doc.get("source"),
        "dialect": doc.get("dialect"),
        "table_count": len(schema.tables),
        "counts": counts,
        "findings": out,
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

BADGE = {"critical": "CRIT", "high": "HIGH", "medium": "MED ", "low": "LOW "}


def render_text(report: dict, show_fix: bool = True) -> str:
    c = report["counts"]
    total = sum(c.values())
    src = report["source"]
    lines = [
        "",
        f"  SCHEMA AUDIT   {src}",
        f"  {report['table_count']} tables · {report['dialect']}",
        "",
    ]
    if not total:
        lines += ["  No findings. This schema is in good shape.", ""]
        return "\n".join(lines)

    widest = max(max(c.values()), 8)
    for sev in ("critical", "high", "medium", "low"):
        n = c.get(sev, 0)
        if not n:
            continue
        bar = "█" * max(1, round(n / widest * 28))
        lines.append(f"  {sev:<9} {n:>3}  {bar}")
    lines += ["", f"  {total} findings across {report['table_count']} tables", ""]

    for sev in ("critical", "high", "medium", "low"):
        group = [f for f in report["findings"] if f["severity"] == sev]
        if not group:
            continue
        title = f"{sev.upper()}  ({len(group)})"
        lines.append("")
        lines.append(f"  {title}")
        lines.append("  " + "─" * max(len(title), 58))
        for f in group:
            loc = f"{f['table']}" + (f".{f['columns'][0]}" if f["columns"] else "")
            lines.append(f"  {loc}")
            lines.append(f"    {f['message']}")
            lines.append(f"    {f['rule']} — {f['why']}")
            if show_fix:
                lines.append("")
                for fl in f["fix"].splitlines():
                    lines.append(f"      {fl}")
            lines.append("")
    return "\n".join(lines)


def render_markdown(report: dict) -> str:
    c = report["counts"]
    out = [
        f"# Schema audit — `{report['source']}`",
        "",
        f"**{report['table_count']} tables** · "
        + " · ".join(
            f"{c[s]} {s}" for s in ("critical", "high", "medium", "low") if c.get(s)
        ),
        "",
        "| Severity | Table | Rule | Finding |",
        "|---|---|---|---|",
    ]
    for f in report["findings"]:
        msg = f["message"].replace("|", "\\|")
        out.append(
            f"| {f['severity']} | `{f['table']}` | `{f['rule']}` | {msg} |"
        )
    out.append("")
    out.append("## Fixes")
    out.append("")
    for f in report["findings"]:
        out.append(f"### `{f['table']}` — {f['rule']}")
        out.append("")
        out.append(f["why"])
        out.append("")
        out.append("```sql")
        out.append(f["fix"])
        out.append("```")
        out.append("")
    return "\n".join(out)


def render_sql(report: dict) -> str:
    out = [
        f"-- Fixes for {report['source']} generated by schemascope",
        "-- Review every statement before running it. Back up first.",
        "",
    ]
    for f in report["findings"]:
        out.append(f"-- [{f['severity']}] {f['table']}: {f['message']}")
        out.append(f["fix"])
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    if not args:
        print(
            "usage: audit.py <schema.json|schema.sql|schema.prisma|db.sqlite> "
            "[--json|--markdown|--sql]",
            file=sys.stderr,
        )
        return 2

    path = args[0]
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
        import introspect

        doc = introspect.load(path)

    report = audit(doc)

    if "--json" in flags:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif "--markdown" in flags:
        print(render_markdown(report))
    elif "--sql" in flags:
        print(render_sql(report))
    else:
        print(render_text(report, show_fix="--no-fix" not in flags))

    crit = report["counts"].get("critical", 0)
    return 1 if crit and "--strict" in flags else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
