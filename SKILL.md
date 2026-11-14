---
name: schemascope
description: Review a database schema and draw it. Use when the user asks to review, audit, critique, diagram, visualize or improve a database schema, an ERD, migrations, a schema.prisma, a SQL dump, or a SQLite file - or right after you have designed or changed a schema yourself. Finds missing indexes on foreign keys, undeclared foreign keys, wrong column types, missing constraints, and unsafe defaults, and emits the fix DDL plus a Mermaid ER diagram.
---

# schemascope

Audit a database schema, then draw it. Report what is wrong in priority order and
give the exact DDL that fixes each thing.

## When to use this

- the user asks for a schema review, audit, critique, ERD or diagram
- the user shares a `.sql` dump, a `schema.prisma`, a migrations folder or a `.sqlite` file
- **immediately after you design or modify a schema yourself** — review your own work before saying it is done

## How to run it

The scripts live in `scripts/` next to this file. They need Python 3.9+ and
nothing else. Resolve `<skill>` to this skill's directory.

```bash
# 1. the audit -- always run this first
python3 <skill>/scripts/audit.py <schema>

# 2. the diagram
python3 <skill>/scripts/render.py <schema> --mermaid

# 3. a single shareable HTML file with both
python3 <skill>/scripts/render.py <schema> --out=schema-review.html
```

`<schema>` is any of:

| Input | Command |
|---|---|
| `.sql` file or migration | `audit.py schema.sql` |
| `schema.prisma` | `audit.py schema.prisma` |
| SQLite file | `audit.py app.db` |
| live PostgreSQL | `pg_dump --schema-only mydb \| audit.py -` |
| live MySQL | `mysqldump --no-data db \| audit.py -` |

Other flags: `--markdown` (for a PR comment), `--sql` (migration only),
`--json` (for tooling), `--strict` (exit 1 on any critical finding), `--no-fix`
(summary without the DDL).

If the project has several schema sources, ask which one is authoritative rather
than guessing. If there is a migrations directory, concatenate it in filename
order and pipe that in.

## How to report the result

1. **Lead with the counts.** "6 critical, 25 high, 7 medium, 12 low across 7 tables."
2. **Show the criticals in full**, each with its fix DDL.
3. **Summarise the rest by rule**, not one by one — "9 foreign keys have no index"
   beats nine near-identical paragraphs.
4. **Show the diagram** when the user asked about structure, or when the schema
   has more than three tables.
5. **Offer the migration** as a single ordered script. Do not run it.

## Rules that matter

Never apply a fix without being asked. These are schema migrations against what
may be a production database; the user decides.

When you do apply them, in this order:

1. additive and non-destructive first — new indexes, new columns
2. backfill data
3. then constraints that would fail on existing rows — `NOT NULL`, `CHECK`, `UNIQUE`, foreign keys
4. type changes last, each with its `USING` clause

Warn explicitly that on a large PostgreSQL table, `CREATE INDEX` and
`ALTER TABLE ... ADD CONSTRAINT` take locks, and that `CREATE INDEX CONCURRENTLY`
plus `NOT VALID` then `VALIDATE CONSTRAINT` is the non-blocking path.

A finding is a judgement, not a fact. `nullable_everything` on a staging table is
fine. `unbounded_text` on PostgreSQL is mostly stylistic. Say so when it is true
rather than reporting a number you do not believe.

## Reference

- [`references/audit-rules.md`](references/audit-rules.md) — all 24 rules, each with rationale and fix
- [`references/diagram-style.md`](references/diagram-style.md) — how to draw an ERD people can read
