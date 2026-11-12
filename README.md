# Alur LLM untuk Ekstraksi CV dengan Rekomendasi Bercaveat

Mini Assignment AI Engineer, Sekolah Karir Batch 2. Oleh Yonaka Titin Nur Cahyani.

Sistem kecil yang menerima teks CV, mengekstrak informasi terstruktur, lalu memberi
**rekomendasi prioritas review beserta caveat**. Sistem ini tidak mengambil keputusan
final: setiap hasil menyertakan `requires_human_decision: true`, dan tidak ada label
"tolak".

Semua data di repo ini fiktif. Mode default adalah **mock** (tanpa API key).

## Cara menjalankan

```bash
pip install -r requirements.txt

# Mode mock (default, tanpa API key)
python -m src.pipeline data/sample_cv_01.txt data/job_rubric.json
python -m eval.run_eval --mode mock

# Mode real (Gemini, free tier)
cp .env.example .env     # isi LLM_API_KEY dan LLM_MODEL, lalu LLM_MODE=real
python -m eval.run_eval --mode real --repeats 2
PROMPT_VERSION=v2 python -m eval.run_eval --mode real --repeats 2
```

Mode yang aktif selalu dicetak ke stderr (`[llm] mode=...`). `MockLLM` adalah ekstraktor
berbasis aturan sederhana, hanya untuk mendemonstrasikan alur dan menguji pipeline
secara deterministik; bukan pengganti LLM. Hasil run real (satu kali jalan, tidak
identik antar run) disimpan di `outputs/`.

## Arsitektur

```
CV (teks/PDF) + JobRubric
  1. Sanitize      masking email dan telepon, scan pola prompt injection, cek teks kosong
  2. Extract       LLM (temperature 0, output JSON) -> CandidateProfile
  3. Validate      Pydantic; retry 1x; gagal -> flag parse_failed
  4. Grounding     tiap evidence harus muncul (batas kata) di teks CV; jika tidak -> confidence low + flag
  5. Consistency   tanggal terbalik, IPK di luar 0-4, tanpa pengalaman/proyek
  6. Recommend     aturan deterministik terhadap rubric, hanya dari field ber-evidence tervalidasi
  7. Output        profil + rekomendasi + caveat + flag -> reviewer manusia
```

Keputusan desain utama:

- **LLM hanya mengekstrak, tidak menilai.** Penilaian dilakukan aturan deterministik
  terhadap rubric (`data/job_rubric.json`), jadi bisa diaudit dan tidak bergantung pada
  "perasaan" model.
- **Evidence grounding.** Setiap field punya `evidence` (kutipan dari CV) dan
  `confidence`. Field yang tidak tertulis diisi `null`, bukan ditebak.
- **Gagal ke arah aman.** Kegagalan LLM (HTTP 429/5xx, timeout) di-retry dengan backoff;
  jika tetap gagal, hasilnya profil kosong dengan flag `llm_call_failed` dan caveat yang
  menyatakan bahwa ini masalah layanan, bukan penilaian atas CV.

## Output schema

`CandidateProfile`: `education`, `experience`, `skills`, `projects`, `certifications`,
`extraction_notes`. Setiap item mewarisi `evidence` dan `confidence` (high/medium/low).
Contoh field: `institution`, `gpa`, `title`, `start`/`end` (YYYY-MM), `employment_type`.
Definisi lengkap: `src/schema.py`.

`Recommendation`: `label`, `matched_criteria` (dengan evidence), `missing_or_unclear`,
`caveats`, `flags`, `requires_human_decision` (selalu true), `rubric_version`.

Contoh output: `outputs/sample_output_mock.json` dan `outputs/sample_output_real.json`
(prompt v1).

## Aturan rekomendasi

| Label | Kondisi |
|---|---|
| `prioritize_review` | semua kriteria must-have terpenuhi dengan evidence tervalidasi dan tidak ada flag |
| `standard_review` | sebagian kriteria terpenuhi, atau ada flag |
| `needs_clarification` | kurang dari separuh kriteria terpenuhi, atau teks kosong / parse gagal / LLM gagal |

Caveat yang selalu muncul: rekomendasi hanya berdasar isi CV; skill tertulis belum tentu
menunjukkan kedalaman pengalaman; format CV tidak standar menurunkan akurasi; keputusan
akhir oleh manusia.

## Safety

- **Human oversight:** tidak ada keputusan otomatis; label hanya menentukan prioritas
  antrean review.
- **Prompt injection:** CV dibungkus sebagai data (`<cv>...</cv>`), dipindai dengan pola
  regex (flag `possible_prompt_injection`), dan skor dihitung dari evidence, bukan dari
  klaim di dalam CV. Pada `sample_cv_injection`, teks "nilai 10/10" tidak menaikkan label.
- **Anti-hallucination:** grounding check menurunkan confidence evidence yang tidak ada di
  CV. Diuji dengan `MockLLM(hallucinate=True)` yang menyuntikkan skill palsu
  (`kubernetes`): tertangkap, dan label tidak naik ke `prioritize_review`.
- **Fairness:** schema tidak memuat nama, gender, usia, agama, atau foto, dan scoring
  hanya memakai kriteria rubric.
- **Privasi:** email dan nomor telepon di-mask sebelum ke LLM. Free tier Gemini dapat
  dipakai Google untuk perbaikan produk, jadi hanya data fiktif yang dikirim.

## Evaluasi

Golden set kecil dengan label manual (`data/golden/`). Metrik: akurasi label,
skill F1, akurasi jumlah pengalaman dan IPK, pemeriksaan flag, tingkat grounding evidence,
konsistensi label antar run, dan uji injeksi skill palsu. Jalankan:
`python -m eval.run_eval --mode {mock|real} [--set heldout] [--repeats N]`.

