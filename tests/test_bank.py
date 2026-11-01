import unittest

from cte.db import FakeDatabase
from cte.engine import BankHandler, Engine
from cte.model import DslError, parse_text


def run(text, scripted=None):
    blocks = parse_text(text)
    db = FakeDatabase(scripted_returns=scripted or {})
    engine = Engine(db)
    engine.run(blocks)
    return engine, db


def procs(db):
    return [c[0] for c in db.calls]


def calls(db, name):
    return [c[1] for c in db.calls if c[0] == name]


NEW_BANK = {
    "API_FIND_BANK": [(None,)],
    "API_FIND_FACE": [(None, None)],
    "API_INS_FACE": [(10,)],
}

SBER = """
bank &sber
  NAME=ПАО Сбербанк
  INN=7707083893
  BIC=044525225
  KORR=30101810400000000225
  CITY=Москва
"""


class BankCreateTests(unittest.TestCase):
    def test_new_bank_goes_through_face_then_bank_record(self):
        engine, db = run(SBER, NEW_BANK)
        self.assertEqual(
            procs(db), ["API_FIND_BANK", "API_FIND_FACE", "API_INS_FACE", "API_SET_BANK"]
        )
        self.assertEqual(engine.aliases["sber"].id, 10)

    def test_face_gets_only_face_fields_bank_gets_only_bank_fields(self):
        _, db = run(SBER, NEW_BANK)
        is_juric, since, face_text = calls(db, "API_INS_FACE")[0]
        self.assertEqual(is_juric, 1)
        self.assertEqual(since, "1900-01-01")
        self.assertIn("NAME=ПАО Сбербанк", face_text)
        self.assertIn("INN=7707083893", face_text)
        for name in ("BIC", "KORR", "CITY", "SWIFT"):
            self.assertNotIn(name + "=", face_text)
        face_id, bank_text = calls(db, "API_SET_BANK")[0]
        self.assertEqual(face_id, 10)
        self.assertEqual(
            bank_text.split("\n"),
            ["BIC=044525225", "KORR=30101810400000000225", "CITY=Москва"],
        )

    def test_defaults_state_and_fs_added_when_not_given(self):
        _, db = run(SBER, NEW_BANK)
        face_text = calls(db, "API_INS_FACE")[0][2]
        self.assertIn("STATE=643", face_text.split("\n"))
        self.assertIn("FS=16", face_text.split("\n"))

    def test_explicit_state_and_fs_win_over_defaults(self):
        _, db = run(
            """
bank &b
  NAME=Foreign Bank
  STATE=840
  FS=12
  SWIFT=CHASUS33
""",
            NEW_BANK,
        )
        lines = calls(db, "API_INS_FACE")[0][2].split("\n")
        self.assertIn("STATE=840", lines)
        self.assertIn("FS=12", lines)
        self.assertNotIn("STATE=643", lines)
        self.assertNotIn("FS=16", lines)

    def test_nothing_else_is_defaulted(self):
        _, db = run(SBER, NEW_BANK)
        keys = {line.split("=")[0] for line in calls(db, "API_INS_FACE")[0][2].split("\n")}
        self.assertEqual(keys, {"NAME", "INN", "STATE", "FS"})

    def test_bank_without_bic_foreign_bank_with_swift(self):
        _, db = run(
            """
bank &jp
  NAME=JP Morgan
  SWIFT=CHASUS33
""",
            NEW_BANK,
        )
        find = calls(db, "API_FIND_BANK")[0]
        self.assertEqual(find, (None, "CHASUS33"))
        self.assertEqual(calls(db, "API_SET_BANK")[0][1], "SWIFT=CHASUS33")

    def test_bank_without_any_code_skips_bank_lookup(self):
        _, db = run("bank &b\n  NAME=Банк без кодов\n", NEW_BANK)
        self.assertNotIn("API_FIND_BANK", procs(db))
        self.assertEqual(calls(db, "API_SET_BANK")[0], (10, ""))

    def test_creation_requires_name(self):
        with self.assertRaisesRegex(DslError, "нужно поле NAME"):
            run("bank &b\n  BIC=044525225\n", NEW_BANK)

    def test_s_type_other_than_one_is_error(self):
        with self.assertRaisesRegex(DslError, "S_TYPE может быть только 1"):
            run("bank &b\n  NAME=X\n  S_TYPE=0\n", NEW_BANK)

    def test_s_type_one_is_accepted_and_not_forwarded(self):
        _, db = run("bank &b\n  NAME=X\n  S_TYPE=1\n", NEW_BANK)
        self.assertNotIn("S_TYPE", calls(db, "API_INS_FACE")[0][2])


