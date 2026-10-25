#!/usr/bin/env python3
"""Fiscalité française des actions pour trader-tax. Bibliothèque standard, pas de réseau.

Pas un conseil fiscal : des calculs sur tes propres chiffres, selon les règles
générales ci-dessous. Ta situation peut en comporter d'autres ; un
professionnel (ou ton IFU) fait foi.

    python3 lots.py rapport                                   # PMP, plus-values latentes, par enveloppe
    python3 lots.py vente ORA.PA 10 --prix 14.20 --frais 1.99 # ce que la vente rapporterait et coûterait
    python3 lots.py vente AAPL 2 --prix 260 --taux-change 1.08 --enregistrer   # elle est exécutée
    python3 lots.py annee 2026 --tmi 11                       # bilan de l'année : flat tax ou barème
    python3 lots.py moins-values                              # moins-values reportables et leur expiration
    python3 lots.py recolte --min-perte 100                   # moins-values latentes à réaliser ?
    python3 lots.py pea --retrait 2000                        # que coûterait un retrait du PEA ?

Les positions sont dans trader/portfolio.json (écrit par trader-broker) :

    {"cash": 500.0, "positions": [{"ticker": "ORA.PA", "enveloppe": "CTO", "shares": 26,
       "lots": [{"id": "ORA.PA-1", "date": "2026-10-26", "shares": 26, "cost": 359.62}]}]}

"cost" est le coût total en EUROS, frais d'achat compris. Une position sans
"enveloppe" est sur le compte-titres (CTO). Les ventes enregistrées et les
moins-values des années passées vont dans trader/state/fiscalite.json.

Les règles appliquées :
  prix moyen pondéré  le prix d'acquisition d'une vente est la valeur moyenne
                      pondérée de tous les titres identiques détenus sur le
                      compte (art. 150-0 D, 3 du CGI), frais d'achat compris ;
                      les frais de vente viennent en déduction du prix de vente
  pas de court/long   en France la durée de détention ne change pas le taux
  terme ni de règle   au prélèvement forfaitaire unique (PFU), et il n'y a pas
  « wash sale »       de règle « wash sale » à l'américaine
  PFU                 12,8 % d'impôt + 18,6 % de prélèvements sociaux = 31,4 %
                      pour les gains réalisés depuis le 1er janvier 2026
                      (30 % avant : 12,8 + 17,2) ; option globale pour le barème
                      possible (ton taux marginal + prélèvements sociaux)
  moins-values        imputées sur les plus-values de même nature de l'année,
                      puis reportables sur les 10 années suivantes
  PEA                 rien à payer tant que l'argent reste dedans ; retrait
                      avant 5 ans : 31,4 % sur la part de gain et clôture du
                      plan (sauf exceptions) ; après 5 ans : 18,6 % de
                      prélèvements sociaux seulement
"""

import argparse
import datetime
import importlib.util
import json
import os
import sys

EPS = 1e-9
# taux (impôt, prélèvements sociaux) selon l'année où le gain est réalisé
TAUX = {2018: (12.8, 17.2), 2026: (12.8, 18.6)}
REPORT_ANS = 10
PEA_ANS = 5
PLAFOND_PEA = 150000
PLAFOND_PEA_JEUNE = 20000


class FiscalErreur(Exception):
    pass


# ---------------------------------------------------------------- fichiers

