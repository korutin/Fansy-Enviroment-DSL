import tempfile
import unittest
from pathlib import Path

from cte.model import DslError, parse_text, parse_file


class ParserTests(unittest.TestCase):
    def test_basic_block_and_fields(self):
        blocks = parse_text(
            """
face &ivanov: individual
  NAME=Иванов Иван Иванович
  INN=770123456789
"""
        )
        self.assertEqual(len(blocks), 1)
        b = blocks[0]
        self.assertEqual(b.kind, "face")
        self.assertEqual(b.alias, "ivanov")
        self.assertEqual(b.subtype, "individual")
        self.assertEqual([f.name for f in b.fields], ["NAME", "INN"])
        self.assertEqual(b.get("NAME").raw, "Иванов Иван Иванович")
        self.assertFalse(b.get("NAME").is_alias)

    def test_comments_and_blank_lines_ignored(self):
        blocks = parse_text(
            """
# это комментарий
face &a: individual

  NAME=Тест
# ещё комментарий
"""
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].get("NAME").raw, "Тест")

    def test_alias_value_whole_match(self):
        blocks = parse_text(
            """
share &gazp: stock
  ISSUER=&gazprom
  NAME=литерал с &амперсандом внутри
"""
        )
        b = blocks[0]
        issuer = b.get("ISSUER")
        self.assertTrue(issuer.is_alias)
        self.assertEqual(issuer.alias, "gazprom")
        name = b.get("NAME")
        self.assertFalse(name.is_alias)
        self.assertEqual(name.raw, "литерал с &амперсандом внутри")

    def test_field_before_header_is_error(self):
        with self.assertRaises(DslError):
            parse_text("  NAME=x")

    def test_field_without_equals_is_error(self):
        with self.assertRaises(DslError):
            parse_text(
                """
face &a: individual
  ПРОСТО_ТЕКСТ_БЕЗ_РАВНО
"""
            )

    def test_unknown_kind_is_error(self):
        with self.assertRaises(DslError):
            parse_text("unknown_kind &a:\n  X=1\n")

    def test_header_without_alias_or_subtype(self):
        blocks = parse_text("bank\n  BIC=044525225\n")
        self.assertIsNone(blocks[0].alias)
        self.assertIsNone(blocks[0].subtype)

    def test_include(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "common.tenv").write_text(
                "face &gazprom: juridical\n  NAME=ПАО Газпром\n", encoding="utf-8"
            )
            (d / "main.tenv").write_text(
                'include "common.tenv"\n\nface &ivanov: individual\n  NAME=Иванов\n',
                encoding="utf-8",
            )
            blocks = parse_file(d / "main.tenv")
            self.assertEqual([b.alias for b in blocks], ["gazprom", "ivanov"])

    def test_circular_include_detected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "a.tenv").write_text('include "b.tenv"\n', encoding="utf-8")
            (d / "b.tenv").write_text('include "a.tenv"\n', encoding="utf-8")
            with self.assertRaises(DslError):
                parse_file(d / "a.tenv")


if __name__ == "__main__":
    unittest.main()
