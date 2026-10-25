#!/usr/bin/env python3
"""Déclarations des dirigeants (AMF) pour trader-dirigeants. Bibliothèque standard, pas de réseau.

Les dirigeants d'une société cotée et leurs proches déclarent à l'AMF leurs
achats et ventes de titres de la société dans les 3 jours ouvrés (règlement
MAR, article 19). L'AMF les publie dans sa base BDIF. Ce script garde ces
déclarations dans un fichier, sans doublon, et en tire des signaux simples :
qui achète, qui vend, combien, et quand plusieurs dirigeants achètent en
même temps.

Claude trouve et lit les déclarations (recherche web sur bdif.amf-france.org,
puis lecture du PDF) et les enregistre ici avec `ajouter` ou `importer`.

    python3 dirigeants.py recherche FR0000133308          # la requête à lancer pour une société
    python3 dirigeants.py ajouter --reference 2026DD1141604 --societe Orange --isin FR0000133308 \\
        --declarant "Y. S., membre du comité exécutif" --nature acquisition --date 2026-10-01 \\
        --prix 13.6941 --volume 10000
    python3 dirigeants.py importer lot.json               # une liste de déclarations
    python3 dirigeants.py liste --jours 30                # les plus récentes d'abord
    python3 dirigeants.py signaux --jours 30              # par société : achats, ventes, achats groupés
    python3 dirigeants.py portefeuille                    # celles qui touchent tes titres
    python3 dirigeants.py nouveaux                        # seulement ce qui n'a pas encore été montré

Fichiers : trader/dirigeants.json (les déclarations), trader/state/dirigeants.json
(ce qui a déjà été montré).

Ce n'est pas un conseil financier. Ces déclarations sont publiques ; un
dirigeant achète ou vend pour mille raisons, et cela ne prédit pas le cours.
"""

import argparse
import datetime
import json
import os
import re
import sys

ACHATS = {"acquisition", "achat", "souscription"}
VENTES = {"cession", "vente"}
CHAMPS = ("reference", "societe", "isin", "declarant", "nature", "date", "prix", "volume")


class DirigeantsErreur(Exception):
    pass


def lire(path, defaut):
    if not os.path.exists(path):
        return defaut
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise DirigeantsErreur("%s n'est pas du JSON valide : %s" % (path, e))


