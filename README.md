# Trader skill, version française

13 skills Claude pour investir depuis la France : les vrais frais de BoursoBank et Fortuneo, la fiscalité française, le PEA, les dirigeants qui achètent, et jamais un ordre sans ton oui.

Adaptation française du [Trader skill de Jake Schincariol](https://github.com/Jakeschincariol/trader-skill)
(MIT). Les 11 skills d'origine sont là, plus deux nouveaux, et ceux qui
touchent à l'argent suivent les règles françaises dès que ta config le dit.

## Installer

Dans Claude Code :

```
/plugin marketplace add budocay/trader-skill
/plugin install trader-skill-fr@trader-skill-fr
```

Les skills s'appellent alors `/trader-skill-fr:trader-frais` et ainsi de suite.
Pour des noms courts (`/trader-frais`), copie les dossiers :

```bash
git clone https://github.com/budocay/trader-skill.git
cp -r trader-skill/trader-* ~/.claude/skills/
```

Copie toujours `trader-frais` avec les autres : budget, risque, ordres, fiscalité
et rééquilibrage s'en servent.

Python 3.8 ou plus récent, rien à installer. Puis copie
`trader-budget/config.fr.example.json` dans `trader/config.json` et règle ton
courtier (`/trader-frais` t'aide à choisir la formule).

## Ce qui change pour la France

| sujet | version d'origine (États-Unis) | version française |
| --- | --- | --- |
| prix de revient | lots FIFO, court ou long terme | **prix moyen pondéré** (art. 150-0 D du CGI), frais d'achat compris |
| impôt | règles fédérales américaines, « wash sale » | **flat tax 31,4 %** depuis 2026 (12,8 + 18,6), option barème, moins-values reportables 10 ans, cases 3VG / 3VH |
| enveloppes | aucune | **CTO et PEA** : éligibilité, plafond de courtage 0,5 %, retrait avant ou après 5 ans |
| frais | aucun (Alpaca sans commission) | **BoursoBank et Fortuneo** formule par formule, **TTF 0,4 %** sur 121 sociétés, frais de change |
| courtier | Alpaca ou IBKR, passe l'ordre après ton oui | BoursoBank et Fortuneo n'ont pas de connecteur : **le ticket te dit quoi saisir**, Claude ne passe rien |
| actions entières | fractions d'action | ces deux courtiers n'achètent **que des actions entières** |
| ETF | tous | **ETF américains bloqués** (PRIIPs : pas de document d'informations clés) |
| compte à l'étranger | | rappel du **formulaire 3916-bis** (1 500 € d'amende par compte et par an) |
| initiés | Form 4, Congrès | **déclarations des dirigeants à l'AMF**, publiées sous 3 jours ouvrés |
| horloge | NYSE | **Euronext Paris** en plus, heure de Paris |
| devise | dollars | **euros**, cours américains convertis avec EURUSD |

## Les treize

| commande | rôle | ce qu'elle fait |
| --- | --- | --- |
| `/trader-frais` | Frais et garde-fous | Nouveau. Ce qu'un ordre coûte vraiment chez BoursoBank ou Fortuneo (courtage, TTF, change, plafond PEA, minimum), la hausse nécessaire pour rentrer dans ses frais, l'éligibilité PEA, les ETF interdits. |
| `/trader-dirigeants` | Suivi des dirigeants | Nouveau. Les achats et ventes déclarés à l'AMF par les dirigeants des sociétés cotées, sans doublon, avec les « achats groupés » et ce qui touche tes titres. |
| `/trader-tax` | Fiscalité française | Réécrit. PMP, plus-values latentes par enveloppe, coût d'une vente en flat tax, bilan annuel, barème, moins-values reportables, retrait du PEA. |
| `/trader-budget` | Budget | Répartit ton budget en actions entières, en euros, en écartant ce qui coûte trop en frais ou passe sous le minimum du courtier. |
| `/trader-risk` | Contrôle de risque | Bloque ce qui dépasse tes limites, plus : titre non éligible au PEA, ETF américain, ordre en montant chez un courtier sans fractions, frais trop lourds. |
| `/trader-broker` | Tickets d'ordre | Un ticket en français par ordre, ton « oui » mot pour mot, puis tu saisis l'ordre toi-même (ou rien, en simulation). Enregistre l'exécution au PMP. |
| `/trader-alerts` | Alertes de cours | Seuils, stops, variations ; horloge NYSE et Euronext Paris ; cours des actions françaises (`MC.PA`) et du taux EURUSD. |
| `/trader-rebalance` | Rééquilibrage | Ramène le portefeuille à ses poids cibles, en euros. |
| `/trader-copycat` | Copie d'un investisseur | Reconstitue le portefeuille d'un fonds américain depuis son 13F (SEC). |
| `/trader-news` | Actualité | Titres Yahoo et 8-K de la SEC sur tes actions (sociétés américaines). |
| `/trader-pelosi` | Congrès américain | Les transactions déclarées par les élus de la Chambre des représentants. |
| `/trader-analyst` | Résultats | Chiffres publiés à la SEC (sociétés américaines). |
| `/trader-screener` | Filtre | Classe des sociétés selon tes propres règles. |

Les cinq derniers lisent des sources américaines (SEC, Chambre des
représentants) et parlent anglais : ils marchent comme dans la version
d'origine.

## Comment ça s'enchaîne

```
trader-frais (régler son courtier une fois)
copycat ou dirigeants -> budget -> risk -> broker -> tax
alerts / news / dirigeants                    (à surveiller, sur rendez-vous)
rebalance / tax -> risk -> broker             (entretien)
```

Tout est écrit dans un dossier `trader/` de ton projet, et chaque skill lit
ce que le précédent a écrit.

## Exemple honnête : 10 €, puis 300 €

**Avec 10 € sur un PEA chez Fortuneo Starter**, `/trader-budget` n'achète
rien : une action Orange coûte 13,69 € et une TotalEnergies 56 €, et ces
courtiers n'achètent pas de fraction d'action. Il le dit, action par action.

`frais.py comparer 10` montre aussi pourquoi les petits ordres coûtent cher :
1,99 € chez BoursoBank Découverte (20 % de l'ordre, et sous son minimum de
20 €), 4,90 € chez Fortuneo Progress, 0,04 € chez Fortuneo Starter (0,35 %,
et le premier ordre du mois jusqu'à 500 € est gratuit).

**Avec 300 € sur un CTO chez BoursoBank Découverte**, cible Orange 40 %,
TotalEnergies 30 %, Apple 30 % :

| | |
| --- | --- |
| Orange | 21 actions, 287,49 €, frais 3,14 € (1,99 € de courtage + 1,15 € de TTF) |
| Apple | écartée : une action vaut 231,48 € (250 $ à 1,08), plus que sa part |
| TotalEnergies | écartée : 2 actions coûteraient 2,44 € de frais, 2,18 % de l'ordre, au-dessus du plafond de 2 % |

`/trader-risk` vérifie, `/trader-broker` affiche « ACHAT de 21 actions
ORA.PA, ordre au marché », tu réponds « oui », tu le saisis dans l'appli (ou
rien, en simulation), et `/trader-tax` suit ton prix moyen pondéré.

## Les outils

```bash
python3 trader-frais/frais.py comparer 10                         # toutes les formules pour 10 €
python3 trader-frais/frais.py ordre MC.PA 500 --isin FR0000121014  # frais d'un ordre
python3 trader-frais/frais.py pea NL00150001Q9                     # éligible au PEA ?
python3 trader-budget/size.py --write                              # -> trader/orders.json
python3 trader-risk/check.py                                       # PASS / BLOCK par ordre
python3 trader-broker/ticket.py show                               # les tickets
python3 trader-tax/lots.py rapport                                 # PMP et plus-values latentes
python3 trader-tax/lots.py annee 2026 --tmi 11                     # flat tax ou barème
python3 trader-tax/lots.py pea --retrait 2000                      # coût d'un retrait du PEA
python3 trader-dirigeants/dirigeants.py signaux --jours 30         # achats des dirigeants
python3 trader-alerts/alerts.py clock --place paris                # Euronext ouvert ?
python3 trader-alerts/alerts.py quote ORA.PA AAPL EURUSD=X --write # cours
python3 trader-copycat/edgar13f.py find buffett                    # un fonds américain
```

```bash
python3 -m unittest discover -s tests -v
```

Les tests tournent hors ligne.

## Les petits caractères

**Pas un conseil financier ni fiscal.** Ce sont des calculs sur des données
publiques et sur tes propres chiffres. Ils ne connaissent pas ta situation et
ne prédisent rien. Tu peux perdre de l'argent. Ton IFU, ton courtier ou un
professionnel font foi.

**Aucun ordre sans ton oui.** Seul `/trader-broker` mène à un ordre, après que
`/trader-risk` l'a validé et que tu as répondu « oui » pour cet ordre précis.
Avec BoursoBank ou Fortuneo, c'est toi qui le saisis.

**Simulation d'abord.** `"paper": true` est la valeur par défaut : rien n'est
saisi chez le courtier, les ordres sont enregistrés comme s'ils étaient passés.

**Les grilles de frais changent.** BoursoBank : brochure applicable au
5 octobre 2026. Fortuneo : grilles relevées entre juin et octobre 2026 ; le
tarif Starter sur les actions américaines diffère selon les sources. La liste
TTF est celle de 2026 et change chaque 1er janvier. Vérifie avant un vrai ordre.

**Ce que la fiscalité ne couvre pas.** Titres achetés avant 2018 et leurs
abattements, dividendes, assurance-vie, PEA-PME, non-résidents.

**Compte à l'étranger.** Un compte réel chez Alpaca ou Interactive Brokers
(Irlande) se déclare chaque année sur le formulaire 3916-bis, même vide.

**Les données publiques.** SEC EDGAR, Chambre des représentants, AMF (BDIF),
Yahoo Finance (non officiel, différé). Un 13F a au moins 45 jours de retard ;
une déclaration de dirigeant, jusqu'à 3 jours ouvrés. Ce ne sont jamais des
informations privilégiées.

MIT. Version d'origine par [Jake Schincariol](https://github.com/Jakeschincariol/trader-skill),
adaptation française par budocay.
