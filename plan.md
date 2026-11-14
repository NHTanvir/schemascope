# schemascope — research, analysis, and build plan

> Point your coding agent at a database. Get a diagram you want to show people,
> and a ranked list of what is wrong with it, each item with the DDL that fixes it.

Research conducted 2026-11-14 against live GitHub, npm, PyPI and web sources.
Every rejected idea below was rejected on evidence, and the evidence is kept so
the reasoning can be re-checked rather than re-litigated.

---

## 1. Objective

Identify something one developer can build that measurably earns GitHub stars
and followers in the current market — then build it.

Starting position: 61 public repos, 1 star in total, 12 followers, 29 repos with
no description, 0 of 61 with topics set. The constraint is therefore not
productivity. It is picking the right target and launching it.

---

## 2. Rejected on evidence

### 2.1 WordPress MCP server — REJECTED

| Repo | Stars | Note |
|---|---|---|
| `Automattic/wordpress-mcp` | 947 | semi-official; deprecating into `mcp-adapter` |
| `msrbuilds/elementor-mcp` | 765 | 234 free tools |
| `AgriciDaniel/wp-mcp-ultimate` | 172 | 58 abilities |
| `deus-h/claudeus-wp-mcp` | 161 | TypeScript, identical approach |
| `techspawn/woocommerce-mcp-server` | 105 | |
| ~35 more | 0–81 | including **15** `woocommerce-mcp` clones at 0–2 |

40+ implementations, a near-official incumbent, and WordPress core standardising
on an Abilities API that commoditises independent servers. A 41st entrant lands
where the clones landed.

### 2.2 Session analytics / "flight recorder" — REJECTED

| Repo | Stars | Created |
|---|---|---|
| `daaain/claude-code-log` | **1,261** | **Jun 2025** |
| `vtemian/claude-notes` | 105 | Jun 2025 |
| `shivamstaq/ccview` | 15 | Mar 2026 |
| `li195111/claude-token-analyzer` | 15 | Mar 2026 |
| `yonk-labs/claude-session-analyzer` | 3 | Jun 2026 |
| `House-lovers7/claude-code-session-health` | **0** | Jul 2026, dead in 3 days |
| 18 further session viewers | **0–4** | 2026 |

Every entrant after mid-2025 scored 0–15. `ccusage` (npm v20.0.50) owns cost
reporting, and Anthropic absorbed the feature into Claude Code's own `/cost`.
When the platform vendor ships the feature, third-party tools in that slice go
to zero.

### 2.3 `deslop` — AI code slop cleanup — REJECTED

| Repo | Stars | Covers |
|---|---|---|
| `pbakaus/impeccable` | 109,676 | design vocabulary for agents |
| `hardikpandya/stop-slop` | 18,927 | AI tells in prose |
| `petergyang/no-ai-slop` | 13,479 | 20+ slop patterns in writing |
| `miqdadbadjuber/anti-slop` | **9,141** | **rules for filtering AI-generated code** |
| `dmmulroy/anti-slop` | 6,070 | Oxlint rules rejecting AI TypeScript |
| `scanaislop/aislop` | 743 | fixes what AI agents leave behind |
| `modem-dev/slop-scan` | 329 | detects AI code slop patterns |
| `LeonardNJU/code-humanizer` | 95 | agent skill removing AI code tells |

npm `deslop` (0.1.1) and `slopcheck` (0.2.0) already published.

**Method note.** Earlier searches for this idea returned *empty* and were almost
acted on. Long descriptive queries ("remove AI slop code refactor simplify agent")
return nothing on GitHub regardless of the truth. The query that found the market
was `slop in:name`. **Short queries, `in:name`, and `--topic=` are the only
reliable instruments.** Every conclusion in this document was re-verified that way.

---

## 3. What the market actually rewards

### 3.1 The field, by stars

| Repo | Stars | Produces |
|---|---|---|
| `morluto/rea` | 457,877 | reverse-engineers anything |
| `anthropics/skills` | 194,179 | official skills |
| `DietrichGebert/ponytail` | 190,416 | agent thinks like a lazy senior dev |
| `addyosmani/agent-skills` | 117,187 | engineering skills |
| `thedotmack/claude-mem` | 116,873 | persistent context |
| `Leonxlnx/taste-skill` | 115,102 | taste, art direction |
| `pbakaus/impeccable` | 109,676 | design vocabulary |
| `tt-a1i/archify` | **96,245** | **code → interactive diagram** |
| `Egonex-AI/Understand-Anything` | **92,556** | **code → graphs that teach** |
| `cathrynlavery/diagram-design` | **66,908** | **editorial diagrams** |
| `blader/humanizer` | 68,858 | removes AI writing tells |
| `ayghri/i-have-adhd` | 61,126 | stops agents burying the answer |
| `heydamir/unslop` | 15,712 | AI-looking UI → designed UI |

