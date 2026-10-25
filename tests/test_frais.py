"""trader-frais et la couche française de trader-budget, trader-risk, trader-broker. Hors ligne."""

import contextlib
import io
import json
import os
import tempfile
import unittest

from _load import ROOT, load

frais = load("trader-frais", "frais")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

FR = {"budget": 1000, "devise": "EUR", "courtier": "boursobank", "formule": "decouverte",
      "enveloppe": "CTO", "cash_buffer_pct": 10, "max_position_pct": 40, "min_order_usd": 1,
      "max_frais_pct": 2, "paper": True}
PRICES = {"ORA.PA": 13.69, "TTE.PA": 56.0, "MC.PA": 600.0, "AAPL": 250.0, "EURUSD=X": 1.08}


def buy(sym, qty, **extra):
    o = {"symbol": sym, "side": "buy", "qty": str(qty), "type": "market", "time_in_force": "day"}
    o.update(extra)
    return o


class Grilles(unittest.TestCase):
    def test_boursobank_decouverte_euronext(self):
        r = frais.frais_ordre("boursobank", "decouverte", "ORA.PA", 287.49, isin="FR0000133308")
        self.assertEqual((r["courtage"], r["ttf"], r["change"], r["total"]), (1.99, 1.15, 0.0, 3.14))
        self.assertEqual(frais.frais_ordre("boursobank", "decouverte", "ORA.PA", 1000)["courtage"], 6.0)

    def test_boursobank_classic_minimum_above_the_flat_fee(self):
        self.assertEqual(frais.frais_ordre("boursobank", "classic", "X.PA", 1000)["courtage"], 5.5)
        self.assertEqual(frais.frais_ordre("boursobank", "classic", "X.PA", 1200)["courtage"], 8.95)
        self.assertEqual(frais.frais_ordre("boursobank", "classic", "X.PA", 5000)["courtage"], 24.0)

    def test_boursobank_minimum_order(self):
        self.assertTrue(frais.frais_ordre("boursobank", "decouverte", "X.PA", 10)["sous_minimum"])
        self.assertFalse(frais.frais_ordre("boursobank", "decouverte", "X.PA", 20)["sous_minimum"])
        self.assertEqual(frais.frais_ordre("boursobank", "classic", "X.PA", 50, enveloppe="PEA")["minimum_ordre"], 100)

    def test_us_order_pays_brokerage_and_exchange(self):
        r = frais.frais_ordre("boursobank", "decouverte", "AAPL", 216, eurusd=1.08)
        self.assertEqual((r["courtage"], r["change"]), (6.95, 0.5))   # 216 x 0,0025 / 1,08
        f = frais.frais_ordre("fortuneo", "progress", "AAPL", 216)
        self.assertEqual((f["courtage"], f["change"]), (9.5, 0.26))   # 0,12 %

    def test_fortuneo_starter(self):
        self.assertEqual(frais.frais_ordre("fortuneo", "starter", "X.PA", 10)["courtage"], 0.04)
        self.assertEqual(frais.frais_ordre("fortuneo", "starter", "X.PA", 300, premier_ordre_du_mois=True)["courtage"], 0.0)
        self.assertEqual(frais.frais_ordre("fortuneo", "starter", "X.PA", 600, premier_ordre_du_mois=True)["courtage"], 2.1)
        self.assertIn("incertain", " ".join(frais.frais_ordre("fortuneo", "starter", "AAPL", 100)["notes"]))

    def test_pea_caps_brokerage_at_half_a_percent(self):
        r = frais.frais_ordre("boursobank", "classic", "X.PA", 200, enveloppe="PEA")
        self.assertEqual(r["courtage"], 1.0)

    def test_ttf_only_on_listed_isins_and_only_on_buys(self):
        self.assertEqual(frais.frais_ordre("fortuneo", "progress", "TTE.PA", 1000, isin="FR0000120271")["ttf"], 4.0)
        self.assertEqual(frais.frais_ordre("fortuneo", "progress", "TTE.PA", 1000, "vente", isin="FR0000120271")["ttf"], 0.0)
        self.assertEqual(frais.frais_ordre("fortuneo", "progress", "ALXXX.PA", 1000, isin="FR0013333432")["ttf"], 0.0)
        no_isin = frais.frais_ordre("fortuneo", "progress", "TTE.PA", 1000)
        self.assertIn("sans ISIN", " ".join(no_isin["notes"]))

    def test_ttf_list_has_121_valid_isins(self):
        with open(os.path.join(ROOT, "trader-frais", "ttf.json"), encoding="utf-8") as fh:
            rows = json.load(fh)["societes"]
        self.assertEqual(len(rows), 121)
        self.assertTrue(all(frais.isin_valide(r["isin"]) for r in rows))

    def test_isin_check_digit(self):
        self.assertTrue(frais.isin_valide("US0378331005"))
        self.assertTrue(frais.isin_valide("FR0000121014"))
        self.assertFalse(frais.isin_valide("FR0000121015"))

    def test_unknown_broker_or_formula(self):
        with self.assertRaises(frais.FraisErreur):
            frais.frais_ordre("degiro", "x", "X.PA", 100)
        with self.assertRaises(frais.FraisErreur):
            frais.frais_ordre("boursobank", "gold", "X.PA", 100)


