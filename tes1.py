from schemas.format.pydantic_ai import ChatMessage
import json
from pprint import pprint


md_file_1 = """
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

"""

md_file_2 = """
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

"""


IMG_1 = {
    "uid": "3f2a9c1e-8b4d-4e7a-9f1c-2d5e6a7b8c90",
    "url": "https://local-tunnel.dfactory.pro/storage/DF-Engine-DEV/Engagement%20of%20Imelda%20&%20Alex_ac0f2698/upload/images/2017_12_03_Borobudur%20(9)_7d4c4f.png",
    "source": "upload",
}
IMG_2 = {
    "uid": "a7c4e2f1-1d3b-4c5e-8a9f-0b1c2d3e4f56",
    "url": "https://local-tunnel.dfactory.pro/storage/DF-Engine-DEV/FEO%20Dinner%20&%20Dance%202026_15406fa0/upload/images/WhatsApp%20Image%202026-11-10%20at%2016.38.53_ea1997.jpeg",
    "source": "upload",
}

sample_data = [
    {"role": "system", "text": md_file_1, "attachments": []},
    {"role": "system", "text": md_file_2, "attachments": []},
    {"role": "user", "text": "Hellooo", "attachments": []},
    {
        "role": "assistant",
        "text": f"Hello! I am the assistant @{IMG_1['uid']} for project Maria Theressa. How can I help you today?",
        "attachments": [IMG_1],
    },
    {
        "role": "user",
        "text": f"based on this image @{IMG_1['uid']} and this image @{IMG_2['uid']}, what do they mean?",
        "attachments": [IMG_1, IMG_2],
    },
]

payload = [ChatMessage(**m).to_payload() for m in sample_data]
# print(json.dumps(payload, indent=2))


# ---------- pydantic_ai ----------
import os
from pydantic_ai import Agent, ImageUrl, NativeOutput
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, SystemPromptPart, TextPart, UserPromptPart
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from schemas.format.pydantic_ai import LLMResponse


def user_content(m: ChatMessage) -> list:
    parts: list = [m.text]
    for a in m.attachments:
        parts += [a.marker(), ImageUrl(url=a.url)]
    return parts


def to_model_messages(rows: list[dict]) -> tuple[list[ModelMessage], list]:
    """rows (last one must be user) -> (message_history, prompt)"""
    msgs = [ChatMessage(**r) for r in rows]
    *past, last = msgs
    system = [SystemPromptPart(m.text) for m in past if m.role == "system"]

    history: list[ModelMessage] = []
    for m in (m for m in past if m.role != "system"):
        if m.role == "user":
            history.append(ModelRequest(parts=[*system, UserPromptPart(user_content(m))]))
            system = []  # system parts only on the first request
        else:
            # ponytail: ModelResponse can't carry image URLs, so assistant turns = text + markers only
            history.append(ModelResponse(parts=[TextPart("\n".join([m.text, *(a.marker() for a in m.attachments)]))]))
    return history, user_content(last)


history, prompt = to_model_messages(sample_data)


import httpx


async def log_request(request: httpx.Request):
    """print the literal JSON body sent to OpenRouter (headers/API key are not printed)"""
    print(f"\n===== {request.method} {request.url} =====")
    print(json.dumps(json.loads(request.content), indent=2, ensure_ascii=False))


agent = Agent(
    OpenRouterModel(
        "google/gemini-2.5-flash",
        provider=OpenRouterProvider(
            api_key="tes",
            http_client=httpx.AsyncClient(event_hooks={"request": [log_request]}),
        ),
    ),
    output_type=NativeOutput(LLMResponse, name="chat_reply", strict=True),
    model_settings={"temperature": 0},
    retries=2,
)
result = agent.run_sync(prompt, message_history=history)
# print(result.output.model_dump_json(indent=2))