### 3.2 Two findings

**Finding 1 — almost no code.** The winners are *taste encoded as markdown*.
`impeccable` is a vocabulary. `ponytail` is an attitude. `anti-slop` is a rule
list. The deliverable is judgement, not software.

**Finding 2 — three of the top ten turn code into a picture.** `archify` (96k),
`Understand-Anything` (92k) and `diagram-design` (66k) all do one thing: take
something a developer already has and render it as something they want to post.

### 3.3 The rule

> **A repo earns stars when its output is something the user wants to show other people.**

Starring is social. The star comes from the screenshot; the screenshot exists only
if the output is show-off-able. This explains the whole dataset — including why 18
competent session viewers scored 0–4. Their output is a private chart about your
own sloppiness. Nobody reposts that.

### 3.4 Derived selection criteria

1. Output is a **visibly impressive artifact** the user wants to post
2. The problem is **embarrassing**, not merely inefficient
3. **Zero friction** — a skill, not infrastructure
4. Not absorbed by the vendor, not owned by a first mover

---

## 4. The gap: the data model

`archify` took software architecture. `Understand-Anything` took knowledge graphs.
`diagram-design` took editorial diagrams. **Nobody took the database.**

### 4.1 Verification — agent-skill space

Short queries, `in:name`, and `--topic=`:

| Query | Best result |
|---|---|
| `database diagram agent` | **empty** |
| `dbml skill` | **empty** |
| `er diagram claude` | **empty** |
| `database skill claude code` | **empty** |
| `sql schema agent skill` | **empty** |
| `schema visualizer postgres` | **empty** |
| `schema audit skill` | **empty** |
| `database review agent` | **empty** |
| `erd mermaid skill` | **empty** |
| `database health check agent skill` | **empty** |
| `erd skill` | 0-star repos only (`erd-skill`, `erd-skills`, `erda-skills`) |
| `schema skill` | *electrical* schematics only (55, 9, 3, 1) |
| `database schema diagram generator` | 1 star |

### 4.2 Verification — established tools (the real competition)

| Tool | Stars | Why it does not close the gap |
|---|---|---|
| `dbeaver/dbeaver` | 52,431 | desktop GUI client; not agent-reachable |
| `drawdb-io/drawdb` | 40,323 | online editor — **you draw it by hand** |
| `ariga/atlas` | 8,822 | declarative migrations, not review or diagrams |
| `schemaspy/schemaspy` | 3,739 | Java + Graphviz install; static HTML docs |
| `holistics/dbml` | 3,726 | a markup language, not an analyser |
| `azimuttapp/azimutt` | 2,199 | SaaS explorer |
| `keonik/prisma-erd-generator` | 1,034 | diagram only, Prisma only |
| `mfvanek/pg-index-health` | 202 | closest in spirit — but a Java library, Postgres-only, no diagram |

The category has incumbents, and none of them is agent-native, cross-source,
zero-install, or pairs a diagram with a prioritised audit. drawDB has 40k stars
for making humans draw schemas by hand; the agent-era version of that job is
unclaimed.

### 4.3 Name availability

| Name | npm | PyPI | GitHub |
|---|---|---|---|
| `schemascope` | free | taken | 3 repos, all 0 stars |
| `dbglance` | free | free | free |
| `erdish` | free | free | free |

`schemascope` selected: clearest and most searchable. The PyPI collision is
irrelevant — distribution is a skill plus a vendored stdlib script, not a package.

---

## 5. Problem validation (independent of this analysis)

The 2026 literature on AI-generated schemas reports a consistent defect set:

- **FK constraints declared, matching indexes omitted** — reported as the single
  most common defect; one walkthrough found `appointment.patient_id` declared as a
  foreign key with no index on it
- **Indexes on primary keys and nothing else**
- **IDs stored as plain columns** with no database-level enforcement at all
- **CHECK constraints skipped**, letting invalid values in via other code paths
- **Wrong timestamp types** (`timestamp without time zone`)
- **Float used for currency**
- **Incorrect cascade delete rules**

Recommended remedy in those sources: *a second review pass over the generated DDL,
verified against the catalog.* That is precisely this product.

