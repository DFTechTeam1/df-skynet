# Formula — Video · LED · Element-gen

Media **video**, permukaan **LED**, mode **element-gen**: satu objek terisolasi (bunga, burung, kupu-kupu, partikel, api, ikan, dan sejenisnya) yang di-**key** menjadi **alpha**, lalu di-**layout dan composite di After Effects**. Dipakai juga saat permukaan terlalu panjang (mis. 100:6) sehingga semua elemen dirakit di AE.

**Output selalu ber-alpha.** Formula ini lapisan **netral model**; notasi teknis dan parameter ada di file model.

---

## Intake — kumpulkan dari pengguna

- **Objek** dan jumlah (default 1).
- **Aksi** objek.
- **Permukaan tujuan** (wall / ceiling / floor) — memengaruhi arah pandang dan pencahayaan.
- **Skala relatif** terhadap komposisi akhir.
- **Warna key** — hitam (default), atau greenscreen / bluescreen sesuai konteks.

---

## Prinsip

1. **Satu objek per klip** — jangan campur; susah di-key dan di-layout.
2. **Output ber-alpha** — key wajib; tujuan akhirnya objek transparan di atas apa pun.
3. **Objek utuh di dalam frame** — tidak ada bagian yang terpotong tepi canvas, agar utuh saat di-composite.
4. **Background keyable sesuai konteks** — hitam untuk glow / partikel / api; **greenscreen** (umum) atau **bluescreen** untuk objek solid; hindari warna yang ada pada objek.
5. **Gerak tertahan (contained)** — objek bergerak di dalam frame, tidak menyentuh atau melewati tepi.
6. **Cahaya konsisten** — arah cahaya sama untuk semua elemen dalam satu komposisi.
7. **Sadar skala** — sebut porsi frame atau tinggi nyata.
8. **Loop** — frame terakhir menyambung ke frame pertama (cyclic).
9. **Audio opsional** — biasanya mati untuk elemen.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
SUBJECT      — satu objek, wujud, ciri terukur
ACTION       — gerak tertahan di dalam frame, cyclic
FRAMING      — objek utuh, ada ruang kosong di keempat tepi, tidak terpotong
BACKGROUND   — keyable sesuai konteks (hitam / greenscreen / bluescreen), tidak ada elemen lain
LIGHTING     — arah eksplisit, kualitas, konsisten antar elemen
MATERIAL     — tekstur dan sifat fisika objek
SCALE        — porsi frame atau tinggi nyata, terpusat
OPTICS       — framing objek (biasanya terpusat), tanpa drift
LOOP LOCK    — frame akhir sama dengan frame awal, cyclic
KEY NOTE     — silhouette bersih untuk keying (alpha), tanpa motion blur yang bleed ke background
```

**Catatan permukaan:** untuk **ceiling / floor**, arahkan pencahayaan dan pose objek agar terbaca dari sudut pandang penonton (mendongak / menunduk).

---

## Model

Default: **`../models/seedance-2.0.md`** (video). Aspect 16:9 atau 1:1. Pasca-generate, buang background dengan `sam_3_video` untuk menghasilkan alpha.

Serahkan intake, prinsip, dan skeleton ke file model.

---

## Checklist formula

- Satu objek per klip; output ditujukan ber-alpha.
- Objek utuh di dalam frame, tidak terpotong tepi.
- Background keyable dipilih sesuai konteks (hitam / green / blue).
- Gerak tertahan dan cyclic.
- Arah cahaya eksplisit dan konsisten dengan elemen lain.
- Skala disebut.
- KEY NOTE (silhouette bersih, tanpa motion-blur bleed) ada.
- Rencana key (`sam_3_video`) dan catatan layout After Effects disiapkan.
