# Formula — Video · Transition

Media **video**, use-case **transition**: **satu shot kontinu yang membawa penonton dari satu keadaan visual ke keadaan lain**. Bukan story multi-shot (itu `video-story-fullgen`), bukan backdrop loop (itu `video-led-fullgen`). Lapisan **netral model**.

> Diadopsi dari kontribusi Yumna (direction-panel i2v, 2026-07-31) — metode Start–End Frame. Cluster kartu Zainul (hidden-occluder & nested-reveal) menyusul sebagai resep di metode yang sama.

---

## Dua metode (pilih SATU per generate)

| metode | input | inti |
|---|---|---|
| **1 · START–END FRAME** | 2 gambar anchor: frame awal + frame akhir, dua-duanya EXACT | **Fokus = CARA MENTRANSISI dari satu gambar ke gambar lainnya.** Kedua ujung terkunci; seluruh kerja prompt ada di PERJALANAN di antaranya (gerak, motivasi, timing) |
| **2 · OMNI REFERENCE** | kumpulan referensi (subjek / lokasi / style / motion-ref / elemen) | **Bebas nge-TAG referensi ke scene-scene-nya.** User menandai referensi mana berperan apa, di adegan mana — karakter A di scene ini, lokasi B di scene itu, style C menyeluruh. Keadaan akhir TIDAK dikunci frame |

Aturan pilih: user kasih **dua frame pasti** → metode 1. User kasih **referensi ber-tag peran/scene tanpa frame target** → metode 2. Start frame + referensi tambahan = metode 1 dengan ACTIVE REFERENCES sebagai pengunci sekunder.

Dukungan model (semua model video kita bisa metode 1): Seedance `frame_images` first/last · Kling `start/end_image_url` · Hailuo H3 first+last frame. Metode 2: Seedance `input_references` · H3 reference-to-video (≤9 img / 3 vid / 3 aud) · Kling `elements`.

---

## Lihat gambar dulu (WAJIB) — aturan anchor

- **Metode 1 — deskripsi frame RINGKAS, bukan penuh.** Kedua gambar dikirim sebagai **frame anchor** — model MELIHAT pikselnya langsung (beda dari referensi longgar). Maka blok START FRAME / END FRAME cukup **1–2 kalimat per frame**: identitas subjek + detail kritis yang rawan hilang (teks/logo, jumlah objek, warna spesifik). JANGAN parafrase seluruh isi gambar — itu duplikasi anchor + bikin prompt meledak. Porsi prompt terbesar = blok perjalanan (CAMERA / ACTION / PHYSICS).
- **Metode 2:** manifest ordinal semua referensi + **tag peran & scene-nya** ("[1] the first reference image — karakter utama, muncul scene 1–2") + intent (`../references/reference-intents.md`).

---

## Intake — Direction Panel (opsional, semua punya Auto)

Arahan user (dari panel app atau teks bebas) dipetakan ke blok — **Auto / tak diisi = jaga karakter visual input, JANGAN karang**:

| arahan | → blok | catatan |
|---|---|---|
| Camera Move (SATU gerak kontinu) | CAMERA | Static = viewpoint diam; nama rig TIDAK diteruskan — gerak positif |
| Speed Ramp / tempo | ACTION | tulis sebagai **timing-beats** ("0.0–3.5s … 3.5–5.0s …") |
| Genre (drama / action / noir / …) | STYLE | phrasing bahasa visual, bukan param |
| Colour Palette | COLOR GRADE | Auto = jaga relasi palette kedua input |
| Lighting | LIGHTING | Auto = jaga logika cahaya kedua input |
| Camera Settings / framing | OPTICS | FOV konsisten sepanjang shot |
| Rasio · durasi · resolusi · audio | params (app) | audio default mati |

---

## Prinsip

