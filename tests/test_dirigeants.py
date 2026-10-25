"""trader-dirigeants (déclarations AMF) et l'horloge Euronext Paris de trader-alerts. Hors ligne."""

import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

from _load import FIX, load

dir_ = load("trader-dirigeants", "dirigeants")
alerts = load("trader-alerts", "alerts")
FIXTURE = os.path.join(FIX, "trader-dirigeants", "declarations.json")


def fixture_rows():
    with open(FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)["declarations"]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dir_.main(argv)
    return code, out.getvalue(), err.getvalue()


class Declarations(unittest.TestCase):
    def setUp(self):
        self.base = {"declarations": []}
        self.ok, self.ko = dir_.ajouter(self.base, fixture_rows())

    def test_normalises_numbers_and_amounts(self):
        orange = [d for d in self.ok if d["reference"] == "2026DD1141604"][0]
        self.assertEqual((orange["prix"], orange["volume"], orange["montant"]), (13.6941, 10000.0, 136941.0))
        self.assertEqual(orange["sens"], "achat")
        gl = [d for d in self.ok if d["reference"] == "2026DD1144609"][0]
        self.assertEqual(gl["montant"], 2913511.4)

    def test_no_duplicates(self):
        ok, ko = dir_.ajouter(self.base, fixture_rows()[:2])
        self.assertEqual((ok, ko), ([], ["2026DD1141604", "2026DD1144609"]))
        self.assertEqual(len(self.base["declarations"]), 5)

    def test_sens(self):
        self.assertEqual([dir_.sens(n) for n in ("Acquisition", "Cession", "Souscription", "Exercice d'options")],
                         ["achat", "vente", "achat", "autre"])

    def test_missing_field_or_bad_isin_is_refused(self):
        with self.assertRaises(dir_.DirigeantsErreur):
            dir_.normaliser({"reference": "X", "societe": "Y", "isin": "FR0000133308"})
        row = dict(fixture_rows()[0], isin="ORANGE")
        with self.assertRaises(dir_.DirigeantsErreur):
            dir_.normaliser(row)

    def test_signals_skip_option_plans_and_flag_group_buying(self):
        rows = dir_.recentes(self.base, 30, datetime.date(2026, 10, 25))
        self.assertEqual({d["reference"] for d in rows},
                         {"2026DD1141604", "2026DD1144609", "TEST0000001", "TEST0000002"})
        s = {x["societe"]: x for x in dir_.signaux(rows)}
        self.assertEqual(s["Orange"]["acheteurs"], 2)
        self.assertTrue(s["Orange"]["achats_groupes"])
        self.assertEqual(s["Orange"]["achats"], 163941.0)              # 136 941 + 27 000, sans le plan
        self.assertFalse(s["GL Events"]["achats_groupes"])
        self.assertEqual(dir_.signaux(rows)[0]["societe"], "Orange")   # les achats groupés d'abord

    def test_portfolio_matching_by_isin(self):
        isins, _ = dir_.isins_suivis({"positions": [{"ticker": "ORA.PA", "isin": "FR0000133308"}]}, {})
        self.assertEqual(isins, {"FR0000133308"})


