# Mimaki RasterLink 7 Gamybinė Specifikacija ir Protokolai

Šis dokumentas aprašo tikslią „Mimaki RasterLink 7“ (v4.x+) vidinę mechaniką, taisykles ir techninius protokolus, būtinus 100% automatizuotai gamybai.

---

## 1. Kodėl kyla klaidos ir kaip jas eliminuoja sistema

### Problema: „cannot be printed at the same time [White, Primer]“
* **Priežastis:** Mimaki spausdintuvuose (UJF, JFX serijose) Gruntas (**Primer**) ir Baltas rašalas (**White**) yra fizinės atskiros galvutės (**Additional Colors**).
* Jei bandoma įkelti vieną failą, kuriame yra abu šie kanalai viename lape be suderinto 3-jų sluoksnių spaudos profilio, RasterLink atmeta užduotį.
* **Sprendimas:** Gamybinėje linijoje failas **privalo būti išskaidytas į atskiras plokštes (Plates)**:
  1. `[Uzsakymas]_Primer.pdf` $\to$ Hot Folder su `Mono Color (Primer)`
  2. `[Uzsakymas]_White.pdf` $\to$ Hot Folder su `Mono Color (White)`
  3. `[Uzsakymas]_CMYK.pdf` $\to$ Hot Folder su `Full Color`

---

## 2. Oficialūs Spot Kanalų Pavadinimai PDF/PostScript lygmenyje

| Paskirtis | Oficialus Mimaki Vardas | PDF Objekto Sintaksė | Overprint Būsena |
| :--- | :--- | :--- | :--- |
| **Baltas rašalas** | `RawWhite` | `/Separation /RawWhite /DeviceCMYK` | `/OP true /op true /OPM 1` |
| **Gruntas (Primer)**| `RawPrimer` / `Primer` | `/Separation /RawPrimer /DeviceCMYK`| `/OP true /op true /OPM 1` |
| **Lakavimas (Clear)**| `RawClear` | `/Separation /RawClear /DeviceCMYK` | `/OP true /op true /OPM 1` |
| **Pjaustymo linija** | `CutContour` | `/Separation /CutContour /DeviceCMYK`| `/OP true /op true /OPM 1` (0.25–0.5 pt) |

---

## 3. Choke (Erozijos) Algoritmas

Kad baltas padas neišlystų pro CMYK kraštus:
* Vykdoma $1 \text{ px}$ arba $2 \text{ px}$ kaimyninių pikselių `bitwise AND` operacija.
* $1 \text{ px} = \frac{1}{300} \text{ colio} \approx 0.084 \text{ mm}$ (idealu smulkiam tekstui ir vektorinei grafikai).
* $2 \text{ px} = \frac{2}{300} \text{ colio} \approx 0.169 \text{ mm}$ (rekomenduojama stambiems objektams ir dėklams).

---

## 4. RasterLink 7 „Composition“ Medžio Struktūra

Kai darbai sujungiami į medį:
* **Tėvinis darbas (Parent):** Pagrindinė užduotis (`Job Name: [Užsakymo ID]`, `Attribute: Color`).
* **Vaikas 1:** `WhitePlate Type` (susietas su White rašalo nustatymais).
* **Vaikas 2:** `PrimerPlate Type` (susietas su Primer UV kietinimo rėžimu).
* **Spaudos seka (Layer Order):**
  $$\text{1 Sluoksnis: Primer} \longrightarrow \text{2 Sluoksnis: White} \longrightarrow \text{3 Sluoksnis: Color}$$