1. **Satu shot kontinu, NO CUT mutlak** — kamera tidak pernah cut sendiri; satu trajectory dari awal sampai akhir; gerak **smooth ber-easing** (akselerasi halus, ease-out presisi), tanpa sentakan. **Konteks LED/panggung: wajib** — transisi backdrop harus mulus total (referensi hasil lapangan Zainul: smooth no-cut); pacing kalem, tanpa gerak kasar yang mengganggu panggung. LED lebih lebar dari rasio model → `../references/canvas-strategy.md`.
2. **Anchor ketat (metode 1)** — frame 0 match START exact; frame akhir match END exact; ease-out presisi ke frame akhir.
3. **Identitas stabil** — subjek yang terlihat menjaga identitas, jumlah, material, tekstur, warna sepanjang shot (identity-lock).
4. **Gerak termotivasi** — perpindahan lewat gerak fisik (retreat, reveal, parallax, occlusion), bukan morph/dissolve ajaib, kecuali user minta.
5. **Positive-only**; tanpa nama alat / rig; timing-beats untuk progres waktu.
6. **Budget WAJIB ≤ ~2.200 char** (Kling-safe; base #5) — kunci hematnya = aturan anchor di atas (frame tidak diparafrase penuh). Resep A/B pun harus terisi dalam budget ini; pangkas prosa, LOCKS selamat.

> **Aman dari moderasi** — efek + material + cahaya, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
SCENE CONTEXT   — satu shot kontinu dari [keadaan A] ke [keadaan B] + relasi keduanya
START FRAME     — (metode 1) RINGKAS: identitas + detail kritis gambar awal (anchor = pikselnya)
END FRAME       — (metode 1) RINGKAS: identitas + detail kritis gambar akhir
ACTIVE REFERENCES — (metode 2 / pengunci sekunder) manifest ordinal + intent
LOCATION MAP    — ruang sebelum · (bidang transisi bila ada) · ruang sesudah
FIRST FRAME / BLOCKING — frame 0 match START exact
FORMAT MODE     — one continuous shot, no cut
OPTICS          — FOV konsisten
CAMERA          — satu gerak kontinu + ease-out ke frame akhir
ACTION          — timing-beats progres transisi
PHYSICS         — parallax / bobot / inersia nyata
LIGHTING        — cahaya A → cahaya B, transisi fisik
COLOR GRADE     — palette A → palette B
STYLE           — genre/moveset sebagai bahasa visual
OUTPUT SETTINGS — real-time, one continuous take, exact start & end adherence
POSITIVE LOCKS  — anchor + identitas + trajectory tunggal
```

---

## Resep metode 1 (dari kontribusi Zainul, 2026-08-01) — OPSIONAL, deteksi dari intent

**Resep ≠ jalur wajib.** Tidak semua transisi harus memakai pola ini. Aturannya:

- **Intent user SUDAH mengarah ke salah satu pola** → terapkan resepnya **OTOMATIS**, tanpa bertanya. Sinyal: user eksplisit minta efeknya ("zoom out dari detail", "kamera mundur nembus", "pindah dunia tanpa keliatan", "kayak one-shot"), ATAU dua gambarnya sendiri bercerita — bisa hidup di **satu dunia fisik** → Nested Reveal; **dua dunia beda / tak berhubungan** → Hidden Occluder (transisi polos antar dua dunia bakal morph jelek — occluder = penyelamat alaminya).
- **Intent TIDAK mengarah ke pola mana pun** → tulis transisi netral biasa (gerak termotivasi generik sesuai Prinsip), **jangan paksakan resep**.

### A · Nested Reveal — start = detail di dalam dunia end

- SCENE CONTEXT: konten START adalah **detail nyata** yang berada di [relasi spasial: di mana persisnya detail itu di dalam dunia END]. Dunia terungkap lewat mundurnya viewpoint + depth + parallax.
- LOCATION MAP **3 lapis**: detail awal · ruang penghubung · lingkungan penuh — ketiganya SATU dunia fisik yang koheren.
- CAMERA: mundur kontinu (akselerasi halus di awal → ease-out presisi ke frame akhir), FOV konstan; fokus mengikuti depth ruang nyata.
- PHYSICS: FG/MG/BG terpisah lewat **parallax otentik**; transisi murni dari spatial reveal — tanpa occluder, tanpa morph.
- LIGHTING/COLOR: satu sumber cahaya bersama; pola cahaya & palette END muncul hanya karena bidang pandang melebar.

### B · Hidden Occluder — pergantian dunia disembunyikan

- SCENE CONTEXT: viewpoint mundur menembus dunia START, **lewat di belakang [OCCLUDER full-frame]**, keluar di dunia END yang **sudah stabil & lengkap** saat pandangan terbuka.
- LOCATION MAP 3 bagian: ruang sebelum · **bidang occluder** (elemen fisik foreground yang wajar mengisi SELURUH frame — posisi, material, tekstur, geraknya) · ruang sesudah.
- ACTION timing-beats 3 babak — **PROPORSI durasi, bukan detik mati**: **~35%** retreat di dunia A (+gerak objek sekunder) → **~15%** occluder mengisi tiap bagian frame, dunia B di-establish penuh SELAMA tertutup → **~50%** pandangan terbuka di dunia B, trajectory & momentum kamera SAMA, resolve ke END exact. (Contoh 10 dtk: 0–3.5 / 3.5–5 / 5–10.) Tulis detik hasil hitungnya di prompt sesuai durasi yang dipilih operator.
- PHYSICS: occluder punya ketebalan nyata, detail permukaan, proximity-parallax; bukan wipe/fade editorial.
- POSITIVE LOCKS tambahan: occluder mengisi seluruh frame saat interval tertutup; dunia B sudah stabil sebelum terbuka; momentum kamera kontinu lintas transisi.

Gerak objek sekunder boleh beda sebelum/sesudah (A maupun B) selama state akhirnya match END.

---

## Model

Model = pilihan operator (final). Default: **`../models/seedance-2.0.md`** (frame first/last + physics kuat). Durasi >12 dtk / multi-shot → `../models/kling-3.0.md` (ingat cap 2.500). 2K + audio native → `../models/minimax-h3.md`. Hemat → `../models/cinema-studio-video.md` (1.5 Pro; cek dukungan end-frame di form app dulu). ⚠️ Frame berisi manusia fotorealistik → jangan Seedance (`../references/anti-nsfw.md` §F).

---

## Checklist formula

- Metode ditentukan (start-end / omni-ref), tidak dicampur aduk.
- Metode 1: KEDUA frame dideskripsikan RINGKAS (aturan anchor); frame 0 & frame akhir dikunci di POSITIVE LOCKS.
- Resep dipakai HANYA bila intent user mengarah ke polanya (auto, tanpa nanya); selain itu → transisi netral.
- Metode 2: manifest ordinal + intent tiap referensi.
- Satu shot kontinu, satu trajectory; gerak termotivasi fisik.
- Arahan panel dipetakan ke blok; Auto = jaga karakter input, tanpa karang.
- Timing-beats di ACTION; positive-only; tanpa rig; ≤ budget.
