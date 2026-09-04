# Produktų Matrica ir Hot Folderių Architektūra

Šis dokumentas pateikia visų gamybinių produktų grupių žemėlapį, atitinkamus sluoksnius, Choke parametrus ir Hot Folderių kelius.

---

## 1. Produktų Grupių Žemėlapis

| Gaminio Tipas | Medžiaga / Paskirtis | Sluoksnių Seka | Choke | Hot Folderis Diske | RasterLink 7 Favorite Nustatymai |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01. Telefono Dėklai** | Skaidrus / Tamsus TPU | White $\to$ CMYK | 1 px | `C:\PrintFlow\HotFolders\01_PhoneCases_UV\` | `White` (Mono White) + `CMYK` (Full Color) |
| **02. Akrilas / Plastikas** | Akriliniai blokai, PVC | Primer $\to$ White $\to$ CMYK | 1 px | `C:\PrintFlow\HotFolders\02_Acrylic_Primer_White_CMYK\` | `Primer` (Mono Primer) + `White` (Mono White) + `CMYK` |
| **03. Lipdukai su Pjovimu** | Lipni plėvelė | CMYK + CutContour | 0 px | `C:\PrintFlow\HotFolders\03_Stickers_Print_Cut\` | `CMYK_Cut` (Print & Cut profilis) |
| **04. Tiesioginė Spauda** | Balti ruošiniai, metalas | CMYK Only | 0 px | `C:\PrintFlow\HotFolders\04_Direct_CMYK_Only\` | `CMYK` (Standard Full Color) |
| **05. Veidrodinis Stiklas** | Skaidrus stiklas / akrilas| CMYK $\to$ White viršuje | 1 px | `C:\PrintFlow\HotFolders\05_Reverse_Glass_Acrylic\` | `CMYK` (Reverse) + `White` (Topcoat Mono) |

---

## 2. Tikslus Katalogų Medis Diske

```
C:\PrintFlow\HotFolders\
├── 01_PhoneCases_UV\
│   ├── CMYK\
│   └── White\
├── 02_Acrylic_Primer_White_CMYK\
│   ├── Primer\
│   ├── White\
│   └── CMYK\
├── 03_Stickers_Print_Cut\
│   └── CMYK_Cut\
├── 04_Direct_CMYK_Only\
│   └── CMYK\
└── 05_Reverse_Glass_Acrylic\
    ├── CMYK\
    └── White\
```

---

## 3. Failų Vardų Standartas

Kad darbai nesusimaišytų ir būtų lengvai atsekami:
* Format: `[UZSAKYMO_NR]_[SLUOKSNIS].pdf`
* Pavyzdys:
  * `ORD-2026-1045_Primer.pdf`
  * `ORD-2026-1045_White.pdf`
  * `ORD-2026-1045_CMYK.pdf`
