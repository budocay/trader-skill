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
    python3 dirigeants.py extraire DD_26_1146018.pdf      # lit un PDF (ou son texte) de l'AMF et l'ajoute
    python3 dirigeants.py amf --jours 30 --societe "ABC ARBITRAGE"   # interroge la BDIF directement
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
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ACHATS = {"acquisition", "achat", "souscription"}
VENTES = {"cession", "vente"}
CHAMPS = ("reference", "societe", "isin", "declarant", "nature", "date", "prix", "volume")
MOIS = {"janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "aout": 8, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12, "décembre": 12}
BDIF = "https://bdif.amf-france.org/back/api/v1"
UA = "trader-skill-fr (+https://github.com/budocay/trader-skill)"


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
    """achat, vente ou autre. Bons de souscription, options et actions gratuites : autre."""
    n = str(nature or "").strip().lower()
    n = n.replace("é", "e").replace("è", "e")
    if any(w in n for w in ("bon", "option", "gratuite", "attribution", "warrant")):
        return "autre"
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


def date_fr(texte):
    """'23 juillet 2026' -> '2026-07-23'."""
    m = re.search(r"(\d{1,2})(?:er)?\s+([a-zA-Zéûè]+)\s+(\d{4})", texte or "")
    if not m or m.group(2).lower() not in MOIS:
        raise DirigeantsErreur("date illisible : %r" % texte)
    return datetime.date(int(m.group(3)), MOIS[m.group(2).lower()], int(m.group(1))).isoformat()


def isin_valide(isin):
    """Clé de contrôle ISIN (Luhn sur les chiffres, A=10 ... Z=35)."""
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin or ""):
        return False
    chiffres = "".join(str(int(c, 36)) for c in isin[:-1])
    total = 0
    for i, ch in enumerate(reversed(chiffres)):
        d = int(ch) * (2 if i % 2 == 0 else 1)
        total += d - 9 if d > 9 else d
    return (10 - total % 10) % 10 == int(isin[-1])


PAYS_ISIN = {"FR", "BE", "NL", "LU", "DE", "IT", "ES", "PT", "IE", "AT", "FI", "SE", "DK", "NO", "CH", "GB",
             "US", "CA", "JE", "GG", "IM", "MC", "XS", "EU", "BM", "KY", "IL", "JP", "AU", "GR", "PL", "CZ",
             "HU", "RO", "BG", "HR", "SI", "SK", "EE", "LV", "LT", "MT", "CY", "IS", "LI", "SN", "CI", "MA",
             "GA", "CM", "TN", "BR", "MX", "ZA", "IN", "CN", "HK", "SG", "KR", "TW", "NZ", "CW", "VG", "PA"}


def _isin(code):
    """Un ISIN valide, avec un vrai code pays, dans le champ du déclarant
    (« xparFR0010557264 » compris), sinon None."""
    s = re.sub(r"\s", "", code or "").upper()
    for i in range(len(s) - 11):
        c = s[i:i + 12]
        if c[:2] in PAYS_ISIN and isin_valide(c):
            return c
    return None


def _nombre(t):
    return float(re.sub(r"[\s\u00a0]", "", t).replace(",", "."))


def extraire_texte(texte, reference=None):
    """Lit le texte d'une déclaration AMF (modèle « Déclaration individuelle relative aux
    opérations des personnes mentionnées à l'article L.621-18-2 ») et rend une ligne par
    transaction, au format de `ajouter`."""
    t = texte.replace("\u2019", "'")
    ref = reference
    m = re.search(r"(\d{4}DD\d{5,})", t)
    if m and not ref:
        ref = m.group(1)
    if not ref:
        raise DirigeantsErreur("référence AMF (AAAADD...) introuvable")
    publie = None
    m = re.search(r"\d{4}DD\d{5,}\s+(\d{1,2}(?:er)?\s+\S+\s+\d{4})", t)
    if m:
        try:
            publie = date_fr(m.group(1))
        except DirigeantsErreur:
            publie = None
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\s*-\s*DD\d+", t)
    isin_entete = m.group(1) if m else ""
    m = re.search(r"PERSONNE ETROITEMENT LIEE\s*:\s*(.+?)\n\s*\n?\s*NOTIFICATION", t, re.S)
    declarant = " ".join(m.group(1).split()) if m else ""
    m = re.search(r"COORDONNEES DE L'EMETTEUR\s+NOM\s*:\s*(.+)", t)
    societe = m.group(1).strip() if m else ""
    blocs = re.split(r"DETAIL DE LA TRANSACTION", t)[1:]
    if not blocs:
        raise DirigeantsErreur("%s : aucun bloc « DETAIL DE LA TRANSACTION »" % ref)
    out = []
    for i, b in enumerate(blocs, 1):
        def champ(nom):
            mm = re.search(nom + r"\s*:\s*(.+)", b)
            return mm.group(1).strip() if mm else None
        agg = b.split("INFORMATIONS AGREGEES")[-1]
        mp = re.search(r"PRIX\s*:\s*([\d\s.,\u00a0]+)", agg)
        mv = re.search(r"VOLUME\s*:\s*([\d\s.,\u00a0]+)", agg)
        lie = champ(r"ATTRIBUTION\s+D'ACTIONS GRATUITES OU DE PERFORMANCES") or ""
        if not lie:
            ml = re.search(r"PERFORMANCES\s*:\s*(OUI|NON)", b)
            lie = ml.group(1) if ml else "NON"
        if not (mp and mv):
            raise DirigeantsErreur("%s : prix ou volume introuvable (transaction %d)" % (ref, i))
        out.append({
            "reference": ref if len(blocs) == 1 else "%s-%d" % (ref, i),
            "societe": societe,
            "isin": _isin(champ(r"CODE D'IDENTIFICATION DE L'INSTRUMENT FINANCIER")) or isin_entete,
            "declarant": declarant, "nature": champ("NATURE DE LA TRANSACTION") or "",
            "date": date_fr(champ("DATE DE LA TRANSACTION") or ""), "publie": publie,
            "prix": _nombre(mp.group(1)), "volume": _nombre(mv.group(1)),
            "instrument": champ(r"DESCRIPTION DE L'INSTRUMENT FINANCIER") or "",
            "lieu": champ("LIEU DE LA TRANSACTION") or "",
            "lie_programme": "oui" if lie.strip().upper().startswith("OUI") else "non"})
    return out


