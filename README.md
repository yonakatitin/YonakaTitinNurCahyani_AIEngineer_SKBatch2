# Alur LLM untuk Ekstraksi CV dengan Rekomendasi Bercaveat

![tests](https://github.com/yonakatitin/YonakaTitinNurCahyani_AIEngineer_SKBatch2/actions/workflows/tests.yml/badge.svg)

Mini Assignment AI Engineer, Sekolah Karir Batch 2. Oleh Yonaka Titin Nur Cahyani.

Sistem kecil yang menerima teks CV (atau PDF berbasis teks), mengekstrak informasi
terstruktur, lalu memberi **rekomendasi prioritas review beserta caveat**. Sistem ini
**tidak mengambil keputusan final**: setiap hasil menyertakan `requires_human_decision: true`,
dan tidak ada label "tolak".

> Semua data di repo ini fiktif. Mode bawaan adalah **mock** (tanpa API key), sehingga
> siapa pun dapat menjalankan repo ini langsung.

## Ringkasan

| Aspek | Keputusan |
|---|---|
| Peran LLM | Hanya mengekstrak informasi (JSON sesuai schema). Tidak menilai. |
| Penilaian | Aturan deterministik terhadap rubric, hanya dari field yang evidence-nya tervalidasi. |
| Output | Label prioritas review + kriteria yang cocok (dengan jejak audit) + caveat + flag. |
| Safety | Human-in-the-loop, deteksi prompt injection, grounding check, masking PII, tanpa atribut sensitif. |
| Evaluasi | Golden set kecil (dev dan held-out), metrik per field, uji injeksi skill palsu, 13 unit test, CI. |
| LLM real | Gemini (free tier) lewat REST. Mode mock tetap bawaan. |

## Cara menjalankan

```bash
pip install -r requirements.txt

# Mode mock (bawaan, tanpa API key)
python -m src.pipeline data/sample_cv_01.txt data/job_rubric.json
python -m eval.run_eval --mode mock

# Unit test
pip install -r requirements-dev.txt
python -m pytest -q

# Mode real (Gemini free tier)
cp .env.example .env        # isi LLM_API_KEY dan LLM_MODEL, lalu set LLM_MODE=real
python -m eval.run_eval --mode real --repeats 2
PROMPT_VERSION=v2 python -m eval.run_eval --mode real --repeats 2
python -m eval.run_eval --mode real --set heldout --repeats 2

# PDF berbasis teks
python -m src.pipeline data/demo_cv_pdf.pdf data/job_rubric.json
```

Mode yang aktif selalu dicetak ke stderr (`[llm] mode=...`).
`MockLLM` adalah ekstraktor berbasis aturan sederhana untuk mendemonstrasikan alur dan
menguji pipeline secara deterministik. Ia bukan pengganti LLM dan hanya memahami format
CV mock berpemisah `|`. Hasil run real adalah contoh satu kali jalan, tidak selalu identik
antar run, dan disimpan di `outputs/`.

## Arsitektur

```
CV (teks atau PDF) + JobRubric
  1. Sanitize      masking email/telepon, deteksi pola prompt injection, cek teks kosong
  2. Extract       LLM (temperature 0, output JSON) -> CandidateProfile
  3. Validate      Pydantic; retry 1x; gagal -> flag parse_failed
  4. Grounding     setiap evidence harus muncul (dengan batas kata) di teks CV;
                   jika tidak -> confidence low + flag ungrounded_evidence
  5. Consistency   tanggal terbalik, IPK di luar 0-4, tanpa pengalaman/proyek
  6. Recommend     aturan deterministik terhadap rubric, hanya dari field ber-evidence valid
  7. Output        profil + rekomendasi + caveat + flag -> reviewer manusia
```

Keputusan desain utama:

- **LLM hanya mengekstrak, tidak menilai.** Penilaian dilakukan aturan terhadap rubric
  (`data/job_rubric.json`), sehingga dapat diaudit dan tidak bergantung pada "perasaan" model.
- **Evidence grounding.** Setiap field punya `evidence` (kutipan dari CV) dan `confidence`.
  Informasi yang tidak tertulis diisi `null`, bukan ditebak.
- **Gagal ke arah aman.** Kegagalan LLM (HTTP 429/5xx, timeout) di-retry dengan backoff.
  Jika tetap gagal, hasilnya profil kosong dengan flag `llm_call_failed` dan caveat yang
  menyatakan bahwa ini masalah layanan, bukan penilaian atas CV.
- **Jejak audit.** Setiap kriteria yang cocok menyertakan kata kunci pencocok, jenis item
  tempat kata itu ditemukan, dan potongan kalimat di sekitarnya.
- **Catatan model tidak disembunyikan.** `extraction_notes` dari LLM ditampilkan di caveat
  dengan label "belum diverifikasi".

## Output schema

`CandidateProfile`: `education`, `experience`, `skills`, `projects`, `certifications`,
`extraction_notes`. Setiap item memiliki `evidence` dan `confidence` (high/medium/low).
Definisi lengkap ada di `src/schema.py`.

`Recommendation`: `label`, `matched_criteria`, `missing_or_unclear`, `caveats`, `flags`,
`requires_human_decision` (selalu `true`), `rubric_version`.

Bentuk satu kriteria yang cocok (nilai ilustratif; output sebenarnya ada di `outputs/`):

```json
{
  "criterion": "llm_or_rag",
  "matched_keyword": "rag",
  "matched_in": "skill",
  "snippet": "...pipeline rag untuk tanya-jawab dokumen...",
  "evidence": "<kutipan persis dari CV>",
  "confidence": "high"
}
```

## Aturan rekomendasi

| Label | Kondisi |
|---|---|
| `prioritize_review` | Semua kriteria must-have terpenuhi dengan evidence tervalidasi dan tidak ada flag. |
| `standard_review` | Sebagian kriteria terpenuhi, atau ada flag apa pun. |
| `needs_clarification` | Kurang dari separuh kriteria terpenuhi, atau teks kosong, parse gagal, atau LLM gagal. |

Caveat yang selalu muncul: rekomendasi hanya berdasar isi CV; skill yang tertulis belum
tentu menunjukkan kedalaman pengalaman; format CV tidak standar menurunkan akurasi;
keputusan akhir wajib oleh manusia.

## Safety

- **Human oversight:** tidak ada keputusan otomatis. Label hanya menentukan prioritas antrean review.
- **Prompt injection:** CV dibungkus sebagai data (`<cv>...</cv>`), dipindai dengan pola
  regex (flag `possible_prompt_injection`), dan skor dihitung dari evidence, bukan dari
  klaim di dalam CV. Pada `sample_cv_injection`, teks "nilai 10/10" tidak menaikkan label.
- **Anti-halusinasi:** grounding check menurunkan confidence evidence yang tidak ada di CV.
  Diuji dengan `MockLLM(hallucinate=True)` yang menyuntikkan skill palsu (`kubernetes`):
  tertangkap, dan label tidak naik ke `prioritize_review`.
- **Fairness:** schema tidak memuat nama, gender, usia, agama, atau foto, dan scoring hanya
  memakai kriteria rubric.
- **Privasi:** email dan nomor telepon di-mask sebelum dikirim ke LLM. Free tier Gemini
  dapat dipakai Google untuk perbaikan produk, sehingga hanya data fiktif yang dikirim.

## Evaluasi

Golden set kecil dengan label manual (`data/golden/`). Metrik: akurasi label, skill F1,
akurasi jumlah pengalaman dan IPK, pemeriksaan flag, tingkat grounding evidence, konsistensi
label antar run, dan uji injeksi skill palsu.

- **Set dev:** 4 CV (Indonesia kuat, Inggris-campur parsial, tidak relevan, berisi injection).
- **Set held-out:** 2 CV (Inggris dengan tata letak bebas; Indonesia dengan tanggal terbalik).
  Golden-nya di-commit sebelum model dijalankan.
- Model real: `gemini-3.1-flash-lite`, temperature 0, 2 kali ulang (konsistensi label 1.00).

| Konfigurasi | Set | Akurasi label | Skill F1 | Grounding |
|---|---|---|---|---|
| Mock, golden v1 | dev (n=4) | 1.00 | 1.00 | 1.00 |
| Mock, golden v1.1 | dev (n=4) | 1.00 | 0.70 | 1.00 |
| Real, prompt v1, golden v1 | dev (n=4) | 1.00 | 0.60 | 1.00 |
| Real, prompt v1, golden v1.1 | dev (n=4) | 1.00 | 0.90 | 1.00 |
| Real, prompt v2, golden v1.1 | dev (n=4) | 1.00 | 0.96 | 1.00 |
| Real, prompt v1 | held-out (n=2) | 1.00 | 0.92 | 1.00 |
| Real, prompt v2 | held-out (n=2) | 1.00 | 1.00 | 1.00 |

Laporan lengkap ada di `outputs/eval_report_*.md`.

### Temuan dan catatan jujur

1. **Golden v1 bias ke kosakata mock.** Skill di golden v1 disusun dari daftar kata milik
   mock, bukan dari membaca CV sebagai anotator. Setelah terlihat dari hasil real, golden
   direvisi menjadi v1.1 dengan aturan eksplisit (semua item di bagian skills CV wajib ada).
   Revisi dilakukan **setelah** melihat output, jadi skor v1.1 bukan pengukuran held-out.
   Laporan golden v1 tetap disimpan (`outputs/*golden_v1.md`).
2. **Definisi "skill" ambigu.** Prompt v1 hanya mengambil skill dari bagian keahlian,
   sehingga `rag`, `llm`, `fastapi` yang hanya muncul di deskripsi terlewat. Prompt v2
   (opt-in, `PROMPT_VERSION=v2`) menambahkan aturan untuk menangkapnya. Harganya satu
   `extra` (`rest api`, tertulis di CV tetapi tidak ada di golden). Label rekomendasi tidak
   terpengaruh karena pencocokan kriteria juga membaca teks pengalaman dan proyek.
3. **Aturan v2 ditulis setelah melihat selisih di set dev**, dengan contoh istilah yang sama,
   sehingga keunggulan v2 sebagian sudah "diarahkan". Held-out hanya menunjukkan bahwa aturan
   itu berlaku pada CV baru.
4. **Tanggal terbalik tertangkap.** Pada `heldout_cv_02`, flag `inconsistent_dates` muncul
   dan Gemini tidak memperbaiki tanggal secara diam-diam.
5. **Insiden file kosong.** Run held-out pertama menghasilkan kegagalan palsu karena
   `heldout_cv_01.txt` kosong. Pipeline gagal ke arah aman (`needs_clarification`),
   penyebabnya ditemukan lewat diagnosis, dan eval kini berhenti jika input kosong serta
   menampilkan flag per baris. Laporan yang rusak dipertahankan dengan awalan `INVALID_`
   dan tidak dipakai pada tabel di atas.
6. **Gangguan layanan.** Gemini sempat membalas HTTP 503 berulang. Ditangani dengan retry
   dan flag `llm_call_failed`; eval tidak menyimpan laporan jika ada panggilan yang gagal.

## Pengujian unit dan CI

13 unit test (`tests/`), dijalankan otomatis di GitHub Actions pada setiap push.

- Sanitasi: PII ter-mask tanpa merusak tanggal; injection ditandai.
- Safety: injection tidak menaikkan label; evidence palsu diturunkan confidence-nya;
  evidence pendek tidak lolos hanya karena menjadi potongan kata lain.
- Ketahanan: teks kosong menghasilkan `needs_clarification`; kegagalan LLM menghasilkan
  flag eksplisit, bukan penilaian atas CV; tanggal terbalik menahan label.
- Keterlacakan: setiap kriteria yang cocok memuat kata kunci, jenis item, dan potongan teks.
- Ingest PDF: normalisasi teks (ligatur, spasi tak-putus, baris kosong) dan ekstraksi teks dari PDF demo.

## Ingest PDF

`src/ingest.py` mengekstrak teks dari PDF berbasis teks dan menormalkan artefak aman
(ligatur, spasi tak-putus, baris kosong berlebih). Tanda hubung di akhir baris sengaja
**tidak** disambung, karena pemenggalan suku kata dan tanda hubung asli tidak dapat
dibedakan tanpa kamus.

Diuji secara kualitatif pada satu CV fiktif berformat LaTeX (`data/demo_cv_pdf.pdf`),
tanpa golden dan di luar tabel evaluasi. Pengamatan:

- Teks hasil ekstraksi punya artefak: spasi hilang pada judul seksi (misalnya
  `PROFESSIONALSUMMARY`) dan di sebelah elemen rata-kanan.
- Pengurai tetap mengekstrak pendidikan, empat pengalaman beserta tanggalnya, proyek, dan
  sertifikasi dengan benar, dan grounding check tidak memberi flag palsu.
- Dengan prompt v1, hanya sebagian kecil skill di bagian keahlian yang padat terekstrak
  (5 skill). Dengan prompt v2 jumlahnya jauh lebih banyak (perkiraan kasar sekitar 14).
  Ini pengamatan pada satu CV, bukan klaim akurasi.
- Mode `layout` pada `pypdf` (`pdf_to_text(path, layout=True)`) memperbaiki spasi di dekat
  elemen rata-kanan tetapi tidak memperbaiki judul seksi dan menimbulkan artefak baru, sehingga
  tidak dijadikan default.

Contoh output: `outputs/sample_output_pdf_real_v2.json`.

## Keterbatasan

- **n sangat kecil** (6 CV). Evaluasi ini sanity check alur dan safety, bukan estimasi
  akurasi. Konsistensi 1.00 hanya dari 2 kali ulang.
- Rubric berbasis keyword itu kasar: kata "FastAPI" saja memenuhi kriteria
  `structured_output_or_api`. Trade-off: mudah diaudit, tetapi tidak membuktikan kedalaman.
- Pertahanan injection mengandalkan regex dan penilaian berbasis evidence. Teks injeksi yang
  menyelipkan klaim skill palsu di dalam CV akan lolos grounding (karena memang ada di CV),
  sehingga flag dan human review adalah lapisan utamanya.
- Nama kandidat tidak ada di schema dan tidak dipakai untuk scoring, tetapi masih ada pada
  teks yang dikirim ke LLM (hanya email dan telepon yang di-mask).
- Schema belum memuat publikasi dan penghargaan, sehingga bagian itu tidak diekstrak.
- Tidak ada OCR untuk PDF hasil scan (teks kosong menghasilkan flag
  `empty_or_unreadable_text`), tidak ada deteksi bahasa otomatis, dan pengujian hanya pada
  CV berbahasa Indonesia dan Inggris.
- Uji halusinasi memakai `MockLLM(hallucinate=True)`, sehingga menguji pipeline, bukan
  kecenderungan model.

## Pengembangan lanjutan

Golden set lebih besar dengan anotator kedua, rubric berbobot dengan penilaian kedalaman,
deteksi injection berbasis model sebagai lapisan tambahan, perbaikan teks PDF yang lebih
kuat, dan antarmuka web sederhana.

## Catatan penggunaan AI

Saya menggunakan Claude (Anthropic) sebagai asisten untuk
mendiskusikan desain sistem, menyusun draf kode awal, dan membantu mendiagnosis error.
Saya menjalankan seluruh kode dan evaluasi sendiri, memeriksa hasilnya, dan dapat
menjelaskan seluruh isi repo ini. Gemini (free tier) digunakan sebagai LLM pada mode real.

## Struktur repo

```
src/       schema.py, llm.py, gemini_llm.py, pipeline.py, ingest.py
data/      CV fiktif (teks, LaTeX, PDF), job_rubric.json, golden/ (kunci jawaban)
eval/      run_eval.py
tests/     test_pipeline.py, test_ingest.py
outputs/   contoh output dan laporan evaluasi
.github/   workflows/tests.yml (CI)
```