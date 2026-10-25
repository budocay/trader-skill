#!/usr/bin/env python3
"""Frais et garde-fous français pour trader-frais. Bibliothèque standard, pas de réseau.

Calcule ce qu'un ordre coûte VRAIMENT chez un courtier français, avant de le
passer : courtage (grilles.json), taxe sur les transactions financières
(ttf.json), frais de change pour une action américaine, plafond du PEA. Dit
aussi si un titre a sa place dans un PEA et si un ETF américain est
achetable par un particulier (PRIIPs).

    python3 frais.py ordre MC.PA 500 --isin FR0000121014     # frais d'un achat
    python3 frais.py ordre AAPL 50 --courtier fortuneo --formule progress
    python3 frais.py ordre AAPL 50 --eurusd 1.08 --json
    python3 frais.py comparer 10                              # toutes les formules pour 10 €
    python3 frais.py comparer 300 --marche us
    python3 frais.py ttf FR0000120271                         # soumis à la TTF ?
    python3 frais.py pea NL00150001Q9                         # éligible au PEA ?
    python3 frais.py isin FR0000121014                        # clé de contrôle d'un ISIN

Le courtier, la formule et l'enveloppe viennent de trader/config.json
("courtier", "formule", "enveloppe") ou des options. Les autres skills
(trader-budget, trader-risk, trader-broker, trader-tax) importent ce fichier.

Ce n'est pas un conseil financier : des calculs sur des grilles publiques, qui
changent. Vérifie chez ton courtier avant de passer un ordre.
"""

import argparse
import json
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
GRILLES = os.path.join(ICI, "grilles.json")
TTF = os.path.join(ICI, "ttf.json")
EPS = 1e-9

# suffixes Yahoo -> place de cotation
EURONEXT = {"PA", "AS", "BR"}            # Paris, Amsterdam, Bruxelles : la grille "euronext"
EUROPE = {"DE", "F", "MI", "MC", "LS", "SW", "VI", "HE", "CO", "ST", "OL", "IR", "L"}
DEVISE_SUFFIXE = {"L": "GBP", "SW": "CHF", "CO": "DKK", "ST": "SEK", "OL": "NOK"}

# pays de l'EEE dont les sociétés peuvent entrer dans un PEA (siège dans l'UE ou l'EEE,
# soumises à l'impôt sur les sociétés). Le Royaume-Uni n'en fait plus partie depuis 2021.
PAYS_PEA = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU",
            "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK",
            "IS", "LI", "NO"}

# ETF cotés aux États-Unis, sans document d'informations clés (DIC) européen :
# un particulier en France ne peut en général pas les acheter (règlement PRIIPs).
ETF_US = {"SPY", "VOO", "IVV", "VTI", "QQQ", "QQQM", "DIA", "IWM", "VT", "VXUS", "VEA", "VWO",
          "SCHD", "VIG", "VYM", "SCHX", "SCHB", "ARKK", "ARKW", "ARKG", "NANC", "GOP", "KRUZ",
          "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "UPRO", "GLD", "IAU", "SLV", "TLT", "IEF",
          "SHY", "BND", "AGG", "HYG", "LQD", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI",
          "XLU", "XLB", "XLRE", "XLC", "SMH", "SOXX", "VGT", "VNQ", "EEM", "EFA", "JEPI", "JEPQ",
          "BITO", "IBIT", "FBTC", "GBTC", "ETHA", "USO", "UNG"}


class FraisErreur(Exception):
    pass


# ---------------------------------------------------------------- données

_cache = {}


def _lire(path):
    if path not in _cache:
        try:
            with open(path, encoding="utf-8") as fh:
                _cache[path] = json.load(fh)
        except FileNotFoundError:
            raise FraisErreur("fichier introuvable : %s" % path)
        except json.JSONDecodeError as e:
            raise FraisErreur("%s n'est pas du JSON valide : %s" % (path, e))
    return _cache[path]


def grilles(path=None):
    return _lire(path or GRILLES)


