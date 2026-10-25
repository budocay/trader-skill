---
name: trader-tax
description: >-
  Fiscalité française. Calcule le prix moyen pondéré (PMP) de chaque ligne,
  frais d'achat compris, sépare compte-titres (CTO) et PEA, dit ce qu'une
  vente réaliserait comme plus- ou moins-value et ce qu'elle coûterait en flat
  tax (31,4 % depuis 2026), fait le bilan de l'année avec l'imputation des
  moins-values reportables sur 10 ans, compare flat tax et barème selon ta
  tranche, simule un retrait du PEA avant ou après 5 ans, et repère les
  moins-values latentes à réaliser. Pas un conseil fiscal. À utiliser quand
  l'utilisateur dit « mes plus-values », « combien d'impôt si je vends »,
  « flat tax », « PFU », « barème », « PMP », « prix de revient »,
  « moins-values », « déclaration 2074 / 2042 C », « IFU », « PEA »,
  « retrait du PEA », « tax-loss harvesting », ou avant toute vente.
argument-hint: "[ticker]"
---

# trader-tax (France)

Fait l'arithmétique fiscale sur les positions de l'utilisateur pour qu'il ne
vende jamais à l'aveugle. Ne décide jamais à sa place. **Ce n'est pas un
conseil fiscal** : dis-le une fois, tôt, dans chaque réponse qui utilise ce
skill. Si son courtier est en France, son IFU fait foi.

`${CLAUDE_SKILL_DIR}` ci-dessous est le dossier de ce skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/lots.py" rapport                      # PMP et +/- latentes, CTO et PEA
python3 "${CLAUDE_SKILL_DIR}/lots.py" rapport --lignes             # avec chaque achat
python3 "${CLAUDE_SKILL_DIR}/lots.py" vente ORA.PA 10 --prix 14.20 --frais 1.99
python3 "${CLAUDE_SKILL_DIR}/lots.py" vente AAPL 1 --prix 270 --taux-change 1.08 --enregistrer
python3 "${CLAUDE_SKILL_DIR}/lots.py" annee 2026 --tmi 11          # bilan, flat tax ou barème
python3 "${CLAUDE_SKILL_DIR}/lots.py" moins-values                 # stock reportable, expirations
python3 "${CLAUDE_SKILL_DIR}/lots.py" moins-values --ajouter 2024 350
python3 "${CLAUDE_SKILL_DIR}/lots.py" recolte --min-perte 100      # moins-values latentes du CTO
python3 "${CLAUDE_SKILL_DIR}/lots.py" pea --retrait 2000           # coût d'un retrait du PEA
```

## Ce qu'il lit et écrit

| fichier | contenu |
| --- | --- |
| `trader/portfolio.json` | les positions, par titre et par enveloppe, avec leurs achats (`cost` en euros, frais compris). trader-broker l'écrit (`ticket.py fill`) ; `portfolio.example.json` ici montre le format |
| `trader/prices.json` | les cours (trader-alerts). Ajoute `EURUSD=X` pour convertir les actions américaines |
| `trader/config.json` | `pea_ouverture`, `pea_versements`, `pea_jeune` (plafond 20 000 €), `pea_liquidites` |
| `trader/state/fiscalite.json` | les ventes enregistrées et les moins-values des années passées |
| `trader/orders.json` | `recolte --ecrire` y met des propositions de vente |

## Les règles appliquées

- **Prix moyen pondéré** (art. 150-0 D, 3 du CGI) : le prix d'acquisition d'une
  vente est la moyenne pondérée de tous les titres identiques du même compte,
  frais d'achat compris. Les frais de vente viennent en déduction. Une vente
  ne change pas le PMP de ce qui reste. Pas de FIFO, pas de choix des lots.
- **Pas de court ou long terme** au PFU, et **pas de règle « wash sale »**.
- **Flat tax (PFU)** : 12,8 % d'impôt + 18,6 % de prélèvements sociaux =
  **31,4 %** pour les gains réalisés depuis le 1er janvier 2026 (30 % avant).
  Option globale possible pour le barème (case 2OP) : elle vaut pour tous les
  revenus de capitaux de l'année. `--tmi` compare les deux.
- **Moins-values** : imputées sur les plus-values de l'année, puis reportables
  sur les 10 années suivantes, les plus anciennes d'abord.
- **PEA** : rien à payer tant que l'argent reste dedans. Retrait avant 5 ans :
  31,4 % sur la part de gain du retrait et, en principe, clôture du plan.
  Après 5 ans : 18,6 % de prélèvements sociaux seulement. Plafond de
  versements : 150 000 € (PEA Jeune : 20 000 €).
- Les montants vont dans la **déclaration 2042 C** : plus-value nette en case
  3VG, moins-value nette en case 3VH. Le formulaire 2074 détaille le calcul
  quand l'IFU ne suffit pas.

## Étapes

1. Lance `rapport` et montre le tableau : par enveloppe, quantité, PMP,
   cours, valeur, plus- ou moins-value latente.
2. Avant toute vente, lance `vente TICKER QUANTITÉ --prix P --frais F` (avec
   `--taux-change` pour un prix en dollars) et montre : la plus-value au PMP
   et l'effet sur la flat tax de l'année. Pour un ordre de trader-rebalance,
   fais-le pour chaque vente.
3. Une vente **exécutée** s'enregistre avec `--enregistrer`, au prix réel et
   aux frais réels de l'avis d'opéré. Jamais une simulation.
4. Pour le bilan : `annee` (avec `--tmi` si l'utilisateur donne sa tranche).
   Les moins-values des années avant ce suivi s'ajoutent une fois avec
   `moins-values --ajouter ANNÉE MONTANT` (sa déclaration de l'an dernier les
   donne).
5. `recolte` en fin d'année : montre les moins-values latentes du CTO et
   l'économie possible. Pas de règle « wash sale » en France, mais un
   aller-retour fait uniquement pour l'impôt peut être contesté (abus de
   droit) : dis-le. `--ecrire` met les ventes dans `trader/orders.json`
   comme propositions, que trader-risk puis trader-broker traitent.

## Ce qu'il ne fait jamais

Il ne passe aucun ordre, ne déclare rien, ne choisit pas entre flat tax et
barème à la place de l'utilisateur, et ne couvre pas : les titres achetés
avant 2018 et leurs abattements pour durée de détention, l'assurance-vie, les
dividendes, le PEA-PME, les situations de non-résident.

## Sécurité

- Pas un conseil fiscal ni financier. Ce sont des calculs sur les chiffres de l'utilisateur ;
  un professionnel ou son IFU fait foi.
- Les ventes qu'il propose passent par trader-risk, puis trader-broker demande un « oui »
  explicite pour chaque ordre. Rien ne part sans ce oui.
- Paper trading (simulation) par défaut : `"paper": true` dans la config.
- Not financial advice: the same rule in English, for the other skills of this pack.