def lire(path, quoi, requis=True):
    if not path or not os.path.exists(path):
        if requis:
            raise FiscalErreur("pas de %s dans %s" % (quoi, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise FiscalErreur("%s n'est pas du JSON valide : %s" % (path, e))


def ecrire(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def jour(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10])
    except ValueError:
        raise FiscalErreur("pas une date (AAAA-MM-JJ) : %r" % s)


def euros(x):
    x = float(x)
    s = "{:,.2f}".format(abs(x)).replace(",", " ").replace(".", ",")
    return ("-" if x < -0.004 else "") + s + " €"


def pct(x):
    return ("%.2f" % x).rstrip("0").rstrip(".").replace(".", ",") + " %"


def frais_module():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-frais", "frais.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("trader_frais", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- taux

def taux(annee):
    """(impôt %, prélèvements sociaux %) pour un gain réalisé cette année-là."""
    annee = int(annee)
    if annee < 2018:
        raise FiscalErreur("règles avant 2018 non couvertes (avant le PFU)")
    ir, ps = TAUX[2018]
    for depuis in sorted(TAUX):
        if annee >= depuis:
            ir, ps = TAUX[depuis]
    return ir, ps


# ---------------------------------------------------------------- positions

def positions(portfolio):
    """{(ticker, enveloppe): {"ticker", "enveloppe", "parts", "cout", "pmp", "lots"}}"""
    out = {}
    for p in (portfolio or {}).get("positions", []):
        t = str(p.get("ticker") or p.get("symbol") or "").upper()
        if not t:
            continue
        env = str(p.get("enveloppe") or "CTO").upper()
        if env not in ("CTO", "PEA"):
            raise FiscalErreur("%s : enveloppe %r inconnue (CTO ou PEA)" % (t, env))
        lots = [l for l in p.get("lots", []) if float(l.get("shares", 0)) > EPS]
        parts = sum(float(l["shares"]) for l in lots)
        cout = sum(float(l.get("cost", 0)) for l in lots)
        if not lots and float(p.get("shares", 0) or 0) > EPS:
            raise FiscalErreur("%s a des titres mais pas de lots (date, shares, cost en euros) dans "
                               "trader/portfolio.json" % t)
        cle = (t, env)
        if cle in out:
            out[cle]["parts"] += parts
            out[cle]["cout"] += cout
            out[cle]["lots"] += lots
        else:
            out[cle] = {"ticker": t, "enveloppe": env, "parts": parts, "cout": cout, "lots": lots}
    for v in out.values():
        v["pmp"] = v["cout"] / v["parts"] if v["parts"] > EPS else 0.0
        v["premier_achat"] = min((str(l.get("date", "")) for l in v["lots"]), default="")
    return out


def prix_en_euros(prices, cfg=None):
    """prices.json -> {ticker: prix en euros}. Les tickers américains sont convertis avec EURUSD=X."""
    clean = {}
    for k, v in (prices or {}).items():
        try:
            clean[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    prices = clean
    F = frais_module()
    if not F:
        return prices
    fx = F.eurusd_de(prices, cfg)
    out = {}
    for t, p in prices.items():
        if t in ("EURUSD=X", "EURUSD"):
            continue
        if F.devise(t) == "USD":
            if fx:
                out[t] = p / fx
        else:
            out[t] = p
    return out


# ---------------------------------------------------------------- calculs

def plus_value(pos, quantite, prix, frais=0.0):
    """Plus- ou moins-value d'une vente au prix moyen pondéré (montants en euros)."""
    quantite, prix, frais = float(quantite), float(prix), float(frais or 0)
    if quantite <= EPS:
        raise FiscalErreur("la quantité doit être positive")
    if quantite > pos["parts"] + 1e-6:
        raise FiscalErreur("tu vends %s %s mais n'en détiens que %s sur ton %s"
                           % (_q(quantite), pos["ticker"], _q(pos["parts"]), pos["enveloppe"]))
    cession = round(quantite * prix - frais, 2)
    acquisition = round(quantite * pos["pmp"], 2)
    return {"ticker": pos["ticker"], "enveloppe": pos["enveloppe"], "quantite": quantite,
            "prix": prix, "frais": round(frais, 2), "prix_cession": round(cession, 2),
            "pmp": round(pos["pmp"], 4), "prix_acquisition": round(acquisition, 2),
            "plus_value": round(cession - acquisition, 2)}


def etat_vide():
    return {"ventes": [], "moins_values_anterieures": {}}


def ventes_cto(etat, annee=None):
    return [v for v in etat.get("ventes", []) if v.get("enveloppe", "CTO") == "CTO"
            and (annee is None or str(v["date"])[:4] == str(annee))]


def solde_annee(etat, annee):
    """(plus-values brutes, moins-values brutes, solde) des ventes CTO de l'année."""
    vs = ventes_cto(etat, annee)
    pv = sum(v["plus_value"] for v in vs if v["plus_value"] > 0)
    mv = -sum(v["plus_value"] for v in vs if v["plus_value"] < 0)
    return round(pv, 2), round(mv, 2), round(pv - mv, 2)


def stock_moins_values(etat, avant_annee):
    """Moins-values nettes reportables, par année d'origine, encore valables pour `avant_annee`.

    Part des moins-values déclarées à la main (moins_values_anterieures) et des
    soldes négatifs des années enregistrées ; impute chaque année positive sur
    les plus anciennes d'abord."""
    stock = {}
    for a, m in (etat.get("moins_values_anterieures") or {}).items():
        if float(m) > 0:
            stock[int(a)] = stock.get(int(a), 0.0) + float(m)
    annees = sorted({int(str(v["date"])[:4]) for v in ventes_cto(etat)} | set(stock))
    for a in annees:
        if a >= avant_annee:
            break
        for vieille in [y for y in stock if y < a - REPORT_ANS]:
            del stock[vieille]
        _, _, solde = solde_annee(etat, a)
        if solde < 0:
            stock[a] = stock.get(a, 0.0) + (-solde)
        elif solde > 0:
            reste = solde
            for y in sorted(stock):
                if y >= a:
                    continue
                pris = min(reste, stock[y])
                stock[y] -= pris
                reste -= pris
                if reste <= EPS:
                    break
    return {y: round(m, 2) for y, m in sorted(stock.items()) if m > 0.004 and y >= avant_annee - REPORT_ANS}


def bilan(etat, annee, tmi=None):
    """Bilan fiscal CTO de l'année : imputation des moins-values, PFU et barème."""
    pv, mv, solde = solde_annee(etat, annee)
    stock = stock_moins_values(etat, annee)
    imputees, reste = [], solde
    if solde > 0:
        for y in sorted(stock):
            pris = min(reste, stock[y])
            if pris > 0:
                imputees.append((y, round(pris, 2)))
                stock[y] = round(stock[y] - pris, 2)
                reste -= pris
            if reste <= EPS:
                break
    imposable = round(max(reste, 0.0), 2) if solde > 0 else 0.0
    nouvelle_mv = round(-solde, 2) if solde < 0 else 0.0
    ir, ps = taux(annee)
    res = {"annee": int(annee), "plus_values": pv, "moins_values": mv, "solde": solde,
           "imputees": imputees, "imposable": imposable, "nouvelle_moins_value": nouvelle_mv,
           "taux_ir": ir, "taux_ps": ps,
           "pfu": {"impot": round(imposable * ir / 100, 2), "prelevements_sociaux": round(imposable * ps / 100, 2)},
           "report": {y: m for y, m in stock.items() if m > 0.004}}
    res["pfu"]["total"] = round(res["pfu"]["impot"] + res["pfu"]["prelevements_sociaux"], 2)
    if nouvelle_mv:
        res["report"][int(annee)] = nouvelle_mv
    if tmi is not None:
        b_ir = round(imposable * float(tmi) / 100, 2)
        res["bareme"] = {"tmi": float(tmi), "impot": b_ir, "prelevements_sociaux": res["pfu"]["prelevements_sociaux"],
                         "total": round(b_ir + res["pfu"]["prelevements_sociaux"], 2)}
    return res


def retrait_pea(valeur, versements, retrait, ouverture, le=None):
    """Coût fiscal d'un retrait de `retrait` euros d'un PEA."""
    valeur, versements, retrait = float(valeur), float(versements), float(retrait)
    if retrait <= 0 or retrait > valeur + EPS:
        raise FiscalErreur("le retrait doit être entre 0 et la valeur du PEA (%s)" % euros(valeur))
    le = le or datetime.date.today()
    ouv = jour(ouverture)
    try:
        cinq = ouv.replace(year=ouv.year + PEA_ANS)
    except ValueError:
        cinq = ouv.replace(year=ouv.year + PEA_ANS, day=28)
    gain_total = max(valeur - versements, 0.0)
    part_gain = retrait * gain_total / valeur if valeur > EPS else 0.0
    ir, ps = taux(le.year)
    avant = le < cinq
    impot = part_gain * ir / 100 if avant else 0.0
    sociaux = part_gain * ps / 100
    return {"ouverture": ouv.isoformat(), "cinq_ans": cinq.isoformat(), "avant_5_ans": avant,
            "retrait": round(retrait, 2), "part_gain": round(part_gain, 2),
            "impot": round(impot, 2), "prelevements_sociaux": round(sociaux, 2),
            "total": round(impot + sociaux, 2), "cloture": avant,
            "net": round(retrait - impot - sociaux, 2)}


# ---------------------------------------------------------------- portefeuille

def enregistrer_vente(portfolio, pos, pv, date):
    """Retire les titres vendus en gardant le PMP (chaque lot perd la même part)."""
    for p in portfolio.get("positions", []):
        t = str(p.get("ticker") or p.get("symbol") or "").upper()
        if t == pos["ticker"] and str(p.get("enveloppe") or "CTO").upper() == pos["enveloppe"]:
            detenu = sum(float(l["shares"]) for l in p.get("lots", []))
            garde = 1.0 - pv["quantite"] / detenu if detenu else 0.0
            for l in p.get("lots", []):
                l["shares"] = round(float(l["shares"]) * garde, 6)
                l["cost"] = round(float(l["cost"]) * garde, 2)
            p["lots"] = [l for l in p["lots"] if float(l["shares"]) > 1e-6]
            p["shares"] = round(float(p.get("shares", detenu)) - pv["quantite"], 6)
    portfolio["positions"] = [p for p in portfolio.get("positions", []) if float(p.get("shares", 0)) > 1e-6]
    if pos["enveloppe"] == "CTO" or "cash" in portfolio:
        portfolio["cash"] = round(float(portfolio.get("cash", 0)) + pv["prix_cession"], 2)
    return portfolio


# ---------------------------------------------------------------- affichage

def _q(x):
    s = ("%.6f" % float(x)).rstrip("0").rstrip(".")
    return (s or "0").replace(".", ",")


def texte_rapport(pos, prix, detail=False, cfg=None):
    lignes = []
    cfg = cfg or {}
    for env in ("CTO", "PEA"):
        rows = [v for (t, e), v in sorted(pos.items()) if e == env]
        if not rows:
            continue
        titre = "Compte-titres (CTO)" if env == "CTO" else "PEA"
        if env == "PEA" and cfg.get("pea_ouverture"):
            ouv = jour(cfg["pea_ouverture"])
            age = (datetime.date.today() - ouv).days / 365.25
            titre += ", ouvert le %s (%s ans%s)" % (ouv.isoformat(), ("%.1f" % age).replace(".", ","),
                                                      ", plus de 5 ans" if age >= 5 else ", moins de 5 ans")
        lignes.append(titre)
        lignes.append("  %-9s %10s %11s %11s %12s %12s" % ("titre", "quantité", "PMP", "cours", "valeur", "+/- latente"))
        tv = tl = 0.0
        for v in rows:
            p = prix.get(v["ticker"])
            val = v["parts"] * p if p else None
            lat = (val - v["cout"]) if val is not None else None
            tv += val or 0
            tl += lat or 0
            lignes.append("  %-9s %10s %11s %11s %12s %12s" % (
                v["ticker"], _q(v["parts"]), euros(v["pmp"]), euros(p) if p else "?",
                euros(val) if val is not None else "?",
                ("%s (%s)" % (euros(lat), pct(100 * lat / v["cout"]))) if lat is not None and v["cout"] else "?"))
            if detail:
                for l in v["lots"]:
                    lignes.append("      achat du %s : %s titres pour %s" % (l.get("date"), _q(l["shares"]), euros(l["cost"])))
        lignes.append("  %-9s %10s %11s %11s %12s %12s" % ("total", "", "", "", euros(tv), euros(tl)))
        if env == "CTO" and tl > 0:
            ir, ps = taux(datetime.date.today().year)
            lignes.append("  si tout était vendu aujourd'hui : environ %s de flat tax (%s) sur la plus-value latente"
                          % (euros(tl * (ir + ps) / 100), pct(ir + ps)))
        if env == "PEA":
            lignes.append("  rien à payer tant que l'argent reste dans le PEA")
        lignes.append("")
    missing = sorted({v["ticker"] for v in pos.values() if not prix.get(v["ticker"])})
    if missing:
        lignes.append("Pas de cours pour %s : alerts.py quote %s EURUSD=X --write" % (", ".join(missing), " ".join(missing)))
    return "\n".join(lignes).rstrip()


def texte_bilan(b):
    l = ["Bilan %d, compte-titres (les ventes dans un PEA n'entrent pas ici)" % b["annee"],
         "  plus-values réalisées   %s" % euros(b["plus_values"]),
         "  moins-values réalisées  %s" % euros(-b["moins_values"]),
         "  solde de l'année        %s" % euros(b["solde"])]
    for y, m in b["imputees"]:
        l.append("  moins-value de %d imputée : %s" % (y, euros(-m)))
    if b["solde"] > 0:
        l.append("  plus-value nette imposable : %s   (déclaration 2042 C, case 3VG)" % euros(b["imposable"]))
        l.append("")
        l.append("  Flat tax (PFU %s) : %s d'impôt (%s) + %s de prélèvements sociaux (%s) = %s" % (
            pct(b["taux_ir"] + b["taux_ps"]), euros(b["pfu"]["impot"]), pct(b["taux_ir"]),
            euros(b["pfu"]["prelevements_sociaux"]), pct(b["taux_ps"]), euros(b["pfu"]["total"])))
        if b.get("bareme"):
            br = b["bareme"]
            mieux = "le barème" if br["total"] < b["pfu"]["total"] - 0.004 else "la flat tax"
            l.append("  Barème (tranche à %s) : %s d'impôt + %s de prélèvements sociaux = %s" % (
                pct(br["tmi"]), euros(br["impot"]), euros(br["prelevements_sociaux"]), euros(br["total"])))
            l.append("  Sur ces seuls chiffres, %s coûte moins. L'option pour le barème vaut pour TOUS tes revenus"
                     % mieux)
            l.append("  de capitaux de l'année (case 2OP), et rend une partie de la CSG déductible l'année suivante.")
        else:
            l.append("  Ajoute --tmi (0, 11, 30, 41, 45) pour comparer avec le barème.")
    elif b["solde"] < 0:
        l.append("  moins-value nette : %s, reportable jusqu'en %d   (2042 C, case 3VH)"
                 % (euros(b["nouvelle_moins_value"]), b["annee"] + REPORT_ANS))
        l.append("  rien à payer sur les plus-values cette année")
    else:
        l.append("  rien à déclarer en plus-values cette année")
    if b["report"]:
        l.append("")
        l.append("Moins-values encore reportables après %d :" % b["annee"])
        for y, m in sorted(b["report"].items()):
            l.append("  de %d : %s, utilisable jusqu'en %d" % (y, euros(m), y + REPORT_ANS))
    l.append("")
    l.append("Si ton courtier est en France, ton IFU (imprimé fiscal unique) reprend ces montants : il fait foi.")
    l.append("Pas un conseil fiscal ni financier.")
    return "\n".join(l)


# ---------------------------------------------------------------- commandes

def _ctx(a):
    cfg = lire(a.config, "config", requis=False) or {}
    pf = lire(a.portfolio, "portefeuille (trader/portfolio.json)", requis=False) or {"positions": []}
    pdoc = lire(a.prices, "cours", requis=False) or {}
    prices = pdoc.get("prices", pdoc) if isinstance(pdoc, dict) else {}
    etat = lire(a.etat, "état fiscal", requis=False) or etat_vide()
    return cfg, pf, prices, etat


def cmd_rapport(a):
    cfg, pf, prices, _ = _ctx(a)
    pos = positions(pf)
    if not pos:
        print("Aucune position dans %s." % a.portfolio)
        return 1
    print(texte_rapport(pos, prix_en_euros(prices, cfg), a.lignes, cfg))
    print("\nPas un conseil fiscal ni financier.")
    return 0


def cmd_vente(a):
    cfg, pf, prices, etat = _ctx(a)
    pos = positions(pf)
    env = (a.enveloppe or "").upper()
    t = a.ticker.upper()
    choix = [v for (tk, e), v in pos.items() if tk == t and (not env or e == env)]
    if not choix:
        raise FiscalErreur("pas de %s%s dans ton portefeuille" % (t, (" sur ton " + env) if env else ""))
    if len(choix) > 1:
        raise FiscalErreur("%s est sur ton CTO et ton PEA : précise --enveloppe" % t)
    p = choix[0]
    prix = a.prix / a.taux_change if a.taux_change else a.prix
    pv = plus_value(p, a.quantite, prix, a.frais)
    date = (a.date or datetime.date.today().isoformat())
    annee = int(date[:4])
    print("Vente de %s %s (%s) à %s%s, frais %s" % (
        _q(pv["quantite"]), t, p["enveloppe"], euros(prix),
        (" (%s $ à 1 € = %s $)" % (str(a.prix).replace(".", ","), str(a.taux_change).replace(".", ","))) if a.taux_change else "",
        euros(pv["frais"])))
    print("  prix de cession net   %s" % euros(pv["prix_cession"]))
    print("  prix d'acquisition    %s  (%s x PMP %s)" % (euros(pv["prix_acquisition"]), _q(pv["quantite"]), euros(pv["pmp"])))
    print("  %s %s" % ("plus-value          " if pv["plus_value"] >= 0 else "moins-value         ", euros(pv["plus_value"])))
    if p["enveloppe"] == "PEA":
        print("  Dans un PEA : rien à payer tant que l'argent reste dans le plan.")
    else:
        avant = bilan(etat, annee, a.tmi)
        apres_etat = {"ventes": etat.get("ventes", []) + [dict(pv, date=date)],
                      "moins_values_anterieures": etat.get("moins_values_anterieures", {})}
        apres = bilan(apres_etat, annee, a.tmi)
        delta = round(apres["pfu"]["total"] - avant["pfu"]["total"], 2)
        print("  effet sur ton bilan %d (flat tax %s) : %s%s" % (
            annee, pct(apres["taux_ir"] + apres["taux_ps"]),
            ("+" if delta > 0 else "") + euros(delta),
            "" if delta else " (aucun impôt en plus : moins-values ou solde négatif)"))
        if pv["plus_value"] < 0:
            print("  cette moins-value s'impute sur tes plus-values de l'année, sinon se reporte 10 ans")
    if a.enregistrer:
        etat.setdefault("ventes", []).append(dict(pv, date=date))
        ecrire(a.etat, etat)
        ecrire(a.portfolio, enregistrer_vente(pf, p, pv, date))
        print("Enregistré dans %s et %s." % (a.etat, a.portfolio))
    else:
        print("Simulation seulement. Une fois la vente exécutée : ajoute --enregistrer.")
    print("Pas un conseil fiscal ni financier.")
    return 0


def cmd_annee(a):
    _, _, _, etat = _ctx(a)
    annee = a.annee or datetime.date.today().year
    print(texte_bilan(bilan(etat, annee, a.tmi)))
    return 0


def cmd_moins_values(a):
    _, _, _, etat = _ctx(a)
    if a.ajouter:
        annee, montant = a.ajouter
        mv = etat.setdefault("moins_values_anterieures", {})
        mv[str(int(annee))] = round(float(mv.get(str(int(annee)), 0)) + float(montant), 2)
        ecrire(a.etat, etat)
        print("Ajouté : %s de moins-value de %d." % (euros(float(montant)), int(annee)))
    annee = datetime.date.today().year
    stock = bilan(etat, annee)["report"]
    if not stock:
        print("Aucune moins-value reportable.")
        return 0
    print("Moins-values reportables (après imputation sur %d) :" % annee)
    for y, m in sorted(stock.items()):
        print("  de %d : %s, à utiliser avant fin %d" % (y, euros(m), y + REPORT_ANS))
    return 0


def cmd_recolte(a):
    cfg, pf, prices, etat = _ctx(a)
    pos = positions(pf)
    px = prix_en_euros(prices, cfg)
    annee = datetime.date.today().year
    b = bilan(etat, annee)
    cands = []
    for (t, env), v in sorted(pos.items()):
        if env != "CTO" or not px.get(t):
            continue
        lat = v["parts"] * px[t] - v["cout"]
        if lat <= -abs(a.min_perte):
            cands.append((t, v, lat))
    print("Plus-value nette imposable déjà réalisée en %d : %s" % (annee, euros(b["imposable"])))
    if not cands:
        print("Aucune ligne du compte-titres avec une moins-value latente d'au moins %s." % euros(a.min_perte))
        return 1
    for t, v, lat in cands:
        print("  %-9s %s titres, moins-value latente %s" % (t, _q(v["parts"]), euros(lat)))
    if b["imposable"] <= 0:
        print("Tu n'as pas de plus-value imposable cette année : réaliser ces pertes ne réduit pas d'impôt "
              "maintenant (elles se reporteraient 10 ans).")
    else:
        eco = min(b["imposable"], -sum(l for _, _, l in cands)) * (b["taux_ir"] + b["taux_ps"]) / 100
        print("Les réaliser avant le 31 décembre réduirait ta flat tax %d d'environ %s." % (annee, euros(eco)))
    print("En France, pas de règle « wash sale » : racheter ensuite reste possible, mais un aller-retour "
          "fait uniquement pour l'impôt peut être contesté (abus de droit). Vérifie avec un professionnel.")
    if a.ecrire:
        orders = [{"symbol": t, "side": "sell", "qty": _q(v["parts"]).replace(",", "."), "type": "market",
                   "time_in_force": "day", "enveloppe": "CTO",
                   "why": "réaliser une moins-value latente de %s" % euros(lat)} for t, v, lat in cands]
        ecrire(a.orders, {"created_by": "trader-tax", "status": "proposed",
                          "created_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
                          "note": "Propositions seulement. trader-risk vérifie, puis tu dis oui ordre par ordre.",
                          "orders": orders})
        print("Propositions de vente écrites dans %s." % a.orders)
    print("Pas un conseil fiscal ni financier.")
    return 0


def cmd_pea(a):
    cfg, pf, prices, _ = _ctx(a)
    ouverture = a.ouverture or cfg.get("pea_ouverture")
    versements = a.versements if a.versements is not None else cfg.get("pea_versements")
    if not ouverture or versements is None:
        raise FiscalErreur("donne --ouverture AAAA-MM-JJ et --versements (total versé), ou mets "
                           "\"pea_ouverture\" et \"pea_versements\" dans trader/config.json")
    valeur = a.valeur
    if valeur is None:
        px = prix_en_euros(prices, cfg)
        pos = [v for (t, e), v in positions(pf).items() if e == "PEA"]
        manque = [v["ticker"] for v in pos if not px.get(v["ticker"])]
        if manque:
            raise FiscalErreur("pas de cours pour %s : donne --valeur" % ", ".join(manque))
        valeur = sum(v["parts"] * px[v["ticker"]] for v in pos) + float(cfg.get("pea_liquidites", 0))
    plafond = PLAFOND_PEA_JEUNE if cfg.get("pea_jeune") else PLAFOND_PEA
    print("PEA ouvert le %s, %s versés (plafond %s), valeur %s" % (
        ouverture, euros(versements), euros(plafond), euros(valeur)))
    if float(versements) > plafond:
        print("  ATTENTION : les versements dépassent le plafond")
    if a.retrait:
        r = retrait_pea(valeur, versements, a.retrait, ouverture)
        print("Retrait de %s le %s :" % (euros(r["retrait"]), datetime.date.today().isoformat()))
        print("  part de gain dans le retrait  %s" % euros(r["part_gain"]))
        if r["avant_5_ans"]:
            print("  AVANT 5 ANS (le %s) : impôt %s + prélèvements sociaux %s = %s" % (
                r["cinq_ans"], euros(r["impot"]), euros(r["prelevements_sociaux"]), euros(r["total"])))
            print("  et en principe le PEA est clôturé (sauf exceptions : licenciement, invalidité, création d'entreprise...)")
        else:
            print("  après 5 ans : pas d'impôt sur le revenu, prélèvements sociaux %s" % euros(r["prelevements_sociaux"]))
        print("  tu récupères environ %s" % euros(r["net"]))
    print("Pas un conseil fiscal ni financier.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fiscalité française de ton portefeuille (trader-tax). Pas un conseil fiscal.")
    sub = ap.add_subparsers(dest="cmd")

    def commun(p):
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--prices", default="trader/prices.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--etat", default="trader/state/fiscalite.json")

    p = sub.add_parser("rapport", help="PMP et plus-values latentes par enveloppe")
    commun(p)
    p.add_argument("--lignes", action="store_true", help="détail des achats")
    p = sub.add_parser("vente", help="ce qu'une vente réaliserait (et --enregistrer quand elle est faite)")
    commun(p)
    p.add_argument("ticker")
    p.add_argument("quantite", type=float)
    p.add_argument("--prix", type=float, required=True, help="prix unitaire (en dollars si --taux-change)")
    p.add_argument("--frais", type=float, default=0.0, help="frais de vente en euros")
    p.add_argument("--taux-change", type=float, help="1 € = x $ le jour de la vente")
    p.add_argument("--enveloppe", choices=["CTO", "PEA", "cto", "pea"])
    p.add_argument("--date")
    p.add_argument("--tmi", type=float)
    p.add_argument("--enregistrer", action="store_true")
    p = sub.add_parser("annee", help="bilan fiscal d'une année")
    commun(p)
    p.add_argument("annee", type=int, nargs="?")
    p.add_argument("--tmi", type=float, help="ta tranche marginale d'imposition, en %%")
    p = sub.add_parser("moins-values", help="moins-values reportables")
    commun(p)
    p.add_argument("--ajouter", nargs=2, metavar=("ANNEE", "MONTANT"),
                   help="une moins-value nette d'une année passée (ta déclaration 2042 C)")
    p = sub.add_parser("recolte", help="moins-values latentes à réaliser")
    commun(p)
    p.add_argument("--min-perte", type=float, default=100.0)
    p.add_argument("--ecrire", action="store_true", help="écrire les ventes dans trader/orders.json")
    p.add_argument("--orders", default="trader/orders.json")
    p = sub.add_parser("pea", help="coût d'un retrait du PEA")
    commun(p)
    p.add_argument("--ouverture")
    p.add_argument("--versements", type=float)
    p.add_argument("--valeur", type=float)
    p.add_argument("--retrait", type=float)
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"rapport": cmd_rapport, "vente": cmd_vente, "annee": cmd_annee,
                "moins-values": cmd_moins_values, "recolte": cmd_recolte, "pea": cmd_pea}[a.cmd](a)
    except FiscalErreur as e:
        print("lots.py : %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