def liste_ttf(path=None):
    doc = _lire(path or TTF)
    return {s["isin"]: s["nom"] for s in doc.get("societes", [])}


# ---------------------------------------------------------------- titres

def isin_valide(isin):
    """Clé de contrôle ISIN (Luhn sur les chiffres, lettres A=10 ... Z=35)."""
    s = str(isin or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", s):
        return False
    digits = "".join(str(int(c, 36)) for c in s[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(s[-1])


def suffixe(ticker):
    t = str(ticker or "").upper()
    if "." in t:
        suf = t.rsplit(".", 1)[1]
        if suf in EURONEXT or suf in EUROPE:
            return suf
    return ""


def marche(ticker):
    """'euronext', 'europe' ou 'us' d'après le suffixe Yahoo (MC.PA, SAP.DE, AAPL)."""
    s = suffixe(ticker)
    if s in EURONEXT:
        return "euronext"
    if s in EUROPE:
        return "europe"
    return "us"


def devise(ticker):
    s = suffixe(ticker)
    if not s and marche(ticker) == "us":
        return "USD"
    return DEVISE_SUFFIXE.get(s, "EUR")


def etf_us_interdit(ticker, isin=None, type_titre=None):
    """(True, raison) si c'est un ETF américain sans DIC européen."""
    t = str(ticker or "").upper()
    us = marche(t) == "us" or str(isin or "").upper().startswith("US")
    if not us:
        return False, ""
    if t in ETF_US or str(type_titre or "").lower() == "etf":
        return True, ("%s est un ETF américain : sans document d'informations clés (DIC), un "
                      "particulier en France ne peut en général pas l'acheter (règlement PRIIPs). "
                      "Cherche un ETF UCITS qui suit le même indice." % t)
    return False, ""


def eligible_pea(ticker, isin=None, type_titre=None):
    """('oui' | 'non' | 'a_verifier', raison)."""
    t = str(ticker or "").upper()
    i = str(isin or "").upper()
    if str(type_titre or "").lower() == "etf":
        return "a_verifier", ("un ETF n'entre dans un PEA que s'il détient au moins 75 % d'actions "
                              "européennes : vérifie la mention « éligible PEA » sur sa fiche")
    if i:
        pays = i[:2]
        if pays in PAYS_PEA:
            return "oui", ("société de l'UE/EEE (ISIN %s) : en principe éligible, si elle est "
                           "soumise à l'impôt sur les sociétés ; ton courtier le confirme" % pays)
        return "non", ("ISIN %s : société hors UE/EEE, pas de place dans un PEA "
                       "(compte-titres seulement)" % pays)
    m = marche(t)
    if m == "us":
        return "non", "action américaine : pas de place dans un PEA (compte-titres seulement)"
    if suffixe(t) == "L":
        return "non", "action britannique : hors PEA depuis le Brexit"
    return "a_verifier", "action européenne sans ISIN : ajoute son ISIN pour vérifier"


def soumis_ttf(isin=None, ticker=None):
    """(True/False/None, nom). None = impossible à dire sans ISIN."""
    i = str(isin or "").strip().upper()
    if i:
        nom = liste_ttf().get(i)
        return (nom is not None), (nom or "")
    if suffixe(ticker) == "PA":
        return None, ""
    return False, ""


# ---------------------------------------------------------------- frais

def _tranche(regle, montant):
    """Courtage d'une grille : forfait jusqu'à un seuil, puis un taux (avec minimum)."""
    if "forfait" in regle:
        if montant <= regle.get("jusqua", float("inf")) + EPS:
            return float(regle["forfait"])
        f = montant * float(regle.get("taux_au_dela", 0)) / 100.0
        return max(f, float(regle.get("minimum_au_dela", 0)))
    f = montant * float(regle.get("taux", 0)) / 100.0
    return max(f, float(regle.get("minimum", 0)))


def formule_de(courtier, formule, g=None):
    g = g or grilles()
    c = g["courtiers"].get(str(courtier or "").lower())
    if not c:
        raise FraisErreur("courtier inconnu %r (connus : %s)" % (courtier, ", ".join(sorted(g["courtiers"]))))
    f = c["formules"].get(str(formule or "").lower())
    if not f:
        raise FraisErreur("formule %r inconnue chez %s (connues : %s)"
                          % (formule, c["nom"], ", ".join(sorted(c["formules"]))))
    return c, f


def frais_ordre(courtier, formule, ticker, montant, sens="achat", enveloppe="CTO", isin=None,
                eurusd=None, premier_ordre_du_mois=False, type_titre=None):
    """Tout ce qu'un ordre de `montant` euros coûte. Retourne un dict :
    courtage, ttf, change, total, pct, minimum_ordre, sous_minimum, notes."""
    g = grilles()
    c, f = formule_de(courtier, formule, g)
    env = str(enveloppe or "CTO").upper()
    m = marche(ticker)
    montant = float(montant)
    sens = {"buy": "achat", "sell": "vente"}.get(str(sens).lower(), str(sens).lower())
    notes = []
    if montant <= 0:
        raise FraisErreur("le montant doit être positif")

    if f.get("enveloppes") and env not in f["enveloppes"]:
        notes.append("la formule %s n'existe pas sur %s chez %s" % (f["nom"], env, c["nom"]))
    regle = f.get(m)
    if regle is None:
        raise FraisErreur("pas de grille %s pour le marché %s chez %s : vérifie sur son site"
                          % (f["nom"], m, c["nom"]))
    if regle.get("premier_ordre_du_mois_gratuit_jusqua") and premier_ordre_du_mois \
            and montant <= regle["premier_ordre_du_mois_gratuit_jusqua"] + EPS:
        courtage = 0.0
        notes.append("premier ordre du mois gratuit (jusqu'à %s €)" % _n(regle["premier_ordre_du_mois_gratuit_jusqua"]))
    else:
        courtage = _tranche(regle, montant)
    if regle.get("a_verifier"):
        notes.append("tarif %s %s incertain : vérifie-le sur le site de %s" % (f["nom"], m, c["nom"]))
    if env == "PEA":
        plafond = montant * float(g.get("plafond_pea_pct", 0.5)) / 100.0
        if courtage > plafond + EPS:
            courtage = plafond
            notes.append("courtage plafonné à %s %% sur PEA" % _n(g.get("plafond_pea_pct", 0.5)).replace(".", ","))

    ttf = 0.0
    if sens == "achat":
        oui, nom = soumis_ttf(isin, ticker)
        if oui:
            ttf = montant * float(g.get("ttf_pct", 0.4)) / 100.0
            notes.append("TTF 0,4 %% (%s)" % nom)
        elif oui is None:
            notes.append("action de Paris sans ISIN : la TTF de 0,4 % s'applique peut-être (ajoute l'ISIN)")

    change = 0.0
    if devise(ticker) != "EUR":
        ch = c.get("change") or {}
        if ch.get("mode") == "points":
            taux = float(eurusd) if eurusd else 1.10
            change = montant * float(ch["valeur"]) / taux
            if not eurusd:
                notes.append("frais de change estimés avec 1 € = 1,10 $ (donne --eurusd pour le vrai taux)")
        elif ch.get("mode") == "pct":
            change = montant * float(ch["valeur"]) / 100.0

    mins = c.get("minimum_ordre", {}).get(env, {})
    minimum = float(mins.get(m, 0) or 0)
    if str(type_titre or "").lower() == "etf" and c.get("minimum_ordre_etf"):
        minimum = max(minimum, float(c["minimum_ordre_etf"].get(env, 0)))
    if env == "PEA" and m not in mins and m == "us":
        notes.append("actions américaines impossibles sur PEA")

    courtage, ttf, change = round(courtage, 2), round(ttf, 2), round(change, 2)
    total = round(courtage + ttf + change, 2)
    return {
        "courtier": c["nom"], "formule": f["nom"], "enveloppe": env, "marche": m,
        "sens": sens, "montant": round(montant, 2), "courtage": courtage, "ttf": ttf,
        "change": change, "total": total, "pct": round(100.0 * total / montant, 2),
        "aller_retour": round(total + courtage + change, 2),
        "minimum_ordre": minimum, "sous_minimum": montant < minimum - EPS,
        "fractionne": bool(c.get("fractionne")), "notes": notes,
    }


def depuis_config(cfg, ticker, montant, sens="achat", isin=None, enveloppe=None, eurusd=None,
                  type_titre=None):
    """frais_ordre avec le courtier, la formule et l'enveloppe de trader/config.json.
    None si la config ne nomme pas de courtier connu de grilles.json."""
    courtier = str((cfg or {}).get("courtier") or "").lower()
    if courtier not in grilles()["courtiers"]:
        return None
    return frais_ordre(courtier, cfg.get("formule"), ticker, montant, sens,
                       enveloppe or cfg.get("enveloppe", "CTO"), isin,
                       eurusd or cfg.get("eurusd"), False, type_titre)


def eurusd_de(prices, cfg=None):
    """Le taux 1 € = x $ : prices["EURUSD=X"] (trader-alerts) ou "eurusd" dans la config."""
    for k in ("EURUSD=X", "EURUSD"):
        v = (prices or {}).get(k)
        if v:
            return float(v)
    v = (cfg or {}).get("eurusd")
    return float(v) if v else None


# ---------------------------------------------------------------- affichage

def _n(x):
    x = float(x)
    return str(int(x)) if abs(x - round(x)) < EPS else ("%.2f" % x).rstrip("0").rstrip(".")


def euros(x):
    s = "{:,.2f}".format(float(x)).replace(",", " ").replace(".", ",")
    return s + " €"


def texte_ordre(r, ticker):
    lignes = ["%s %s de %s, %s %s, %s" % ("Achat" if r["sens"] == "achat" else "Vente",
                                          euros(r["montant"]), ticker, r["courtier"], r["formule"],
                                          r["enveloppe"]),
              "  courtage      %s" % euros(r["courtage"]),
              "  TTF           %s" % euros(r["ttf"]),
              "  change        %s" % euros(r["change"]),
              "  total         %s  (%s %% de l'ordre)" % (euros(r["total"]), _n(r["pct"]).replace(".", ","))]
    if r["sens"] == "achat":
        lignes.append("  aller-retour  %s (achat puis revente au même prix)" % euros(r["aller_retour"]))
        lignes.append("  hausse nécessaire pour rentrer dans tes frais : %s %%"
                      % _n(round(100.0 * r["aller_retour"] / r["montant"], 2)).replace(".", ","))
    if r["minimum_ordre"]:
        lignes.append("  minimum d'ordre %s : %s" % (euros(r["minimum_ordre"]),
                                                     "PAS ATTEINT" if r["sous_minimum"] else "ok"))
    if not r["fractionne"]:
        lignes.append("  %s n'achète que des actions entières" % r["courtier"])
    for n in r["notes"]:
        lignes.append("  note : " + n)
    return "\n".join(lignes)


# ---------------------------------------------------------------- commandes

def _config(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Frais réels d'un ordre chez un courtier français (trader-frais).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("ordre", help="frais d'un ordre")
    p.add_argument("ticker")
    p.add_argument("montant", type=float, help="montant de l'ordre en euros")
    p.add_argument("--vente", action="store_true")
    p.add_argument("--courtier")
    p.add_argument("--formule")
    p.add_argument("--enveloppe", choices=["CTO", "PEA", "cto", "pea"])
    p.add_argument("--isin")
    p.add_argument("--eurusd", type=float, help="1 € = x $")
    p.add_argument("--etf", action="store_true", help="le titre est un ETF")
    p.add_argument("--premier-ordre-du-mois", action="store_true")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("comparer", help="un même ordre chez tous les courtiers et formules")
    p.add_argument("montant", type=float)
    p.add_argument("--marche", default="euronext", choices=["euronext", "us", "europe"])
    p.add_argument("--enveloppe", default="CTO", choices=["CTO", "PEA"])
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("ttf", help="une société est-elle soumise à la TTF ?")
    p.add_argument("isin")
    p = sub.add_parser("pea", help="un titre est-il éligible au PEA ?")
    p.add_argument("isin_ou_ticker")
    p.add_argument("--etf", action="store_true")
    p = sub.add_parser("isin", help="vérifie la clé de contrôle d'un ISIN")
    p.add_argument("isin")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "ordre":
            cfg = _config(a.config)
            courtier = a.courtier or cfg.get("courtier")
            formule = a.formule or cfg.get("formule")
            if not courtier or not formule:
                raise FraisErreur("donne --courtier et --formule, ou mets \"courtier\" et \"formule\" "
                                  "dans trader/config.json")
            env = (a.enveloppe or cfg.get("enveloppe") or "CTO").upper()
            interdit, raison = etf_us_interdit(a.ticker, a.isin, "etf" if a.etf else None)
            r = frais_ordre(courtier, formule, a.ticker, a.montant, "vente" if a.vente else "achat",
                            env, a.isin, a.eurusd or cfg.get("eurusd"), a.premier_ordre_du_mois,
                            "etf" if a.etf else None)
            if interdit:
                r["notes"].insert(0, "BLOQUANT : " + raison)
            if env == "PEA":
                ok, why = eligible_pea(a.ticker, a.isin, "etf" if a.etf else None)
                if ok != "oui":
                    r["notes"].insert(0, ("BLOQUANT : " if ok == "non" else "") + "PEA : " + why)
            print(json.dumps(r, indent=2, ensure_ascii=False) if a.json else texte_ordre(r, a.ticker.upper()))
        elif a.cmd == "comparer":
            g = grilles()
            ticker = {"euronext": "XXX.PA", "us": "XXX", "europe": "XXX.DE"}[a.marche]
            rows = []
            for ck, c in sorted(g["courtiers"].items()):
                for fk in c["formules"]:
                    try:
                        r = frais_ordre(ck, fk, ticker, a.montant, "achat", a.enveloppe)
                    except FraisErreur:
                        continue
                    rows.append(r)
            rows.sort(key=lambda r: (r["sous_minimum"], r["total"]))
            if a.json:
                print(json.dumps(rows, indent=2, ensure_ascii=False))
            else:
                print("Achat de %s sur %s (%s), hors TTF :" % (euros(a.montant), a.marche, a.enveloppe))
                for r in rows:
                    flag = "  minimum %s non atteint" % euros(r["minimum_ordre"]) if r["sous_minimum"] else ""
                    print("  %-28s %10s  %6s %%  aller-retour %s%s" % (
                        "%s %s" % (r["courtier"].split(" ")[0], r["formule"]), euros(r["total"]),
                        _n(r["pct"]).replace(".", ","), euros(r["aller_retour"]), flag))
                print("Pas un conseil financier. Grilles relevées le 25/10/2026 : vérifie chez le courtier.")
        elif a.cmd == "ttf":
            i = a.isin.upper()
            oui, nom = soumis_ttf(i)
            print("%s : %s" % (i, ("soumise à la TTF de 0,4 %% à l'achat (%s)" % nom) if oui
                               else "pas dans la liste TTF 2026"))
        elif a.cmd == "pea":
            x = a.isin_ou_ticker.upper()
            isin = x if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", x) else None
            ok, why = eligible_pea(None if isin else x, isin, "etf" if a.etf else None)
            print("%s : %s, %s" % (x, {"oui": "éligible", "non": "non éligible", "a_verifier": "à vérifier"}[ok], why))
        elif a.cmd == "isin":
            print("%s : %s" % (a.isin.upper(), "clé valide" if isin_valide(a.isin) else "INVALIDE"))
        else:
            ap.print_help()
            return 1
    except FraisErreur as e:
        print("frais.py : %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
