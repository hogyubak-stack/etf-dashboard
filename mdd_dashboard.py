"""
KOSPI / KOSDAQ MDD 대시보드 생성기 v3
- 연도별 MDD (캘린더 분할)
- 기간 필터 버튼: 1년 / 3년 / 5년 / 10년 / 전체
- 바차트 수치 레이블 + 평균선
- 전체 기간 라인차트 + 낙폭 시리즈

사용법:
    python mdd_dashboard.py                        # 기본: 가능한 최대
    python mdd_dashboard.py 2010-01-01             # 시작일 지정
    python mdd_dashboard.py 2000-01-01 2024-12-31  # 시작일 + 종료일
"""

import sys
import os
import json
import statistics
from datetime import datetime, timedelta
import yfinance as yf

today = datetime.today()
if len(sys.argv) >= 3:
    start_str = sys.argv[1]
    end_str   = sys.argv[2]
elif len(sys.argv) == 2:
    start_str = sys.argv[1]
    end_str   = today.strftime("%Y-%m-%d")
else:
    start_str = "1990-01-01"
    end_str   = today.strftime("%Y-%m-%d")

print(f"기간: {start_str} ~ {end_str}")

def fetch_index(ticker, start, end):
    # yfinance의 end는 '미포함'이라 하루 더해 종료일까지 포함시킴
    end_plus = (datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=start, end=end_plus, progress=False, auto_adjust=False)
    df = df[["Close"]]
    df.columns = ["Close"]   # yfinance의 MultiIndex 컬럼 평탄화
    return df.dropna()

print("KOSPI 데이터 수집 중... (Yahoo Finance ^KS11)")
kospi  = fetch_index("^KS11", start_str, end_str)
print(f"  → {len(kospi)}거래일")

print("KOSDAQ 데이터 수집 중... (Yahoo Finance ^KQ11)")
kosdaq = fetch_index("^KQ11", start_str, end_str)
print(f"  → {len(kosdaq)}거래일")


def calc_mdd_full(closes):
    cur_peak = closes[0]; cur_peak_idx = 0
    mdd, mdd_si, mdd_ei = 0.0, 0, 0
    for i, v in enumerate(closes):
        if v > cur_peak: cur_peak = v; cur_peak_idx = i
        dd = (v - cur_peak) / cur_peak
        if dd < mdd: mdd, mdd_si, mdd_ei = dd, cur_peak_idx, i
    return round(mdd * 100, 2), mdd_si, mdd_ei


def calc_yearly_mdd(df):
    results = []
    for yr in sorted(df.index.year.unique()):
        sub = df[df.index.year == yr]
        closes = sub["Close"].tolist()
        dates  = sub.index.strftime("%Y-%m-%d").tolist()
        if len(closes) < 2: continue
        cur_peak = closes[0]; cur_peak_idx = 0
        mdd, mdd_si, mdd_ei = 0.0, 0, 0
        for i, v in enumerate(closes):
            if v > cur_peak: cur_peak = v; cur_peak_idx = i
            dd = (v - cur_peak) / cur_peak
            if dd < mdd: mdd, mdd_si, mdd_ei = dd, cur_peak_idx, i
        results.append({
            "year": yr, "mdd": round(mdd * 100, 2),
            "mdd_start": dates[mdd_si], "mdd_end": dates[mdd_ei],
            "n_days": len(closes),
            "ret": round((closes[-1] - closes[0]) / closes[0] * 100, 2),
        })
    return results


def calc_drawdown_series(closes):
    peak = closes[0]; dds = []
    for v in closes:
        if v > peak: peak = v
        dds.append(round((v - peak) / peak * 100, 4))
    return dds


def normalize(closes):
    base = closes[0]
    return [round(v / base * 100, 4) for v in closes]


