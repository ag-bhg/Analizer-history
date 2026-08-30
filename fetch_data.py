import json, re, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "draws.json"
WINDOW = 20

def norm_date(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", s)
    if m:
        d, mo, y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None

def clean_number(s):
    digits = re.sub(r"\D", "", str(s))
    return digits.zfill(4)[-4:] if len(digits) <= 4 and digits else ""

def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    m = re.search(r"[?&]m=(\d+)", url)
    mid = m.group(1) if m else url

    rows = []
    # Prefer tables whose headers mention date/tanggal and number/nomor.
    tables = soup.find_all("table")
    for table in tables:
        trs = table.find_all("tr")
        for tr in trs:
            cells = [x.get_text(" ", strip=True) for x in tr.find_all(["td","th"])]
            if len(cells) < 2:
                continue
            date = None
            number = ""
            period = ""
            for c in cells:
                if not date:
                    date = norm_date(c)
                if re.fullmatch(r"\d{4}", re.sub(r"\D","",c)):
                    number = re.sub(r"\D","",c)
                if not period and ("periode" in c.lower() or "period" in c.lower()):
                    period = c
            if date and number:
                rows.append({"date": date, "period": period, "number": clean_number(number)})

    # Fallback: scan visible table-like rows.
    if not rows:
        for tr in soup.select("tr"):
            cells = [x.get_text(" ", strip=True) for x in tr.select("td,th")]
            if not cells:
                continue
            date = next((norm_date(c) for c in cells if norm_date(c)), None)
            nums = [re.sub(r"\D","",c) for c in cells if len(re.sub(r"\D","",c)) == 4]
            if date and nums:
                rows.append({"date": date, "period": "", "number": clean_number(nums[-1])})

    # Deduplicate by date; keep first valid row and newest 20.
    unique = {}
    for r in rows:
        if r["date"] and len(r["number"]) == 4:
            unique.setdefault(r["date"], r)
    rows = sorted(unique.values(), key=lambda x: x["date"], reverse=True)[:WINDOW]

    # Clean title to a useful market name; actual site title may include DANA100 text.
    name = re.sub(r"\s+", " ", title).strip()
    return {"id": mid, "name": name or mid, "url": url, "rows": rows}

def main():
    urls = [x.strip() for x in (ROOT/"sources.txt").read_text().splitlines() if x.strip()]
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; DANA100-History-Analyzer/1.0)",
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"
    })
    markets, errors = [], []
    for i, url in enumerate(urls, 1):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            market = parse_page(r.text, url)
            if market["rows"]:
                markets.append(market)
            else:
                errors.append({"url":url, "id":market["id"], "error":"Tidak menemukan baris hasil 4D"})
        except Exception as e:
            errors.append({"url":url, "id":re.search(r"m=(\d+)",url).group(1), "error":str(e)})
        time.sleep(0.15)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "configured_markets": len(urls),
        "loaded_markets": len(markets),
        "errors": errors,
        "markets": markets
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Loaded {len(markets)}/{len(urls)} markets; errors={len(errors)}")
    if len(markets) == 0:
        raise SystemExit("No market data parsed; refusing to publish empty dataset.")

if __name__ == "__main__":
    main()
