
import re
from collections import defaultdict, Counter
from itertools import combinations
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template_string, request

app = Flask(__name__)

DEFAULT_OVERLAP = 2
DEFAULT_WINDOW = 20
DEFAULT_MIN_DAYS = 8

def source_id(url):
    return parse_qs(urlparse(url).query).get("m", [""])[0]

# Period cells look like "HK-6382" or "TTM12-1123": letters (+ optional digits)
# for the market's short code, a dash, then the period/session number.
PERIOD_RE = re.compile(r"^([A-Za-z]+\d*)\s*-\s*(\d+)$")

def period_code(period):
    m = PERIOD_RE.match(str(period).strip())
    return m.group(1).upper() if m else None

def fetch_market(url, session):
    r = session.get(url, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # DANA100 table is a simple 3-column table: Tanggal | Periode | Nomor.
    table = None
    for t in soup.find_all("table"):
        headers = [x.get_text(" ", strip=True).lower() for x in t.find_all("th")]
        if any("tanggal" in h for h in headers) and any("nomor" in h for h in headers):
            table = t
            break

    if table is None:
        # Fallback to pandas table detection.
        tables = pd.read_html(r.text)
        for df in tables:
            cols = [str(c).lower() for c in df.columns]
            if any("tanggal" in c for c in cols) and any("nomor" in c for c in cols):
                table = df
                break

    rows = []
    if hasattr(table, "find_all"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 3 and re.match(r"\d{2}-\d{2}-\d{4}", cells[0]):
                date, period, number = cells[0], cells[1], cells[2]
                number = re.sub(r"\D", "", number)
                if len(number) == 4:
                    rows.append((pd.to_datetime(date, dayfirst=True), period, number))
    else:
        df = table.copy()
        cols = {str(c).lower(): c for c in df.columns}
        dc = next(c for k,c in cols.items() if "tanggal" in k)
        nc = next(c for k,c in cols.items() if "nomor" in k)
        pc = next((c for k,c in cols.items() if "periode" in k), None)
        for _, row in df.iterrows():
            date = pd.to_datetime(str(row[dc]), dayfirst=True, errors="coerce")
            number = re.sub(r"\D", "", str(row[nc]))
            period = str(row[pc]) if pc is not None else ""
            if pd.notna(date) and len(number) == 4:
                rows.append((date, period, number))

    # Keep the newest 20 rows and retain leading zeroes.
    rows = sorted(rows, key=lambda x: x[0], reverse=True)[:DEFAULT_WINDOW]
    market = re.sub(r"\s+", " ", title.replace("DANA100", "")).strip(" -|")
    codes = Counter(c for c in (period_code(p) for _, p, _ in rows) if c)
    code = codes.most_common(1)[0][0] if codes else None
    mid = source_id(url)
    return {
        "id": mid,
        "code": code or mid,
        "url": url,
        "name": market or mid,
        "rows": rows,
    }

def digit_set(number):
    return set(number)

def overlap(a, b):
    return len(digit_set(a) & digit_set(b))

def load_sources():
    path = Path(__file__).with_name("sources.txt")
    return [x.strip() for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.lstrip().startswith("#")]

def collect():
    urls = load_sources()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; DANA100-Cluster-Analyzer/1.0)"
    })
    markets, errors = [], []
    for url in urls:
        try:
            markets.append(fetch_market(url, session))
        except Exception as e:
            errors.append({"url": url, "id": source_id(url), "error": str(e)})
    return markets, errors

