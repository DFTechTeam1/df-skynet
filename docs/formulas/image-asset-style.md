# Formula — Image · Asset · Style

Media **image** (still), use-case **asset**, mode **style**: bikin **plate referensi GAYA VISUAL** — bukan subjek tertentu, tapi **bahasa rupa** (palette · material/tekstur · teknik render · kualitas cahaya · mood) supaya bisa **dikunci konsisten** lintas generate scene/asset lain. **Berdiri sendiri**, **wajib hires**. Lapisan **netral model**.

> Diadopsi dari starter Edward (2026-07-24), di-tune Edwin 2026-08-04. Pasangan hilirnya: plate hasil formula ini dipakai sebagai **style-ref** di `image-restyle.md` (intent `style`) dan sebagai elemen kategori **Visual Styles** di storyboard (`breakdown.md` → `needsAsset`).

---

## Intake — kumpulkan dari pengguna

- **Nama / rujukan gaya** (mis. "neo-noir cyberpunk", "storybook watercolor", "clay stop-motion").
- **Teknik render** — photoreal | 3D | 2D illustration | painterly | cel | dll.
- **Palette** — warna dominan + aksen.
- **Material / tekstur** khas (grain, brush, plastik, logam, kertas…).
- **Cahaya + mood** — kualitas & suhu cahaya, atmosfer.
- **Reference (opsional)** — moodboard / contoh gaya; rujuk secara ordinal (`../references/reference-intents.md`).

---

## Prinsip

1. **Gaya, bukan cerita** — output = *sampel gaya* (style board / swatch), bukan adegan naratif. Subjek sederhana/generik biar fokus ke LOOK.
2. **Wajib hires** — 4K plate.
3. **Describe-into-prompt** — eja tekniknya (teknik render + material + palette + cahaya) sebagai kata; jangan sebut nama seniman/brand nyata (anti-mimic + anti-moderasi).
4. **Bukan alpha**; **output blok**; positive-only; tanpa nama alat / rig.

> **Aman dari moderasi** — frasekan efek + material, bukan label mentah; jangan wajah orang nyata bernama. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
STYLE NAME — label gaya (deskriptif, bukan brand/seniman nyata)
RENDER — teknik: photoreal photo | 3D render | 2D illustration | painterly | watercolor | cel | dll
PALETTE — warna dominan + aksen (ikat ke material + cahaya)
MATERIAL/TEXTURE — grain / brush / permukaan khas gaya
LIGHTING — kualitas + suhu + arah cahaya khas gaya
MOOD — atmosfer / emosi gaya
SAMPLE SUBJECT — subjek generik netral sebagai kanvas gaya (still-life sederhana / sosok berpose netral / patch environment) — cukup untuk MEMPERLIHATKAN gaya, tanpa jadi cerita
LOCK — penegas: RENDER + PALETTE + MATERIAL + LIGHTING tetap konsisten
```

---

## Model

Default: **`../models/nano-banana-pro.md`** — 4K, rasio bebas (1:1 / 4:3 untuk board). Model = pilihan operator (final). Upscale saat cocok. ~~Provider per eksekusi~~ — ARSIP; eksekusi via app → OpenRouter.

---

## Checklist formula

- Teknik render + palette + material + cahaya + mood ditentukan (bahasa rupa, bukan cerita).
- Sample subject = kanvas netral (memperlihatkan gaya, bukan adegan).
- 4K; bukan alpha; output blok; positive-only; tanpa nama alat / seniman / brand nyata.
- Plate siap dipakai ulang: style-ref untuk `image-restyle`, elemen Visual Styles untuk storyboard.
