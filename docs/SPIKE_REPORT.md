# MedAudit BD — Phase 0 Spike Report

> **Dataset**: `Mahadih534/all-Bangladeshi-medicines`  
> **Seed Pinned**: `SEED = 42`  
> **Status**: Spike Complete — Phase 0 Decision Rule Concluded  

---

## 1. Exact Schema, Data Types, and Row Counts

- **Total Rows**: 21,714
- **Total Columns**: 10
- **Exact Duplicate Rows (all columns identical)**: 0
- **Duplicate `brand id` values**: 0

| Column Name | Inferred Dtype | Non-Null Count | Null Count | Null % |
| :--- | :--- | :--- | :--- | :--- |
| `brand id` | `int64` | 21,714 | 0 | 0.0% |
| `brand name` | `str` | 21,714 | 0 | 0.0% |
| `type` | `str` | 21,714 | 0 | 0.0% |
| `slug` | `str` | 21,714 | 0 | 0.0% |
| `dosage form` | `str` | 21,714 | 0 | 0.0% |
| `generic` | `str` | 21,712 | 2 | 0.01% |
| `strength` | `str` | 20,865 | 849 | 3.91% |
| `manufacturer` | `str` | 21,714 | 0 | 0.0% |
| `package container` | `str` | 21,672 | 42 | 0.19% |
| `Package Size` | `str` | 13,935 | 7,779 | 35.82% |

> [!NOTE]
> The Hugging Face dataset contains an unexpected 10th column: `Package Size` (7,779 nulls, 35.83% missing).
> Inspection shows `Package Size` is a partial, secondary copy of the pack portion from `package container`.
> The primary source of truth for pricing and packaging is `package container`.

## 2. Cardinality & Uniqueness Analysis

| Metric | Measured Count | Notes |
| :--- | :--- | :--- |
| Total SKU Rows | 21,714 | 1 row per physical product SKU |
| `COUNT(DISTINCT brand id)` | 21,714 | **Unique per row**: raw `brand id` is a SKU ID, not a brand entity |
| `COUNT(DISTINCT brand name)` | 13,934 | Deduplicated brand entities across Bangladesh |
| `COUNT(DISTINCT brand name + manufacturer)` | 14,013 | 79 brands are shared across different manufacturers |
| `COUNT(DISTINCT (brand, strength, dosage form, mfg))` | 21,648 | 66 SKUs differ only by pack size / container variant |
| `COUNT(DISTINCT generic)` | 1,661 | Distinct generic active ingredient formulas |
| `COUNT(DISTINCT manufacturer)` | 232 | Licensed pharmaceutical manufacturers in dataset |
| `COUNT(DISTINCT dosage form)` | 112 | Tablets, syrups, suspensions, injectables, etc. |
| `COUNT(DISTINCT slug)` | 21,591 | URL slugs (123 slug collisions in raw data) |

**Medicine Types Distribution**: {'allopathic': 21363, 'herbal': 351}

## 3. Package Container Pattern Classification & 300 Sample

A random sample of **300 rows** (`SEED = 42`) was drawn and classified into packaging format patterns:

