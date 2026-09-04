# Gamybinio Variklio Architektūra (Production Grade)

Šiame dokumente pateikiama techninė specifikacija sistemai, kuri veikia be jokių fiktyvių (mockup) elementų.

---

## 1. Branduolio Komponentai

1. **Pre-Press Processor (`prepress.py`):**
   * Įvestis: `PDF / TIFF / PNG / JPG`.
   * Visi procesai atliekami per 64-bit NumPy matricų operacijas.
   * `PyMuPDF` užtikrina PDF srautų analizę, mastelį ir 300 DPI rastravimą.
   * `ReportLab` užtikrina švarių PostScript/PDF 1.4 suderinamų plokščių generavimą su tiksliais `MediaBox`, `ColorSpace` ir `ExtGState` atributais.

2. **Hot Folder Router (`router.py`):**
   * Saugo konfigūraciją `presets.json`.
   * Automatiškai patikrina ir sukuria reikiamus aplankus diske.
   * Naudoja saugias atominio failų perkėlimo operacijas (`shutil.copy2` su klaidų gaudymu).

3. **Fono Valdiklis (`rasterlink_bridge.py`):**
   * Windows API (`win32gui`, `win32con`) fono gija.
   * Stebi langus su klase `#32770` ir automatiškai patvirtina įspėjimus.

4. **Operacinė Sąsaja (Kiosk Web UI):**
   * Realaus laiko Canvas 2D peržiūra (Composite, CMYK, Choked White, Primer).
   * Barcode / Scanner palaikymas su automatiniu užsakymo priskyrimu.
   * Greitaveika: visas pre-press ciklas $\le 300\text{ ms}$.

---

## 2. Žingsniai Standalone `.EXE` Kompiliavimui

Norint viską supakuoti į vieną `.exe` failą:
* Naudojamas `PyInstaller` su `--onefile --windowed`.
* Įterpiami visi statiniai failai (`templates`, `presets.json`, `static`).
* Vykdomasis failas neturi jokių išorinių priklausomybių ir pasileidžia bet kokiame Windows 10/11 kompiuteryje be instaliuoto Python.