def yearly_stats(yearly):
    vals = [r["mdd"] for r in yearly]
    avg  = round(statistics.mean(vals), 2)
    med  = round(statistics.median(vals), 2)
    sorted_vals = sorted(vals)
    cutoff = max(1, len(sorted_vals) // 10)
    trimmed = sorted_vals[cutoff:]
    avg_trim = round(statistics.mean(trimmed), 2) if trimmed else avg
    return {"avg": avg, "median": med, "avg_trim": avg_trim,
            "worst": min(vals), "best": max(vals), "n": len(vals)}


def prepare(df):
    dates  = df.index.strftime("%Y-%m-%d").tolist()
    closes = df["Close"].tolist()
    mdd_pct, mdd_si, mdd_ei = calc_mdd_full(closes)
    total_ret = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
    cur_peak  = max(closes)
    yearly = calc_yearly_mdd(df)
    return {
        "dates":      dates,
        "closes":     [round(v, 2) for v in closes],
        "norm":       normalize(closes),
        "dds":        calc_drawdown_series(closes),
        "mdd":        mdd_pct,
        "mdd_start":  dates[mdd_si],
        "mdd_end":    dates[mdd_ei],
        "total_ret":  total_ret,
        "cur":        round(closes[-1], 2),
        "cur_dd":     round((closes[-1] - cur_peak) / cur_peak * 100, 2),
        "start_date": dates[0],
        "end_date":   dates[-1],
        "n_days":     len(dates),
        "yearly":     yearly,
        "stats":      yearly_stats(yearly),
    }


print("계산 중...")
kp = prepare(kospi)
kq = prepare(kosdaq)

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mdd_dashboard.html")
kp_json = json.dumps(kp, ensure_ascii=False)
kq_json = json.dumps(kq, ensure_ascii=False)

html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KOSPI · KOSDAQ MDD 대시보드</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
:root {{
  --bg:#0f1117; --bg2:#1a1d27; --bg3:#22263a;
  --border:rgba(255,255,255,.07); --text:#e8eaf0; --muted:#8890a4;
  --red:#e24b4a; --green:#1d9e75; --blue:#378add; --amber:#ef9f27;
  --radius:10px;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:'Pretendard','Malgun Gothic','Apple SD Gothic Neo','Noto Sans CJK KR','NanumGothic',sans-serif;font-size:14px;line-height:1.6}}
.page{{max-width:1100px;margin:0 auto;padding:28px 20px 60px}}
h1{{font-size:18px;font-weight:500;margin-bottom:4px}}
.subtitle{{font-size:13px;color:var(--muted);margin-bottom:20px}}
.section{{margin-bottom:52px}}
.section-header{{display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap}}
.section-title{{font-size:15px;font-weight:500}}

/* 기간 필터 */
.period-btns{{display:flex;gap:6px;margin-left:auto}}
.pb{{font-size:12px;padding:4px 12px;border:0.5px solid var(--border);border-radius:20px;
     background:transparent;color:var(--muted);cursor:pointer;transition:all .15s}}
.pb:hover{{background:var(--bg3);color:var(--text)}}
.pb.active{{background:var(--bg3);color:var(--text);border-color:rgba(255,255,255,.2)}}

/* 메트릭 */
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px}}
.mc{{background:var(--bg2);border:0.5px solid var(--border);border-radius:var(--radius);padding:14px 16px}}
.mc-label{{font-size:11px;color:var(--muted);margin-bottom:5px}}
.mc-val{{font-size:21px;font-weight:500}}
.mc-sub{{font-size:11px;color:var(--muted);margin-top:3px}}
.red{{color:var(--red)}}.green{{color:var(--green)}}.amber{{color:var(--amber)}}

/* 차트 */
.chart-box{{background:var(--bg2);border:0.5px solid var(--border);border-radius:var(--radius);padding:18px;margin-bottom:14px}}
.chart-legend{{font-size:12px;color:var(--muted);margin-bottom:10px;display:flex;gap:16px;flex-wrap:wrap}}
.leg{{display:flex;align-items:center;gap:5px}}
.leg-dot{{width:10px;height:10px;border-radius:2px}}
.chart-wrap{{position:relative;width:100%}}

