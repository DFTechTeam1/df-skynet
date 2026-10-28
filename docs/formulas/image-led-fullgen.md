# Formula — Image · LED · Full-gen

Media **image** (still), permukaan **LED** (wall / ceiling / floor), mode **full-gen**: satu gambar diam penuh yang menutupi permukaan. Karena diam, **komposisi** yang menahan mata, bukan gerak.

Formula ini lapisan **netral model**. Notasi teknis dan parameter ada di file model.

---

## Intake — kumpulkan dari pengguna

- **Permukaan** — wall, ceiling, atau floor.
- **Tema** — abstrak atau tematik, hanya sesuai yang user sebut. Tak disebut: default abstrak netral; jangan karang tema spesifik.
- **Rasio dan ukuran permukaan** — untuk canvas, mis. 21:9, 32:9, custom.
- **Mood / warna** — hanya yang user sebut; tak disebut: netral / tenang. Plus resolusi target.
- **Referensi (opsional)** — satu atau lebih media + intent (`exact` / `composition` / `style` / `subject` / `pose`), bisa di-blend. Mis. render 3D untuk ambil **composition**-nya saja. Lihat `../references/reference-intents.md`.

---

## Prinsip

1. **Latar yang tenang** — komposisi seimbang, tidak ada titik yang terlalu ramai menarik mata dari panggung.
2. **Kedalaman tiga lapis** — foreground, midground, background agar tidak flat.
3. **Hemat dulu** — mulai resolusi rendah dan rasio secukupnya untuk draft, upscale saat sudah cocok; 4k hanya untuk final besar.
4. **Tanpa gerak, tanpa audio** — ini gambar diam.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
SCENE        — adegan atau latar apa, suasananya
DEPTH LAYERS — foreground / midground / background terpisah
COMPOSITION  — penempatan elemen dan titik fokus (menahan mata tanpa gerak)
LIGHTING     — sumber, arah, kualitas cahaya, kabut
COLOR        — palette diikat ke material + cahaya + peran
OPTICS       — ukuran shot dan seberapa lebar / sempit framing
ATMOSPHERE   — kabut / dust / shimmer dan kepadatannya
ORIENTATION  — sesuai permukaan (lihat LED surface rules)
```

---

## LED surface rules (mengisi blok ORIENTATION)

| Permukaan | Sudut pandang | Aturan komposisi |
|---|---|---|
| **wall** | bidang vertikal, penonton menghadap | perspektif normal, garis horizon boleh, gravitasi normal |
| **ceiling** | di atas kepala, penonton mendongak | tanpa horizon, komposisi radial / terpusat, terbaca dari berbagai arah bawah |
| **floor** | bidang bawah, penonton menunduk atau menginjak | perspektif top-down, pola aliran / radial, tanpa kedalaman jurang |

---

## Canvas

Rasio permukaan menentukan strategi generate dan pipeline After Effects. Lihat `../references/canvas-strategy.md`. Untuk gambar, upscale memakai `bytedance_image_upscale` atau `topaz_image`.

---

## Model

Default: **`../models/nano-banana-pro.md`** — image, mendukung 21:9 dan 4k, tajam. Alternatif: `gpt-image-2.md` (unggul teks / tipografi, maks 16:9). Lihat `../models/_index.md`.

Serahkan intake, prinsip, dan skeleton ke file model.

---

## Checklist formula

- Permukaan ditentukan dan aturannya diterapkan pada blok ORIENTATION.
- Tema ditentukan bila user menyebut; tak disebut: default abstrak netral. Cocok sebagai latar tenang.
- Rasio permukaan diketahui sehingga strategi canvas terpilih.
- Komposisi menahan mata tanpa mengandalkan gerak.
- Model default dipilih, atau model lain ditentukan pengguna.
