---
name: trader-dirigeants
description: >-
  Le suivi des dirigeants, version française du suivi des initiés. Les
  dirigeants des sociétés cotées et leurs proches doivent déclarer à l'AMF
  leurs achats et ventes de titres de leur société dans les 3 jours ouvrés
  (règlement MAR, article 19) ; l'AMF les publie dans sa base BDIF. Ce skill
  trouve ces déclarations, les lit, les garde sans doublon, et en tire des
  signaux : achats et ventes par société, montant net, et « achats groupés »
  quand plusieurs dirigeants achètent en même temps. Il signale celles qui
  touchent les titres de l'utilisateur. Bien plus frais qu'un 13F (45 jours).
  À utiliser quand l'utilisateur dit « que font les dirigeants de Orange »,
  « achats des dirigeants », « déclarations AMF », « initiés français »,
  « insiders », « qui achète ses propres actions », « surveille les
  dirigeants de mes actions », ou cherche un équivalent français de
  /trader-pelosi ou du Form 4.
argument-hint: "[société ou ISIN]"
---

# trader-dirigeants

Les déclarations des dirigeants sont publiques : c'est l'information la plus
fraîche qu'on ait sur ce que font les gens qui connaissent le mieux une
société française. Ce skill les rassemble et les résume. Il ne dit jamais
d'acheter ou de vendre.

`${CLAUDE_SKILL_DIR}` ci-dessous est le dossier de ce skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" recherche FR0000133308    # la requête web à lancer
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" ajouter --reference 2026DD1141604 --societe Orange \
    --isin FR0000133308 --declarant "membre du comité exécutif" --nature acquisition \
    --date 2026-10-01 --prix 13.6941 --volume 10000
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" importer trader/lot.json   # plusieurs d'un coup
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" amf --jours 30              # directement depuis l'AMF
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" liste --jours 30
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" signaux --jours 30
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" portefeuille               # sur tes titres
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" nouveaux                   # une seule fois chacune
```

## Étape 1 : trouver les déclarations

**Si le poste de travail peut joindre `bdif.amf-france.org`** (domaine autorisé
dans les réglages de Claude), une seule commande suffit : elle interroge la base
de l'AMF, télécharge les PDF et les lit (pdftotext requis) :

```bash
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" amf --jours 30                       # toutes les sociétés
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" amf --jours 90 --societe "TF1"       # une société
python3 "${CLAUDE_SKILL_DIR}/dirigeants.py" extraire chemin/vers/declaration.pdf
```

Les déclarations illisibles (champ mal rempli par le déclarant) sont listées :
relève-les à la main. **Sinon**, passe par tes outils web :

1. `dirigeants.py recherche ISIN` donne la requête. Lance-la avec WebSearch
   (par exemple `site:bdif.amf-france.org "FR0000133308"`). Les titres des
   résultats ressemblent à « 2026DD1141604 FR0000133308 - DD194172 01 octobre
   2026 » : la référence, l'ISIN, la date de publication.
2. Ouvre chaque PDF avec WebFetch et relève : la référence (2026DD...), la
   société, l'ISIN, le déclarant et sa fonction, la nature (acquisition,
   cession, souscription, exercice d'options...), la date de la transaction,
   le prix unitaire, le volume, et si elle est liée à un plan d'options ou
   d'actions gratuites. Une déclaration peut contenir plusieurs transactions :
   une ligne par transaction, avec un suffixe à la référence (-1, -2).
3. Enregistre-les avec `ajouter` ou, pour plusieurs, écris un JSON
   (`{"declarations": [{...}]}`) et lance `importer`. Les doublons (même
   référence) sont ignorés.

Ne recopie jamais un chiffre que tu n'as pas lu dans la déclaration. Si un
champ manque ou est illisible, dis-le et laisse la déclaration de côté.

## Étape 2 : résumer

- `signaux --jours 30` : par société, achats, ventes et net, hors plans
  d'options et d'actions gratuites (ce sont des rémunérations, pas des choix
  d'investissement). « ACHATS GROUPÉS » quand au moins deux dirigeants
  différents ont acheté sur la période.
- `portefeuille` : les déclarations sur les titres de l'utilisateur (par
  ISIN, dans `trader/portfolio.json`, `trader/targets.json` ou ses ordres).
- `nouveaux` : sur un rendez-vous régulier, ne montre que ce qui n'a jamais
  été montré.

Donne toujours, pour chaque ligne : la date, la fonction du déclarant, le
sens, le montant, et la référence AMF pour que l'utilisateur puisse vérifier.

## Ce qu'il faut dire

- Une vente de dirigeant a souvent une raison personnelle (impôts, achat
  immobilier, diversification). Un achat est un geste plus rare. Aucun des
  deux ne prédit le cours.
- Les déclarations arrivent jusqu'à 3 jours ouvrés après la transaction ;
  le cours a pu bouger depuis.
- Ce sont des données publiques, pas de l'information privilégiée.

## Ce qu'il ne fait jamais

Il ne passe aucun ordre et ne crée aucune proposition d'ordre : pour agir,
l'utilisateur passe par `/trader-budget`, `/trader-risk` puis `/trader-broker`.

## Sécurité

- Pas un conseil financier. Not financial advice.
- Rien ne part chez un courtier sans un « oui » (yes) explicite de l'utilisateur pour chaque ordre.
