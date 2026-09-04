# UV Spaudos TIFF Failų (CMYK + Alpha + Spot White W) Generavimo Specifikacija

Šis dokumentas ir šalia esantis failas `crop_engine.py` pateikia pilną techninę logiką, kaip „Podbase“ gamybos linijoje generuojami profesionalūs 6-ių kanalų TIFF failai, suderinami su **ColorGATE RIP** ir **Adobe Photoshop**.

---

## 1. 6-ių Kanalų Struktūra (TIFF Array)

Failas formuojamas kaip `numpy.ndarray` su forma `(Aukštis, Plotis, 6)`, `dtype=uint8` (0..255 reikšmės):

| Kanalo Nr. | Kanalo Pavadinimas | Paskirtis | Reikšmių Reikšmė |
| :--- | :--- | :--- | :--- |
| **0** | **Cyan (C)** | CMYK spalvų kanalas | `0` = 0% dažų, `255` = 100% dažų |
| **1** | **Magenta (M)** | CMYK spalvų kanalas | `0` = 0% dažų, `255` = 100% dažų |
| **2** | **Yellow (Y)** | CMYK spalvų kanalas | `0` = 0% dažų, `255` = 100% dažų |
| **3** | **Black (K)** | CMYK spalvų kanalas | `0` = 0% dažų, `255` = 100% dažų |
| **4** | **Transparency (Alpha)** | Sluoksnio skaidrumas (`ASSOCALPHA`) | `255` = matomas produktas, `0` = 100% permatomas fonas |
| **5** | **Spot White ("W")** | Baltas UV dažų padas po spauda (`UNSPECIFIED`) | `0` = 100% baltas rašalas po dizainu, `255` = 0% baltas rašalas fone |

---

## 2. Adobe Photoshop 8BIM Metaduomenų Blokai (Tag 34377)

Tam, kad „Adobe Photoshop“ atidarytų failą teisingai kaip atskirą sluoksnį su papildomu „Spot Color“ kanalu, į TIFF antraštę įrašomi standartiniai 8BIM Resource blokai:

1. **Resource 1005 (`0x03ED`) – ResolutionInfo**:
   - Nustato fiksuotą **300 DPI** vertikalią ir horizontalią rezoliuciją.
2. **Resource 1006 (`0x03EE`) – Alpha Channel Names**:
   - Paskelbia papildomų kanalų pavadinimus: `\x0cTransparency` ir `\x01W`.
3. **Resource 1045 (`0x0415`) – Unicode Alpha Names**:
   - UTF-16BE koduotės kanalų vardai: `Transparency` ir `W`.
4. **Resource 1077 (`0x0435`) – DisplayInfo v2**:
   - 30 baitų Photoshop struktūra su 4 baitų versijos antrašte:
     - 1-as papildomas kanalas: `ColorSpace=0` (RGB), `Opacity=100%`, `Kind=1` (Mask/Transparency).
     - 2-as papildomas kanalas: `ColorSpace=0` (RGB), `Opacity=100%`, `Solidity=5%`, `Kind=2` (Spot Color).
5. **Resource 1050 (`0x041A`) – Alpha Channel IDs**:
   - Unikalūs kanalų identifikatoriai `1` ir `2`.

---

## 3. TIFF Žymos (TIFF Tags)

- **Tag 332 (`InkSet`)**: Nustatomas į `1` (CMYK + Spot Colors).
- **Tag 333 (`InkNames`)**: Nurodo visų kanalų seką: `Cyan\0Magenta\0Yellow\0Black\0Transparency\0W\0`.
- **Tag 34675 (`ICC Profile`)**: Įterpiamas oficialus `U.S. Web Coated (SWOP) v2` ICC spalvų profilio binarinis masyvas.
- **`photometric='separated'`**: CMYK spalvų atskyrimo režimas.
- **`extrasamples=[1, 0]`**:
  - `1` = `ASSOCALPHA` (Transparency kanalas).
  - `0` = `UNSPECIFIED` (Spot White W kanalas).
- **`byteorder='>'`**: Macintosh / Big-Endian baitų tvarka (Photoshop standartas).
- **`compression='lzw'`**: LZW suspaudimas be kokybės praradimo.

---

## 4. Choke Kaukės Algoritmas (1 px Choke)

Kad baltas UV rašalas neišlystų pro spalvoto dizaino kraštus, Spot White kaukė yra sutraukiama per 1 pikselį (`choke_pixels = 1`):

```python
def _compute_choke_mask(mask: np.ndarray, choke_pixels: int = 1) -> np.ndarray:
    if choke_pixels <= 0:
        return mask
    p = choke_pixels
    eroded = np.zeros_like(mask)
    eroded[p:-p, p:-p] = (
        mask[p:-p, p:-p] & 
        mask[:-p*2, p:-p] & 
        mask[p*2:, p:-p] & 
        mask[p:-p, :-p*2] & 
        mask[p:-p, p*2:]
    )
    return eroded
```

---

## 5. Pagrindinio Variklio Failas

Pilnas Python įgyvendinimas yra faile:
👉 `C:\Users\user\Desktop\crop_engine.py`
