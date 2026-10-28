# Formula — Video · LED · Full-gen

Media **video**, permukaan **LED** (wall / ceiling / floor), mode **full-gen**: satu adegan atau latar penuh yang menutupi permukaan dan berputar terus (loop).

Formula ini adalah lapisan **netral model** — apa yang dikumpulkan dari pengguna, prinsip output yang baik, kerangka blok prompt (skeleton), dan aturan permukaan LED. Notasi teknis dan parameter diserahkan ke file model (lihat bagian **Model**).

---

## Intake — kumpulkan dari pengguna

- **Permukaan** — wall, ceiling, atau floor.
- **Tema** — abstrak (partikel / gradient / cahaya) atau tematik (awan, laut, kota, alam, kejadian), hanya sesuai yang user sebut. Tak disebut: default abstrak netral; jangan karang tema spesifik.
- **Rasio dan ukuran permukaan** — untuk canvas, mis. 21:9, 32:9, atau custom.
- **Durasi target**, dan **mood / warna** hanya yang user sebut; tak disebut: netral / tenang.
- **Loop** — default ya.
- **Referensi (opsional)** — gambar untuk `style` / `composition` / palette (role `image_references`), atau video acuan untuk **meniru gerak** (motion transfer, role `video_references`). Lihat `../references/reference-intents.md` dan `../models/seedance-2.0.md`.

---

## Prinsip

1. **Latar, bukan tontonan** — gerak pelan dan menerus, tanpa potongan, tanpa subjek dominan yang menarik mata dari orang di panggung.
2. **Loop** — frame terakhir menyambung ke frame pertama (gerak cyclic).
3. **Kedalaman tiga lapis** — foreground, midground, background terpisah agar tidak flat.
4. **Audio opsional** — default mati untuk backdrop; nyalakan bila konten memang butuh suara.
5. **Hemat dulu** — generate resolusi rendah / rasio secukupnya untuk draft, upscale saat sudah cocok.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

Isi tiap blok, buang yang tidak perlu. Kerangka ini **netral model** — cara menuliskannya (mis. FOV dalam derajat, kecepatan dalam km/h) ditentukan oleh file model.

```
SCENE        — adegan atau latar apa, suasananya
DEPTH LAYERS — foreground / midground / background terpisah
MOTION       — gerak pelan, menerus, cyclic (arah dan kecepatan)
LIGHTING     — sumber, arah, kualitas cahaya, kabut
COLOR        — palette diikat ke material + cahaya + peran
OPTICS       — ukuran shot dan seberapa lebar / sempit framing
CAMERA       — diam (lock) atau gerak halus yang bermotivasi
ATMOSPHERE   — kabut / dust / shimmer dan kepadatannya
ORIENTATION  — sesuai permukaan (lihat LED surface rules)
LOOP LOCK    — frame akhir sama dengan frame awal, gerak cyclic
```

---

## LED surface rules (mengisi blok ORIENTATION)

| Permukaan | Sudut pandang | Aturan komposisi & gerak |
|---|---|---|
| **wall** | bidang vertikal, penonton menghadap | perspektif normal, garis horizon boleh, gravitasi normal, gerak horizontal atau vertikal wajar |
| **ceiling** | di atas kepala, penonton mendongak | tanpa horizon, komposisi radial / terpusat, gerak memancar atau berputar dari tengah, terbaca dari berbagai arah bawah |
| **floor** | bidang bawah, penonton menunduk atau menginjak | perspektif top-down, pola aliran / radial, gerak lambat dan stabil (hindari vertigo), tanpa kedalaman jurang |

---

## Canvas

Rasio permukaan menentukan strategi generate dan pipeline After Effects (21:9 langsung, panel, black-bar lalu crop, atau per-element). Lihat `../references/canvas-strategy.md`.

---

## Model

Default: **`../models/seedance-2.0.md`** — video, mendukung 21:9 dan 4k, serta loop mulus (end_image = start_image).

Serahkan intake, prinsip, dan skeleton di atas ke file model. File model menerjemahkan tiap blok ke phrasing modelnya, mengisi parameter, dan menulis prompt final. Model lain bisa dipilih dari `../models/_index.md` (pilihan operator = final).

---

## Checklist formula (sebelum diserahkan ke model)

- Permukaan ditentukan (wall / ceiling / floor) dan aturannya diterapkan pada blok ORIENTATION.
- Tema ditentukan bila user menyebut; tak disebut: default abstrak netral. Cocok sebagai latar.
- Rasio permukaan diketahui sehingga strategi canvas terpilih.
- Semua blok skeleton yang relevan terisi; blok yang tak perlu dibuang.
- Loop diminta (default ya).
- Model default dipilih, atau model lain ditentukan pengguna.
