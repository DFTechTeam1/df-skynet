# Formula — Image · Asset · Character

Media **image** (still), use-case **asset**, mode **character**: bikin **asset referensi makhluk BERNYAWA** (manusia / hewan / makhluk fantasi / monster) dari beberapa view + closeup, buat **ngunci konsistensi** saat generate scene/video. **Berdiri sendiri.** **Wajib hires.** Lapisan **netral model**.

> **Pembeda:** `character` = **bernyawa**. Benda mati (produk, kendaraan, robot, aksesori) → `image-asset-object.md`.

---

## Intake — kumpulkan dari pengguna

- **Jenis**: `manusia` | `hewan` | `makhluk fantasi` | `monster`.
- **Anatomi / ciri identitas** terukur.
- **Pose default** + **ekspresi** (netral by default).
- **Wardrobe / kulit / bulu / sisik** + tekstur.
- **Palette.**
- **Fokus (opsional)** — full body (default) | wajah | tangan / part lain (dari teks).
- **Reference (opsional)** — dari kita / klien (hires). Ada → `image_references` intent `subject`/`exact`; gak ada → dari spec teks. Lihat `../references/reference-intents.md`.

---

## Prinsip

1. **Independen** — tidak butuh mode asset lain.
2. **Wajib hires** — 4K; wajah / kepala (paling rawan error) dibuat **plate full-frame terpisah**.
3. **Satu makhluk identik di semua view** — identitas / anatomi / proporsi / palette konsisten (LOCKS).
4. **describe-into-prompt** — eja tiap ciri.
5. **Bukan alpha** — referensi, bukan elemen composite. Background plain solid **#6B6B6B** (abu gelap netral) + divider tipis.
6. **Output blok berlabel** (bukan paragraf).
7. **positive-only**; jangan sebut nama alat / rig kamera.
8. **Studio lighting HANYA untuk foto real / 3D** — main + side + rim biar karakter kebaca jelas & berdimensi. Style non-foto (kartun / cat air / ilustrasi) ikut gayanya, JANGAN dipaksa studio.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; **jangan pakai wajah orang asli / selebriti** sebagai reference (anti-deepfake) — pakai subjek stylized / generated. → `../references/anti-nsfw.md`

---

## View-set

Default: **full body**, satu gambar **4 panel** — **front · left · right · back** (pose & skala identik antar panel).

**Arah hadap eksplisit** (biar left/right TAK ketuker — sebut posisi kamera, bukan cuma "profile"):
- **front** — menghadap kamera.
- **left** — kamera di sisi **KIRI** subjek (sisi kiri subjek menghadap kamera).
- **right** — kamera di sisi **KANAN** subjek.
- **back** — membelakangi kamera.

**Label penanda (WAJIB):** render teks kecil di **bawah tiap panel** dengan nama angle-nya — `FRONT` · `LEFT` · `RIGHT` · `BACK`. Kalau pakai angle lain, label ikut nama angle itu.

**Fokus (dari teks brief):** kalau brief nyebut "fokus / tampil **wajah**" → keempat view di-crop **leher ke atas**. "fokus **tangan**" / part lain → cuma part itu, tetap 4 view. Default (tak disebut) = **full body**.

---

## Kerangka blok prompt (skeleton)

```
SUBJECT            — jenis makhluk + ciri identitas terukur
VIEWS              — 4 panel: front (hadap kamera) · left (kamera di sisi KIRI subjek) · right (kamera di sisi KANAN) · back (belakang); pose & skala identik antar panel
FOCUS              — full body (default) | wajah (leher ke atas) | tangan / part lain (crop ke part itu) — dari teks; tetap 4 view
ANATOMY/BUILD      — proporsi tubuh, struktur, ciri anatomis khas
WARDROBE/COVERING  — pakaian / kulit / bulu / sisik + tekstur
EXPRESSION         — ekspresi wajah / bahasa tubuh (netral by default)
PALETTE            — warna kunci, diulang konsisten antar view
LIGHTING           — JIKA STYLE foto real / 3D → studio 3-point: main/key (arah utama) + side/fill (isi bayangan lembut) + rim/back (pisahin subjek dari background); subjek kebaca jelas & berdimensi, 5600K, catchlights di mata. JIKA STYLE non-foto (kartun / cat air / ilustrasi) → cahaya ikut gaya, JANGAN paksa studio
BACKGROUND         — plain solid background, warna PERSIS hex #6B6B6B (abu gelap netral) — tulis string "#6B6B6B" eksplisit di prompt; no gradient / props / reflection; thin dark dividers antar panel
STYLE              — gaya render: photorealistic photo | 3D render | cartoon | watercolor | illustration | dll. Default `photorealistic photo` kalau tak disebut; nyetir LIGHTING
LABELS             — di bawah tiap panel, teks kecil nama angle: FRONT / LEFT / RIGHT / BACK (atau nama angle lain bila beda)
LOCKS              — satu makhluk identik semua view (identitas / anatomi / proporsi / palette / STYLE); kaki / telapak terlihat; backdrop & cahaya identik
```

---

## Model

Default: **`../models/nano-banana-pro.md`** — 4K, multi-ref. Aspect: sheet 16:9 / 21:9; closeup 1:1 / 4:5. Model = pilihan operator (final); eksekusi via app → OpenRouter. Upscale saat cocok. Serahkan intake / prinsip / skeleton ke file model.

---

## Checklist formula

- Jenis makhluk (bernyawa) ditentukan.
- View default **4 panel** (front/left/right/back) full body; arah hadap eksplisit (left=kamera sisi KIRI subjek, right=KANAN); fokus (wajah=leher ke atas / tangan / part) → crop, tetap 4 view.
- **LABEL teks angle** (FRONT/LEFT/RIGHT/BACK) di bawah tiap panel.
- Satu makhluk identik semua view (LOCKS).
- Reference opsional di-wire (`subject` / `exact`) bila ada.
- STYLE dinyatakan; studio 3-point (main/side/rim) HANYA kalau foto real / 3D.
- Bukan alpha; BG **#6B6B6B** + divider; output blok.
- describe-into-prompt; positive-only; tanpa nama alat.
