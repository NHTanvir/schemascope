# Drawing an ERD people can actually read

A diagram nobody can read is worse than no diagram, because it looks like
documentation. Rules that make the difference.

## Choose how much to show

| Tables | Show |
|---|---|
| up to ~8 | every column, with PK/FK/UK markers |
| 9–20 | keys, foreign keys and a handful of identifying columns |
| 20+ | relationships only, plus a per-subsystem diagram |

`render.py` supports this directly:

```bash
python3 scripts/render.py schema.sql --mermaid                 # all columns
python3 scripts/render.py schema.sql --mermaid --max-cols=6    # first 6, then a count
python3 scripts/render.py schema.sql --mermaid --no-columns    # relationships only
```

A 40-table diagram with every column is not a diagram, it is a wall. Split it by
subsystem and draw each one.

## Make cardinality mean something

Mermaid's crow's feet carry real information, so get them right:

```
users ||--o{ posts     one user, zero-or-more posts, author is mandatory
posts |o--o{ media     media may have no post -- the FK is nullable
users ||--o| profiles  one-to-one: the FK is unique or is the primary key
comments |o--o{ comments   self-reference: a threaded reply
```

The left symbol comes from whether the foreign key is nullable. The right symbol
comes from whether it is unique. Both are facts already in the schema, so neither
should be guessed — `render.py` derives them.

## Label the relationship with the key

Label edges with the foreign key column, not a verb. `user_id` tells a reader
which column to look at; "has" tells them nothing they had not assumed.

## Keep types honest but short

`decimal(10,2)` matters — it is the difference between money being right and
wrong. `character varying(255)` does not; `varchar_255` carries the same
information in half the width. Mermaid identifiers cannot contain parentheses or
commas, so `render.py` normalises them: `decimal(10,2)` becomes `decimal_10_2`
and `enum('a','b')` becomes `enum`.

## Mark what constrains the data

`PK`, `FK` and `UK` markers are the highest-value characters in the diagram —
they are what turns a picture of boxes into a statement about integrity. A reader
scanning for `FK` with no corresponding relationship line has found a bug.

## Put it where it will be read

Mermaid renders inline on GitHub, GitLab and most wikis. A fenced ```mermaid
block in the README stays correct because it is regenerated from the schema, and
it needs no image pipeline, no asset to commit and no build step. That is why it
is the default output.

The HTML report is for sharing with people who will not open the repo: one file,
diagram plus every finding and its fix, light and dark, nothing fetched from
anywhere except the Mermaid renderer.
