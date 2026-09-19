# Formula — Image · Restyle

Media **image** (still), use-case **restyle**: **render ULANG seluruh gambar dalam GAYA baru** — palette, tekstur, linework, medium — sambil **mengunci identitas subjek + pose + komposisi + layout**. Gambar attach = **BASE** (img2img). Lapisan **netral model**.

> **Batas vs `image-edit` = KONTEN vs LOOK, bukan luas area.** Edit mengubah APA yang ada di frame (add/remove/fix — di region yang user select, atau seluruh frame tanpa region; termasuk keep-only "simpan hanya X"). Restyle mengubah CARA render-nya: tiap piksel boleh berubah, isi frame tetap sama. User mau ubah isi → `image-edit`; mau ubah look → restyle.

---

## Lihat gambar dulu (WAJIB)

Restyle selalu punya minimal 1 gambar attach (BASE). Sebelum menulis prompt:

1. **Lihat BASE.** Deskripsikan: subjek + identitas (wajah / bentuk khas), **pose / ekspresi**, **komposisi + layout** (penempatan, framing, arah pandang), **aspek asli**.
2. (Opsional) **STYLE-REF** — bila ada gambar kedua sebagai acuan gaya, perankan sebagai **style-ref** (intent `style`), **bukan** BASE: ambil palette / tekstur / mood-nya, bukan subjeknya. Rujuk secara **ordinal** ("the second reference image") — lihat `../references/reference-intents.md`.
3. Eja **detail kritis yang wajib dikunci** (identitas subjek, jumlah objek, teks yang harus tetap terbaca) — restyle rawan menggeser subjek saat look diganti.

---

## Pecah instruksi (dekomposisi)

Teks bebas restyle dipecah jadi 3:

- **STYLE** — look target: medium (cat air / 3D render / anime / film noir / cel-shade), palette, tekstur, linework, era / genre, mood.
- **BASE-LOCK** — yang WAJIB tetap: subjek + identitas, pose, komposisi, layout.
- **SCOPE** — seluruh frame (default restyle; menyeluruh, bukan tempelan sebagian).

Contoh: "Jadikan gaya cat air lembut." → STYLE = cat air, palette lembut, tekstur kertas, sapuan basah · BASE-LOCK = subjek + pose + komposisi identik · SCOPE = seluruh frame.

### Dua sumber gaya (teks + style-ref) — aturan prioritas

| Sumber tersedia | Cara pakai |
|---|---|
| Teks saja | Bangun STYLE penuh dari teks; eja medium + palette + tekstur secara konkret (describe-into-prompt). |
| Style-ref saja | Style-ref = acuan utama; deskripsikan look-nya ke dalam STYLE (palette, tekstur, kualitas cahaya) — jangan cuma "like the reference". |
| **Keduanya** | **Style-ref = jangkar look** (palette / tekstur / rendering); **teks = arah + penajaman** di atasnya ("lebih gelap", "linework lebih tebal"). **Bila bertentangan → TEKS menang** (teks = intent user paling akhir); style-ref turun jadi acuan sekunder untuk yang tidak disebut teks. Nyatakan resolusinya di STYLE, jangan biarkan model menebak. |

---

## Prinsip

1. **BASE = img2img** — BASE dipass sebagai base image; ambil **struktur** (subjek, pose, komposisi) darinya, **look** dari STYLE. Bukan style-transfer satu arah yang membuang subjek.
2. **Ganti look MENYELURUH** — palette, tekstur, linework, shading, medium berubah konsisten satu frame. Bukan filter tempel di sebagian.
3. **KEEP identitas + komposisi** — subjek tetap dikenali (wajah / bentuk khas), pose sama, penempatan + framing + layout sama; jumlah objek + teks yang terbaca tetap. Hanya rendering yang berganti. Jangan biarkan restyle menggeser subjek jadi karakter / objek lain (identity-lock).
4. **Positive-only** — deskripsikan look target secara positif; jangan "tanpa X" / "no X".
5. **Describe-into-prompt**; **aspect = ikut BASE** (jangan paksa rasio baru); draft resolusi rendah → upscale saat cocok.
6. **Output blok berlabel** (bukan paragraf); tanpa nama alat / rig kamera; tanpa nama seniman / brand nyata (anti-mimic).

> **Aman dari moderasi** — frasekan konten SFW pakai vocab sinematik / material agar tidak false-block; tulis efek + material + cahaya, bukan label mentah. → `../references/anti-nsfw.md`

---

## Kerangka blok prompt (skeleton)

```
BASE — deskripsi gambar sumber: subjek + identitas, pose, komposisi / layout + aspek asli
STYLE — look target: medium, palette, tekstur, linework, era / mood (teks = arah; style-ref = jangkar)
APPLY — terapkan style ke SELURUH frame, konsisten & menyeluruh
KEEP — identitas subjek + pose + komposisi + layout tetap identik; hanya rendering / look berubah
```

Catatan intake app: media editor mengirim skeleton `BASE / RESTYLE / STYLE-REF / CHANGE / KEEP` — petakan: `RESTYLE`+`STYLE-REF` → **STYLE**, `CHANGE` → **APPLY**. Nama blok output tetap yang di atas.

---

## Model (dialect style-transfer)

Model = pilihan operator (final). Referensi phrasing per model:

- **`../models/nano-banana-pro.md`** (default) — img2img kuat, ikut aspek BASE, konsisten satu frame. Phrasing: nyatakan "repaint the entire image as <medium>" + eja palette / tekstur; BASE cukup kuat menjaga struktur tanpa instruksi panjang.
- **`../models/gpt-image-2.md`** — pilih bila ada **teks / tipografi** yang harus tetap terbaca (string persis dalam tanda kutip; maks 16:9). Unggul instruction-following: boleh instruksi bertingkat ("keep the label text legible, render everything else in watercolor").
- **`../models/seedance-2.0.md` / model lain** — cek dialect di file model; prinsip sama: struktur dari BASE, look dari STYLE, KEEP eksplisit.

Upscale saat sudah cocok. ~~Provider per eksekusi (OpenArt/Higgsfield)~~ — ARSIP; eksekusi via app → OpenRouter.

---

## Checklist formula

- BASE dilihat + dideskripsikan (subjek, pose, komposisi, aspek asli); style-ref (bila ada) diperankan `style` + dirujuk ordinal, bukan BASE.
- Instruksi dipecah: STYLE · BASE-LOCK · SCOPE; dua sumber gaya di-resolve (teks menang saat konflik).
- Look diganti MENYELURUH (palette + tekstur + linework + medium), konsisten satu frame.
- Identitas subjek + pose + komposisi + layout + jumlah objek + teks terbaca dikunci (KEEP ketat).
- Positive-only; aspect ikut BASE; draft → upscale.
- Output blok berlabel; tanpa nama alat / rig / seniman nyata; aman moderasi.
