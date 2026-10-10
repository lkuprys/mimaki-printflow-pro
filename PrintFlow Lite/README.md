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

## 🖥️ Sąsaja (v1.2 – Podbase WORK dizainas)
| Skirtukas | Paskirtis |
|---|---|
| **Stebėjimas** | „Pradėti stebėjimą“ / „Skenuoti dabar“, šiandien įkeltų ir dėmesio reikalaujančių užsakymų skaičius, datos filtras, veiklos žurnalas. |
| **Istorija** | Visi apdoroti užsakymai su paieška; detalėse – plokštės, šaltinis, klaidos. „Atidaryti plokščių aplanką“, „Pakartoti“, „Ištrinti įrašą“. |
| **Produktai** | Produktų sąrašas + forma: pavadinimas, raktažodžiai (su atpažinimo testu), kurios plokštės generuojamos (CMYK / White / Primer), kiekvienos HotFolderis, thinning px ir kėlimo tvarka (↑ ↓). |
| **Nustatymai** | Serverio aplankas, vietinis rezervas, talpykla (su pasiekiamumo būsena), apdorojimo parametrai, šviesi / tamsi tema. |

Svarbūs įvykiai (įkelta, dalinis įkėlimas, nepavyko, serveris nepasiekiamas) rodomi pranešimais dešinėje viršuje. Trynimas visada su patvirtinimu.

## 🔄 Atnaujinimai (nuotoliniu būdu)
Programa pati tikrina naujas versijas GitHub'e (paleidus ir kas 30 min.) ir pasiūlo atnaujinti.
Paspaudus **„Atnaujinti dabar“**: atsisiunčiama → patikrinamas dydis, SHA-256 ir ZIP → programa užsidaro →
failai pakeičiami → programa pasileidžia iš naujo. Nepavykus – automatiškai atstatoma ankstesnė versija.
`config.json`, `jobs_registry.json` ir žurnalai **niekada neperrašomi**.

Rankinis tikrinimas: viršutinės juostos ⟳ arba **Nustatymai → Atnaujinimai → „Tikrinti atnaujinimus“**.
Diagnostika: `%TEMP%\printflow_updater.log`.

### Kaip išleisti naują versiją
1. Pakeitimus aprašykite `KAS_NAUJO.md` (punktai „- …“, lietuviškai) – tai bus atnaujinimo lango tekstas.
2. Sujunkite pakeitimus į `main`.
3. **GitHub → Actions → „Išleisti PrintFlow Lite atnaujinimą“ → Run workflow** (iš `main`), pasirinkite
   `patch` (taisymai) / `minor` (pastebimi pakeitimai) / `major`.
4. Workflow: versija → testai → kompiliavimas → `PrintFlowLite_vX.Y.Z.zip` → žymė `lite-vX.Y.Z` → GitHub Release.
5. Visi kompiuteriai atnaujinimą pamatys per ≤ 30 min.

**Pirmas įdiegimas**: atsisiųskite `PrintFlowLite_vX.Y.Z.zip` iš GitHub Releases, išarchyvuokite į vartotojo
rašomą aplanką (pvz. `C:\PrintFlowLite\` arba `E:\PrintFlowLite\`, **ne** `Program Files`) ir paleiskite
`PrintFlowLite\PrintFlowLite.exe`. Senąjį `config.json` galite nukopijuoti šalia `.exe`.

## 🛡️ Patikimumas (v1.1 auditas)
| Sritis | Kaip užtikrinta |
|---|---|
| **DPI / geometrija** | Visos White/Primer kaukės tiksliai **300 DPI** tinklelyje (`plate_dpi`). Visos plokštės gauna identiškus `MediaBox / CropBox / TrimBox / BleedBox / ArtBox` ir `/Rotate`. Po generavimo kiekviena plokštė automatiškai patikrinama – nesutapus užsakymas NEkeliamas. |
| **Tinklo strigimai** | Serverio patikra su timeout (`server_timeout_sec`), skenavimas atskiroje gijoje, visos klaidos rodomos žurnale ir `printflow_lite.log`. Dar kopijuojami į serverį failai (`min_file_age_sec`) praleidžiami iki kito ciklo. |
| **Vietinis kaupimas** | Atsisiuntimas `.part ➔ .pdf` su dydžio patikra; nutrūkus tinklui `.part` ištrinamas. |
| **Atmintis** | `jobs_registry.json` rašomas atomiškai (`.tmp ➔ fsync ➔ replace`) su `.bak`; sugadintas failas atkuriamas iš `.bak`, o ne „išvalomas“. Saugu gijoms. Klaidos kartojamos iki `max_attempts`, po to – rankinis „🔁 Pakartoti pažymėtą“. Dalinis įkėlimas niekada nekartojamas automatiškai (dublikatų prevencija). |
| **Be Admin teisių** | Jei programos aplankas neįrašomas – nustatymai ir atmintis keliami į `%LOCALAPPDATA%\PodbasePrintFlowLite`, talpykla – į `%USERPROFILE%\Podbase_PrintFlow_Storage`. |
| **Vienas egzempliorius** | Antras programos paleidimas blokuojamas (kitaip užsakymai būtų keliami dukart). |
| **Startas** | `auto_scan: false` – stebėjimas laukia operatoriaus paspaudimo. |

### Testai ir kompiliavimas
```bat
python -m pytest tests                        :: visi testai (E2E + atnaujinimai)
set PRINTFLOW_TEST_INBOX=E:\Projektai\TEST\INBOX_PRINT_FILES
python tests\test_lite_e2e.py                 :: + realūs gamybiniai PDF
build_lite_exe.bat                            :: testai + PyInstaller --onedir (tik bandymams)
```
GitHub Actions darbo eiga `PrintFlow Lite (Windows EXE)` kiekvieno pakeitimo metu sukompiliuoja ir patikrina `PrintFlowLite.exe` (artefaktas `PrintFlowLite-Windows-x64`).

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
