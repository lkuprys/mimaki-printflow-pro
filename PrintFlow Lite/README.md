# Podbase Mimaki PrintFlow Lite

Nepriklausoma, lengva ir stabili produkcijos paruošimo programa, skirta Mimaki spausdintuvams.

---

## 🎯 Programos Paskirtis
1. **Stebi tinklo serverio aplanką** (pvz. `\\192.168.1.143\podbase-hotfolder\BENDRAS_PODBASE_HOTFOLDER`).
2. **Filtruoja pagal datą**: skenuoja tik šiandienos datą (senesnių datų aplankų neliečia).
3. **Automatiškai atpažįsta produktus**:
   - `magnetic-wallet`
   - `magsafe-ring-holders`
   - `clear-cases-magsafe-v2`
   - `clear-cases-v1`
   - `clear-cases-v0`
4. **Paruošia spaudos plokštes (Prepress)**:
   - Ištraukia integruotą SMask kaukę arba rastroja 300 DPI.
   - Pritaikomas **Thinning (erozija / sutraukimas)** arba **Thickening (išpūtimas)** pikseliais atskirai Baltai ir Gruntui.
5. **Perkelia į Mimaki Hot Folderius**:
   - **Atominis įrašymas (.tmp ➔ .pdf)**: failai niekada „neprasimeta“, nes RasterLink mato tik pilnai baigtą failą.
   - **Konfigūruojama seka**: nustatoma tvarka (pvz. `Primer ➔ White ➔ CMYK`) su užlaikymo pauze tarp kėlimų (pvz. 0.5s).
6. **Atmintis (Registry)**:
   - Visi apdoroti failai registruojami `jobs_registry.json`.
   - Paleidus programą iš naujo ar perkrovus kompiuterį, tie patys užsakymai **niekada nebėra keliami antrą kartą**.

---

## 🖨️ Operatoriaus Darbas prie Spausdintuvo
Kadangi visa trapi GUI automatizacija pašalinta:
1. Operatorius atsidaro **Mimaki RasterLink 7**.
2. Ekrane mato jau atvykusias plokštes (pvz. Primer, White, Color).
3. Pažymi jas pelės klavišu, paspaudžia **Composition** ir **RIP and Print**.

---

## 🚚 Perkėlimas į Kitą Gamybos Kompiuterį
1. Tiesiog nukopijuokite visą šį aplanką `PrintFlow Lite` į naująjį kompiuterį (pvz., į `C:\PrintFlow Lite` arba ant `Desktop`).
2. Paleiskite `PrintFlowLite.exe` (arba dukart spustelėkite `PALEISTI_PRINTFLOW_LITE.bat`).
3. Valdymo panelėje patikrinkite arba nurodykite:
   - **Serverio aplanko kelią** (jei skiriasi tinklo disko raidė ar IP).
   - **Hotfolderių kelius** (jei Mimaki aplankai yra kitoje disko vietoje nei `C:\MijCtrl\Hot\...`).
4. Spustelėkite **„Išsaugoti pakeitimus“**. Viskas!
