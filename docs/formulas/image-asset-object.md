# Formula — Image · Asset · Object

Media **image** (still), use-case **asset**, mode **object**: bikin **asset referensi benda TIDAK bernyawa** — produk hero (mis. sepatu), kendaraan (mobil / motor), benda dibawa (gelas), aksesori (jam), atau detail nempel (decal) — buat **ngunci konsistensi** saat generate scene/video. **Berdiri sendiri.** **Wajib hires.** Lapisan **netral model**.

> **Pembeda:** `object` = **tidak bernyawa** (termasuk kendaraan & robot). Makhluk hidup → `image-asset-character.md`. Peran (hero / pendukung / aksesori / nempel) cuma ngatur **jumlah view**, bukan mode terpisah.

---

## Intake — kumpulkan dari pengguna

- **Objek** + ciri terukur (bentuk, warna, material, teks / logo bila ada).
- **PERAN**: `hero` (fokus utama) | `pendukung` | `aksesori` | `nempel`.
- **POSISI** — kalau `nempel`, di mana pada objek induk (mis. "decal di pintu depan kiri, di bawah spion").
- **Material / finish.**
- **Fokus (opsional)** — full object (default) | part tertentu, mis. sol sepatu (dari teks).
- **Reference (opsional)** — ada → objek dibuat match ref (`image_references`).

---

## Prinsip

1. **Independen** — tidak butuh character mode.
2. **Wajib hires** — 4K full-frame; default **4-view** (front / left / right / back).
3. **View:** default 4 panel; **kendaraan** → front/back **¾ dari atas** (roof kelihatan); **nempel** (decal) → 1 plate + POSITION.
4. **POSISI dieja** (kalau nempel) — penempatan saat scene-gen akurat.
5. **Konsistensi objek WAJIB (esp. part / detail)** — model gampang bikin variasi tiap panel (mis. headlamp beda-beda tiap sisi). Enumerasi ciri di OBJECT + LOCK "satu unit identik, turntable"; kalau text-lock masih melenceng → generate 1 view dulu → pakai sbg `image_references` buat view lain.
6. **describe-into-prompt**; **bukan alpha**; background plain neutral; **output blok**; positive-only.
7. **Studio lighting HANYA untuk foto real / 3D** — main + side + rim biar objek kebaca jelas & berdimensi. Style non-foto (kartun / cat air / ilustrasi) ikut gayanya, JANGAN dipaksa studio.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## View-set

Default: **full object**, satu gambar **4 panel** — **front · left · right · back** (skala identik antar panel). Arah hadap eksplisit (sebut sisi objek yg menghadap kamera): **left** = sisi kiri objek ke kamera, **right** = sisi kanan.

- **Kendaraan (mobil / motor):** 4 sisi doang kurang → 4 panel = **left side · right side · front ¾ dari atas · back ¾ dari atas** — front & back di-angle **¾ sedikit dari atas** biar **roof kelihatan**.
- **Nempel (decal / emblem):** bukan objek 3D → **1 plate + POSITION** (bukan 4 view).
- **Fokus (dari teks):** "fokus <part>" (mis. sol sepatu, gagang) → crop ke part itu, tetap multi-view.
- **Label penanda (WAJIB):** teks kecil di **bawah tiap panel** dengan nama angle — `FRONT` · `LEFT` · `RIGHT` · `BACK` (kendaraan: `LEFT SIDE` · `RIGHT SIDE` · `FRONT 3/4` · `REAR 3/4`; angle lain ikut namanya).

---

## Kerangka blok prompt (skeleton)

```
OBJECT      — benda + ciri terukur + **enumerasi sub-part khas SEKALI** (mis. headlamp: proyektor luar, reflektor tengah, strip DRL, bentuk housing & trim) → jadi spesifikasi TETAP yg direproduksi tiap panel; bentuk, warna, material, teks / logo
ROLE        — hero / pendukung / aksesori / nempel (konteks)
VIEWS       — default 4 panel: front · left · right · back (arah hadap eksplisit: left=sisi kiri objek ke kamera, right=kanan; skala identik); KENDARAAN → left side · right side · front ¾-atas · back ¾-atas (roof kelihatan); NEMPEL → 1 plate
FOCUS       — full object (default) | part tertentu (crop, tetap multi-view) — dari teks
POSITION    — (kalau nempel) lokasi item pada objek induk
FORM        — geometri / siluet / konstruksi
MATERIAL    — tekstur, finish, sifat permukaan
SCALE       — porsi frame / ukuran nyata
BACKGROUND  — plain solid, warna PERSIS hex #6B6B6B (abu gelap netral) — tulis string "#6B6B6B" eksplisit di prompt; no gradient / props / reflection; tidak ada objek lain
LIGHTING    — JIKA STYLE foto real / 3D → studio 3-point: main/key + side/fill + rim/back (pisahin objek dari background); objek kebaca jelas & berdimensi, catchlights di permukaan glossy. JIKA STYLE non-foto (kartun / cat air / ilustrasi) → cahaya ikut gaya, JANGAN paksa studio
STYLE       — gaya render: photorealistic photo | 3D render | cartoon | watercolor | illustration | dll. Default `photorealistic photo` kalau tak disebut; nyetir LIGHTING
LABELS      — di bawah tiap panel, teks kecil nama angle: FRONT/LEFT/RIGHT/BACK (kendaraan: LEFT SIDE/RIGHT SIDE/FRONT 3/4/REAR 3/4; angle lain ikut namanya)
LOCK        — SATU unit fisik IDENTIK di semua panel (kayak turntable render objek yang SAMA): geometri, proporsi, jumlah & posisi tiap sub-part, material, warna, STYLE sama PERSIS — objek yang sama diputar, JANGAN redesign / variasikan antar panel. "100% matches @ref" bila reference dilampirkan
```

---

## Model

Default: **`../models/nano-banana-pro.md`**. Berteks / logo (decal, tipografi) → **`../models/gpt-image-2.md`** (string persis dalam tanda kutip; maks 16:9). Model = pilihan operator (final); eksekusi via app → OpenRouter. Upscale saat cocok.

---

## Checklist formula

- Objek (tidak bernyawa) + PERAN ditentukan.
- View default **4 panel** (front/left/right/back); arah hadap eksplisit (left=sisi kiri objek); **kendaraan** front/back ¾-atas (roof); **nempel** 1 plate + POSISI; fokus part → crop.
- **LABEL teks angle** di bawah tiap panel (FRONT/LEFT/RIGHT/BACK; kendaraan LEFT SIDE/RIGHT SIDE/FRONT 3/4/REAR 3/4).
- **Konsistensi:** ciri di-enumerasi di OBJECT + LOCK "satu unit identik turntable, jangan redesign antar panel". Part rumit → fallback generate 1 view → `image_references`.
- Reference di-wire (LOCK "100% matches @ref") bila ada.
- STYLE dinyatakan; studio 3-point (main/side/rim) HANYA kalau foto real / 3D.
- Berlogo → `gpt-image-2`.
- Bukan alpha; BG **#6B6B6B**; output blok; positive-only.
