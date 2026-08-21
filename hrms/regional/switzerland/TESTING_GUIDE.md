# Guide de Test — Module de Paie Suisse HRMS

> **Instance de test** : https://osiris.neoffice.me
> **Société** : AlpInnovate Sàrl (abbr: `pri`)
> **Employés test** : Jean Claude, Helie Copter

---

> **Ajout 21.08.2026** — deux pages desk pilotent désormais le cycle :
> - `/app/swiss-payroll-cycle` : cycle mensuel (préflight → génération → récap → soumission)
> - `/app/swiss-year-end` : clôture annuelle (concordance → certificats en lot → décompte IS par canton)
> Le moteur IS est validé contre l'oracle Swissdec annexe 1 (70 cas au centime, test_annexe1_oracle).

---

## Vue d'ensemble

Le module suisse couvre l'intégralité de la paie suisse pour une PME :

| Fonctionnalité | Description |
|---|---|
| **Assurances sociales** | AVS/AI/APG, AC/ALV (plafond), LPP/BVG (taux par âge), LAA, IJM, allocations familiales |
| **13ème salaire** | Mode annuel (versé en décembre) ou mensuel (1/12 chaque mois) |
| **Impôt à la source** | 26 cantons, modèle mensuel (21 cantons) + annuel (FR/GE/TI/VD/VS), barèmes ESTV |
| **Travailleurs frontaliers** | DE (flat 4.5%), FR (exempté sauf GE), IT (ancien/nouveau régime) |
| **Certificat de salaire** | Lohnausweis Form 11, 15 positions, code-barres eCH-0270 |
| **Swissdec ELM 5.0** | Export XML, déclarations annuelles/mensuelles/correctives, transmission |
| **Notifications EMA** | Entrée/Mutation/Sortie employé, notification aux institutions |

**11 DocTypes** créés, **14 composants salariaux**, **~350 tests unitaires**.

---

## 0. Prérequis — Configuration initiale

Avant de tester, ces éléments doivent être configurés :

### 0.1 Société

