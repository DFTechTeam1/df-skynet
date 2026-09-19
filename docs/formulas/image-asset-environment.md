# Formula — Image · Asset · Environment

Media **image** (still), use-case **asset**, mode **environment**: bikin **plate referensi setting / suasana** buat **ngunci kondisi visual** saat scene/video. **Berdiri sendiri** (kadang tak dibutuhkan). **Wajib hires.** Umumnya **tanpa karakter**. Lapisan **netral model**.

---

## Intake — kumpulkan dari pengguna

- **Lokasi / setting.**
- **Mood / atmosfer**, **waktu / cahaya.**
- **Palette.**
- **Reference (opsional)** — mood / style.

---

## Prinsip

1. **Independen** — opsional; hanya bila lock suasana dibutuhkan.
2. **Wajib hires** — 4K plate.
3. **Tanpa karakter** (default).
4. **Single plate** (bukan turnaround multi-panel) → tak ada angle/panel, jadi **tak ada label penanda** (beda dari character/object).
5. **describe-into-prompt**; **bukan alpha**; **output blok**; positive-only; tanpa nama alat / rig.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
SCENE         — setting / lokasi
LOCATION MAP  — FG / MG / BG (kedalaman)
LIGHTING      — arah, kualitas, suhu Kelvin
COLOR/PALETTE — ikat ke material + cahaya
MOOD          — atmosfer
STYLE         — gaya render: photorealistic photo | 3D render | cartoon | watercolor | illustration | dll (samain gaya target scene). Default `photorealistic photo` kalau tak disebut
LOCK          — penegas konsistensi (palette / mood / STYLE tetap)
```

---

## Model

Default: **`../models/nano-banana-pro.md`** — 21:9 / 4k. Model = pilihan operator (final); eksekusi via app → OpenRouter. Upscale saat cocok.

---

## Checklist formula

- Setting + mood + cahaya + palette + STYLE ditentukan.
- 4K; default tanpa karakter.
- Reference mood / style di-wire bila ada.
- Bukan alpha; output blok; positive-only; tanpa nama alat.
