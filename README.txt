DANA100 HTML Analyzer

File utama:
- index.html

Fitur:
- window 20 tanggal
- minimal 2/3/4 digit unik sama
- minimal kemunculan pasangan
- cluster berdasarkan hubungan berantai
- detail per tanggal
- export JSON

PENTING:
HTML murni tidak selalu dapat membaca halaman DANA100 langsung karena pembatasan CORS/browser.
Untuk produksi, gunakan backend/proxy kecil yang mengambil URL DANA100 lalu memberikan JSON ke halaman ini.
Struktur JSON yang diharapkan tersedia sebagai window.__DANA100_DATA__:
[
  {
    "id":"2699",
    "name":"TOTO MACAU 13:00",
    "url":"https://dana100nl.com/draw-history?m=2699",
    "rows":[
      {"date":"2026-08-30","period":"...","number":"5451"}
    ]
  }
]

Database lama tidak digunakan atau diubah.