class Titres(unittest.TestCase):
    def test_market_and_currency_from_the_suffix(self):
        self.assertEqual([frais.marche(t) for t in ("MC.PA", "ASML.AS", "SAP.DE", "AAPL", "BRK.B")],
                         ["euronext", "euronext", "europe", "us", "us"])
        self.assertEqual([frais.devise(t) for t in ("MC.PA", "AAPL", "VOD.L")], ["EUR", "USD", "GBP"])

    def test_pea_eligibility(self):
        self.assertEqual(frais.eligible_pea("STLAP.PA", "NL00150001Q9")[0], "oui")
        self.assertEqual(frais.eligible_pea("AAPL")[0], "non")
        self.assertEqual(frais.eligible_pea("X", "US0378331005")[0], "non")
        self.assertEqual(frais.eligible_pea("VOD.L")[0], "non")
        self.assertEqual(frais.eligible_pea("CW8.PA", type_titre="etf")[0], "a_verifier")
        self.assertEqual(frais.eligible_pea("MC.PA")[0], "a_verifier")

    def test_us_etfs_are_flagged(self):
        self.assertTrue(frais.etf_us_interdit("VOO")[0])
        self.assertTrue(frais.etf_us_interdit("NANC")[0])
        self.assertTrue(frais.etf_us_interdit("XYZ", type_titre="etf")[0])
        self.assertFalse(frais.etf_us_interdit("AAPL")[0])
        self.assertFalse(frais.etf_us_interdit("CW8.PA", type_titre="etf")[0])


class Budget(unittest.TestCase):
    def rows(self, *pairs):
        return size.parse_weights([{"ticker": t, "weight": w, "isin": i} for t, w, i in pairs])

    def test_whole_shares_fees_and_euro_conversion(self):
        cfg = dict(FR, budget=300, cash_buffer_pct=0, max_position_pct=100)
        r = size.size(self.rows(("ORA.PA", 40, "FR0000133308"), ("TTE.PA", 30, "FR0000120271"),
                                ("AAPL", 30, None)), cfg, prices=dict(PRICES))
        self.assertTrue(r["whole_shares"])
        held = {p["ticker"]: p for p in r["positions"]}
        self.assertEqual(list(held), ["ORA.PA"])
        self.assertEqual(held["ORA.PA"]["shares"], 21)
        self.assertEqual(held["ORA.PA"]["fees"]["total"], 3.14)
        why = {d["ticker"]: d["reason"] for d in r["dropped"]}
        self.assertIn("231,48 €", why["AAPL"])                       # 250 $ / 1,08
        self.assertIn("dépassent ton plafond de 2 %", why["TTE.PA"])

    def test_ten_euros_buys_nothing_and_says_why(self):
        cfg = dict(FR, budget=10, courtier="fortuneo", formule="starter", cash_buffer_pct=0, max_position_pct=100)
        with self.assertRaises(size.SizeError) as e:
            size.size(self.rows(("ORA.PA", 50, "FR0000133308"), ("TTE.PA", 50, "FR0000120271")), cfg,
                      prices=dict(PRICES))
        self.assertIn("ORA.PA: one share costs", str(e.exception))

    def test_orders_carry_envelope_isin_and_fees(self):
        cfg = dict(FR, budget=300, cash_buffer_pct=0, max_position_pct=100)
        r = size.size(self.rows(("ORA.PA", 100, "FR0000133308")), cfg, prices=dict(PRICES))
        o = size.orders_from(r)[0]
        self.assertEqual((o["qty"], o["enveloppe"], o["isin"], o["frais_estimes"]),
                         ("21", "CTO", "FR0000133308", 3.14))

    def test_dollar_prices_need_a_rate(self):
        cfg = dict(FR, budget=300)
        p = {"AAPL": 250.0}
        with self.assertRaises(size.SizeError):
            size.size(self.rows(("AAPL", 100, None)), cfg, prices=p)


