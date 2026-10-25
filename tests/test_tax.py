"""trader-tax : fiscalité française (PMP, flat tax, moins-values, PEA). Hors ligne."""

import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

from _load import ROOT, load

lots = load("trader-tax", "lots")
EXAMPLE = os.path.join(ROOT, "trader-tax", "portfolio.example.json")


def example():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = lots.main(argv)
    return code, out.getvalue(), err.getvalue()


class Taux(unittest.TestCase):
    def test_flat_tax_is_31_4_from_2026(self):
        self.assertEqual(lots.taux(2026), (12.8, 18.6))
        self.assertEqual(lots.taux(2027), (12.8, 18.6))

    def test_flat_tax_was_30_before(self):
        self.assertEqual(lots.taux(2025), (12.8, 17.2))
        self.assertEqual(lots.taux(2018), (12.8, 17.2))
        with self.assertRaises(lots.FiscalErreur):
            lots.taux(2017)


class PrixMoyenPondere(unittest.TestCase):
    def setUp(self):
        self.pos = lots.positions(example())

    def test_one_position_per_ticker_and_envelope(self):
        self.assertEqual(sorted(self.pos), [("AAPL", "CTO"), ("ORA.PA", "CTO"), ("TTE.PA", "PEA")])

    def test_pmp_includes_purchase_fees(self):
        ora = self.pos[("ORA.PA", "CTO")]
        self.assertEqual(ora["parts"], 36)
        self.assertAlmostEqual(ora["cout"], 481.61, places=2)
        self.assertAlmostEqual(ora["pmp"], 481.61 / 36, places=6)

    def test_gain_uses_the_pmp_and_takes_sale_fees_off(self):
        ora = self.pos[("ORA.PA", "CTO")]
        pv = lots.plus_value(ora, 18, 14.00, 1.99)
        self.assertEqual(pv["prix_cession"], 250.01)              # 18 x 14 - 1,99
        self.assertEqual(pv["prix_acquisition"], 240.81)          # 18 x 481,61 / 36 = 240,805
        self.assertEqual(pv["plus_value"], 9.2)

    def test_cannot_sell_more_than_held(self):
        with self.assertRaises(lots.FiscalErreur):
            lots.plus_value(self.pos[("AAPL", "CTO")], 2, 250)

    def test_recording_a_sale_keeps_the_pmp(self):
        pf = example()
        ora = self.pos[("ORA.PA", "CTO")]
        pv = lots.plus_value(ora, 18, 14.00, 1.99)
        lots.enregistrer_vente(pf, ora, pv, "2026-11-20")
        after = lots.positions(pf)[("ORA.PA", "CTO")]
        self.assertAlmostEqual(after["parts"], 18, places=6)
        self.assertAlmostEqual(after["pmp"], ora["pmp"], places=2)
        self.assertEqual(pf["cash"], 370.01)                      # 120 + 250,01


class Bilan(unittest.TestCase):
    ETAT = {"ventes": [
        {"date": "2026-03-01", "enveloppe": "CTO", "plus_value": 500},
        {"date": "2026-05-01", "enveloppe": "CTO", "plus_value": -200},
        {"date": "2025-06-01", "enveloppe": "CTO", "plus_value": -400},
        {"date": "2026-07-01", "enveloppe": "PEA", "plus_value": 9999}],
        "moins_values_anterieures": {"2020": 100, "2015": 50}}

    def test_old_losses_are_used_oldest_first_and_expire_after_ten_years(self):
        b = lots.bilan(self.ETAT, 2026)
        self.assertEqual((b["plus_values"], b["moins_values"], b["solde"]), (500, 200, 300))
        self.assertEqual(b["imputees"], [(2020, 100.0), (2025, 200.0)])   # 2015 a expiré fin 2025
        self.assertEqual(b["imposable"], 0.0)
        self.assertEqual(b["report"], {2025: 200.0})

    def test_pea_sales_stay_out_of_the_cto_balance(self):
        self.assertEqual(lots.solde_annee(self.ETAT, 2026)[0], 500)

    def test_flat_tax_and_bareme(self):
        etat = {"ventes": [{"date": "2026-02-01", "enveloppe": "CTO", "plus_value": 1000}]}
        b = lots.bilan(etat, 2026, tmi=11)
        self.assertEqual(b["imposable"], 1000)
        self.assertEqual(b["pfu"], {"impot": 128.0, "prelevements_sociaux": 186.0, "total": 314.0})
        self.assertEqual(b["bareme"]["total"], 296.0)             # 110 + 186
        b30 = lots.bilan(etat, 2026, tmi=30)
        self.assertEqual(b30["bareme"]["total"], 486.0)

    def test_a_losing_year_creates_a_loss_to_carry(self):
        etat = {"ventes": [{"date": "2027-02-01", "enveloppe": "CTO", "plus_value": -300}]}
        b = lots.bilan(etat, 2027)
        self.assertEqual(b["nouvelle_moins_value"], 300)
        self.assertEqual(b["report"], {2027: 300})
        self.assertEqual(b["pfu"]["total"], 0)
        later = {"ventes": etat["ventes"] + [{"date": "2028-03-01", "enveloppe": "CTO", "plus_value": 450}]}
        b2 = lots.bilan(later, 2028)
        self.assertEqual(b2["imputees"], [(2027, 300.0)])
        self.assertEqual(b2["imposable"], 150)

    def test_report_text_names_the_tax_boxes(self):
        etat = {"ventes": [{"date": "2026-02-01", "enveloppe": "CTO", "plus_value": 1000}]}
        text = lots.texte_bilan(lots.bilan(etat, 2026, tmi=11))
        self.assertIn("3VG", text)
        self.assertIn("314,00 €", text)
        self.assertIn("le barème coûte moins", text)
        self.assertIn("Pas un conseil fiscal", text)


