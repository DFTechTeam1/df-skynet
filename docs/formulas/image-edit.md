# Formula — Image · Edit

Media **image** (still), use-case **edit**: **ubah gambar yang sudah ada** — **tambah / kurangi / perbaiki** objek. Gambar yang di-attach = **BASE** (img2img), bukan style-ref. Boleh + **SOURCE** opsional (objek yang mau ditambah). **Wajib lihat tiap gambar** (describe-into-prompt). Lapisan **netral model**.

> **ACTION** = `add` | `remove` | `fix` — **field**, disimpulkan dari teks bebas (bukan mode terpisah). Satu skeleton, penekanan beda per action.

---

## Lihat gambar dulu (WAJIB)

image-edit selalu punya minimal 1 gambar attach. Sebelum menulis prompt:

1. **Lihat SEMUA gambar** yang dilampirkan.
2. Tentukan peran tiap gambar:
   - **BASE** — gambar target yang diedit (selalu ada; 1).
   - **SOURCE** — objek / elemen yang mau ditambah (opsional; untuk `add`, mis. logo / produk).
3. **Deskripsikan BASE akurat** ke blok `BASE`: apa yang ada sekarang, komposisi, **aspek asli**, + **detail kritis yang wajib dijaga** (wajah, teks, warna, jumlah objek) — model bisa menjatuhkan yang sudah ada. Lihat `../references/reference-intents.md`.

---

## Pecah instruksi (dekomposisi)

Instruksi teks bebas dipecah jadi 4 (+1):

- **Subjek** — objek yang disasar ("orang", "langit", "logo").
- **Posisi / Kondisi** — di mana / keadaannya ("di tengah foto", "yang buram").
- **Tindakan (ACTION)** — `add` / `remove` / `fix`.
- **Detail** — hasil akhir yang diinginkan / constraint ("latar tetap rapi").
- **PRESERVE** — segala yang TIDAK berubah tetap identik.

Contoh: "Hapus orang yang berdiri di tengah foto." → Subjek=orang · Posisi=tengah foto · ACTION=`remove` · Detail=latar tetap rapi · PRESERVE=sisa foto identik.

Contoh 2 (keep-only): "Simpan hanya tiang dan lantai, sisanya hapus." → Subjek=tiang + lantai (yang DIPERTAHANKAN) · ACTION=`remove` (hapus SELAIN target) · Detail=tiang & lantai tetap utuh, area lain jadi bersih rapi · PRESERVE=tiang + lantai TIDAK BOLEH hilang.

---

## Prinsip

1. **BASE = img2img** — gambar target dipass sebagai base (bukan style-ref). Region ditunjuk lewat **kata** (posisi), bukan mask (MCP tak punya mask).
2. **PRESERVE ketat** — hanya region target berubah; sisanya identik (identitas, komposisi, palette, lighting).
3. **positive-only** — untuk `remove`, jangan tulis "no X" / "tanpa X"; deskripsikan **hasil positif** ("bagian tengah jadi lantai bersih rapi"). Frasa negatif bisa memunculkan X.
4. **Match BASE** — objek `add` / hasil `fix` mengikuti **style + lighting + perspektif + skala** BASE biar menyatu.
5. **describe-into-prompt**; **aspect = ikut BASE** (jangan paksa rasio baru); draft resolusi rendah → upscale saat cocok.
6. **Output blok berlabel** (bukan paragraf); tanpa nama alat / rig kamera.

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / abstrak agar tidak false-block; tulis efek + material, bukan label mentah; jangan pakai wajah orang asli. → `../references/anti-nsfw.md`

---

## Penekanan per ACTION

| ACTION | fokus | tambahan |
|---|---|---|
| **add** | tambah objek di posisi tertentu | SOURCE opsional (deskripsi objek dari referensi ter-attach, dirujuk ordinal, intent `subject`); cocokin lighting / perspektif / skala / style BASE |
| **remove** | (a) "hapus X" → hilangkan HANYA X + isi-ulang BG mulus, objek lain tetap. (b) "simpan hanya X / sisanya hapus" → pertahankan X UTUH (JANGAN blank X), bersihin sekelilingnya | DETAIL = rekonstruksi latar seamless, positive-only ("area jadi [permukaan] bersih"); target yang disimpan tak pernah dikosongkan |
| **fix** | perbaiki / tingkatkan region | DETAIL = target-state (tajam / warna benar / natural / proporsi betul); PRESERVE paling ketat |

---

## Kerangka blok prompt (skeleton)

```
BASE      — deskripsi gambar target (apa yang ada sekarang) + aspek asli
TARGET    — subjek + posisi/kondisi region yang diedit
ACTION    — add | remove | fix (+ objek/perubahan spesifik)
DETAIL    — hasil akhir yang diinginkan + constraint
PRESERVE  — segala di luar region target tetap identik
```

---

## Model

Default: **`../models/nano-banana-pro.md`** — 4K, edit kuat, ikut aspek BASE. Edit **teks / tipografi / logo** atau **instruction-editing presisi** → **`../models/gpt-image-2.md`** (unggul "editing berbasis instruksi"; string teks persis dalam tanda kutip; maks 16:9). Model = pilihan operator (final); eksekusi via app → OpenRouter, BASE = base image img2img, SOURCE dirujuk ordinal. Upscale saat cocok.

---

## Checklist formula

- Semua gambar attach dilihat; BASE vs SOURCE ditentukan.
- BASE dideskripsikan + detail kritis dijaga (describe-into-prompt).
- Instruksi dipecah: Subjek · Posisi/Kondisi · ACTION · Detail · PRESERVE.
- ACTION jelas (add/remove/fix); penekanan sesuai tabel.
- `remove` positive-only (hasil, bukan "no X").
- `add` / `fix` match style + lighting + perspektif + skala BASE.
- Aspect ikut BASE; BASE = base image img2img (via app → OpenRouter); draft → upscale.
- Output blok berlabel; positive-only; tanpa nama alat / rig.