class TexteAmf(unittest.TestCase):
    """Le modèle réel d'une déclaration publiée par l'AMF (texte de pdftotext -layout)."""

    def test_extraire(self):
        with open(os.path.join(FIX, "trader-dirigeants", "declaration-amf.txt"), encoding="utf-8") as fh:
            rows = dir_.extraire_texte(fh.read())
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["reference"], r["societe"], r["isin"]), ("2026DD1128895", "ABC ARBITRAGE", "FR0004040608"))
        self.assertEqual((r["date"], r["publie"], r["nature"]), ("2026-07-23", "2026-07-24", "Cession"))
        self.assertEqual((r["prix"], r["volume"], r["lie_programme"]), (5.0316, 3832.0, "non"))
        self.assertIn("conseil d'administration", r["declarant"])
        self.assertEqual(dir_.normaliser(r)["sens"], "vente")

    def test_isin_typed_badly_falls_back_to_the_header(self):
        self.assertEqual(dir_._isin("xparFR0010557264"), "FR0010557264")
        self.assertIsNone(dir_._isin("FR 00053027"))

    def test_warrants_and_options_are_not_buys(self):
        self.assertEqual(dir_.sens("Acquisition de bon de souscription"), "autre")
        self.assertEqual(dir_.sens("Acquisition de stock-options"), "autre")
        self.assertEqual(dir_.sens("Acquisition"), "achat")

    def test_french_dates(self):
        self.assertEqual(dir_.date_fr("1er août 2026"), "2026-08-01")
        with self.assertRaises(dir_.DirigeantsErreur):
            dir_.date_fr("demain")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "dirigeants.json")
        self.etat = os.path.join(self.tmp.name, "etat.json")
        self.args = ["--base", self.base, "--etat", self.etat]

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_then_new_only_once(self):
        code, out, _ = run(self.args + ["importer", FIXTURE])
        self.assertIn("5 ajoutée(s)", out)
        code, out, _ = run(self.args + ["nouveaux"])
        self.assertIn("5 nouvelle(s)", out)
        code, out, _ = run(self.args + ["nouveaux"])
        self.assertEqual(code, 1)
        self.assertIn("0 nouvelle(s)", out)

    def test_ajouter_and_liste(self):
        code, out, _ = run(self.args + ["ajouter", "--reference", "2026DD1141604", "--societe", "Orange",
                                        "--isin", "FR0000133308", "--declarant", "Dirigeant A",
                                        "--nature", "acquisition", "--date", "2026-10-01",
                                        "--prix", "13.6941", "--volume", "10000"])
        self.assertEqual(code, 0, out)
        self.assertIn("136 941 €", out)
        code, out, _ = run(self.args + ["liste"])
        self.assertIn("2026DD1141604", out)

    def test_recherche_gives_the_query(self):
        code, out, _ = run(self.args + ["recherche", "FR0000133308"])
        self.assertIn('site:bdif.amf-france.org "FR0000133308"', out)


class EuronextClock(unittest.TestCase):
    def st(self, iso):
        return alerts.market_status_paris(alerts.parse_now(iso, "paris"))

    def test_open_and_closed(self):
        self.assertTrue(self.st("2026-10-26T10:00")["open"])
        self.assertFalse(self.st("2026-10-26T17:31")["open"])
        self.assertFalse(self.st("2026-10-25T11:00")["open"])           # dimanche
        self.assertEqual(self.st("2026-10-25T11:00")["next_open"], "2026-10-26 09:00")

    def test_holidays_and_early_close(self):
        self.assertIn("Lundi de Pâques", self.st("2026-04-06T10:00")["reason"])
        dec24 = self.st("2026-12-24T14:30")
        self.assertEqual((dec24["closes"], dec24["open"]), ("14:05", False))
        self.assertEqual(dec24["next_open"], "2026-12-28 09:00")
        self.assertFalse(self.st("2027-03-26T10:00")["open"])           # Vendredi saint 2027

    def test_summer_and_winter_time(self):
        self.assertEqual(alerts.paris_offset(datetime.datetime(2026, 10, 25, 0, 59)), 2)
        self.assertEqual(alerts.paris_offset(datetime.datetime(2026, 10, 25, 1, 0)), 1)
        self.assertEqual(alerts.paris_offset(datetime.datetime(2026, 3, 29, 1, 0)), 2)
        self.assertTrue(self.st("2026-10-26T08:30Z")["open"])           # 9 h 30 à Paris en hiver
        self.assertTrue(self.st("2026-07-01T07:30Z")["open"])           # 9 h 30 à Paris en été
        self.assertFalse(self.st("2026-07-01T06:30Z")["open"])          # 8 h 30 à Paris en été

    def test_yahoo_keeps_exchange_suffixes(self):
        self.assertIn("/chart/MC.PA?", alerts.yahoo_url("mc.pa"))
        self.assertIn("/chart/BRK-B?", alerts.yahoo_url("brk.b"))
        self.assertEqual(alerts.currency_mark("MC.PA"), "€")
        self.assertEqual(alerts.currency_mark("AAPL"), "$")


if __name__ == "__main__":
    unittest.main()
