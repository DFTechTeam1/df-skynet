# Formula — Image · LED · Element-gen

Media **image** (still), permukaan **LED**, mode **element-gen**: satu objek diam terisolasi di background keyable, untuk di-**key** menjadi **alpha** lalu di-**layout dan composite di After Effects**.

**Output selalu ber-alpha.** Formula ini lapisan **netral model**; notasi teknis dan parameter ada di file model.

---

## Intake — kumpulkan dari pengguna

- **Objek** dan jumlah (default 1).
- **Permukaan tujuan** (wall / ceiling / floor) — memengaruhi arah pandang dan pencahayaan.
- **Skala relatif** terhadap komposisi akhir.
- **Warna key** — hitam (default), atau greenscreen / bluescreen sesuai konteks.
- **Referensi (opsional)** — media + intent (`subject` untuk memindah objek acuan, `style`, atau `exact`). Lihat `../references/reference-intents.md`.

---

## Prinsip

1. **Satu objek per gambar** — jangan campur.
2. **Output ber-alpha** — key wajib.
3. **Objek utuh di dalam frame** — tidak ada bagian yang terpotong tepi canvas.
4. **Background keyable sesuai konteks** — hitam untuk objek ber-glow; **greenscreen** (umum) atau **bluescreen** untuk objek solid; hindari warna yang ada pada objek.
5. **Cahaya konsisten** — arah cahaya sama untuk semua elemen dalam satu komposisi.
6. **Sadar skala** — sebut porsi frame atau tinggi nyata.
7. **Resolusi tinggi** (upscale saat cocok), tanpa audio.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
SUBJECT      — satu objek, wujud, ciri terukur
FRAMING      — objek utuh, ada ruang kosong di keempat tepi, tidak terpotong
BACKGROUND   — keyable sesuai konteks (hitam / greenscreen / bluescreen), tidak ada elemen lain
LIGHTING     — arah eksplisit, kualitas, konsisten antar elemen
MATERIAL     — tekstur dan sifat permukaan objek
SCALE        — porsi frame atau tinggi nyata, terpusat
OPTICS       — framing objek (biasanya terpusat)
KEY NOTE     — silhouette bersih untuk keying (alpha), tepi tegas
```

**Catatan permukaan:** untuk **ceiling / floor**, arahkan pencahayaan dan pose objek agar terbaca dari sudut pandang penonton.

---

## Model

Default: **`../models/nano-banana-pro.md`** (image). Aspect 16:9 atau 1:1. Pasca-generate, buang background dengan `image_background_remover` untuk menghasilkan alpha.

Serahkan intake, prinsip, dan skeleton ke file model.

---

## Checklist formula

- Satu objek per gambar; output ditujukan ber-alpha.
- Objek utuh di dalam frame, tidak terpotong tepi.
- Background keyable dipilih sesuai konteks (hitam / green / blue).
- Arah cahaya eksplisit dan konsisten dengan elemen lain.
- Skala disebut.
- KEY NOTE (silhouette bersih, tepi tegas) ada.
- Rencana key (`image_background_remover`) dan catatan layout After Effects disiapkan.
