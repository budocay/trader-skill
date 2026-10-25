---
name: trader-frais
description: >-
  Frais et garde-fous français. Calcule ce qu'un ordre coûte vraiment chez
  BoursoBank ou Fortuneo avant de le passer : courtage selon la formule,
  taxe sur les transactions financières (0,4 % sur 121 grandes sociétés
  françaises), frais de change sur une action américaine, plafond de 0,5 %
  sur PEA, minimum d'ordre du courtier, et la hausse nécessaire pour rentrer
  dans ses frais. Dit si un titre a sa place dans un PEA et si un ETF
  américain est achetable (PRIIPs). Compare toutes les formules pour un
  montant. trader-budget, trader-risk, trader-broker et trader-tax s'en
  servent. À utiliser quand l'utilisateur dit « combien ça coûte », « frais
  de courtage », « quel courtier », « quelle formule », « TTF »,
  « éligible PEA », « je peux acheter cet ETF ? », « ça vaut le coup avec
  10 € ? », ou avant de régler son courtier dans la config.
argument-hint: "[ticker] [montant]"
---

# trader-frais

Avec de petits montants, les frais décident de tout : un ordre de 10 € à
1,99 € de courtage part avec 20 % de perte. Ce skill met un chiffre sur
chaque ordre avant qu'il parte, et les autres skills refusent ceux dont les
frais dépassent la limite de l'utilisateur.

`${CLAUDE_SKILL_DIR}` ci-dessous est le dossier de ce skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/frais.py" comparer 10                    # toutes les formules, 10 € à Paris
python3 "${CLAUDE_SKILL_DIR}/frais.py" comparer 300 --marche us
python3 "${CLAUDE_SKILL_DIR}/frais.py" ordre MC.PA 500 --isin FR0000121014
python3 "${CLAUDE_SKILL_DIR}/frais.py" ordre AAPL 200 --courtier fortuneo --formule progress --eurusd 1.08
python3 "${CLAUDE_SKILL_DIR}/frais.py" ttf FR0000120271                # soumise à la TTF ?
python3 "${CLAUDE_SKILL_DIR}/frais.py" pea NL00150001Q9                # éligible au PEA ?
python3 "${CLAUDE_SKILL_DIR}/frais.py" isin FR0000121014               # clé de contrôle
```

## Fichiers

| fichier | contenu |
| --- | --- |
| `grilles.json` | les grilles BoursoBank (brochure du 05/10/2026) et Fortuneo (relevées entre juin et octobre 2026), avec leur source |
| `ttf.json` | les 121 sociétés soumises à la TTF en 2026 (liste du 1er décembre 2025), par ISIN |
| `trader/config.json` | `courtier`, `formule`, `enveloppe`, `max_frais_pct`, `devise`, `eurusd` |

## Étape 1 : régler le courtier une fois

Si `trader/config.json` n'a pas de `courtier`, copie `config.example.json` de
trader-budget et demande à l'utilisateur, en mots simples :

- **courtier** : `boursobank` ou `fortuneo` (les deux seuls dont les grilles sont ici).
- **formule** : BoursoBank `decouverte`, `classic`, `trader`, `ultimate_trader` ;
  Fortuneo `starter`, `progress`, `trader_pro`. S'il ne sait pas, lance
  `comparer` avec le montant typique de ses ordres et montre le résultat.
- **enveloppe** : `CTO` (compte-titres) ou `PEA`.
- **max_frais_pct** : au-delà, un ordre est refusé (2 % par défaut).
- **devise** : `EUR`, pour que tous les montants soient en euros.

## Étape 2 : chiffrer

`ordre TICKER MONTANT` montre courtage, TTF, change, total, le coût d'un
aller-retour et la hausse nécessaire pour rentrer dans ses frais. Donne
toujours l'ISIN d'une action de Paris : sans lui, la TTF ne peut pas être
vérifiée. Cherche-le si l'utilisateur ne l'a pas.

## Ce qu'il faut savoir et dire

- **BoursoBank** : minimum 20 € par ordre sur compte-titres, 100 € sur PEA
  (2 500 € pour les autres bourses européennes en PEA). Découverte n'existe
  que sur compte-titres. Actions américaines : 6,95 € jusqu'à 6 000 €.
- **Fortuneo Starter** : le premier ordre d'achat du mois jusqu'à 500 € est
  gratuit, puis 0,35 % sans minimum. C'est la seule formule ici où un ordre
  de quelques euros garde des frais raisonnables. Son tarif sur les actions
  américaines diffère selon les sources : à vérifier sur fortuneo.fr.
- **Aucun des deux n'achète de fractions d'action** : il faut acheter au
  moins une action entière, donc avoir au moins son prix.
- **TTF** : 0,4 % de chaque achat d'une des 121 sociétés de `ttf.json`, PEA
  compris. Elle ne s'applique pas à la vente.
- **PEA** : actions de sociétés de l'UE ou de l'EEE seulement (pas
  d'américaines, pas de britanniques depuis le Brexit), et ETF qui détiennent
  au moins 75 % d'actions européennes. Courtage plafonné à 0,5 %.
- **ETF américains** (VOO, QQQ, SPY, NANC...) : en général impossibles à
  acheter pour un particulier en France, faute de document d'informations
  clés (PRIIPs). Propose un ETF UCITS qui suit le même indice.
- **Compte à l'étranger** (Alpaca, Interactive Brokers Ireland, ou tout
  courtier dont le compte n'est pas tenu en France) : à déclarer chaque
  année sur le formulaire 3916-bis, même vide, sous peine de 1 500 €
  d'amende par compte et par an.

## Ce qu'il ne fait jamais

Il ne passe aucun ordre et ne recommande pas de courtier : il compare des
grilles publiques, qui changent. Dis la date des grilles et invite à
vérifier sur le site du courtier avant un vrai ordre.

## Sécurité

- Pas un conseil financier : des calculs sur des grilles publiques.
- Not financial advice. Nothing in this pack places an order without the user's explicit yes
  ("oui") for that one order, after trader-risk passed it.