class BankFindTests(unittest.TestCase):
    def test_found_by_bic_is_reused_untouched(self):
        scripted = {"API_FIND_BANK": [(77,)]}
        engine, db = run(SBER, scripted)
        self.assertEqual(engine.aliases["sber"].id, 77)
        self.assertEqual(procs(db), ["API_FIND_BANK"])

    def test_found_as_plain_face_becomes_bank(self):
        scripted = {"API_FIND_BANK": [(None,)], "API_FIND_FACE": [(55, None)]}
        engine, db = run(SBER, scripted)
        self.assertEqual(engine.aliases["sber"].id, 55)
        self.assertNotIn("API_INS_FACE", procs(db))
        self.assertEqual(calls(db, "API_SET_BANK")[0][0], 55)

    def test_ambiguous_face_is_error_not_duplicate(self):
        scripted = {"API_FIND_BANK": [(None,)], "API_FIND_FACE": [(None, "5,6")]}
        with self.assertRaisesRegex(DslError, "несколько записей"):
            run(SBER, scripted)


class BankRevisionTests(unittest.TestCase):
    def revision(self, body):
        return run(
            SBER
            + """
bank &sber
  as_of=2021-01-01
"""
            + body,
            NEW_BANK,
        )

    def test_as_of_versions_only_face_fields(self):
        _, db = self.revision("  NAME=ПАО Сбербанк России\n  KORR=30101810400000000999\n")
        face_id, as_of, face_text = calls(db, "API_UPD_FACE")[0]
        self.assertEqual((face_id, as_of), (10, "2021-01-01"))
        self.assertEqual(face_text, "NAME=ПАО Сбербанк России")
        bank_calls = calls(db, "API_SET_BANK")
        self.assertEqual(bank_calls[-1], (10, "KORR=30101810400000000999"))

    def test_bank_only_revision_does_not_touch_face(self):
        _, db = self.revision("  CITY=Санкт-Петербург\n")
        self.assertEqual(calls(db, "API_UPD_FACE"), [])
        self.assertEqual(calls(db, "API_SET_BANK")[-1], (10, "CITY=Санкт-Петербург"))

    def test_defaults_not_reapplied_on_revision(self):
        _, db = self.revision("  NAME=Новое имя\n")
        self.assertNotIn("STATE=", calls(db, "API_UPD_FACE")[0][2])
        self.assertNotIn("FS=", calls(db, "API_UPD_FACE")[0][2])

    def test_revision_requires_as_of(self):
        with self.assertRaisesRegex(DslError, "нужен as_of"):
            run(SBER + "\nbank &sber\n  NAME=Другое\n", NEW_BANK)

    def test_first_declaration_rejects_as_of(self):
        with self.assertRaisesRegex(DslError, "as_of недопустим при первом"):
            run("bank &b\n  NAME=X\n  as_of=2020-01-01\n", NEW_BANK)

    def test_as_of_must_increase(self):
        with self.assertRaisesRegex(DslError, "должен быть позже"):
            run(
                SBER
                + "\nbank &sber\n  as_of=2021-01-01\n  NAME=A\n"
                + "\nbank &sber\n  as_of=2020-01-01\n  NAME=B\n",
                NEW_BANK,
            )


class BankChildrenTests(unittest.TestCase):
    def test_activity_under_bank_uses_bank_face_id(self):
        _, db = run(
            SBER
            + """  activity: bank
    NUM_LIC=1481
    BEG_LIC=1990-01-01
""",
            NEW_BANK,
        )
        face_id, dial_mode, fields = calls(db, "API_SET_P_FACE")[0]
        self.assertEqual((face_id, dial_mode), (10, 14))
        self.assertIn("NUM_LIC=1481", fields)

    def test_activity_under_bank_revision_block(self):
        _, db = run(
            SBER
            + """
bank &sber
  as_of=2021-01-01
  NAME=ПАО Сбербанк России
  activity: bank
""",
            NEW_BANK,
        )
        self.assertEqual(calls(db, "API_SET_P_FACE")[0][0], 10)

    def test_only_activity_is_allowed_under_bank(self):
        for kind in ("code: nsd\n    CODE=1", "attorney\n    NAME=Иванов"):
            with self.assertRaisesRegex(DslError, "недопустим внутри 'bank'"):
                parse_text("bank &b\n  NAME=X\n  " + kind + "\n")


class BankContractTests(unittest.TestCase):
    def test_bank_fields_do_not_overlap_face_fields_the_platform_knows(self):
        # поля OD_BANKS, которые API_UPD_FACE не знает и молча бы проигнорировал
        self.assertEqual(
            set(BankHandler.BANK_FIELDS),
            {"BIC", "KORR", "CITY", "SWIFT", "REG_NUM", "IS_INSURANCE"},
        )

    def test_dry_run_database_does_not_stop_on_bank(self):
        from cte.db import DryRunDatabase

        blocks = parse_text(SBER)
        engine = Engine(DryRunDatabase())
        engine.run(blocks)
        self.assertIsNotNone(engine.aliases["sber"].id)
        self.assertEqual(engine.warnings, [])


if __name__ == "__main__":
    unittest.main()