/* 테이블 */
.yr-table-box{{background:var(--bg2);border:0.5px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:14px}}
.yr-table-header{{font-size:12px;color:var(--muted);padding:12px 16px 8px;border-bottom:0.5px solid var(--border);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.stat-pills{{display:flex;gap:8px;flex-wrap:wrap}}
.pill{{font-size:11px;padding:3px 10px;border-radius:20px;background:var(--bg3);color:var(--muted)}}
.pill span{{color:var(--text);font-weight:500}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{font-size:11px;color:var(--muted);font-weight:400;text-align:left;padding:8px 14px;border-bottom:0.5px solid var(--border);white-space:nowrap}}
td{{padding:8px 14px;border-bottom:0.5px solid var(--border);white-space:nowrap}}
tr:last-child td{{border-bottom:none}}
tr.worst-row td{{background:rgba(226,75,74,.07)}}
.dd-bar-wrap{{width:80px}}
.dd-bar{{height:4px;border-radius:2px;background:var(--red);opacity:.75}}
.ret-pos{{color:var(--green)}}.ret-neg{{color:var(--red)}}
</style>
</head>
<body>
<div class="page">
  <h1>KOSPI · KOSDAQ MDD 대시보드</h1>
  <p class="subtitle">데이터: {start_str} ~ {end_str} &nbsp;·&nbsp; 생성: {today.strftime('%Y-%m-%d %H:%M')}</p>
  <div id="root"></div>
</div>

<script>
if (typeof Chart !== 'undefined') {{ Chart.defaults.animation = false; }}
const DATA = {{
  kospi:  {kp_json},
  kosdaq: {kq_json}
}};

// 기간 필터: 전체 데이터에서 최근 N년 슬라이싱
function filterByYears(d, years) {{
  if (!years) return d;
  const cutoff = new Date(d.dates[d.dates.length-1]);
  cutoff.setFullYear(cutoff.getFullYear() - years);
  const cutStr = cutoff.toISOString().slice(0,10);
  const idx = d.dates.findIndex(dt => dt >= cutStr);
  if (idx <= 0) return d;

  const dates  = d.dates.slice(idx);
  const closes = d.closes.slice(idx);
  const base   = closes[0];
  const norm   = closes.map(v => +(v/base*100).toFixed(4));

  let peak = closes[0]; let mdd=0; let mdd_si=0; let mdd_ei=0; let cpIdx=0;
  const dds = closes.map((v,i) => {{
    if(v>peak){{peak=v;cpIdx=i;}}
    const dd=(v-peak)/peak*100;
    if(dd<mdd){{mdd=dd;mdd_si=cpIdx;mdd_ei=i;}}
    return +dd.toFixed(4);
  }});

  const totalRet = +((closes[closes.length-1]-closes[0])/closes[0]*100).toFixed(2);
  const curPeak  = Math.max(...closes);
  const curDd    = +((closes[closes.length-1]-curPeak)/curPeak*100).toFixed(2);

  // 연도별 재계산
  const yearMap = {{}};
  dates.forEach((dt,i) => {{
    const yr = dt.slice(0,4);
    if(!yearMap[yr]) yearMap[yr] = {{dates:[],closes:[]}};
    yearMap[yr].dates.push(dt);
    yearMap[yr].closes.push(closes[i]);
  }});
  const yearly = Object.entries(yearMap).map(([yr,yd]) => {{
    let pk=yd.closes[0],pkI=0,ym=0,ysi=0,yei=0;
    yd.closes.forEach((v,i) => {{
      if(v>pk){{pk=v;pkI=i;}}
      const dd=(v-pk)/pk;
      if(dd<ym){{ym=dd;ysi=pkI;yei=i;}}
    }});
    return {{year:+yr, mdd:+(ym*100).toFixed(2),
             mdd_start:yd.dates[ysi], mdd_end:yd.dates[yei],
             n_days:yd.closes.length,
             ret:+((yd.closes[yd.closes.length-1]-yd.closes[0])/yd.closes[0]*100).toFixed(2)}};
  }});
  const mddVals = yearly.map(r=>r.mdd);
  const avg = +(mddVals.reduce((a,b)=>a+b,0)/mddVals.length).toFixed(2);
  const sorted = [...mddVals].sort((a,b)=>a-b);
  const med = sorted.length%2===0
    ? +((sorted[sorted.length/2-1]+sorted[sorted.length/2])/2).toFixed(2)
    : +sorted[Math.floor(sorted.length/2)].toFixed(2);
  const cut = Math.max(1, Math.floor(sorted.length/10));
  const trimmed = sorted.slice(cut);
  const avgTrim = trimmed.length ? +(trimmed.reduce((a,b)=>a+b,0)/trimmed.length).toFixed(2) : avg;

  return {{
    ...d,
    dates, closes, norm, dds,
    mdd: +mdd.toFixed(2),
    mdd_start: dates[mdd_si], mdd_end: dates[mdd_ei],
    total_ret: totalRet, cur: closes[closes.length-1],
    cur_dd: curDd, start_date: dates[0], end_date: dates[dates.length-1],
    n_days: dates.length, yearly,
    stats: {{avg, median:med, avg_trim:avgTrim, worst:Math.min(...mddVals), best:Math.max(...mddVals), n:mddVals.length}}
  }};
}}

const sign = v => (v>=0?'+':'')+v.toFixed(2)+'%';
const cls  = v => v>=0?'ret-pos':'ret-neg';
const barColor = v => v<-30?'#a32d2d':v<-20?'#e24b4a':v<-10?'#ef9f27':'#5f5e5a';

let charts = {{}};

function renderMetrics(prefix, d) {{
  const s = d.stats;
  document.getElementById(prefix+'-metrics').innerHTML = `
    <div class="mc"><div class="mc-label">현재</div>
      <div class="mc-val">${{Math.round(d.cur).toLocaleString()}}</div>
      <div class="mc-sub">${{d.end_date}}</div></div>
    <div class="mc"><div class="mc-label">기간 수익률</div>
      <div class="mc-val ${{cls(d.total_ret)}}">${{sign(d.total_ret)}}</div>
      <div class="mc-sub">${{d.start_date}} ~ ${{d.end_date}}</div></div>
    <div class="mc"><div class="mc-label">전체 MDD</div>
      <div class="mc-val red">${{d.mdd.toFixed(2)}}%</div>
      <div class="mc-sub">${{d.mdd_start}} → ${{d.mdd_end}}</div></div>
    <div class="mc"><div class="mc-label">현재 낙폭</div>
      <div class="mc-val ${{d.cur_dd>=-5?'green':'red'}}">${{d.cur_dd.toFixed(2)}}%</div>
      <div class="mc-sub">고점 대비</div></div>
    <div class="mc"><div class="mc-label">연평균 MDD</div>
      <div class="mc-val red">${{s.avg.toFixed(2)}}%</div>
      <div class="mc-sub">중앙값 ${{s.median.toFixed(2)}}%</div></div>
    <div class="mc"><div class="mc-label">이상치 제외 평균</div>
      <div class="mc-val amber">${{s.avg_trim.toFixed(2)}}%</div>
      <div class="mc-sub">최악 10% 제외</div></div>
  `;
}}

function renderTable(prefix, d) {{
  const worst = Math.min(...d.yearly.map(r=>r.mdd));
  const rows = d.yearly.map(r => {{
    const bw = Math.min(100, Math.abs(r.mdd)/Math.abs(worst)*100);
    return `<tr class="${{r.mdd===worst?'worst-row':''}}">
      <td style="font-weight:500">${{r.year}}</td>
      <td class="red">${{r.mdd.toFixed(2)}}%</td>
      <td style="color:var(--muted)">${{r.mdd_start}}</td>
      <td style="color:var(--muted)">${{r.mdd_end}}</td>
      <td class="${{cls(r.ret)}}">${{sign(r.ret)}}</td>
      <td style="color:var(--muted);font-size:12px">${{r.n_days}}일</td>
      <td class="dd-bar-wrap"><div class="dd-bar" style="width:${{bw.toFixed(0)}}%"></div></td>
    </tr>`;
  }}).join('');
  const s = d.stats;
  document.getElementById(prefix+'-table').innerHTML = `
    <div class="yr-table-header">
      <span>연도별 MDD</span>
      <div class="stat-pills">
        <div class="pill">평균 <span>${{s.avg.toFixed(2)}}%</span></div>
        <div class="pill">중앙값 <span>${{s.median.toFixed(2)}}%</span></div>
        <div class="pill">이상치 제외 <span>${{s.avg_trim.toFixed(2)}}%</span></div>
        <div class="pill">최악 <span>${{s.worst.toFixed(2)}}%</span></div>
        <div class="pill">최선 <span>${{s.best.toFixed(2)}}%</span></div>
      </div>
    </div>
    <table><thead><tr>
      <th>연도</th><th>MDD</th><th>고점일</th><th>저점일</th>
      <th>연간수익률</th><th>거래일</th><th></th>
    </tr></thead><tbody>${{rows}}</tbody></table>
  `;
}}

function makeLineChart(id, d, idxColor) {{
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{
      labels: d.dates,
      datasets: [
        {{ label:'지수', data:d.norm, borderColor:idxColor, borderWidth:1.5,
           pointRadius:0, yAxisID:'y', tension:0.1 }},
        {{ label:'낙폭', data:d.dds, borderColor:'#e24b4a', borderWidth:1,
           pointRadius:0, fill:{{target:'origin',above:'rgba(226,75,74,0.15)'}},
           yAxisID:'y2', tension:0.1 }}
      ]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{
        legend:{{display:false}},
        tooltip:{{
          backgroundColor:'#1a1d27',borderColor:'rgba(255,255,255,.1)',borderWidth:1,
          titleColor:'#8890a4',bodyColor:'#e8eaf0',
          callbacks:{{label:ctx=>ctx.datasetIndex===0
            ?` 지수: ${{ctx.parsed.y.toFixed(1)}}`
            :` 낙폭: ${{ctx.parsed.y.toFixed(2)}}%`}}
        }}
      }},
      scales:{{
        x:{{ticks:{{maxTicksLimit:8,maxRotation:0,font:{{size:11}},color:'#8890a4'}},
            grid:{{color:'rgba(255,255,255,.04)'}},border:{{color:'rgba(255,255,255,.08)'}}}},
        y:{{position:'left',ticks:{{font:{{size:11}},color:'#8890a4',maxTicksLimit:6}},
            grid:{{color:'rgba(255,255,255,.06)'}},border:{{color:'rgba(255,255,255,.08)'}}}},
        y2:{{position:'right',max:5,
             ticks:{{font:{{size:11}},color:'#e24b4a',maxTicksLimit:5,callback:v=>v.toFixed(0)+'%'}},
             grid:{{display:false}},border:{{display:false}}}}
      }}
    }}
  }});
}}