class Risk(unittest.TestCase):
    def run_check(self, orders, **cfg):
        c = dict(FR)
        c.update(cfg)
        return check.check(orders, c, None, dict(PRICES), None, "2026-10-26")

    def test_french_blocks(self):
        res = self.run_check([
            buy("ORA.PA", 21, isin="FR0000133308"),
            buy("TTE.PA", 2, isin="FR0000120271"),
            {"symbol": "AAPL", "side": "buy", "notional": "300", "type": "market", "time_in_force": "day"},
            buy("VOO", 1),
            buy("MSFT", 1, enveloppe="PEA"),
        ])
        r = res["results"]
        self.assertEqual([x["verdict"] for x in r], ["PASS", "BLOCK", "BLOCK", "BLOCK", "BLOCK"])
        self.assertEqual(r[0]["fees"], 3.14)
        self.assertIn("frais :", " ".join(r[1]["reasons"]))
        self.assertIn("fractionné", " ".join(r[2]["reasons"]))
        self.assertIn("priips", " ".join(r[3]["reasons"]))
        self.assertIn("pea:", " ".join(r[4]["reasons"]))
        self.assertEqual(res["cash_after"], 709.37)                 # 1000 - 287,49 - 3,14

    def test_minimum_order_blocks(self):
        res = self.run_check([buy("ORA.PA", 1, isin="FR0000133308")], max_frais_pct=100)
        self.assertIn("sous le minimum", " ".join(res["results"][0]["reasons"]))

    def test_envelope_is_part_of_the_fingerprint(self):
        a = buy("ORA.PA", 21)
        b = buy("ORA.PA", 21, enveloppe="PEA")
        self.assertNotEqual(check.fingerprint(a), check.fingerprint(b))
        self.assertEqual(check.fingerprint(b), ticket.fingerprint(b))

    def test_us_rules_untouched_without_french_config(self):
        res = check.check([buy("VOO", 1)], {"budget": 1000, "max_position_pct": 100}, None, {"VOO": 500},
                          None, "2026-10-26")
        self.assertEqual(res["results"][0]["verdict"], "PASS")


class Broker(unittest.TestCase):
    def test_oui_counts_and_batches_do_not(self):
        o = buy("ORA.PA", 21)
        self.assertTrue(ticket.parse_yes("oui", o)[0])
        self.assertTrue(ticket.parse_yes("Oui, 21 ORA.PA", o)[0])
        self.assertFalse(ticket.parse_yes("oui pour tous", o)[0])
        self.assertFalse(ticket.parse_yes("oui mais attends", o)[0])
        self.assertFalse(ticket.parse_yes("oui 30", o)[0])
        self.assertFalse(ticket.parse_yes("ok", o)[0])

    def test_french_ticket_is_manual(self):
        o = buy("ORA.PA", 21, isin="FR0000133308", enveloppe="CTO", frais_estimes=3.14)
        risk = {"date": "2026-10-26", "results": [{"fingerprint": ticket.fingerprint(o), "verdict": "PASS"}]}
        text, ready = ticket.render(o, 1, 1, FR, risk, {"orders": []}, "2026-10-26")
        self.assertTrue(ready)
        self.assertIn("ACHAT de 21 actions ORA.PA", text)
        self.assertIn("Claude ne passe pas cet ordre", text)
        self.assertIn("Simulation", text)
        live, _ = ticket.render(o, 1, 1, dict(FR, paper=False), risk, {"orders": []}, "2026-10-26")
        self.assertIn("saisis-le toi-même dans l'appli BoursoBank", live)
        j = ticket.ticket_json(o, 1, FR, risk, {"orders": []}, "2026-10-26")
        self.assertTrue(j["manual"])
        self.assertIsNone(j["tool"])

    def test_foreign_live_account_gets_the_3916_reminder(self):
        o = buy("AAPL", 1)
        cfg = {"broker": "alpaca", "paper": False, "devise": "EUR"}
        text, _ = ticket.render(o, 1, 1, cfg, None, {"orders": []}, "2026-10-26")
        self.assertIn("3916-bis", text)

    def test_fills_keep_the_weighted_average_cost(self):
        with tempfile.TemporaryDirectory() as d:
            pf = os.path.join(d, "portfolio.json")
            cfg = dict(FR)
            ticket.apply_fill(pf, cfg, "ORA.PA", "buy", 26, 13.70, "2026-10-26", 3.42)
            ticket.apply_fill(pf, cfg, "ORA.PA", "buy", 10, 12.00, "2026-11-02", 1.99)
            ticket.apply_fill(pf, cfg, "ORA.PA", "sell", 18, 14.00, "2026-11-20", 1.99)
            ticket.apply_fill(pf, cfg, "AAPL", "buy", 1, 250, "2026-11-03", 7.18, fx=1.08)
            with open(pf, encoding="utf-8") as fh:
                doc = json.load(fh)
        ora = [p for p in doc["positions"] if p["ticker"] == "ORA.PA"][0]
        cost = sum(l["cost"] for l in ora["lots"])
        self.assertAlmostEqual(cost / 18, 481.61 / 36, places=2)
        self.assertEqual(ora["enveloppe"], "CTO")
        aapl = [p for p in doc["positions"] if p["ticker"] == "AAPL"][0]
        self.assertEqual(aapl["lots"][0]["cost"], 238.66)            # 250 / 1,08 + 7,18
        self.assertEqual(doc["cash"], 529.74)                         # 1000 - 359,62 - 121,99 + 250,01 - 238,66


class Cli(unittest.TestCase):
    def test_comparer_and_ordre(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(frais.main(["comparer", "10"]), 0)
            self.assertEqual(frais.main(["ordre", "VOO", "100", "--courtier", "boursobank", "--formule",
                                         "decouverte", "--config", "none.json"]), 0)
        text = out.getvalue()
        self.assertIn("Fortuneo Starter", text)
        self.assertIn("minimum 20,00 € non atteint", text)
        self.assertIn("BLOQUANT", text)


if __name__ == "__main__":
    unittest.main()
