# Formula — Video · Story · Full-gen

Media **video**, use-case **story** (film / narasi). **Inti story = kesinambungan antar shot** (karakter, look, geometri konsisten) — bukan rasio tertentu. Rasio **fleksibel**: bioskop (21:9), standar (16:9), atau **vertikal (9:16, hape / sosmed)**.

Beda dari LED: ini **tontonan** — ada subjek, akting, cerita, potongan. Pakai **semua** blok sinematik. Format & notasi ada di file model (bagian **Story / cinematic**).

---

## Intake

- **Beat cerita / adegan** — apa yang terjadi.
- **Karakter + ciri** — untuk identity-lock.
- **Setting, waktu, mood / genre** — tulis hanya yang user sebut. Tak disebut: jangan tambah; pakai dunia realistis apa adanya, jangan geser era / genre / lokasi. User sebut genre: ikuti.
- **Rasio** — 21:9 bioskop / 16:9 standar / 9:16 vertikal.
- **Struktur potongan** — satu shot / beberapa cut / timed.
- **Referensi karakter** (look-ref) — untuk kesinambungan.

---

## Prinsip

1. **Kesinambungan = nyawa.** Karakter, wardrobe, cahaya, arah pandang, screen-direction, prop **tetap** lintas shot.
2. **Tontonan** — akting konkret (gerak otot, bukan label), blocking jelas, pace sesuai dramatik.
3. **Motivate every camera move.**
4. Positive-only; **jangan sebut alat / rig kamera** (dirender jadi objek).
5. **Kunci identitas subjek** — sekali subjek dikenalkan (nama elemen / look-ref "the first reference image" / sebutan pertama), rujuk dengan sebutan yang SAMA di tiap shot / kalimat; jangan ganti ke kata ganti yang bisa menggeser kelamin / jumlah / umur. User tak sebut kelamin: tetapkan sekali, pertahankan konsisten.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah; jangan pakai wajah orang asli. → `../references/anti-nsfw.md`

---

## Kerangka blok (skeleton penuh)

```
SCENE CONTEXT · ACTIVE REFERENCES (@char) · LOCATION MAP · FIRST FRAME / BLOCKING ·
FORMAT MODE (cuts / timing) · OPTICS · CAMERA · ACTION · PERFORMANCE · PHYSICS ·
LIGHTING · COLOR GRADE · WARDROBE · AUDIO · STYLE · OUTPUT SETTINGS · POSITIVE LOCKS
```

---

## Kesinambungan (dua mode)

**A. Dalam satu generate (multishot).** Pakai FORMAT MODE cuts. Lintas cut, **pertahankan**: karakter sama, geometri, screen-direction, gaze, cahaya, wardrobe, prop-state.

**B. Antar generate (shot terpisah, dirakit di edit).** Kunci pakai **look-ref karakter yang sama** (referensi ter-attach yang sama, dirujuk ordinal) di tiap shot + wardrobe & cahaya dideskripsikan sama + **POSITIVE LOCKS** mengulang identitas. Bisa **chain**: frame akhir shot N jadi `start_image` shot N+1 (`frame_images` frame_type first — sambungan mulus). **Jangan** `end = start` (itu loop, bukan story).

---

## Directing

- **Blocking** — posisi tiap karakter, tangan, apa yang di antara mereka.
- **Pace** — confession → ruang / held shot; action → cut pendek; reveal → satu close-up ditahan.
- **Acting** — emosi jadi arahan konkret ("rahang mengencang, menelan sekali", bukan "marah"). Restraint by default.
- **Continuity** — state terbawa (basah / kering / berdarah), emosi nyambung dari shot sebelumnya, satu waktu & cuaca kecuali lokasi ganti.
- **Camera language** — konkret: FOV°, tinggi, gerak, **motivasi** tiap move.

---

## Cuts / timing

Pilih presisi sesuai kebutuhan: **oner** (satu shot) / **sequential** (CUT 1 · CUT 2 · CUT 3) / **timed** (HARD CUT di detik tertentu) / **freestyle** (b-roll). Tipe cut: `HARD CUT` · `SMASH CUT` · `MATCH CUT` · `INSERT CUT` · `REVERSE CUT` · `WHIP CUT`. Format detail di file model. Selalu kunci: "cuts only at the specified points, the camera does not cut on its own."

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

Default: **`../models/seedance-2.0.md`** — identity-lock (`image_references`), chaining start/end frame, cuts, 21:9 & 9:16. Multishot native + kontrol genre → `cinematic_studio_video_v2` (maksimal 16:9). Bagian **Story / cinematic** di file model = notasi cuts/timing/continuity.

---

## Checklist formula

- Kesinambungan diamankan (identity-lock karakter + wardrobe / cahaya konsisten + POSITIVE LOCKS).
- Rasio ditentukan (21:9 / 16:9 / 9:16).
- Struktur potongan dipilih (oner / sequential / timed) + "cuts only at specified points".
- Blocking + acting konkret; tiap camera move ada motivasi.
- Semua kalimat positif; tanpa nama alat / rig kamera.