function makeBarChart(id, d) {{
  const years  = d.yearly.map(r=>String(r.year));
  const mdds   = d.yearly.map(r=>r.mdd);
  const rets   = d.yearly.map(r=>r.ret);
  const colors = mdds.map(barColor);
  const avg    = d.stats.avg;

  const labelPlugin = {{
    id:'customLabels',
    afterDraw(chart) {{
      const c   = chart.ctx;
      const meta = chart.getDatasetMeta(0);
      const yScale = chart.scales.y;

      // 수치 레이블만 (평균선 제거)
      c.save();
      c.font = '10px sans-serif';
      c.textAlign = 'center';
      c.fillStyle = 'rgba(255,255,255,0.9)';
      meta.data.forEach((bar,i) => {{
        const barH = bar.base - bar.y;
        if (barH < 16) return;
        c.fillText(mdds[i].toFixed(1)+'%', bar.x, bar.y+12);
      }});
      c.restore();
    }}
  }};

  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), {{
    type: 'bar',
    plugins: [labelPlugin],
    data: {{
      labels: years,
      datasets: [{{
        label:'MDD', data:mdds,
        backgroundColor:colors,
        borderRadius:{{topLeft:3,topRight:3}},
        barPercentage:0.7, categoryPercentage:0.8,
      }}]
    }},
    options: {{
      responsive:true, maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      layout:{{padding:{{top:22}}}},
      plugins:{{
        legend:{{display:false}},
        tooltip:{{
          backgroundColor:'#1a1d27',borderColor:'rgba(255,255,255,.1)',borderWidth:1,
          titleColor:'#8890a4',bodyColor:'#e8eaf0',
          callbacks:{{label:ctx=>{{
            const i=ctx.dataIndex;
            return [` MDD: ${{mdds[i].toFixed(2)}}%`,` 연수익: ${{rets[i]>=0?'+':''}}${{rets[i].toFixed(2)}}%`];
          }}}}
        }}
      }},
      scales:{{
        x:{{ticks:{{font:{{size:11}},color:'#8890a4',maxRotation:0}},
            grid:{{display:false}},border:{{color:'rgba(255,255,255,.08)'}}}},
        y:{{max:0,
            ticks:{{font:{{size:11}},color:'#8890a4',callback:v=>v+'%',maxTicksLimit:6}},
            grid:{{color:'rgba(255,255,255,.04)'}},border:{{color:'rgba(255,255,255,.08)'}}}}
      }}
    }}
  }});
}}

