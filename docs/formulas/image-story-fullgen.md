# Formula — Image · Story · Full-gen

Media **image** (still), use-case **story**: satu **film-still sinematik** (key frame / concept frame / poster shot). **Kesinambungan** dijaga lintas still lewat **referensi** (pakai look-ref karakter / look yang sama → seri konsisten).

Rasio **fleksibel**: bioskop 21:9 / standar 16:9 / **vertikal 9:16** (hape / sosmed).

---

## Intake

- **Adegan / momen** — satu frame kunci.
- **Karakter + ciri** — identity-lock untuk seri.
- **Setting, mood / genre, wardrobe** — tulis hanya yang user sebut. Tak disebut: jangan tambah; pakai dunia realistis apa adanya, jangan geser era / genre / lokasi. User sebut genre (mis. "hutan scifi"): ikuti, boleh spesifik ke arah itu.
- **Rasio** — 21:9 / 16:9 / 9:16.
- **Referensi karakter / look** — untuk kesinambungan antar still.

---

## Prinsip

1. **Satu frame kunci sinematik** — komposisi yang menahan mata (tidak ada gerak).
2. **Kesinambungan lewat referensi** — look-ref karakter / palette yang sama membuat still-still nyambung jadi seri.
3. **Akting beku konkret** (ekspresi / pose), wardrobe, dan cahaya sinematik.
4. **Kunci identitas subjek** — sekali subjek dikenalkan (nama elemen / look-ref "the first reference image" / sebutan pertama), rujuk dengan sebutan yang SAMA di tiap kalimat; jangan ganti ke kata ganti (dia / he / she) yang bisa menggeser kelamin / jumlah / umur. User tak sebut kelamin: tetapkan sekali, pertahankan konsisten.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah; jangan pakai wajah orang asli. → `../references/anti-nsfw.md`

---

## Kerangka blok (skeleton — still)

```
SCENE CONTEXT · ACTIVE REFERENCES (@char) · LOCATION MAP · FIRST FRAME / BLOCKING (komposisi) ·
OPTICS · PERFORMANCE (ekspresi / pose beku) · LIGHTING · COLOR GRADE · WARDROBE · STYLE
```

(Tanpa FORMAT MODE / ACTION / AUDIO — ini gambar diam.)

---

## Rasio (fleksibel)

| target | native | catatan |
|---|---|---|
| bioskop scope 2.39:1 | 21:9 | letterbox / crop tipis di post |
| bioskop flat 1.85:1 | 16:9 atau 21:9 | crop ringan |
| standar | 16:9 | — |
| vertikal (hape / sosmed) | 9:16 | — |

---

## Model

Default: **`../models/nano-banana-pro.md`** — 21:9 / 4k, tajam. Butuh teks / logo dalam frame → `gpt-image-2.md` (maksimal 16:9). Kesinambungan seri → pakai `image_references` look-ref yang sama di tiap still (lihat `../references/reference-intents.md`).

---

## Checklist formula

- Satu frame kunci sinematik; komposisi menahan mata tanpa gerak.
- Karakter + wardrobe + cahaya diarahkan untuk kesinambungan seri (look-ref konsisten).
- Rasio ditentukan (21:9 / 16:9 / 9:16).
- Akting beku konkret. Genre / mood: tegaskan hanya bila user menyebut; bila tidak, pertahankan dunia realistis yang user tulis — perkaya detail di dalam dunia itu, jangan ganti dunianya.
