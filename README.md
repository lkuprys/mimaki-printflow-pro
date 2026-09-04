# Mimaki PrintFlow PRO

Automatizuota spaudos paruošimo (Pre-Press) ir nukreipimo sistema, skirta **Mimaki UJF-6042 MkII e** UV spausdintuvui ir **RasterLink 7** RIP programai.

Sistema integruojasi su **Podbase MES** gamybos linija (`mfgpodbase.com`), automatiškai apdoroja gaunamus didelius (100MB+) gamybinius PDF failus, išskaido juos į suderintas spaudos plokštes (Primer, White su Choke erozija, CMYK) ir paskirsto į fizinius Hot Folderius.

---

## 🚀 Pagrindinės Funkcijos

1. **Greitaeigis Pre-Press Variklis (NumPy + PyMuPDF):**
   * Apdoroja 35.6 MP (7192 × 4948 px @ 300 DPI) spaudos stalą per **< 2.5 sekundės**.
   * Ištraukia integruotas `SMask` kaukes.
   * Apskaičiuoja 1 px / 2 px Choke (thinning) baltam rašalui ir gruntui.
2. **Plokščių generavimas RasterLink 7:**
   * `Plate_1_CMYK.pdf` $\to$ Full Color
   * `Plate_2_White.pdf` $\to$ WhitePlate Type (su Choke)
   * `Plate_3_Primer.pdf` $\to$ PrimerPlate Type
   * Visi sluoksniai turi identiškas koordinates (0.00 mm poslinkis).
3. **Konfigūruojama Gaminių Matrica:**
   * Dinaminis gaminių valdymas (MagSafe Ring Holders, Clear Cases, Wallets ir kt.).
   * Kiekvienam gaminiui priskiriami konkretūs Hot Folderių keliai ir Choke nustatymai.
4. **Architektūra:**
   * Core: Python / NumPy / PyMuPDF.
   * UI: Pereinama į Native Desktop UI (**PySide6 + QML / Qt Quick**) ir Nuitka Standalone `.exe`.

---

## 🛠️ Reikalavimai ir Diegimas

```bash
# Įdiegti priklausomybes:
pip install -r requirements.txt

# Paleisti testus:
python test_pipeline.py
```

---

## 📁 Projekto Struktūra

```
├── printflow/
│   ├── config/          # Gaminių ir Hot Folderių JSON konfigūracijos
│   ├── core/            # Pre-Press variklis, Choke algoritmai, Router
│   ├── server/          # Backend servisas
│   └── static/          # Laikina web peržiūros sąsaja (migruojama į QML)
├── knowledge_base/      # Mimaki RasterLink 7 specifikacijos ir gamybiniai protokolai
├── INBOX_PRINT_FILES/   # Gaunamų spaudos failų aplankas
└── test_pipeline.py     # Integraciniai testai
```
