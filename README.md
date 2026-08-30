# DANA100 Cluster Analyzer

Sistem ini membaca daftar URL `draw-history?m=...`, mengambil 20 hasil terbaru per pasaran,
lalu membandingkan angka berdasarkan DIGIT UNIK yang sama pada tanggal yang sama.

Aturan awal:
- 0–1 digit sama: tidak terhubung
- >=2 digit unik sama: terhubung
- window: 20 hasil terbaru per pasaran
- pasangan stabil default: muncul >=8 tanggal
- hubungan dihitung berdasarkan tanggal, bukan posisi baris

## Jalankan

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python app.py
```

Buka `http://127.0.0.1:5000`

## Mengubah sumber

Edit `sources.txt`. Satu URL per baris.

## Mengubah tingkat kelonggaran

Di dashboard:
- Minimal digit unik sama: default 2
- Minimal kemunculan pasangan: default 8 dari window 20

Catatan:
- Sistem membaca web dan melakukan analisis statistik/deskriptif.
- Tidak menyimpulkan bahwa dua pasaran benar-benar dimiliki operator yang sama.
- Database/sistem lama tidak disentuh.