| Lien | Description |
|---|---|
| [AlpInnovate Sàrl](https://osiris.neoffice.me/app/company/AlpInnovate%20S%C3%A0rl) | Section "Swiss Payroll Settings" |

**À configurer :**
- [ ] `UID-BFS` : numéro d'identification (CHE-XXX.XXX.XXX)
- [ ] `Contact Swissdec` : nom, téléphone, email
- [ ] `Default Social Insurance Config` : lien vers la config

### 0.2 Configuration assurance sociale

| Lien | Description |
|---|---|
| [Liste des configs](https://osiris.neoffice.me/app/swiss-social-insurance-config) | Créer une config par société |
| [Nouvelle config](https://osiris.neoffice.me/app/swiss-social-insurance-config/new) | Formulaire de création |

**À configurer :**
- [ ] Société : AlpInnovate Sàrl
- [ ] Canton : ex. VD, GE, FR...
- [ ] Cocher "Is Default"
- [ ] **Onglet AVS/AI/APG** : taux 5.3% employé + employeur
- [ ] **Onglet AC/ALV** : taux 1.1%, plafond 148'200 (aucune cotisation au-delà — solidarité supprimée au 1.1.2023)
- [ ] **Onglet LAA** : taux professionnel (employeur) + non-professionnel (employé)
- [ ] **Onglet LPP/BVG** : déduction de coordination, seuil d'entrée, part employeur ≥50%
- [ ] **Onglet IJM/KTG** : taux selon assureur
- [ ] **Onglet Allocations familiales** : taux cantonal
- [ ] **Onglet 13ème** : mode (Disabled/Annual/Monthly)
- [ ] **Onglet Lohnausweis** : mapping des composants vers les positions Form 11

### 0.3 Types de salaire suisses

| Lien | Description |
|---|---|
| [Swiss Wage Type](https://osiris.neoffice.me/app/swiss-wage-type) | ~170 types standards (codes Swissdec) |

**Vérifier :**
- [ ] Les types sont importés (1000=Salaire de base, 1181=13ème, 5010=AVS, etc.)

### 0.4 Composants salariaux

| Lien | Description |
|---|---|
| [Salary Component](https://osiris.neoffice.me/app/salary-component) | 14 composants suisses |
| [Composants avec Wage Type](https://osiris.neoffice.me/app/salary-component?ch_wage_type=%5B%22is%22%2C%22set%22%5D) | Filtre sur les composants liés à un type suisse |

**Composants attendus :**
- [ ] Basic, 13th Month Salary (revenus)
- [ ] AVS/AI/APG Employee, AC/ALV Employee, LAA Employee, LPP/BVG Employee, IJM Employee, Source Tax Employee (déductions — AC Solidarity : désactivé, cotisation supprimée en 2023)
- [ ] AVS/AI/APG Employer, AC/ALV Employer, LAA Employer, LPP/BVG Employer, IJM Employer, Family Allowances Employer (contributions employeur)
- [ ] Chaque composant a les bons flags : `ch_subject_to_avs`, `ch_subject_to_ac`, etc.

---

## 1. Configuration employé

| Lien | Description |
|---|---|
| [Jean Claude](https://osiris.neoffice.me/app/employee/Jean%20Claude) | Employé test principal |
| [Helie Copter](https://osiris.neoffice.me/app/employee/Helie%20Copter) | Second employé test |
| [Liste des employés](https://osiris.neoffice.me/app/employee) | Tous les employés |

### Section "Swiss Payroll" (sur la fiche employé)

- [ ] **Type de permis** : Swiss Citizen / Permis B / C / G / L
- [ ] **Canton fiscal** : sélectionner un canton (ex. VD)
- [ ] **N° AVS** : format 756.XXXX.XXXX.XX (obligatoire pour le certificat de salaire)
- [ ] **Nationalité** : lien vers Country
- [ ] **% activité** : 100% par défaut
- [ ] **Date d'entrée ELM** : date de début (pour Swissdec)

### Section "Source Tax / Quellensteuer" (si employé assujetti)

- [ ] **Assujetti à l'impôt source** : cocher si applicable
- [ ] **Lettre tarif** : A (célibataire), B (marié), C (double revenu)...
- [ ] **Nombre d'enfants** : 0, 1, 2...
- [ ] **Impôt ecclésiastique** : oui/non
- [ ] **Code tarif** : calculé automatiquement (ex. B2Y = marié + 2 enfants + église)
- [ ] **Canton d'imposition** : peut différer du canton de travail

### Section "Cross-Border Worker" (si frontalier)

- [ ] **Frontalier** : cocher si applicable
- [ ] **Pays de résidence** : DE, FR, IT
- [ ] **Date début frontalier** : pour le régime IT ancien/nouveau

---

## 2. Structure salariale

| Lien | Description |
|---|---|
| [Swiss Payroll - Standard](https://osiris.neoffice.me/app/salary-structure/Swiss%20Payroll%20-%20Standard) | Structure créée par le setup |
| [Salary Structure Assignment](https://osiris.neoffice.me/app/salary-structure-assignment) | Assignations aux employés |
| [Nouvelle assignation](https://osiris.neoffice.me/app/salary-structure-assignment/new) | Assigner la structure à un employé |

**À tester :**
- [ ] La structure "Swiss Payroll - Standard" existe et contient les composants suisses
- [ ] Assigner la structure à Jean Claude (base = ex. 8000 CHF/mois)
- [ ] Assigner la structure à Helie Copter

---

## 3. Bulletin de salaire (Salary Slip)

| Lien | Description |
|---|---|
| [Liste des bulletins](https://osiris.neoffice.me/app/salary-slip) | Tous les bulletins |
| [Nouveau bulletin](https://osiris.neoffice.me/app/salary-slip/new?employee=Jean%20Claude) | Créer pour Jean Claude |

### Création d'un bulletin

1. Sélectionner l'employé (Jean Claude)
2. Définir la période (ex. 01.01.2025 – 31.01.2025)
3. **Sauvegarder** → le hook `update_swiss_social_contributions` calcule automatiquement :

**Vérifications des calculs :**
- [ ] **AVS/AI/APG** : 5.3% du salaire brut (employé ET employeur)
- [ ] **AC/ALV** : 1.1% du brut jusqu'au plafond de 148'200/an, 0% au-delà (solidarité supprimée 2023)
- [ ] **LPP/BVG** : taux selon âge de l'employé :
  - 25-34 ans : 7%
  - 35-44 ans : 10%
  - 45-54 ans : 15%
  - 55-65 ans : 18%
- [ ] **LAA non-professionnel** : taux configuré (employé)
- [ ] **LAA professionnel** : taux configuré (employeur)
- [ ] **IJM/KTG** : taux configuré
- [ ] **Allocations familiales** : employeur uniquement
- [ ] **13ème salaire** : selon mode configuré (annuel = décembre, mensuel = 1/12 chaque mois)
- [ ] **Impôt à la source** : si employé assujetti, montant calculé selon barème ESTV

### Print Format "Salary Slip Swiss"

Après sauvegarde, imprimer le bulletin :

| Lien | Description |
|---|---|
| Format d'impression | Sélectionner "Salary Slip Swiss" dans le menu d'impression |

**Vérifications :**
- [ ] En-tête : nom employé, n° AVS, canton, permis
- [ ] Colonnes : composant, taux, montant, YTD (cumul annuel)
- [ ] Déductions employé séparées des contributions employeur
- [ ] Salaire net affiché
- [ ] Contributions employeur en informationnel (grisées)

---

## 4. 13ème salaire

La configuration se fait dans la [Swiss Social Insurance Config](https://osiris.neoffice.me/app/swiss-social-insurance-config).

**3 modes :**

| Mode | Comportement |
|---|---|
| **Disabled** | Pas de 13ème |
| **Annual** | Versé intégralement en décembre (prorata si embauche/départ en cours d'année) |
| **Monthly** | 1/12 du salaire annuel versé chaque mois |

**À tester :**
- [ ] Mode Annual : créer un bulletin de décembre → 13ème ajouté automatiquement
- [ ] Mode Monthly : chaque bulletin contient 1/12
- [ ] Prorata : employé embauché en juillet → 6/12 en décembre
- [ ] Impact sur LPP : le 13ème entre dans le calcul LPP annualisé

---

## 5. Impôt à la source (Quellensteuer)

### 5.1 Barèmes ESTV

| Lien | Description |
|---|---|
| [Swiss QST Tariff](https://osiris.neoffice.me/app/swiss-qst-tariff) | Liste des barèmes importés |

**Import des barèmes :**
- [ ] Créer un nouveau tarif → sélectionner année
- [ ] Bouton "Fetch All Cantons" → importe ~800'000 tranches pour 26 cantons
- [ ] Vérifier statut "Active"

### 5.2 Configuration employé

Sur la [fiche employé](https://osiris.neoffice.me/app/employee/Jean%20Claude), section "Source Tax" :

- [ ] Cocher "Subject to Source Tax"
- [ ] Sélectionner lettre tarif (A, B, C...)
- [ ] Nombre d'enfants
- [ ] Impôt ecclésiastique oui/non
- [ ] Code tarif auto-calculé (ex. B2Y)

### 5.3 Calcul sur le bulletin

- [ ] Créer un bulletin → montant QST calculé automatiquement
- [ ] **Modèle mensuel** (ZH, BE, LU...) : lookup direct dans les tranches
- [ ] **Modèle annuel** (FR, GE, TI, VD, VS) : projection annuelle + correction en décembre

---

## 6. Travailleurs frontaliers

| Lien | Description |
|---|---|
| [Cross-Border Telework Log](https://osiris.neoffice.me/app/cross-border-telework-log) | Suivi du télétravail frontalier |

### 6.1 Frontalier allemand (DE)

- [ ] Configurer employé : frontalier + résidence DE + attestation Gre-1 cochée
- [ ] Impôt ordinaire PLAFONNÉ à 4.5% du brut (barèmes L-P) ; sans Gre-1 : barème ordinaire sans plafond
- [ ] Limite de 60 nuits de non-retour par an (art. 15a al. 2 CDI CH-DE)

### 6.2 Frontalier français (FR)

- [ ] Configurer employé : frontalier + résidence FR + attestation 2041-AS cochée
- [ ] Exempté de QST (8 cantons de l'accord, sauf GE) — sans 2041-AS : barème ordinaire
- [ ] Suivi du seuil de télétravail 40% via le Cross-Border Telework Log

### 6.3 Frontalier italien (IT)

- [ ] Ancien régime (avant 17.07.2023) : imposé au barème ordinaire PLEIN (pas exempté — le ristorno est l'affaire du canton)
- [ ] Nouveau régime : barèmes R-V tels quels (la réduction de 80% est déjà dans les fichiers de barèmes)

---

## 7. Certificat de salaire (Lohnausweis / Form 11)

| Lien | Description |
|---|---|
| [Liste des certificats](https://osiris.neoffice.me/app/swiss-salary-certificate) | Tous les certificats |
| [CH-CERT-2024-Jean Claude](https://osiris.neoffice.me/app/swiss-salary-certificate/CH-CERT-2024-Jean%20Claude) | Certificat existant |
| [Print Format Form 11](https://osiris.neoffice.me/app/print/Swiss%20Salary%20Certificate/CH-CERT-2024-Jean%20Claude?format=Salary%20Certificate%20Swiss) | Aperçu du formulaire imprimé |
| [Nouveau certificat](https://osiris.neoffice.me/app/swiss-salary-certificate/new) | Créer un nouveau certificat |

### 7.1 Création et remplissage

1. Nouveau certificat → sélectionner employé + année fiscale
2. **Bouton "Populate from Salary Slips"** → remplit automatiquement les 15 positions

**Positions à vérifier :**

| Position | Contenu | Auto-calculé |
|---|---|---|
| 1 | Salaire (brut sans 13ème) | |
| 2.1 | Autres prestations | |
| 2.2 | Pension, logement | |
| 2.3 | Autres avantages en nature | |
| 3 | Prestations irrégulières (13ème, bonus) | |
| 4 | Prestations en capital | |
| 5 | Droits de participation | |
| 6 | Indemnités conseil d'administration | |
| 7 | Autres prestations | |
| **8** | **Revenu brut total** (somme 1-7) | ✅ |
| 9 | Cotisations AVS/AC/AANP (SANS l'IJM — guide 2026 Cm 42) | |
| 10.1 | LPP ordinaire | |
| 10.2 | LPP rachat | |
| **11** | **Salaire net** (8 - 9 - 10.1 - 10.2) | ✅ |
| 12 | Impôt à la source | |
| 13.x | Frais (déplacements, représentation...) | |
| 14 | Contributions employeur | |
| 15 | Remarques | Manuel |

### 7.2 Code-barres eCH-0270

- [ ] **Bouton "Generate Barcode"** → génère le code-barres PDF417
- [ ] Sur le print format : barcode visible dans la Section H (à gauche)
- [ ] Données encodées : toutes les positions + identification employeur/employé

### 7.3 Print Format Form 11

- [ ] Fond officiel Form 11 (605.040.18N) visible
- [ ] Sections A/B : case Certificat de salaire cochée
- [ ] Section C : n° AVS, date de naissance, transport gratuit
- [ ] Section D : année, période, repas
- [ ] Section H : barcode PDF417 + nom/adresse employé
- [ ] Positions 1-15 : montants alignés dans les barres roses
- [ ] Section I : date sous "Ort und Datum", nom société sous "Die Richtigkeit..."
- [ ] Pied de page : "Form. 11 dfi 605.040.18N 01.21" visible

### 7.4 Validation

- [ ] Sans n° AVS → erreur à la sauvegarde
- [ ] Sans date de naissance → erreur
- [ ] Sans posting date → erreur

---

## 8. Swissdec ELM 5.0 — Déclarations

| Lien | Description |
|---|---|
| [Liste des déclarations](https://osiris.neoffice.me/app/swissdec-declaration) | Toutes les déclarations |
| [SDD-pri-2026-Year-End](https://osiris.neoffice.me/app/swissdec-declaration/SDD-pri-2026-Year-End) | Déclaration existante |
| [Nouvelle déclaration](https://osiris.neoffice.me/app/swissdec-declaration/new) | Créer une déclaration |
| [Transmitter Settings](https://osiris.neoffice.me/app/swissdec-transmitter-settings) | Configuration du gateway |

### 8.1 Configuration gateway

- [ ] URL gateway : `http://swissdec.neoffice.me:8745`
- [ ] API Key : configurée
- [ ] **Bouton "Test Connection"** → statut OK

### 8.2 Types de déclaration

| Type | Usage | Nommage |
|---|---|---|
| **Year-End** | Déclaration annuelle complète | SDD-{abbr}-{year} |
| **Monthly** | Déclaration mensuelle | SDD-{abbr}-{year}-M{mm} |
| **Correction** | Correction d'une déclaration acceptée | SDD-{abbr}-{year}-C{seq} |
| **BVG-Projection** | Projection LPP annualisée | SDD-{abbr}-{year}-BVG |

### 8.3 Workflow de test (déclaration annuelle)

1. Créer une déclaration Year-End (société + année)
2. **Bouton "Populate Employees"** → liste les employés avec résumé salaire
3. **Bouton "Run Validation"** → affiche erreurs/warnings
4. Corriger les erreurs (n° AVS manquant, etc.)
5. **Bouton "Export XML"** → génère le XML ELM 5.0
6. Vérifier le XML (champ `result_xml` ou téléchargement)
7. **Bouton "Transmit"** → envoi via gateway au serveur Swissdec
8. **Bouton "Check Status"** → vérifie le résultat (Accepted/Rejected)

### 8.4 Institutions couvertes

- [ ] AVS/AHV : cotisations AVS/AI/APG
- [ ] AC/ALV : cotisations chômage
- [ ] LPP/BVG : prévoyance professionnelle
- [ ] LAA/UVG : accidents
- [ ] IJM/KTG : maladie
- [ ] QST : impôt à la source
- [ ] FAK/CAF : allocations familiales
- [ ] OFS/BFS : statistique fédérale

---

## 9. Notifications EMA (Employee Mutation Announcement)

| Lien | Description |
|---|---|
| [Liste EMA](https://osiris.neoffice.me/app/swissdec-ema-notification) | Toutes les notifications |

### Déclenchement automatique

Les notifications sont créées **automatiquement** quand on modifie un employé :

| Événement | Déclencheur |
|---|---|
| **Eintritt** (Entrée) | Nouvel employé avec `ch_entry_date` |
| **Mutation** (Changement) | Modification de : état civil, canton, % activité, permis, n° AVS, nationalité |
| **Austritt** (Sortie) | Statut → "Left" ou `ch_exit_date` définie |

**À tester :**
- [ ] Modifier le canton de Jean Claude → notification Mutation créée automatiquement
- [ ] Vérifier les institutions sélectionnées (AVS, FAK, BVG)
- [ ] Export XML possible sur la notification
- [ ] Transmission possible via gateway

---

## 10. Scénario de test complet (end-to-end)

### Étape 1 : Configuration
1. [Configurer la société](https://osiris.neoffice.me/app/company/AlpInnovate%20S%C3%A0rl) (UID-BFS, contact)
2. [Créer la config assurance](https://osiris.neoffice.me/app/swiss-social-insurance-config/new) (taux, comptes)
3. [Vérifier les composants](https://osiris.neoffice.me/app/salary-component?ch_wage_type=%5B%22is%22%2C%22set%22%5D)

### Étape 2 : Employé
4. [Configurer Jean Claude](https://osiris.neoffice.me/app/employee/Jean%20Claude) (AVS, canton, permis)
5. [Assigner la structure salariale](https://osiris.neoffice.me/app/salary-structure-assignment/new) (Swiss Payroll - Standard, base 8000)

### Étape 3 : Paie mensuelle
6. [Créer un bulletin janvier](https://osiris.neoffice.me/app/salary-slip/new?employee=Jean%20Claude) → vérifier les cotisations
7. Créer les bulletins février à décembre (ou utiliser Payroll Entry)
8. Vérifier le 13ème en décembre (si mode Annual)

### Étape 4 : Certificat de salaire
9. [Créer le certificat annuel](https://osiris.neoffice.me/app/swiss-salary-certificate/new)
10. Populate from Salary Slips → vérifier les 15 positions
11. Generate Barcode → vérifier le PDF417
12. [Imprimer le Form 11](https://osiris.neoffice.me/app/print/Swiss%20Salary%20Certificate/CH-CERT-2024-Jean%20Claude?format=Salary%20Certificate%20Swiss)

### Étape 5 : Déclaration Swissdec
13. [Configurer le transmitter](https://osiris.neoffice.me/app/swissdec-transmitter-settings) → Test Connection
14. [Créer la déclaration annuelle](https://osiris.neoffice.me/app/swissdec-declaration/new)
15. Populate → Validate → Export XML → Transmit → Check Status

---

## Annexe A : Architecture technique

```
hrms/regional/switzerland/
├── constants.py          # Taux 2025, cantons, types de permis
├── utils.py              # Calculs LPP, AC, 13ème
├── payroll_hooks.py      # Hook Salary Slip.validate → calcul cotisations
├── source_tax.py         # Impôt à la source (mensuel/annuel)
├── estv_parser.py        # Import barèmes ESTV (FTP)
├── cross_border.py       # Travailleurs frontaliers DE/FR/IT
├── ema_hooks.py          # Détection mutations employé → notifications EMA
├── lohnausweis_barcode.py # Code-barres eCH-0270 (PDF417 + CODE128C)
├── swissdec_xml.py       # Génération XML ELM 5.0
├── swissdec_validation.py # Validation pré-export
├── swissdec_data.py      # Agrégation données salaire
├── swissdec_transmitter.py # Client HTTP gateway
├── setup.py              # Installation (custom fields, composants, structure)
├── wage_type_data.py     # Catalogue ~170 types de salaire
└── gateway/app.py        # Service Flask sur VM Windows (port 8745)
```

## Annexe B : Commandes de test

```bash
# Tous les tests suisses (~350 tests)
cd /home/neoffice/frappe-bench/apps/hrms
python -m pytest hrms/regional/switzerland/ -v

# Tests spécifiques
python -m pytest hrms/regional/switzerland/test_utils.py -v          # 45 tests (LPP, AC, 13ème)
python -m pytest hrms/regional/switzerland/test_source_tax.py -v     # 24 tests (QST)
python -m pytest hrms/regional/switzerland/test_cross_border.py -v   # 44 tests (frontaliers)
python -m pytest hrms/regional/switzerland/test_swissdec.py -v       # 136 tests (XML, validation)
python -m pytest hrms/regional/switzerland/test_lohnausweis.py -v    # 14 tests (certificat)
python -m pytest hrms/regional/switzerland/test_lohnausweis_barcode.py -v  # 32 tests (eCH-0270)
python -m pytest hrms/regional/switzerland/test_wage_types.py -v     # 28 tests (types salaire)
python -m pytest hrms/regional/switzerland/test_estv_parser.py -v    # 13 tests (parser ESTV)
```

## Annexe C : Tâches planifiées

| Fréquence | Tâche | Description |
|---|---|---|
| **Horaire** | `swissdec_transmitter.poll_pending_transmissions` | Vérifie le statut des transmissions en cours |
| **Quotidien** | `source_tax.auto_fetch_new_tariffs` | Télécharge les barèmes ESTV (actif du 1er déc au 15 jan) |