def texte_pdf(path):
    exe = shutil.which("pdftotext")
    if not exe:
        raise DirigeantsErreur("pdftotext introuvable (paquet poppler-utils) : donne le texte du PDF")
    r = subprocess.run([exe, "-layout", path, "-"], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", "replace")


def bdif_recherche(jours=30, societe=None, aujourdhui=None):
    """Déclarations des dirigeants publiées par l'AMF (API publique de la BDIF)."""
    debut = (aujourdhui or datetime.date.today()) - datetime.timedelta(days=int(jours))
    res, start = [], 0
    while True:
        q = {"TypesInformation": "DD", "DateDebut": debut.isoformat() + "T00:00:00.000Z",
             "From": start, "Size": 200}
        if societe:
            q["RechercheTexte"] = societe
        url = BDIF + "/informations?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        res += d.get("result", [])
        start += 200
        if start >= d.get("total", 0):
            return res
        time.sleep(0.3)


def bdif_pdf(info, dossier):
    os.makedirs(dossier, exist_ok=True)
    for doc in info.get("documents", []):
        path = os.path.join(dossier, "%s.pdf" % info["numero"])
        if not os.path.exists(path):
            req = urllib.request.Request(BDIF + "/documents/" + doc["path"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            with open(path, "wb") as fh:
                fh.write(data)
            time.sleep(0.25)
        return path
    return None


def valides(lignes):
    """Sépare les lignes complètes des autres : (bonnes, [erreurs])."""
    bonnes, erreurs = [], []
    for l in lignes:
        try:
            normaliser(l)
            bonnes.append(l)
        except DirigeantsErreur as e:
            erreurs.append(str(e))
    return bonnes, erreurs


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
    p = sub.add_parser("extraire", help="lire une déclaration AMF (PDF ou texte) et l'ajouter")
    p.add_argument("fichiers", nargs="+")
    p = sub.add_parser("amf", help="interroger la BDIF de l'AMF et ajouter les déclarations trouvées")
    p.add_argument("--jours", type=int, default=30)
    p.add_argument("--societe", action="append", help="raison sociale (répétable) ; toutes sinon")
    p.add_argument("--dossier", default="trader/state/amf_pdf")
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
        if a.cmd == "extraire":
            lignes, erreurs = [], []
            for f in a.fichiers:
                try:
                    texte = texte_pdf(f) if f.lower().endswith(".pdf") else open(f, encoding="utf-8").read()
                    lignes += extraire_texte(texte)
                except DirigeantsErreur as e:
                    erreurs.append("%s : %s" % (f, e))
            lignes, err2 = valides(lignes)
            erreurs += err2
            ok, ko = ajouter(base, lignes)
            ecrire(a.base, base)
            for e in erreurs:
                print("illisible, à relever à la main : " + e)
            print("%d transaction(s) ajoutée(s), %d déjà connue(s), %d fichier(s) illisible(s)."
                  % (len(ok), len(ko), len(erreurs)))
            return 0 if ok or ko else 1
        if a.cmd == "amf":
            infos = []
            for soc in (a.societe or [None]):
                infos += bdif_recherche(a.jours, soc)
            if a.societe:
                voulu = {s.strip().upper() for s in a.societe}
                infos = [i for i in infos if any(s["raisonSociale"].strip().upper() in voulu
                                                 for s in i.get("societes", []))]
            lignes, erreurs = [], []
            for info in infos:
                try:
                    path = bdif_pdf(info, a.dossier)
                    if path:
                        lignes += extraire_texte(texte_pdf(path), info["numero"])
                except (DirigeantsErreur, OSError) as e:
                    erreurs.append("%s : %s" % (info.get("numero"), e))
            lignes, err2 = valides(lignes)
            erreurs += err2
            ok, ko = ajouter(base, lignes)
            ecrire(a.base, base)
            for e in erreurs:
                print("illisible, à relever à la main : " + e)
            print("%d déclaration(s) AMF, %d transaction(s) ajoutée(s), %d déjà connue(s)."
                  % (len(infos), len(ok), len(ko)))
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
