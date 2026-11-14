# Contributing

The most useful contribution is a **new rule**, or a **false positive**.

## Reporting a false positive

Open an issue with the smallest schema that triggers it and one sentence on why
the flag is wrong in that context. False positives are the highest-priority bug
class here: a report people learn to ignore is worthless, so a rule that fires
when it should not is worse than a rule that does not exist.

## Adding a rule

1. Add the check to the matching `rule_*` function in `scripts/audit.py`.
2. Give it a fix. A finding without copy-pasteable DDL is a complaint, not a
   finding, and will not be merged.
3. Add **two** tests in `tests/test_schemascope.py`: one asserting the rule fires
   on a schema with the defect, one asserting it stays silent on a schema without
   it. The second is the important one.
4. Document it in `references/audit-rules.md` — what it catches, why it matters,
   the fix.

```bash
python3 -m unittest discover -s tests
```

## Adding an input format

One parser in `scripts/introspect.py` returning the normalized shape, plus tests.
Django models, SQLAlchemy, Rails `schema.rb`, DBML and Drizzle are all wanted.

## Constraints

- **Standard library only.** No dependencies, ever. Zero-install is the product.
- **Python 3.9+.**
- Nothing may leave the machine. No telemetry, no network calls.