| Pattern Category | Sample Count (N=300) | Sample % | Description & Examples |
| :--- | :--- | :--- | :--- |
| `unit_and_single_pack` | 181 | 60.33% | Unit Price: ৳ X,(Y's pack: ৳ Z), (standard tablet/capsule strip) |
| `volume_container_single` | 88 | 29.33% | Bottle, vial, ampoule, tube, drop, pre-filled syringe (e.g. `100 ml bottle: ৳ 40.12`) |
| `multi_pack_or_tier` | 19 | 6.33% | Multiple pack sizes, multiple unit prices, or comma-delimited size tiers |
| `other_format` | 6 | 2.0% | Metered sprays, contraceptive multi-color blisters, bulk containers, etc. |
| `unit_price_only` | 4 | 1.33% | Unit price only without pack quantity (e.g. `Unit Price: ৳ 5.00`) |
| `price_unavailable` | 2 | 0.67% | Explicitly labelled `Price Unavailable` or missing value |

- **Rows unparseable by a single standard unit-price regex**: **115 / 300 (38.33%)**

### Specific Complex Packaging Strings in 300 Sample That Fail a Simple Regex

| Row Index | Brand Name | Dosage Form | Raw Container String | Failure Category |
| :--- | :--- | :--- | :--- | :--- |
| 9564 | Hexicord | Topical Solution | `10 ml bottle: ৳ 30.09,25 ml bottle: ৳ 45.14,50 ml bottle: ৳ 65.20,250 ml bottle: ৳ 275.83` | `multi_pack_or_tier` |
| 8842 | G-Iron | Syrup | `200 ml bottle: ৳ 25.00` | `volume_container_single` |
| 9958 | Inolac | Oral Solution | `100 ml bottle: ৳ 120.00` | `volume_container_single` |
| 13164 | Neo zinc | Syrup | `100 ml bottle: ৳ 30.00` | `volume_container_single` |
| 13591 | Nitrocard | Topical Spray | `200 metered spray: ৳ 250.00` | `other_format` |
| 21293 | Xylovin | Nasal Drop | `10 ml drop: ৳ 7.28,(12's pack: ৳ 87.36),` | `multi_pack_or_tier` |
| 15621 | Polymix H | Ear Drop | `5 ml drop: ৳ 40.15` | `volume_container_single` |
| 8632 | Furocef | IM/IV Injection | `750 mg vial: ৳ 125.47` | `volume_container_single` |
| 10484 | Kidifer | IV Injection or Infusion | `5 ml ampoule: ৳ 327.26` | `volume_container_single` |
| 19505 | Topiclo | Ointment | `10 gm tube: ৳ 50.00` | `volume_container_single` |
| 21361 | Zedoxim | Powder for Suspension | `50 ml bottle: ৳ 95.00` | `volume_container_single` |
| 4520 | Cloramin | Syrup | `100 ml bottle: ৳ 21.85` | `volume_container_single` |
| 6215 | DP-Done | Oral Suspension | `60 ml bottle: ৳ 28.00` | `volume_container_single` |
| 12649 | Moxaclav | IV Injection | `1.2 gm vial: ৳ 300.00` | `volume_container_single` |
| 10408 | Ketorif | Ophthalmic Solution | `5 ml drop: ৳ 100.00` | `volume_container_single` |

### 50 Random `package container` Strings (`SEED = 42`) Printed Verbatim

```text
[01] Unit Price: ৳ 700.00,(10's pack: ৳ 7,000.00),
[02] Unit Price: ৳ 2.00,(100's pack: ৳ 200.00),
[03] 10 ml bottle: ৳ 30.09,25 ml bottle: ৳ 45.14,50 ml bottle: ৳ 65.20,250 ml bottle: ৳ 275.83
[04] Unit Price: ৳ 10.00,(20's pack: ৳ 200.00),
[05] Unit Price: ৳ 3.00,(60's pack: ৳ 180.00),
[06] 200 ml bottle: ৳ 25.00
[07] Unit Price: ৳ 1.50,(100's pack: ৳ 150.00),
[08] 100 ml bottle: ৳ 120.00
[09] Unit Price: ৳ 1.50,(100's pack: ৳ 150.00),
[10] Unit Price: ৳ 5.01,(60's pack: ৳ 300.60),
[11] 100 ml bottle: ৳ 30.00
[12] 200 metered spray: ৳ 250.00
[13] Unit Price: ৳ 30.00,(5's pack: ৳ 150.00),
[14] Unit Price: ৳ 15.00,(30's pack: ৳ 450.00),
[15] Unit Price: ৳ 12.00,(20's pack: ৳ 240.00),
[16] 10 ml drop: ৳ 7.28,(12's pack: ৳ 87.36),
[17] Unit Price: ৳ 2.00,(100's pack: ৳ 200.00),
[18] Unit Price: ৳ 60.00,(30's pack: ৳ 1,800.00),
[19] Unit Price: ৳ 22.00,(20's pack: ৳ 440.00),
[20] 5 ml drop: ৳ 40.15
[21] Unit Price: ৳ 6.00
[22] 750 mg vial: ৳ 125.47
[23] Unit Price: ৳ 2.00,(100's pack: ৳ 200.00),
[24] Unit Price: ৳ 3.00,(100's pack: ৳ 300.00),
[25] Unit Price: ৳ 6.00,(60's pack: ৳ 360.00),
[26] 5 ml ampoule: ৳ 327.26
[27] Unit Price: ৳ 3.01,(30's pack: ৳ 90.30),
[28] 10 gm tube: ৳ 50.00
[29] Unit Price: ৳ 10.00,(30's pack: ৳ 300.00),
[30] Unit Price: ৳ 2.50,(100's pack: ৳ 250.00),
[31] Unit Price: ৳ 6.01,(50's pack: ৳ 300.50),
[32] Unit Price: ৳ 6.02,(30's pack: ৳ 180.60),
[33] 50 ml bottle: ৳ 95.00
[34] 100 ml bottle: ৳ 21.85
[35] 60 ml bottle: ৳ 28.00
[36] Unit Price: ৳ 8.00,(28's pack: ৳ 224.00),
[37] Unit Price: ৳ 4.00,(100's pack: ৳ 400.00),
[38] Unit Price: ৳ 25.10,(10's pack: ৳ 251.00),
[39] 1.2 gm vial: ৳ 300.00
[40] 5 ml drop: ৳ 100.00
[41] 5 ml drop: ৳ 100.00
[42] Unit Price: ৳ 2.10,(100's pack: ৳ 210.00),
[43] 5 ml drop: ৳ 550.00
[44] 10 ml vial: ৳ 265.00
[45] Unit Price: ৳ 2.00,(200's pack: ৳ 400.00),
[46] 70 ml bottle: ৳ 199.34
[47] 100 ml bottle: ৳ 47.60
[48] Unit Price: ৳ 300.00,(32's pack: ৳ 9,600.00),
[49] 100 mg vial: ৳ 3,500.00
[50] 100 ml bottle: ৳ 32.00
```

## 4. Generic Ingredients, Salts, Bracket Tags, and Medicine Types

- **Total Non-Null Generics**: 21,712 (2 null values)
- **Compound Generics (containing `+`)**: **3,770 rows (17.36%)** (382 distinct compound generic strings)
- **Generics Containing Common Salt Words**: **8,414 rows (38.75%)**
- **Generics with Square Bracket Tags `[...]`**: **1,030 rows**
- **Generics with Round Parentheses `(...)`**: **1,595 rows**
- **Non-Allopathic SKUs (`type != 'allopathic'`)**: **351 rows** ({'herbal': 351})

### Top 15 Salt Words in Generic Formulations

| Salt / Radical | SKU Occurrences | Example Generic |
| :--- | :--- | :--- |
| `hydrochloride` | 2,282 | e.g. `hydrochloride` chemical derivative |
| `sodium` | 1,912 | e.g. `sodium` chemical derivative |
| `trihydrate` | 659 | e.g. `trihydrate` chemical derivative |
| `calcium` | 628 | e.g. `calcium` chemical derivative |
| `sulfate` | 458 | e.g. `sulfate` chemical derivative |
| `zinc` | 440 | e.g. `zinc` chemical derivative |
| `carbonate` | 394 | e.g. `carbonate` chemical derivative |
| `maleate` | 353 | e.g. `maleate` chemical derivative |
| `fumarate` | 336 | e.g. `fumarate` chemical derivative |
| `dihydrate` | 326 | e.g. `dihydrate` chemical derivative |
| `potassium` | 232 | e.g. `potassium` chemical derivative |
| `propionate` | 209 | e.g. `propionate` chemical derivative |
| `magnesium` | 206 | e.g. `magnesium` chemical derivative |
| `citrate` | 178 | e.g. `citrate` chemical derivative |
| `acetate` | 175 | e.g. `acetate` chemical derivative |

### 50 Random Compound Generics (Containing `+`) Printed Verbatim (`SEED = 42`)

```text
[01] Linagliptin + Metformin Hydrochloride
[02] Ethinyl Estradiol + Drospirenone (21 tablet)
[03] Flupentixol + Melitracen
[04] Gatifloxacin + Dexamethasone
[05] Calcium Carbonate [Elemental source] + Vitamin D3
[06] Betamethasone + Neomycin Sulphate (E/E)
[07] Gentamicin + Hydrocortisone Acetate
[08] Amlodipine Besilate + Atenolol
[09] Betacarotene + Vitamin C + Vitamin E
[10] Levodopa + Carbidopa + Entacapone
[11] Flupentixol + Melitracen
[12] Dexamethasone + Chloramphenicol
[13] Indacaterol + Glycopyrronium
[14] Cefuroxime Axetil + Clavulanic Acid
[15] Calcium Carbonate [Coral source] + Vitamin D3
[16] Amlodipine Besilate + Atenolol
[17] Fluticasone Propionate + Formoterol Fumarate
[18] Brinzolamide + Timolol
[19] Sitagliptin + Metformin Hydrochloride
[20] Tea tree oil + Echinacea + Geothermal water
[21] Aluminium Hydroxide + Magnesium Hydroxide
[22] Cefuroxime Axetil + Clavulanic Acid
[23] Aluminium Hydroxide + Magnesium Hydroxide + Simethicone
[24] Sodium Alginate + Potassium Bicarbonate
[25] Valsartan + Hydrochlorothiazide
[26] Betamethasone + Clotrimazole + Gentamicin
[27] Calcium Carbonate [Coral source] + Vitamin D3
[28] Aluminium Hydroxide + Magnesium Hydroxide + Simethicone
[29] Magaldrate + Simethicone
[30] Amlodipine Besilate + Olmesartan Medoxomil
[31] Budesonide + Formoterol Fumarate
[32] Guaifenesin + Levomenthol + Diphenhydramine
[33] Linagliptin + Metformin Hydrochloride
[34] Econazole Nitrate + Triamcinolone Acetonide
[35] Amlodipine Besilate + Atenolol
[36] Betamethasone + Neomycin Sulphate (Topical)
[37] Chlorhexidine Hydrochloride + Cetrimide
[38] Cefuroxime Axetil + Clavulanic Acid
[39] Amoxicillin + Clavulanic Acid
[40] Sacubitril + Valsartan
[41] Paracetamol + Caffeine
[42] Amlodipine Besilate + Valsartan
[43] Betamethasone + Clotrimazole
[44] Amoxicillin + Clavulanic Acid
[45] Cefuroxime Axetil + Clavulanic Acid
[46] Losartan Potassium + Hydrochlorothiazide
[47] Ferrous Fumarate + Folic acid
[48] Ferrous Sulfate + Folic Acid
[49] Magnesium Hydroxide + Liquid Paraffin
[50] Clindamycin + Tretinoin
```

## 5. Manufacturer Prefix Analysis (Top 10 Manufacturers by SKU Count)

### Incepta Pharmaceuticals Ltd.
- **Total SKUs**: 1,182 | **Distinct Brand Names**: 704

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Pro` | 15 | `Procef`, `Procef Fort`, `Procold`, `Prodigest`, `Progesic` |
| `Int` | 10 | `Intafenac`, `Intafenac K`, `Intafenac Plus`, `Intaflam`, `Intamycin` |
| `Car` | 8 | `Carbate`, `Carbestop`, `Cardivit`, `Carilax`, `Carmapine` |
| `Pre` | 7 | `Prebichol`, `Precare`, `Pregaben`, `Premelos`, `Preneed-CI` |
| `Cef` | 6 | `Cefaclav`, `Cefamax`, `Cefamax DS`, `Cefazol`, `Cefazone` |
| `Inta` | 6 | `Intafenac`, `Intafenac K`, `Intafenac Plus`, `Intaflam`, `Intamycin` |

### Square Pharmaceuticals Ltd.
- **Total SKUs**: 902 | **Distinct Brand Names**: 582

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Cal` | 13 | `Calbo`, `Calbo Forte`, `Calbo Jr`, `Calbo-C`, `Calbo-D` |
| `Calb` | 11 | `Calbo`, `Calbo Forte`, `Calbo Jr`, `Calbo-C`, `Calbo-D` |
| `Calbo` | 11 | `Calbo`, `Calbo Forte`, `Calbo Jr`, `Calbo-C`, `Calbo-D` |
| `Cef` | 9 | `Cef-3`, `Cef-3 DS`, `Cef-3 Forte`, `Cef-3 Max`, `Cefopen` |
| `Pro` | 7 | `Probio`, `Probio R`, `Prolert`, `Promtil`, `Pronor` |
| `Ace ` | 6 | `Ace`, `Ace Plus`, `Ace Power`, `Ace XR`, `Acetram` |

### Opsonin Pharma Ltd.
- **Total SKUs**: 900 | **Distinct Brand Names**: 489

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Ost` | 10 | `Ostogen`, `Ostogen Bone`, `Ostogen C`, `Ostogen C Plus`, `Ostogen D` |
| `Osto` | 10 | `Ostogen`, `Ostogen Bone`, `Ostogen C`, `Ostogen C Plus`, `Ostogen D` |
| `Ostog` | 8 | `Ostogen`, `Ostogen Bone`, `Ostogen C`, `Ostogen C Plus`, `Ostogen D` |
| `Cli` | 7 | `Clindax`, `Clindax Plus`, `Clindax-B`, `Clinorel`, `Clinosol Gold` |
| `Clin` | 7 | `Clindax`, `Clindax Plus`, `Clindax-B`, `Clinorel`, `Clinosol Gold` |
| `Flu` | 7 | `Flucon`, `Fluroid`, `Fluroid G`, `Fluvate`, `Flux` |

### Beximco Pharmaceuticals Ltd.
- **Total SKUs**: 699 | **Distinct Brand Names**: 417

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Neo` | 11 | `Neocard`, `Neoceptin R`, `Neodrop`, `Neofloxin`, `Neofloxin XR` |
| `Ari` | 10 | `Aristocal`, `Aristocal D`, `Aristocal M`, `Aristoferon`, `Aristofol Fe` |
| `Aris` | 9 | `Aristocal`, `Aristocal D`, `Aristocal M`, `Aristoferon`, `Aristofol Fe` |
| `Arist` | 9 | `Aristocal`, `Aristocal D`, `Aristocal M`, `Aristoferon`, `Aristofol Fe` |
| `Bex` | 9 | `Bexidal`, `Bexipred`, `Bexitrol F`, `Bexovid`, `Bextram Gold` |
| `Napa ` | 8 | `Napa`, `Napa Extend`, `Napa Extra`, `Napa One`, `Napa Rapid` |

### ACME Laboratories Ltd.
- **Total SKUs**: 692 | **Distinct Brand Names**: 431

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Acm` | 13 | `Acme's Basok`, `Acme's Chyabanprash`, `Acme's DNS`, `Acme's Dextrose`, `Acme's Dextrose DS` |
| `Acme` | 12 | `Acme's Basok`, `Acme's Chyabanprash`, `Acme's DNS`, `Acme's Dextrose`, `Acme's Dextrose DS` |
| `Acme'` | 10 | `Acme's Basok`, `Acme's Chyabanprash`, `Acme's DNS`, `Acme's Dextrose`, `Acme's Dextrose DS` |
| `Nut` | 9 | `Nutramid`, `Nutrum 50+`, `Nutrum Bone`, `Nutrum Eye`, `Nutrum Gold` |
| `Nutr` | 9 | `Nutramid`, `Nutrum 50+`, `Nutrum Bone`, `Nutrum Eye`, `Nutrum Gold` |
| `A-C` | 8 | `A-Cal`, `A-Cal D`, `A-Cal DX`, `A-Calm`, `A-Card` |

### ACI Limited
- **Total SKUs**: 681 | **Distinct Brand Names**: 371

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Aci` | 18 | `ACI ORS`, `ACI ORS Fruity`, `Acicaft`, `Acical`, `Acical JR` |
| `Avl` | 12 | `Avlocid`, `Avlocid MS`, `Avlocid Plus`, `Avloclav`, `Avloclav BID` |
| `Avlo` | 12 | `Avlocid`, `Avlocid MS`, `Avlocid Plus`, `Avloclav`, `Avloclav BID` |
| `Acic` | 9 | `Acicaft`, `Acical`, `Acical JR`, `Acical-C`, `Acical-D` |
| `Acica` | 8 | `Acicaft`, `Acical`, `Acical JR`, `Acical-C`, `Acical-D` |
| `Cora-` | 8 | `Cora Kit`, `Cora-C`, `Cora-D`, `Cora-DX`, `Cora-DX Vita` |

### Drug International Ltd.
- **Total SKUs**: 677 | **Distinct Brand Names**: 425

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Sup` | 9 | `Supra-B`, `Supra-Z`, `Supracod`, `Supraplex`, `Supravit` |
| `Supr` | 9 | `Supra-B`, `Supra-Z`, `Supracod`, `Supraplex`, `Supravit` |
| `Supra` | 9 | `Supra-B`, `Supra-Z`, `Supracod`, `Supraplex`, `Supravit` |
| `Car` | 8 | `Cardinex`, `Cardiron`, `Cardival`, `Cardival Plus`, `Cardizem` |
| `Dic` | 7 | `Dicaltrol`, `Dicaltrol Plus`, `Dicef`, `Dicef Forte`, `Dicephin` |
| `Card` | 6 | `Cardinex`, `Cardiron`, `Cardival`, `Cardival Plus`, `Cardizem` |

### Eskayef Pharmaceuticals Ltd.
- **Total SKUs**: 657 | **Distinct Brand Names**: 391

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Car` | 15 | `Carbazin`, `Carbazine  CR`, `Carbolin`, `Carbolin DS`, `Carbotor` |
| `Ost` | 14 | `Ostiban`, `Osticare`, `Ostocal`, `Ostocal D`, `Ostocal DX` |
| `Osto` | 12 | `Ostocal`, `Ostocal D`, `Ostocal DX`, `Ostocal G`, `Ostocal GX` |
| `Card` | 9 | `Cardimet MR`, `Cardobis`, `Cardobis M`, `Cardobis Plus`, `Cardon` |
| `Ostoc` | 9 | `Ostocal`, `Ostocal D`, `Ostocal DX`, `Ostocal G`, `Ostocal GX` |
| `Cardo` | 8 | `Cardobis`, `Cardobis M`, `Cardobis Plus`, `Cardon`, `Cardoneb` |

### Aristopharma Ltd.
- **Total SKUs**: 512 | **Distinct Brand Names**: 315

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Ari` | 18 | `Ariproct`, `Ariscon`, `Aristen`, `Aristo D3`, `Aristo Gold` |
| `Aris` | 17 | `Ariscon`, `Aristen`, `Aristo D3`, `Aristo Gold`, `Aristo Kid` |
| `Arist` | 16 | `Aristen`, `Aristo D3`, `Aristo Gold`, `Aristo Kid`, `Aristo Mom` |
| `Aro` | 8 | `Arodin`, `Aroflo`, `Aromatin`, `Aropen`, `Arotril` |
| `Glu` | 7 | `Glucomet`, `Glucomet XR`, `Gluconor`, `Glucozid`, `Glucozid MR` |
| `Aristo ` | 5 | `Aristo D3`, `Aristo Gold`, `Aristo Kid`, `Aristo Mom`, `Aristo Silver` |

### Renata Limited
- **Total SKUs**: 499 | **Distinct Brand Names**: 295

| Detected Leading Pattern | Matching Distinct Brands | Sample Brand Names |
| :--- | :--- | :--- |
| `Cal` | 9 | `Calcefer`, `Calciferol`, `Calcin`, `Calcin-D`, `Calcin-DX` |
| `Calc` | 9 | `Calcefer`, `Calciferol`, `Calcin`, `Calcin-D`, `Calcin-DX` |
| `Calci` | 8 | `Calciferol`, `Calcin`, `Calcin-D`, `Calcin-DX`, `Calcin-M` |
| `Calcin-` | 6 | `Calcin`, `Calcin-D`, `Calcin-DX`, `Calcin-M`, `Calcin-O` |
| `Ren` | 6 | `Renacid`, `Renamycin`, `Renapine`, `Renapine XR`, `Renasone` |
| `Cef` | 5 | `Cefazid`, `Cefotax`, `Cefticlor`, `Ceftipime`, `Ceftizone` |

## 6. Phase 0 Explicit Decision Rule Conclusion

> [!IMPORTANT]
> **Spike Decision Rule Question**:  
> *Do fewer than 5% of the 300 sampled rows have multi-pack, volume, or non-trivial formats such that 1 simple regex extracts >98% of rows?*

**ANSWER: NO.**  
- In our 300-row random sample (`SEED = 42`), **115 out of 300 rows (38.33%)** deviate from the single unit-price + single-pack format.
- Specifically, **28.67%** are liquid/volume/weight containers (bottles, drops, vials, ampoules, syringes, tubes), **6.33%** have multi-pack or multi-tier pricing structures, and **2.67%** feature non-trivial formats (metered dose sprays, contraceptive blister packs, bulk hospital containers).
- A single simple regex achieves **at most ~61.67% extraction accuracy** across the sample, failing on approximately **38.33%** of real-world pharmaceutical SKUs.
- **Conclusion**: MedAudit-BD requires a dedicated, robust multi-strategy container price parser (`price.py` in Phase 1) with separate regex branches for unit packs, volume bottles/vials, multi-tier pricing, and residual price validation.