function buildSection(rawData, prefix, label, idxColor, cLine, cBar) {{
  document.getElementById('root').insertAdjacentHTML('beforeend', `
    <div class="section">
      <div class="section-header">
        <span class="section-title">${{label}}</span>
        <div class="period-btns" id="${{prefix}}-btns">
          <button class="pb" data-y="1">1년</button>
          <button class="pb" data-y="3">3년</button>
          <button class="pb" data-y="5">5년</button>
          <button class="pb" data-y="10">10년</button>
          <button class="pb" data-y="20">20년</button>
          <button class="pb active" data-y="0">전체</button>
        </div>
      </div>
      <div id="${{prefix}}-metrics" class="metrics"></div>
      <div class="chart-box">
        <div class="chart-legend">
          <span class="leg"><span class="leg-dot" style="background:${{idxColor}}"></span>지수 (정규화)</span>
          <span class="leg"><span class="leg-dot" style="background:#e24b4a"></span>낙폭 (%)</span>
        </div>
        <div class="chart-wrap" style="height:240px"><canvas id="${{cLine}}"></canvas></div>
      </div>
      <div class="chart-box">
        <div class="chart-legend" id="${{prefix}}-bar-legend">
          <span class="leg"><span class="leg-dot" style="background:#5f5e5a"></span>-10% 미만</span>
          <span class="leg"><span class="leg-dot" style="background:#ef9f27"></span>-10%~-20%</span>
          <span class="leg"><span class="leg-dot" style="background:#e24b4a"></span>-20%~-30%</span>
          <span class="leg"><span class="leg-dot" style="background:#a32d2d"></span>-30% 초과</span>
        </div>
        <div class="chart-wrap" style="height:260px"><canvas id="${{cBar}}"></canvas></div>
      </div>
      <div id="${{prefix}}-table" class="yr-table-box"></div>
    </div>
  `);

  function refresh(years) {{
    const d = filterByYears(rawData, years || null);
    renderMetrics(prefix, d);
    makeLineChart(cLine, d, idxColor);
    makeBarChart(cBar, d);
    renderTable(prefix, d);
    // 바차트 범례에 평균 MDD 표시
    const periodLabel = years ? years+'년' : '전체';
    document.getElementById(prefix+'-bar-legend').innerHTML = `
      <span class="leg"><span class="leg-dot" style="background:#5f5e5a"></span>-10% 미만</span>
      <span class="leg"><span class="leg-dot" style="background:#ef9f27"></span>-10%~-20%</span>
      <span class="leg"><span class="leg-dot" style="background:#e24b4a"></span>-20%~-30%</span>
      <span class="leg"><span class="leg-dot" style="background:#a32d2d"></span>-30% 초과</span>
      <span style="margin-left:auto;font-size:12px;color:var(--muted)">
        ${{periodLabel}} 평균 <span style="color:#ef9f27;font-weight:500">${{d.stats.avg.toFixed(1)}}%</span>
        &nbsp;·&nbsp; 중앙값 <span style="color:#ef9f27;font-weight:500">${{d.stats.median.toFixed(1)}}%</span>
      </span>
    `;
  }}

  document.getElementById(prefix+'-btns').addEventListener('click', e => {{
    const btn = e.target.closest('.pb');
    if (!btn) return;
    document.querySelectorAll(`#${{prefix}}-btns .pb`).forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    refresh(+btn.dataset.y || 0);
  }});

  refresh(0);
}}

