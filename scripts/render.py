#!/usr/bin/env python3
"""Render a normalized schema as a Mermaid ER diagram or a standalone HTML report.

Mermaid output renders inline on GitHub, so the diagram can live in a README.
HTML output is one self-contained file holding the diagram and the audit.
Standard library only.
"""
from __future__ import annotations

import html
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Mermaid
# --------------------------------------------------------------------------

def mermaid_ident(name: str) -> str:
    """Mermaid entity/attribute names must be bare words."""
    out = re.sub(r"[^0-9A-Za-z_]", "_", name or "")
    return out or "unnamed"


def mermaid_type(t: str) -> str:
    """decimal(10,2) -> decimal_10_2 ; enum('a','b') -> enum."""
    t = (t or "").strip()
    if not t:
        return "unknown"
    base = re.sub(r"\(.*", "", t).strip()
    nums = re.findall(r"\d+", t.split("(", 1)[1]) if "(" in t else []
    arr = "_array" if "[]" in t else ""
    base = re.sub(r"\[\s*\d*\s*\]", "", base).strip()
    base = re.sub(r"[^0-9A-Za-z_]", "_", base).strip("_")
    return (base + ("_" + "_".join(nums) if nums and len(nums) <= 2 else "") + arr) or "unknown"


def to_mermaid(doc: dict, include_columns: bool = True, max_cols: int = 0) -> str:
    tables = doc.get("tables", [])
    by_name = {t["name"]: t for t in tables}
    lines = ["erDiagram"]

    if include_columns:
        for t in tables:
            ent = mermaid_ident(t["name"])
            pk = set(t.get("primary_key") or [])
            fk_cols = {c for fk in t.get("foreign_keys", []) for c in fk["columns"]}
            uniq = {c for u in t.get("uniques", []) if len(u) == 1 for c in u}
            lines.append(f"    {ent} {{")
            cols = t.get("columns", [])
            shown = cols[:max_cols] if max_cols else cols
            for c in shown:
                keys = []
                if c["name"] in pk:
                    keys.append("PK")
                if c["name"] in fk_cols:
                    keys.append("FK")
                if c["name"] in uniq and c["name"] not in pk:
                    keys.append("UK")
                note = "" if c["nullable"] else "\"not null\""
                parts = [mermaid_type(c["type"]), mermaid_ident(c["name"])]
                if keys:
                    parts.append(",".join(keys))
                if note:
                    parts.append(note)
                lines.append("        " + " ".join(parts))
            if max_cols and len(cols) > max_cols:
                lines.append(f"        more {len(cols) - max_cols}_columns")
            lines.append("    }")

    seen = set()
    for t in tables:
        child = mermaid_ident(t["name"])
        for fk in t.get("foreign_keys", []):
            parent_tbl = fk.get("ref_table")
            if not parent_tbl:
                continue
            parent = mermaid_ident(parent_tbl)
            colmap = {c["name"]: c for c in t.get("columns", [])}
            cols = fk.get("columns") or []
            optional = any(colmap.get(c, {}).get("nullable", True) for c in cols)
            left = "|o" if optional else "||"
            uniq_sets = [set(u) for u in t.get("uniques", []) if u]
            pk = set(t.get("primary_key") or [])
            one_to_one = any(set(cols) == u for u in uniq_sets) or set(cols) == pk
            right = "o|" if one_to_one else "o{"
            label = ", ".join(cols) or "ref"
            key = (parent, child, label)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"    {parent} {left}--{right} {child} : \"{label}\"")

    # entities with no relationship still need to appear
    if not include_columns:
        linked = {k[0] for k in seen} | {k[1] for k in seen}
        for t in tables:
            ent = mermaid_ident(t["name"])
            if ent not in linked:
                lines.append(f"    {ent} {{")
                lines.append("    }")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_SEV_META = [
    ("critical", "#dc2626"),
    ("high", "#ea580c"),
    ("medium", "#ca8a04"),
    ("low", "#0891b2"),
]

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #ffffff; --panel: #f6f7f9; --border: #dfe3e8;
    --fg: #14171a; --muted: #5b6672; --accent: #2563eb; --code: #f0f2f5;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0f1216; --panel: #161b21; --border: #262d36;
      --fg: #e6e9ed; --muted: #9aa4b0; --accent: #60a5fa; --code: #10141a;
    }
  }
  :root[data-theme="dark"] {
    --bg: #0f1216; --panel: #161b21; --border: #262d36;
    --fg: #e6e9ed; --muted: #9aa4b0; --accent: #60a5fa; --code: #10141a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  header { padding: 28px 16px 20px; border-bottom: 1px solid var(--border); }
  .wrap { max-width: 1240px; margin: 0 auto; }
  h1 { margin: 0 0 6px; font-size: 20px; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 13px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .bars { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 18px; }
  .bar { display: flex; align-items: center; gap: 8px; font-size: 13px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
  .bar b { font-variant-numeric: tabular-nums; }
  main { max-width: 1240px; margin: 0 auto; padding: 0 16px 64px; }
  .grid { display: grid; grid-template-columns: minmax(0,1.15fr) minmax(0,1fr); gap: 24px; margin-top: 24px; }
  @media (max-width: 960px) { .grid { grid-template-columns: 1fr; } }
  section > h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--muted); margin: 0 0 12px; font-weight: 600;
  }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .diagram { overflow: auto; }
  .diagram svg { max-width: 100%; height: auto; }
  details { border: 1px solid var(--border); border-radius: 8px; background: var(--panel); margin-bottom: 8px; }
  details[open] { background: var(--bg); }
  summary {
    cursor: pointer; padding: 10px 12px; display: flex; gap: 10px;
    align-items: baseline; list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  .tag {
    font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em;
    padding: 2px 6px; border-radius: 4px; color: #fff; flex: none;
  }
  .loc { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
  .msg { color: var(--muted); font-size: 13px; }
  .body { padding: 0 12px 12px; }
  .why { font-size: 13.5px; color: var(--fg); margin: 2px 0 10px; }
  pre {
    background: var(--code); border: 1px solid var(--border); border-radius: 6px;
    padding: 10px 12px; overflow: auto; margin: 0;
    font: 12.5px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .rule { font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--muted); }
  footer { max-width: 1240px; margin: 0 auto; padding: 0 16px 48px; color: var(--muted); font-size: 12.5px; }
  footer a { color: var(--accent); }
  .empty { color: var(--muted); font-size: 14px; }
</style>
</head>
<body>
<header><div class="wrap">
  <h1>__HEADING__</h1>
  <div class="sub">__SOURCE__ · __TABLES__ tables · __DIALECT__</div>
  <div class="bars">__BARS__</div>
</div></header>
<main>
  <div class="grid">
    <section>
      <h2>Entity relationships</h2>
      <div class="card diagram"><pre class="mermaid">__MERMAID__</pre></div>
    </section>
    <section>
      <h2>Findings</h2>
      __FINDINGS__
    </section>
  </div>
</main>
<footer>
  Generated by <a href="https://github.com/NHTanvir/schemascope">schemascope</a>.
  Review every statement before running it.
</footer>
<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs";
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  mermaid.initialize({
    startOnLoad: true,
    theme: dark ? "dark" : "default",
    er: { useMaxWidth: true, entityPadding: 12 },
  });
</script>
</body>
</html>
"""


def to_html(doc: dict, report: dict | None = None, title: str | None = None) -> str:
    counts = (report or {}).get("counts", {})
    total = sum(counts.values())
    src = doc.get("source") or "schema"
    heading = title or "Schema review"

    bars = []
    for sev, color in _SEV_META:
        n = counts.get(sev, 0)
        if not n:
            continue
        bars.append(
            f'<span class="bar"><span class="dot" style="background:{color}"></span>'
            f"<b>{n}</b> {sev}</span>"
        )
    if not bars:
        bars.append('<span class="bar">No findings</span>')

    blocks = []
    if report and total:
        colors = dict(_SEV_META)
        for sev, _ in _SEV_META:
            for f in report["findings"]:
                if f["severity"] != sev:
                    continue
                loc = f["table"] + (f".{f['columns'][0]}" if f["columns"] else "")
                blocks.append(
                    "<details>"
                    f'<summary><span class="tag" style="background:{colors[sev]}">{sev}</span>'
                    f'<span class="loc">{html.escape(loc)}</span>'
                    f'<span class="msg">{html.escape(f["message"])}</span></summary>'
                    f'<div class="body"><div class="why">{html.escape(f["why"])}</div>'
                    f"<pre>{html.escape(f['fix'])}</pre>"
                    f'<div class="rule">{html.escape(f["rule"])}</div></div>'
                    "</details>"
                )
    else:
        blocks.append('<p class="empty">No findings. This schema is in good shape.</p>')

    out = HTML_TEMPLATE
    for needle, value in (
        ("__TITLE__", html.escape(f"{heading} — {os.path.basename(str(src))}")),
        ("__HEADING__", html.escape(heading)),
        ("__SOURCE__", html.escape(str(src))),
        ("__TABLES__", str(doc.get("table_count", len(doc.get("tables", []))))),
        ("__DIALECT__", html.escape(str(doc.get("dialect", "sql")))),
        ("__BARS__", "".join(bars)),
        ("__MERMAID__", html.escape(to_mermaid(doc))),
        ("__FINDINGS__", "".join(blocks)),
    ):
        out = out.replace(needle, value)
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a.split("=")[0]: (a.split("=", 1)[1] if "=" in a else True)
             for a in argv[1:] if a.startswith("--")}
    if not args:
        print(
            "usage: render.py <schema.sql|schema.prisma|db.sqlite|schema.json> "
            "[--mermaid|--html] [--out=FILE] [--no-columns] [--max-cols=N]",
            file=sys.stderr,
        )
        return 2

    path = args[0]
    if path.endswith(".json"):
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import introspect

        doc = introspect.load(path)
    doc.setdefault("table_count", len(doc.get("tables", [])))

    if "--mermaid" in flags:
        text = to_mermaid(
            doc,
            include_columns="--no-columns" not in flags,
            max_cols=int(flags.get("--max-cols") or 0),
        )
    else:
        import audit as audit_mod

        text = to_html(doc, audit_mod.audit(doc))

    dest = flags.get("--out")
    if isinstance(dest, str):
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"wrote {dest}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