def ecrire(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def euros(x):
    return "{:,.0f}".format(float(x)).replace(",", " ") + " €"


def sens(nature):
    n = str(nature or "").strip().lower()
    n = n.replace("é", "e").replace("è", "e")
    if any(n.startswith(a) for a in ACHATS):
        return "achat"
    if any(n.startswith(v) for v in VENTES):
        return "vente"
    return "autre"


def normaliser(d):
    """Vérifie une déclaration et calcule son montant. Lève DirigeantsErreur si un champ manque."""
    manque = [k for k in CHAMPS if d.get(k) in (None, "")]
    if manque:
        raise DirigeantsErreur("déclaration %s : il manque %s" % (d.get("reference", "?"), ", ".join(manque)))
    out = dict(d)
    out["reference"] = str(d["reference"]).strip().upper()
    out["isin"] = str(d["isin"]).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", out["isin"]):
        raise DirigeantsErreur("%s : ISIN invalide %r" % (out["reference"], d["isin"]))
    try:
        out["date"] = datetime.date.fromisoformat(str(d["date"])[:10]).isoformat()
        if d.get("publie"):
            out["publie"] = datetime.date.fromisoformat(str(d["publie"])[:10]).isoformat()
        out["prix"] = float(str(d["prix"]).replace(",", "."))
        out["volume"] = float(str(d["volume"]).replace(",", ".").replace(" ", ""))
    except ValueError as e:
        raise DirigeantsErreur("%s : %s" % (out["reference"], e))
    if out["prix"] < 0 or out["volume"] <= 0:
        raise DirigeantsErreur("%s : prix ou volume impossible" % out["reference"])
    out["sens"] = sens(d["nature"])
    out["montant"] = round(out["prix"] * out["volume"], 2)
    lp = str(d.get("lie_programme", "non")).strip().lower()
    out["lie_programme"] = lp in ("oui", "true", "1", "yes")
    return out


def ajouter(base, declarations):
    """Ajoute sans doublon (même référence AMF). Retourne (ajoutées, ignorées)."""
    deja = {d["reference"] for d in base.get("declarations", [])}
    ajoutees, ignorees = [], []
    for d in declarations:
        n = normaliser(d)
        if n["reference"] in deja:
            ignorees.append(n["reference"])
            continue
        base.setdefault("declarations", []).append(n)
        deja.add(n["reference"])
        ajoutees.append(n)
    return ajoutees, ignorees


def recentes(base, jours=None, aujourdhui=None):
    aujourdhui = aujourdhui or datetime.date.today()
    rows = list(base.get("declarations", []))
    if jours:
        debut = (aujourdhui - datetime.timedelta(days=int(jours))).isoformat()
        rows = [d for d in rows if d["date"] >= debut]
    return sorted(rows, key=lambda d: (d["date"], d["reference"]), reverse=True)


def signaux(rows, min_montant=0.0):
    """Par société : achats et ventes hors plans d'options ou d'actions gratuites."""
    par = {}
    for d in rows:
        if d["lie_programme"] or d["sens"] == "autre":
            continue
        s = par.setdefault(d["isin"], {"isin": d["isin"], "societe": d["societe"], "achats": 0.0,
                                       "ventes": 0.0, "acheteurs": set(), "vendeurs": set(), "n": 0})
        s["n"] += 1
        if d["sens"] == "achat":
            s["achats"] += d["montant"]
            s["acheteurs"].add(d["declarant"].strip().lower())
        else:
            s["ventes"] += d["montant"]
            s["vendeurs"].add(d["declarant"].strip().lower())
    out = []
    for s in par.values():
        net = s["achats"] - s["ventes"]
        if max(s["achats"], s["ventes"]) < min_montant:
            continue
        out.append({"isin": s["isin"], "societe": s["societe"], "achats": round(s["achats"], 2),
                    "ventes": round(s["ventes"], 2), "net": round(net, 2),
                    "acheteurs": len(s["acheteurs"]), "vendeurs": len(s["vendeurs"]),
                    "achats_groupes": len(s["acheteurs"]) >= 2, "declarations": s["n"]})
    out.sort(key=lambda s: (-s["achats_groupes"], -s["net"]))
    return out


def isins_suivis(portfolio, targets, orders=None):
    """Les ISIN (et noms) de tes positions, de tes cibles et de tes ordres."""
    isins, noms = set(), set()
    for doc, cle in ((portfolio, "positions"), (targets, "weights"), (orders, "orders")):
        for r in (doc or {}).get(cle, []) if isinstance(doc, dict) else []:
            if r.get("isin"):
                isins.add(str(r["isin"]).upper())
            if r.get("name"):
                noms.add(str(r["name"]).strip().lower())
    return isins, noms


def ligne(d):
    flag = " (plan d'options/actions gratuites)" if d["lie_programme"] else ""
    return "%s  %-6s %-22s %s x %s = %s  %s%s  [%s]" % (
        d["date"], d["sens"].upper(), d["societe"][:22], ("%g" % d["volume"]).replace(".", ","),
        ("%.2f" % d["prix"]).replace(".", ","), euros(d["montant"]), d["declarant"][:50], flag, d["reference"])


# ---------------------------------------------------------------- commandes

def main(argv=None):
    ap = argparse.ArgumentParser(description="Déclarations des dirigeants à l'AMF (trader-dirigeants).")
    ap.add_argument("--base", default="trader/dirigeants.json")
    ap.add_argument("--etat", default="trader/state/dirigeants.json")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("recherche", help="la requête web pour trouver les déclarations d'une société")
    p.add_argument("isin_ou_nom")
    p = sub.add_parser("ajouter", help="enregistrer une déclaration")
    for k in ("reference", "societe", "isin", "declarant", "nature", "date"):
        p.add_argument("--" + k, required=True)
    p.add_argument("--prix", required=True)
    p.add_argument("--volume", required=True)
    p.add_argument("--publie", help="date de publication par l'AMF")
    p.add_argument("--instrument", default="action")
    p.add_argument("--lie-programme", default="non", help="oui si liée à des options ou actions gratuites")
    p.add_argument("--lien", help="adresse du PDF sur bdif.amf-france.org")
    p = sub.add_parser("importer", help="enregistrer une liste de déclarations (JSON)")
    p.add_argument("fichier")
    p = sub.add_parser("liste")
    p.add_argument("--jours", type=int)
    p.add_argument("--isin")
    p.add_argument("--achats", action="store_true")
    p = sub.add_parser("signaux")
    p.add_argument("--jours", type=int, default=30)
    p.add_argument("--min-montant", type=float, default=0.0)
    p = sub.add_parser("portefeuille", help="les déclarations sur tes titres")
    p.add_argument("--jours", type=int, default=90)
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--targets", default="trader/targets.json")
    p.add_argument("--orders", default="trader/orders.json")
    p = sub.add_parser("nouveaux", help="seulement ce qui n'a jamais été montré")
    p.add_argument("--garder", action="store_true", help="ne pas les marquer comme vus")
    a = ap.parse_args(argv)
    try:
        base = lire(a.base, {"declarations": []})
        if a.cmd == "recherche":
            x = a.isin_ou_nom.strip()
            print("Requête web : site:bdif.amf-france.org \"%s\"" % x)
            print("Autre forme : \"déclaration des dirigeants\" %s AMF" % x)
            print("Les titres des résultats ressemblent à « 2026DD1141604 FR0000133308 - DD194172 01 octobre 2026 ».")
            print("Lis chaque PDF, puis : dirigeants.py ajouter --reference ... (ou importer un JSON).")
            return 0
        if a.cmd == "ajouter":
            d = {"reference": a.reference, "societe": a.societe, "isin": a.isin, "declarant": a.declarant,
                 "nature": a.nature, "date": a.date, "prix": a.prix, "volume": a.volume,
                 "publie": a.publie, "instrument": a.instrument, "lie_programme": a.lie_programme,
                 "lien": a.lien}
            ok, ko = ajouter(base, [{k: v for k, v in d.items() if v is not None}])
            ecrire(a.base, base)
            print("Ajoutée : " + ligne(ok[0]) if ok else "Déjà enregistrée : %s" % ko[0])
            return 0
        if a.cmd == "importer":
            doc = lire(a.fichier, None)
            if doc is None:
                raise DirigeantsErreur("fichier introuvable : %s" % a.fichier)
            rows = doc.get("declarations", doc) if isinstance(doc, dict) else doc
            ok, ko = ajouter(base, rows)
            ecrire(a.base, base)
            print("%d ajoutée(s), %d déjà connue(s)." % (len(ok), len(ko)))
            return 0
        if a.cmd == "liste":
            rows = recentes(base, a.jours)
            if a.isin:
                rows = [d for d in rows if d["isin"] == a.isin.upper()]
            if a.achats:
                rows = [d for d in rows if d["sens"] == "achat"]
            for d in rows:
                print(ligne(d))
            print("%d déclaration(s)." % len(rows))
            return 0 if rows else 1
        if a.cmd == "signaux":
            out = signaux(recentes(base, a.jours), a.min_montant)
            if not out:
                print("Aucun achat ni vente (hors plans d'options) sur %d jours." % a.jours)
                return 1
            print("Sur %d jours, hors plans d'options et d'actions gratuites :" % a.jours)
            for s in out:
                tag = "  ACHATS GROUPÉS (%d dirigeants)" % s["acheteurs"] if s["achats_groupes"] else ""
                print("  %-24s achats %s, ventes %s, net %s%s" % (
                    s["societe"][:24], euros(s["achats"]), euros(s["ventes"]), euros(s["net"]), tag))
            print("Des déclarations publiques, pas une prédiction. Pas un conseil financier.")
            return 0
        if a.cmd == "portefeuille":
            isins, noms = isins_suivis(lire(a.portfolio, {}), lire(a.targets, {}), lire(a.orders, {}))
            if not isins and not noms:
                raise DirigeantsErreur("aucun ISIN dans ton portefeuille ni tes cibles : ajoute \"isin\" "
                                       "à tes positions ou à trader/targets.json")
            rows = [d for d in recentes(base, a.jours)
                    if d["isin"] in isins or d["societe"].strip().lower() in noms]
            for d in rows:
                print(ligne(d))
            print("%d déclaration(s) sur tes titres en %d jours." % (len(rows), a.jours))
            return 0 if rows else 1
        if a.cmd == "nouveaux":
            etat = lire(a.etat, {"vus": []})
            vus = set(etat.get("vus", []))
            rows = [d for d in recentes(base) if d["reference"] not in vus]
            for d in rows:
                print(ligne(d))
            if not a.garder and rows:
                etat["vus"] = sorted(vus | {d["reference"] for d in rows})
                ecrire(a.etat, etat)
            print("%d nouvelle(s)." % len(rows))
            return 0 if rows else 1
        ap.print_help()
        return 1
    except DirigeantsErreur as e:
        print("dirigeants.py : %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
