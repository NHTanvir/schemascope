#!/usr/bin/env python3
"""Test suite for schemascope. Standard library only: python3 -m unittest discover tests"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

import audit  # noqa: E402
import introspect  # noqa: E402
import render  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def parse(sql):
    return introspect.parse_sql(sql)


def tbl(doc, name):
    return next(t for t in doc["tables"] if t["name"] == name)


def rules_for(doc, table=None):
    rep = audit.audit(doc)
    return {f["rule"] for f in rep["findings"] if table is None or f["table"] == table}


class TestSqlParsing(unittest.TestCase):
    def test_basic_table(self):
        d = parse("CREATE TABLE t (id SERIAL PRIMARY KEY, name TEXT NOT NULL);")
        t = tbl(d, "t")
        self.assertEqual(t["primary_key"], ["id"])
        self.assertEqual([c["name"] for c in t["columns"]], ["id", "name"])
        self.assertFalse(t["columns"][1]["nullable"])
        self.assertTrue(t["columns"][0]["identity"])

    def test_column_named_key_is_not_an_index(self):
        """MySQL writes `KEY idx (col)`, but `key` is also a legal column name."""
        d = parse('CREATE TABLE settings (key TEXT, value TEXT);')
        self.assertEqual([c["name"] for c in tbl(d, "settings")["columns"]], ["key", "value"])

    def test_mysql_key_is_an_index(self):
        d = parse("CREATE TABLE t (`a` int, `b` int, KEY `idx_a` (`a`));")
        self.assertEqual(tbl(d, "t")["indexes"][0]["columns"], ["a"])

    def test_quoted_and_schema_qualified_names(self):
        d = parse('CREATE TABLE public."Order Items" ("Qty" int);')
        self.assertEqual(tbl(d, "Order Items")["columns"][0]["name"], "Qty")

    def test_inline_reference_with_actions(self):
        d = parse(
            "CREATE TABLE a (id int PRIMARY KEY);"
            "CREATE TABLE b (a_id int REFERENCES a(id) ON DELETE CASCADE);"
        )
        fk = tbl(d, "b")["foreign_keys"][0]
        self.assertEqual((fk["ref_table"], fk["on_delete"]), ("a", "cascade"))

    def test_table_level_constraints(self):
        d = parse(
            "CREATE TABLE t ("
            " a int, b int,"
            " PRIMARY KEY (a, b),"
            " CONSTRAINT fk_x FOREIGN KEY (a) REFERENCES u (id) ON DELETE SET NULL,"
            " UNIQUE (b),"
            " CHECK (b > 0)"
            ");"
        )
        t = tbl(d, "t")
        self.assertEqual(t["primary_key"], ["a", "b"])
        self.assertEqual(t["foreign_keys"][0]["on_delete"], "set null")
        self.assertIn(["b"], t["uniques"])
        self.assertEqual(len(t["checks"]), 1)

    def test_alter_table_adds_constraint(self):
        d = parse(
            "CREATE TABLE b (a_id int);"
            "ALTER TABLE b ADD CONSTRAINT fk FOREIGN KEY (a_id) REFERENCES a (id);"
        )
        self.assertEqual(tbl(d, "b")["foreign_keys"][0]["ref_table"], "a")

    def test_create_index_unique(self):
        d = parse("CREATE TABLE t (a int); CREATE UNIQUE INDEX ix ON t (a);")
        t = tbl(d, "t")
        self.assertTrue(t["indexes"][0]["unique"])
        self.assertIn(["a"], t["uniques"])

    def test_comments_and_strings_are_not_confused(self):
        d = parse(
            "-- CREATE TABLE ghost (x int);\n"
            "/* CREATE TABLE phantom (y int); */\n"
            "CREATE TABLE real_t (note TEXT DEFAULT 'a; b -- c');"
        )
        self.assertEqual([t["name"] for t in d["tables"]], ["real_t"])

    def test_decimal_precision_preserved(self):
        d = parse("CREATE TABLE t (amt decimal(10,2));")
        self.assertEqual(tbl(d, "t")["columns"][0]["type"], "decimal(10,2)")

    def test_dialect_detection(self):
        self.assertEqual(introspect.detect_dialect("id INT AUTO_INCREMENT"), "mysql")
        self.assertEqual(introspect.detect_dialect("id BIGSERIAL"), "postgres")


class TestPrisma(unittest.TestCase):
    SRC = """
    model User {
      id    Int     @id @default(autoincrement())
      email String  @unique @db.VarChar(255)
      name  String?
      posts Post[]
      @@map("users")
    }
    model Post {
      id       Int  @id @default(autoincrement())
      authorId Int  @map("author_id")
      author   User @relation(fields: [authorId], references: [id], onDelete: Cascade)
      @@index([authorId])
    }
    """

    def setUp(self):
        self.doc = introspect.parse_prisma(self.SRC)

    def test_map_renames_table(self):
        self.assertEqual({t["name"] for t in self.doc["tables"]}, {"users", "Post"})

    def test_relation_resolves_to_mapped_name(self):
        fk = tbl(self.doc, "Post")["foreign_keys"][0]
        self.assertEqual((fk["ref_table"], fk["on_delete"]), ("users", "cascade"))

    def test_navigation_field_is_not_a_column(self):
        self.assertNotIn("author", [c["name"] for c in tbl(self.doc, "Post")["columns"]])
        self.assertNotIn("posts", [c["name"] for c in tbl(self.doc, "users")["columns"]])

    def test_nested_default_parsed_whole(self):
        col = tbl(self.doc, "users")["columns"][0]
        self.assertEqual(col["default"], "autoincrement()")

    def test_optional_is_nullable(self):
        cols = {c["name"]: c for c in tbl(self.doc, "users")["columns"]}
        self.assertTrue(cols["name"]["nullable"])
        self.assertFalse(cols["email"]["nullable"])


class TestSqliteIntrospection(unittest.TestCase):
    def test_live_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.sqlite")
            con = sqlite3.connect(path)
            con.executescript(
                "CREATE TABLE a (id INTEGER PRIMARY KEY, n TEXT NOT NULL);"
                "CREATE TABLE b (id INTEGER PRIMARY KEY,"
                " a_id INTEGER REFERENCES a(id) ON DELETE CASCADE);"
                "CREATE UNIQUE INDEX ix_a_n ON a(n);"
            )
            con.commit()
            con.close()
            doc = introspect.introspect_sqlite(path)
            self.assertEqual({t["name"] for t in doc["tables"]}, {"a", "b"})
            self.assertEqual(tbl(doc, "b")["foreign_keys"][0]["ref_table"], "a")
            self.assertIn(["n"], tbl(doc, "a")["uniques"])


class TestAuditRules(unittest.TestCase):
    def test_no_primary_key(self):
        self.assertIn("no_primary_key", rules_for(parse("CREATE TABLE t (a int);")))

    def test_undeclared_foreign_key(self):
        d = parse(
            "CREATE TABLE users (id int PRIMARY KEY);"
            "CREATE TABLE posts (id int PRIMARY KEY, user_id int);"
        )
        self.assertIn("fk_without_constraint", rules_for(d, "posts"))

    def test_declared_foreign_key_is_not_flagged(self):
        d = parse(
            "CREATE TABLE users (id int PRIMARY KEY);"
            "CREATE TABLE posts (id int PRIMARY KEY,"
            " user_id int REFERENCES users(id) ON DELETE CASCADE);"
            "CREATE INDEX ix ON posts(user_id);"
        )
        self.assertNotIn("fk_without_constraint", rules_for(d, "posts"))

    def test_by_suffix_infers_users(self):
        d = parse(
            "CREATE TABLE users (id int PRIMARY KEY);"
            "CREATE TABLE f (id int PRIMARY KEY, uploaded_by int);"
        )
        self.assertIn("fk_without_constraint", rules_for(d, "f"))

    def test_self_reference_inferred(self):
        d = parse("CREATE TABLE comments (id int PRIMARY KEY, parent_id int);")
        self.assertIn("fk_without_constraint", rules_for(d, "comments"))

    def test_unindexed_and_uncascaded_fk(self):
        d = parse(
            "CREATE TABLE a (id int PRIMARY KEY);"
            "CREATE TABLE b (id int PRIMARY KEY, a_id int REFERENCES a(id));"
        )
        found = rules_for(d, "b")
        self.assertIn("unindexed_fk", found)
        self.assertIn("no_cascade_rule", found)

    def test_type_smells(self):
        d = parse(
            "CREATE TABLE t (id int PRIMARY KEY, is_active TEXT, created_at TEXT,"
            " view_count TEXT, price REAL, metadata TEXT, status TEXT);"
        )
        found = rules_for(d, "t")
        for rule in (
            "boolean_as_text", "timestamp_as_text", "numeric_as_text",
            "money_as_float", "json_as_text", "enum_as_free_text",
        ):
            self.assertIn(rule, found, rule)

    def test_plaintext_secret(self):
        d = parse("CREATE TABLE u (id int PRIMARY KEY, password TEXT);")
        self.assertIn("plaintext_secret", rules_for(d, "u"))

    def test_hashed_password_is_not_flagged(self):
        d = parse("CREATE TABLE u (id int PRIMARY KEY, password_hash TEXT);")
        found = rules_for(d, "u")
        self.assertNotIn("plaintext_secret", found)
        self.assertNotIn("unbounded_text", found)

    def test_missing_unique_on_identifier_column(self):
        d = parse("CREATE TABLE t (id int PRIMARY KEY, slug TEXT);")
        self.assertIn("missing_unique", rules_for(d, "t"))

    def test_unique_column_is_not_flagged(self):
        d = parse("CREATE TABLE t (id int PRIMARY KEY, slug varchar(80) UNIQUE NOT NULL);")
        self.assertNotIn("missing_unique", rules_for(d, "t"))

    def test_join_table_duplicate_pairs(self):
        d = parse(
            "CREATE TABLE a (id int PRIMARY KEY); CREATE TABLE b (id int PRIMARY KEY);"
            "CREATE TABLE ab (id int PRIMARY KEY,"
            " a_id int REFERENCES a(id) ON DELETE CASCADE,"
            " b_id int REFERENCES b(id) ON DELETE CASCADE);"
        )
        self.assertIn("duplicate_rows_possible", rules_for(d, "ab"))

    def test_join_table_with_composite_pk_is_clean(self):
        d = parse(
            "CREATE TABLE a (id int PRIMARY KEY); CREATE TABLE b (id int PRIMARY KEY);"
            "CREATE TABLE ab (a_id int NOT NULL REFERENCES a(id) ON DELETE CASCADE,"
            " b_id int NOT NULL REFERENCES b(id) ON DELETE CASCADE,"
            " PRIMARY KEY (a_id, b_id));"
            "CREATE INDEX ix ON ab(b_id);"
        )
        found = rules_for(d, "ab")
        self.assertNotIn("duplicate_rows_possible", found)
        self.assertNotIn("no_updated_at", found)

    def test_fk_type_mismatch(self):
        d = parse(
            "CREATE TABLE a (id bigint PRIMARY KEY);"
            "CREATE TABLE b (id int PRIMARY KEY,"
            " a_id smallint REFERENCES a(id) ON DELETE CASCADE);"
            "CREATE INDEX ix ON b(a_id);"
        )
        self.assertIn("fk_type_mismatch", rules_for(d, "b"))

    def test_serial_matches_integer(self):
        d = parse(
            "CREATE TABLE a (id SERIAL PRIMARY KEY);"
            "CREATE TABLE b (id int PRIMARY KEY,"
            " a_id integer REFERENCES a(id) ON DELETE CASCADE);"
            "CREATE INDEX ix ON b(a_id);"
        )
        self.assertNotIn("fk_type_mismatch", rules_for(d, "b"))

    def test_redundant_index(self):
        d = parse(
            "CREATE TABLE t (a int, b int, id int PRIMARY KEY);"
            "CREATE INDEX i1 ON t (a); CREATE INDEX i2 ON t (a, b);"
        )
        self.assertIn("redundant_index", rules_for(d, "t"))

    def test_status_is_not_a_reserved_word(self):
        d = parse("CREATE TABLE t (id int PRIMARY KEY, status TEXT,"
                  " created_at timestamptz, CHECK (status IN ('a')));")
        self.assertNotIn("reserved_word_column", rules_for(d, "t"))

    def test_genuinely_reserved_word(self):
        d = parse('CREATE TABLE t (id int PRIMARY KEY, "order" int);')
        self.assertIn("reserved_word_column", rules_for(d, "t"))

    def test_severity_ordering(self):
        d = parse("CREATE TABLE users (id int PRIMARY KEY);"
                  "CREATE TABLE t (a int, user_id int, created_at TEXT);")
        sevs = [f["severity"] for f in audit.audit(d)["findings"]]
        ranks = [audit.SEVERITY_ORDER[s] for s in sevs]
        self.assertEqual(ranks, sorted(ranks))

    def test_every_finding_carries_a_fix(self):
        d = introspect.load(os.path.join(ROOT, "examples/blog-schema/before.sql"))
        for f in audit.audit(d)["findings"]:
            self.assertTrue(f["fix"].strip(), f["rule"])
            self.assertTrue(f["why"].strip(), f["rule"])


class TestExamples(unittest.TestCase):
    def test_before_has_findings_after_has_none(self):
        before = audit.audit(introspect.load(os.path.join(ROOT, "examples/blog-schema/before.sql")))
        after = audit.audit(introspect.load(os.path.join(ROOT, "examples/blog-schema/after.sql")))
        self.assertGreater(sum(before["counts"].values()), 20)
        self.assertEqual(sum(after["counts"].values()), 0)


class TestRender(unittest.TestCase):
    def setUp(self):
        self.doc = introspect.load(os.path.join(ROOT, "examples/blog-schema/after.sql"))

    def test_mermaid_header_and_entities(self):
        m = render.to_mermaid(self.doc)
        self.assertTrue(m.startswith("erDiagram"))
        self.assertIn("users {", m)
        self.assertIn("PK", m)

    def test_mermaid_relationships(self):
        m = render.to_mermaid(self.doc)
        self.assertIn("users ||--o{ posts", m)

    def test_mermaid_type_sanitising(self):
        self.assertEqual(render.mermaid_type("decimal(10,2)"), "decimal_10_2")
        self.assertEqual(render.mermaid_type("enum('a','b')"), "enum")
        self.assertEqual(render.mermaid_type("text[]"), "text_array")
        self.assertEqual(render.mermaid_type(""), "unknown")

    def test_mermaid_has_no_unsafe_characters_in_identifiers(self):
        doc = introspect.parse_sql('CREATE TABLE "Order Items" ("Unit Price" decimal(10,2));')
        m = render.to_mermaid(doc)
        self.assertIn("Order_Items", m)
        self.assertNotIn("Order Items", m)

    def test_html_is_self_contained_and_complete(self):
        out = render.to_html(self.doc, audit.audit(self.doc))
        self.assertTrue(out.startswith("<!doctype html>"))
        self.assertNotIn("__", out)
        self.assertIn("erDiagram", out)
        self.assertIn("prefers-color-scheme", out)

    def test_html_escapes_findings(self):
        doc = introspect.parse_sql("CREATE TABLE t (a int);")
        out = render.to_html(doc, audit.audit(doc))
        self.assertNotIn("<script>alert", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