**The rule set below was written before this search and independently matches it.**
That is the strongest signal in this document: the defects are real, repeatable,
and nobody ships the review pass.

---

## 6. Product

### 6.1 Positioning

Not "another ERD tool" — that fights drawDB's 40k stars. The pitch is:

> **Your agent just designed your database. Here is what it got wrong.**

The diagram is the screenshot. The audit is the product.

### 6.2 Inputs (no drivers, no install)

| Source | Path |
|---|---|
| Postgres | `pg_dump --schema-only mydb \| introspect.py -` |
| MySQL / MariaDB | `mysqldump --no-data db \| introspect.py -` |
| SQLite | direct file read via stdlib `sqlite3` |
| Prisma | `schema.prisma` parsed natively |
| Raw DDL | any `.sql` migration or schema file |

Deliberately no database drivers: dump output and schema files cover every stack
with zero install, which is criterion 3.

### 6.3 Outputs

1. **Mermaid ER diagram** — renders inline on GitHub, so the output *is* the
   README screenshot. This is the star engine.
2. **Standalone interactive HTML** — one file, no build, shareable.
3. **The audit** — findings ranked critical → low, each with the exact fix DDL.

### 6.4 Audit rules

*Critical* — `no_primary_key`, `fk_without_constraint`, `plaintext_secret`
*High* — `unindexed_fk`, `boolean_as_text`, `timestamp_as_text`, `numeric_as_text`,
`money_as_float`, `missing_unique`, `no_cascade_rule`, `nullable_everything`
*Medium* — `enum_as_free_text`, `json_as_text`, `unbounded_text`,
`missing_timestamps`, `duplicate_rows_possible` (join table with a surrogate key
and no unique pair), `fk_type_mismatch`, `self_fk_no_constraint`, `redundant_index`
*Low* — `no_updated_at`, `inconsistent_naming`, `reserved_word_column`, `wide_table`

Every finding carries copy-pasteable DDL. A finding without a fix is a complaint.

### 6.5 Distribution — modelled on `archify` (96,245 stars)

Its README was studied directly. The format that works:

1. Hero image first, above everything
2. Tagline, then intro, **then** badges
3. Install framed as an instruction *for the agent*, not a command for the human:
   `Install schemascope for me by reading https://raw.githubusercontent.com/NHTanvir/schemascope/master/llms.txt`
4. `npx skills` route as the alternative, plus manual `~/.claude/skills/` placement
5. Long README (2,500–3,000 words), tables, example gallery

Therefore ship: `SKILL.md`, `llms.txt`, `.claude-plugin/` manifests, and a
`~/.claude/skills/` install path. Works in Claude Code, Cursor, Codex and any
agent that reads markdown.

---

## 7. Repo layout

```
schemascope/
├── README.md               hero diagram first, install in one line
├── SKILL.md                the skill
├── llms.txt                agent-readable install instructions
├── LICENSE                 MIT
├── plan.md                 this document
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── references/
│   ├── audit-rules.md      24 rules, each with rationale + fix DDL
│   └── diagram-style.md    how to draw an ERD people can actually read
├── scripts/
│   ├── introspect.py       DDL / Prisma / SQLite -> normalized JSON
│   ├── audit.py            JSON -> ranked findings + fix DDL
│   └── render.py           JSON -> Mermaid + standalone HTML
├── examples/blog-schema/   before.sql, after.sql, diagram, audit output
└── .github/workflows/ci.yml
```

---

## 8. Launch plan

Code without a launch scores zero — that is what the 18 session viewers prove,
and what 61 repos with 1 star prove. Non-negotiable:

1. README opens with the rendered Mermaid diagram of the example schema
2. `examples/blog-schema/` holds a real before/after with the audit output
3. **Set GitHub topics** — `agent-skills`, `claude-skills`, `claude-code`,
   `database`, `erd`, `mermaid`, `postgres`, `schema-design`. All 61 existing
   repos have none, making them invisible to the exact search that surfaced every
   repo in this document
4. Write the repo description
5. Then post: r/ClaudeAI, r/PostgreSQL, r/Database, HN "Show HN", X
6. Lead with the finding, not the tool:
   *"Your agent wrote 7 tables, 9 foreign keys, and 0 indexes on them."*

## 9. After launch

One flagship plus a visible cadence beats 61 repos with empty descriptions.
Ship `schemascope`, publish `references/audit-rules.md` as a standalone read
(it is linkable on its own), then revisit `lancer` — `uphiago/recon-skills`
proves that audience is real at 1,367 stars and 229 forks.