def analyze(markets, overlap_min=2, min_days=DEFAULT_MIN_DAYS):
    # date -> market id -> record
    by_date = defaultdict(dict)
    meta = {}
    for m in markets:
        meta[m["id"]] = m
        for d, period, number in m["rows"]:
            by_date[d.date()][m["id"]] = {
                "period": period, "number": number,
                "name": m["name"], "code": m["code"]
            }

    pair_counts = Counter()
    pair_samples = defaultdict(list)
    daily_clusters = {}

    for d, vals in sorted(by_date.items(), reverse=True):
        ids_here = list(vals)
        graph = {i: set() for i in ids_here}
        for a, b in combinations(ids_here, 2):
            ov = overlap(vals[a]["number"], vals[b]["number"])
            if ov >= overlap_min:
                graph[a].add(b)
                graph[b].add(a)
                key = tuple(sorted((a, b)))
                pair_counts[key] += 1
                if len(pair_samples[key]) < 20:
                    pair_samples[key].append({
                        "date": d.isoformat(),
                        "a": vals[a]["number"],
                        "b": vals[b]["number"],
                        "overlap": ov
                    })

        # Connected components for this date.
        seen = set()
        comps = []
        for root in ids_here:
            if root in seen:
                continue
            stack, comp = [root], []
            seen.add(root)
            while stack:
                x = stack.pop()
                comp.append(x)
                for y in graph[x]:
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
            if len(comp) >= 2:
                comps.append(sorted(comp))
        # BAG labels + member "CODE-number" strings for this date.
        comps.sort(key=lambda c: -len(c))
        bags = []
        for i, comp in enumerate(comps):
            bags.append({
                "label": f"BAG{i+1}",
                "members": [{"id": x, "code": vals[x]["code"], "number": vals[x]["number"]} for x in comp],
            })
        grouped_ids = {x for comp in comps for x in comp}
        singles = [{"id": x, "code": vals[x]["code"], "number": vals[x]["number"]}
                   for x in ids_here if x not in grouped_ids]
        daily_clusters[d.isoformat()] = {"bags": bags, "singles": sorted(singles, key=lambda s: s["code"])}

    # Stable pairs across the window.
    stable_pairs = []
    total_dates = len(by_date)
    for (a,b), count in pair_counts.items():
        if count >= min_days:
            stable_pairs.append({
                "a": a, "b": b, "count": count,
                "rate": round(count / max(total_dates,1) * 100, 1),
                "code_a": meta[a]["code"], "code_b": meta[b]["code"],
                "samples": pair_samples[(a,b)]
            })
    stable_pairs.sort(key=lambda x: (-x["count"], -x["rate"], x["a"], x["b"]))

    # Stable clusters: connect pairs that meet the min_days threshold.
    graph = defaultdict(set)
    for p in stable_pairs:
        graph[p["a"]].add(p["b"])
        graph[p["b"]].add(p["a"])

    dates_desc = sorted(by_date.keys(), reverse=True)

    stable_clusters = []
    seen = set()
    for root in graph:
        if root in seen:
            continue
        stack, comp = [root], []
        seen.add(root)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in graph[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        if len(comp) >= 2:
            members = sorted(comp)
            internal = []
            for a,b in combinations(members,2):
                k = tuple(sorted((a,b)))
                c = pair_counts.get(k,0)
                internal.append(c)
            avg = round(sum(internal)/len(internal),1) if internal else 0
            rate = round(avg / max(total_dates,1) * 100, 1)

            # Recent history: up to 5 latest dates, "CODE-number" per member present.
            histories = []
            for i, d in enumerate(dates_desc[:5]):
                vals = by_date[d]
                parts = [f'{meta[x]["code"]}-{vals[x]["number"]}' for x in members if x in vals]
                if parts:
                    histories.append({"date": d.isoformat(), "text": ", ".join(parts), "latest": i == 0})

            stable_clusters.append({
                "members": members,
                "codes": [meta[x]["code"] for x in members],
                "avg_pair_days": avg,
                "freq_text": f"{avg}/{total_dates} hari ({rate}%)",
                "histories": histories,
                "size": len(members)
            })
    stable_clusters.sort(key=lambda x: (-x["avg_pair_days"], -x["size"]))
    for i, c in enumerate(stable_clusters):
        c["label"] = f"BAG{i+1}"

    return {
        "markets": markets,
        "by_date": by_date,
        "dates_desc": [d.isoformat() for d in dates_desc],
        "daily_clusters": daily_clusters,
        "stable_pairs": stable_pairs,
        "stable_clusters": stable_clusters,
        "total_dates": total_dates,
        "overlap_min": overlap_min,
        "min_days": min_days,
        "errors": [],
    }

TEMPLATE = """
<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DANA100 Cluster Analyzer</title>
<style>
body{font-family:Arial,sans-serif;margin:20px;background:#f5f5f5;color:#222}
.card{background:white;border-radius:10px;padding:16px;margin-bottom:16px;box-shadow:0 1px 4px #bbb}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}
.badge{display:inline-block;padding:4px 8px;border-radius:12px;background:#eee;margin:2px;font-weight:bold}
.hist{margin:2px 0}
.hist.latest{font-weight:bold}
.err{color:#b00020}
.bag0{background:#ffd9d9}.bag1{background:#ffe8b3}.bag2{background:#fff5b3}
.bag3{background:#d9f7be}.bag4{background:#c2f0e8}.bag5{background:#c2e0ff}
.bag6{background:#dcc2ff}.bag7{background:#ffc2e8}
</style>
</head>
<body>
<div class="card">
<h1>DANA100 — Analisis Kelompok Angka</h1>
<form>
<label>Minimal digit unik sama:
<input type="number" name="overlap" min="1" max="4" value="{{overlap}}">
</label>
&nbsp;
<label>Minimal kemunculan pasangan:
<input type="number" name="mindays" min="1" max="20" value="{{mindays}}">
</label>
&nbsp;
<label>Tanggal (tabel per-tanggal):
<select name="day">
{% for d in dates_desc %}<option value="{{d}}" {% if d==selected_day %}selected{% endif %}>{{d}}</option>{% endfor %}
</select>
</label>
&nbsp;<button type="submit">Analisis ulang</button>
</form>
<p>Window: {{window}} hasil terbaru per pasaran. Terhubung jika minimal {{overlap}} digit unik sama.</p>
</div>

<div class="card">
<h2>Tabel 1 — Kelompok Stabil (window {{window}} data)</h2>
{% if clusters %}
<table><tr><th>BAG</th><th>Freq</th><th>Data histori</th></tr>
{% for c in clusters %}
<tr>
<td><span class="badge bag{{loop.index0 % 8}}">{{c.label}}</span></td>
<td>{{c.freq_text}}</td>
<td>
{% for h in c.histories %}
<div class="hist{% if h.latest %} latest{% endif %}">{{h.date}}: {{h.text}}</div>
{% endfor %}
</td>
</tr>
{% endfor %}
</table>
{% else %}<p>Belum ada kelompok yang memenuhi ambang.</p>{% endif %}
</div>

<div class="card">
<h2>Tabel 2 — Kelompok per Tanggal ({{selected_day}})</h2>
{% if day_bags %}
<table><tr><th>BAG</th><th>Anggota</th></tr>
{% for b in day_bags %}
<tr>
<td><span class="badge bag{{loop.index0 % 8}}">{{b.label}}</span></td>
<td>{% for m in b.members %}<span class="badge bag{{loop.index0 % 8}}">{{m.code}}-{{m.number}}</span>{% endfor %}</td>
</tr>
{% endfor %}
</table>
{% else %}<p>Belum ada kelompok di tanggal ini.</p>{% endif %}
{% if day_singles %}
<p><b>Tidak berkelompok:</b> {% for s in day_singles %}<span class="badge">{{s.code}}-{{s.number}}</span>{% endfor %}</p>
{% endif %}
</div>

<div class="card">
<h2>Pasangan terkuat</h2>
<table><tr><th>Pasaran A</th><th>Pasaran B</th><th>Terhubung</th><th>Persentase</th></tr>
{% for p in pairs[:100] %}
<tr><td>{{p.code_a}}</td><td>{{p.code_b}}</td><td>{{p.count}}/{{dates}}</td><td>{{p.rate}}%</td></tr>
{% endfor %}
</table>
</div>

<div class="card">
<h2>Pasaran berhasil dibaca</h2>
<p>{{markets}} / {{configured}}</p>
{% if errors %}
<h3 class="err">Gagal dibaca</h3>
<ul>{% for e in errors %}<li class="err">{{e.id}} — {{e.error}}</li>{% endfor %}</ul>
{% endif %}
</div>
</body>
</html>
"""

@app.route("/")
def index():
    overlap_min = int(request.args.get("overlap", DEFAULT_OVERLAP))
    min_days = int(request.args.get("mindays", DEFAULT_MIN_DAYS))
    markets, errors = collect()
    result = analyze(markets, overlap_min, min_days)
    result["errors"] = errors

    dates_desc = result["dates_desc"]
    selected_day = request.args.get("day") or (dates_desc[0] if dates_desc else None)
    if selected_day not in dates_desc and dates_desc:
        selected_day = dates_desc[0]
    day_data = result["daily_clusters"].get(selected_day, {"bags": [], "singles": []})

    return render_template_string(
        TEMPLATE,
        clusters=result["stable_clusters"],
        pairs=result["stable_pairs"],
        dates=result["total_dates"],
        dates_desc=dates_desc,
        selected_day=selected_day,
        day_bags=day_data["bags"],
        day_singles=day_data["singles"],
        markets=len(markets),
        configured=len(load_sources()),
        errors=errors,
        overlap=overlap_min,
        mindays=min_days,
        window=DEFAULT_WINDOW,
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