class Pea(unittest.TestCase):
    def test_withdrawal_before_five_years(self):
        r = lots.retrait_pea(12000, 10000, 3000, "2023-01-15", datetime.date(2026, 10, 25))
        self.assertTrue(r["avant_5_ans"])
        self.assertEqual(r["part_gain"], 500.0)                   # 3000 x 2000 / 12000
        self.assertEqual((r["impot"], r["prelevements_sociaux"], r["total"]), (64.0, 93.0, 157.0))
        self.assertTrue(r["cloture"])

    def test_withdrawal_after_five_years_pays_social_charges_only(self):
        r = lots.retrait_pea(12000, 10000, 3000, "2023-01-15", datetime.date(2028, 2, 1))
        self.assertFalse(r["avant_5_ans"])
        self.assertEqual((r["impot"], r["prelevements_sociaux"]), (0.0, 93.0))
        self.assertEqual(r["net"], 2907.0)

    def test_no_gain_no_tax(self):
        r = lots.retrait_pea(9000, 10000, 1000, "2020-01-01", datetime.date(2026, 1, 1))
        self.assertEqual(r["total"], 0.0)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.pf = os.path.join(d, "portfolio.json")
        self.prices = os.path.join(d, "prices.json")
        self.etat = os.path.join(d, "fiscalite.json")
        self.orders = os.path.join(d, "orders.json")
        with open(self.pf, "w", encoding="utf-8") as fh:
            json.dump(example(), fh)
        with open(self.prices, "w", encoding="utf-8") as fh:
            json.dump({"prices": {"ORA.PA": 12.0, "AAPL": 270.0, "TTE.PA": 60.0, "EURUSD=X": 1.08}}, fh)
        self.common = ["--portfolio", self.pf, "--prices", self.prices, "--etat", self.etat,
                       "--config", os.path.join(d, "none.json")]

    def tearDown(self):
        self.tmp.cleanup()

    def test_rapport_converts_dollars_and_splits_envelopes(self):
        code, out, _ = run(["rapport"] + self.common)
        self.assertEqual(code, 0)
        self.assertIn("Compte-titres (CTO)", out)
        self.assertIn("PEA", out)
        self.assertIn("250,00 €", out)                            # 270 $ / 1,08

    def test_vente_records_and_updates_both_files(self):
        code, out, _ = run(["vente", "ORA.PA", "18", "--prix", "14", "--frais", "1.99", "--date",
                            "2026-11-20", "--enregistrer"] + self.common)
        self.assertEqual(code, 0, out)
        self.assertIn("9,20 €", out)
        with open(self.etat, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["ventes"][0]["plus_value"], 9.2)
        with open(self.pf, encoding="utf-8") as fh:
            ora = [p for p in json.load(fh)["positions"] if p["ticker"] == "ORA.PA"][0]
        self.assertAlmostEqual(sum(l["shares"] for l in ora["lots"]), 18)

    def test_vente_in_dollars(self):
        code, out, _ = run(["vente", "AAPL", "1", "--prix", "270", "--taux-change", "1.08"] + self.common)
        self.assertEqual(code, 0)
        self.assertIn("11,34 €", out)                            # 250 - 238,66
        self.assertIn("Simulation seulement", out)

    def test_vente_in_the_pea_pays_nothing_yet(self):
        code, out, _ = run(["vente", "TTE.PA", "7", "--prix", "60"] + self.common)
        self.assertEqual(code, 0)
        self.assertIn("rien à payer tant que l'argent reste", out)

    def test_recolte_writes_sell_proposals(self):
        code, out, _ = run(["recolte", "--min-perte", "10", "--ecrire", "--orders", self.orders] + self.common)
        self.assertEqual(code, 0, out)
        self.assertIn("ORA.PA", out)                              # 36 x 12 - 481,61 = -49,61
        self.assertIn("abus de droit", out)
        with open(self.orders, encoding="utf-8") as fh:
            o = json.load(fh)["orders"]
        self.assertEqual([(x["symbol"], x["side"], x["qty"], x["enveloppe"]) for x in o],
                         [("ORA.PA", "sell", "36", "CTO")])

    def test_moins_values_ajouter(self):
        code, out, _ = run(["moins-values", "--ajouter", "2024", "350"] + self.common)
        self.assertEqual(code, 0)
        self.assertIn("de 2024 : 350,00 €", out)

    def test_unknown_ticker_is_an_error(self):
        code, _, err = run(["vente", "MC.PA", "1", "--prix", "600"] + self.common)
        self.assertEqual(code, 1)
        self.assertIn("pas de MC.PA", err)


if __name__ == "__main__":
    unittest.main()