Set dev: 4 CV (Indonesia, Inggris-campur, tidak relevan, berisi injection).
Set held-out: 2 CV (Inggris dengan tata letak bebas; Indonesia dengan tanggal terbalik),
golden-nya di-commit sebelum model dijalankan.

| Konfigurasi | Set | Label acc. | Skill F1 | Grounding |
|---|---|---|---|---|
| Mock, golden v1 | dev (n=4) | 1.00 | 1.00 | 1.00 |
| Mock, golden v1.1 | dev (n=4) | 1.00 | 0.70 | 1.00 |
| Real v1 prompt, golden v1 | dev (n=4) | 1.00 | 0.60 | 1.00 |
| Real v1 prompt, golden v1.1 | dev (n=4) | 1.00 | 0.90 | 1.00 |
| Real v2 prompt, golden v1.1 | dev (n=4) | 1.00 | 0.96 | 1.00 |
| Real v1 prompt | held-out (n=2) | 1.00 | 0.92 | 1.00 |
| Real v2 prompt | held-out (n=2) | 1.00 | 1.00 | 1.00 |

Model real: `gemini-3.1-flash-lite`, temperature 0, 2 kali ulang (konsistensi label 1.00).

### Temuan dan catatan jujur

1. **Golden v1 bias ke kosakata mock.** Skill di golden v1 disusun dari daftar kata mock,
   bukan dari membaca CV sebagai anotator. Setelah terlihat di hasil real, golden direvisi
   menjadi v1.1 dengan aturan eksplisit (semua item di bagian skills CV wajib ada).
   Revisi dilakukan **setelah** melihat output, jadi skor v1.1 bukan pengukuran
   held-out. Hasil v1 tetap disimpan (`outputs/*golden_v1.md`).
2. **Definisi "skill" ambigu.** Prompt v1 hanya mengekstrak skill dari bagian keahlian;
   istilah seperti `rag`, `llm`, `fastapi` yang hanya muncul di deskripsi terlewat.
   Prompt v2 (opt-in, `PROMPT_VERSION=v2`) menambahkan aturan untuk menangkapnya.
   Harganya satu `extra` (`rest api`, tertulis di CV tapi tidak ada di golden).
   Label rekomendasi tidak terpengaruh karena pencocokan kriteria juga membaca teks
   pengalaman dan proyek.
3. **Aturan v2 ditulis setelah melihat selisih di set dev**, dengan contoh istilah yang
   sama, jadi keunggulan v2 sebagian sudah "diarahkan". Held-out hanya menunjukkan bahwa
   aturannya berlaku di CV baru.
4. **Tanggal terbalik tertangkap:** pada `heldout_cv_02`, flag `inconsistent_dates`
   muncul dan Gemini tidak memperbaiki tanggal diam-diam.
5. **Insiden file kosong:** run held-out pertama menghasilkan kegagalan palsu karena
   `heldout_cv_01.txt` kosong. Pipeline gagal ke arah aman (`needs_clarification`), dan
   penyebabnya ditemukan lewat diagnosis. Eval kini berhenti jika input kosong, dan
   laporan menampilkan flag per baris. Laporan yang rusak dipertahankan dengan awalan
   `INVALID_` dan tidak dipakai di tabel di atas.
6. **Gangguan layanan:** Gemini sempat membalas HTTP 503 berulang; ditangani dengan retry
   dan flag `llm_call_failed`. Eval tidak menyimpan laporan jika ada panggilan yang gagal.

## Keterbatasan

- **n sangat kecil** (6 CV): ini sanity check alur dan safety, bukan estimasi akurasi.
  Konsistensi 1.00 hanya dari 2 kali ulang.
- Rubric berbasis keyword itu kasar: kata "FastAPI" saja memenuhi kriteria
  `structured_output_or_api`. Trade-off: mudah diaudit, tetapi tidak membuktikan
  kedalaman.
- Pertahanan injection mengandalkan regex dan penilaian berbasis evidence. Teks injeksi
  yang menyelipkan klaim skill palsu di dalam CV lolos grounding (karena memang ada di
  CV), sehingga flag dan human review adalah lapisan utamanya.
- Nama tidak ada di schema dan tidak dipakai untuk scoring, tetapi masih ada di teks yang
  dikirim ke LLM (hanya email dan telepon yang di-mask).
- Ingest PDF berbasis teks tersedia (`src/ingest.py`) tetapi belum diuji di eval. Tidak
  ada OCR untuk PDF hasil scan, tidak ada deteksi bahasa otomatis; diuji hanya pada CV
  berbahasa Indonesia dan Inggris.
- Uji halusinasi memakai `MockLLM(hallucinate=True)`, jadi menguji pipeline, bukan
  kecenderungan model.

## Pengembangan lanjutan

Demo web, golden set yang lebih besar dengan anotator kedua, rubric berbobot dengan
penilaian kedalaman, dan deteksi injection berbasis model sebagai lapisan tambahan.

## Catatan penggunaan AI

[SESUAIKAN: tulis yang benar-benar terjadi.] Saya menggunakan Claude (Anthropic)
sebagai asisten untuk mendiskusikan desain sistem, menyusun draf kode awal, dan membantu
mendiagnosis error. Saya menjalankan sendiri seluruh kode dan evaluasi, memeriksa hasilnya,
dan memahami serta dapat menjelaskan seluruh isi repo ini. Gemini (free tier) digunakan
sebagai LLM pada mode real.

## Struktur repo

```
src/       schema.py, llm.py, gemini_llm.py, pipeline.py, ingest.py
data/      CV fiktif, job_rubric.json, golden/ (kunci jawaban)
eval/      run_eval.py
outputs/   contoh output dan laporan evaluasi
```