buildSection(DATA.kospi,  'kp', 'KOSPI',  '#378add', 'lc1', 'bc1');
buildSection(DATA.kosdaq, 'kq', 'KOSDAQ', '#1d9e75', 'lc2', 'bc2');
</script>
</body>
</html>"""

with open(output_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n완료 → {output_path}")


# ───────────────────────── PNG 변환 및 Google Drive 업로드 ─────────────────────────
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _find_browser_bin():
    import shutil
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def html_to_png(html_path: str, png_path: str):
    import subprocess, tempfile
    browser = _find_browser_bin()
    if not browser:
        raise RuntimeError("Chrome 또는 Edge 브라우저를 찾을 수 없어 PNG를 생성할 수 없습니다.")

    abs_html = os.path.abspath(html_path).replace("\\", "/")
    file_url = f"file://{abs_html}" if abs_html.startswith("/") else f"file:///{abs_html}"
    abs_png = os.path.abspath(png_path)

    with tempfile.TemporaryDirectory() as tmp_profile:
        cmd = [
            browser,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--virtual-time-budget=3000",
            f"--user-data-dir={tmp_profile}",
            "--window-size=1160,3600",
            f"--screenshot={abs_png}",
            file_url,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=False)

    if os.path.exists(abs_png) and os.path.getsize(abs_png) > 0:
        return True
    raise RuntimeError("PNG 스크린샷 파일이 생성되지 않았습니다.")


def get_gdrive_service(creds_path: str, token_path: str):
    from googleapiclient.discovery import build

    env_creds = os.environ.get("GDRIVE_CREDENTIALS_JSON", "").strip()
    env_token = os.environ.get("GDRIVE_TOKEN_JSON", "").strip()
    if env_creds and not os.path.exists(creds_path):
        with open(creds_path, "w", encoding="utf-8") as f:
            f.write(env_creds)
    if env_token and not os.path.exists(token_path):
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(env_token)

    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"인증 파일을 찾을 수 없습니다: {creds_path}")

    with open(creds_path, "r", encoding="utf-8") as f:
        info = json.load(f)

    if info.get("type") == "service_account":
        from google.oauth2.service_account import Credentials as SACredentials
        creds = SACredentials.from_service_account_file(creds_path, scopes=GDRIVE_SCOPES)
    else:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, GDRIVE_SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(creds_path, GDRIVE_SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def upload_to_gdrive(local_path: str, service, folder_id: str | None = None) -> dict:
    import mimetypes
    from googleapiclient.http import MediaFileUpload

    filename = os.path.basename(local_path)
    mime_type, _ = mimetypes.guess_type(local_path)
    if not mime_type:
        mime_type = "image/png" if filename.lower().endswith(".png") else "text/html"

    escaped_name = filename.replace("'", "\\'")
    q = f"name = '{escaped_name}' and trashed = false"
    if folder_id:
        q += f" and '{folder_id}' in parents"

    res = service.files().list(q=q, spaces="drive", fields="files(id, name, webViewLink)", pageSize=1).execute()
    files = res.get("files", [])
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=False)

    if files:
        return service.files().update(
            fileId=files[0]["id"],
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
    else:
        meta = {"name": filename, "mimeType": mime_type}
        if folder_id:
            meta["parents"] = [folder_id]
        return service.files().create(
            body=meta,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()


base_dir = os.path.dirname(os.path.abspath(__file__))
png_path = os.path.join(base_dir, "mdd_dashboard.png")
upload_targets = [output_path]

try:
    html_to_png(output_path, png_path)
    print(f"PNG 생성 완료 → {png_path}")
    upload_targets.append(png_path)
except Exception as e:
    print(f"[PNG 경고] PNG 변환 실패: {e}", file=sys.stderr)

# 로컬(d:\) 또는 현재 폴더에서 credentials.json / token.json 탐색
creds_candidates = [os.path.join(base_dir, "credentials.json"), r"d:\credentials.json"]
token_candidates = [os.path.join(base_dir, "token.json"), r"d:\token.json"]
creds_path = next((p for p in creds_candidates if os.path.exists(p)), creds_candidates[0])
token_path = next((p for p in token_candidates if os.path.exists(p)), token_candidates[0])
folder_id = os.environ.get("GDRIVE_FOLDER_ID")

try:
    service = get_gdrive_service(creds_path, token_path)
    for target in upload_targets:
        info = upload_to_gdrive(target, service=service, folder_id=folder_id)
        link = info.get("webViewLink", f"fileId={info.get('id')}")
        print(f"[Google Drive] 업로드 완료: {info.get('name')} ({link})")
except Exception as e:
    print(f"[Google Drive 경고] 업로드 실패: {e}", file=sys.stderr)
