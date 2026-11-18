#!/usr/bin/env python3
"""
섹터별 대표 ETF 대시보드
 - 컬럼: 종목명 | 현재가 | 등락률 | L일봉H | L주봉H | L월봉H | L연봉H | 시가총액(억)
 - 데이터: 네이버 금융 (FinanceDataReader 경유)
 - 결과: etf_dashboard.html 및 etf_dashboard.png 생성 + Google Drive API 업로드 + 평일(월~금) 08:00, 13:00, 20:30 자동 갱신

설치:  pip install finance-datareader pandas requests google-api-python-client google-auth-httplib2 google-auth-oauthlib pillow
실행:  python etf_dashboard.py                         # 최초 1회 생성/업로드 후 평일 08:00/13:00/20:30 자동 갱신
       python etf_dashboard.py --once                  # 1회만 생성 및 업로드 후 종료
       python etf_dashboard.py --gdrive-folder <폴더ID> # 특정 Google Drive 폴더에 업로드
       python etf_dashboard.py --demo                  # 네트워크 없이 가짜 데이터로 화면 확인
"""
import argparse, datetime as dt, html, json, mimetypes, os, re, shutil, subprocess, sys, tempfile, time, webbrowser

import pandas as pd

SCHEDULE_TIMES = [(9, 40), (13, 0), (20, 30)]  # 평일(월~금) 자동 갱신 시각 (시, 분)
GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

ETF_NAMES = [
    "KODEX 200", "KODEX 코스닥150", "TIGER 반도체TOP10", "SOL AI반도체소부장",
    "KoAct 바이오헬스케어액티브", "KODEX 2차전지산업", "KODEX 자동차",
    "KODEX AI전력핵심설비", "TIGER 코리아원자력", "TIGER 코리아휴머노이드로봇산업",
    "TIGER 화장품", "SOL 조선TOP3플러스", "PLUS K방산", "PLUS 우주항공",
    "PLUS 태양광&ESS", "KODEX 신재생에너지액티브", "TIGER 여행레저",
    "ACE KPOP포커스", "TIGER 소프트웨어", "KoAct 광통신&위성네트워크액티브",
    "KODEX 건설", "TIGER 은행고배당플러스TOP10", "KODEX 증권",
]

PERIODS = [("D", "L일봉H"), ("W", "L주봉H"), ("M", "L월봉H"), ("Y", "L연봉H")]
UP, DOWN, FLAT = "#e0262b", "#1f5fd6", "#333"


# ───────────────────────── 데이터 수집 ─────────────────────────
def norm(s: str) -> str:
    return re.sub(r"\s+", "", s).upper()


def load_listing() -> pd.DataFrame:
    import FinanceDataReader as fdr
    df = fdr.StockListing("ETF/KR")  # Symbol, Name, Price, ChangeRate, MarCap(억원) ...
    df["key"] = df["Name"].map(norm)
    return df


def resolve(listing: pd.DataFrame, name: str):
    """종목명 → 행. 정확 일치 우선, 없으면 공백 무시/부분 일치."""
    k = norm(name)
    hit = listing[listing["key"] == k]
    if hit.empty:
        hit = listing[listing["key"].str.startswith(k) | listing["key"].str.contains(re.escape(k))]
    return None if hit.empty else hit.iloc[0]


WINDOWS = {"D": 1, "W": 5, "M": 20, "Y": 240}  # 최근 N거래일 (롤링)


def period_candles(daily: pd.DataFrame) -> dict:
    """
    일봉 → 롤링 캔들. 최근 N거래일(1/5/20/240)의
    시가=N거래일 전 첫날 시가, 고/저=구간 최고/최저, 종가=최신 종가,
    기준가=구간 직전 거래일 종가 (예: 주봉은 6거래일 전 종가).
    """
    out = {}
    daily = daily.dropna(subset=["Close"]).sort_index()
    for p, n in WINDOWS.items():
        if len(daily) == 0:
            continue
        w = daily.iloc[-n:]
        short = len(daily) < n + 1  # 데이터 부족(신규 상장 등)
        base = float(daily["Close"].iloc[-n - 1]) if not short else float(w["Open"].iloc[0])
        out[p] = dict(O=float(w["Open"].iloc[0]), H=float(w["High"].max()),
                      L=float(w["Low"].min()), C=float(w["Close"].iloc[-1]),
                      base=base, days=len(w), short=short)
    return out


def fetch_live():
    import FinanceDataReader as fdr
    listing = load_listing()
    start = (dt.date.today() - dt.timedelta(days=400)).isoformat()  # 241거래일 이상 확보
    rows, missing = [], []
    for name in ETF_NAMES:
        r = resolve(listing, name)
        if r is None:
            missing.append(name); continue
        try:
            daily = fdr.DataReader(r["Symbol"], start)
        except Exception as e:
            print(f"[경고] {name}({r['Symbol']}) 일봉 실패: {e}", file=sys.stderr)
            daily = pd.DataFrame()
        rows.append(dict(name=r["Name"], code=r["Symbol"], price=float(r["Price"]),
                         chg=float(r["ChangeRate"]), mcap=float(r["MarCap"]),
                         candles=period_candles(daily) if len(daily) else {}))
    return rows, missing


def fetch_demo():
    """화면 확인용 가짜 데이터 (실제 시세 아님)."""
    import numpy as np
    rng = np.random.default_rng(0)
    idx = pd.bdate_range(dt.date.today() - dt.timedelta(days=400), dt.date.today())
    rows = []
    for i, name in enumerate(ETF_NAMES):
        p = 10000 * np.exp(np.cumsum(rng.normal(0.0008, 0.018, len(idx))))
        o = p * (1 + rng.normal(0, .004, len(idx)))
        daily = pd.DataFrame({"Open": o, "Close": p,
                              "High": np.maximum(o, p) * (1 + abs(rng.normal(0, .006, len(idx)))),
                              "Low": np.minimum(o, p) * (1 - abs(rng.normal(0, .006, len(idx))))}, index=idx)
        c = period_candles(daily)
        rows.append(dict(name=name, code=f"DEMO{i:02d}", price=c["D"]["C"],
                         chg=(c["D"]["C"] / c["D"]["base"] - 1) * 100,
                         mcap=float(rng.integers(80, 220000)), candles=c))
    return rows, []


# ───────────────────────── 렌더링 ─────────────────────────
def candle_svg(c: dict, span: float, w=96, h=16) -> str:
    """
    가로형 미니 캔들 (키움 'L일봉H' 스타일).
    가로축 = 직전 기간 종가 대비 % (컬럼 전체 공통 스케일 ±span%), 중앙 세로선 = 기준가.
    얇은 선 = 저가~고가, 굵은 막대 = 시가~종가 (빨강 상승 / 파랑 하락).
    """
    if not c:
        return ""
    pct = lambda v: (v / c["base"] - 1) * 100
    x = lambda v: 4 + (pct(v) + span) / (2 * span) * (w - 8)
    col = UP if c["C"] > c["O"] else DOWN if c["C"] < c["O"] else FLAT
    xl, xh, xo, xc = x(c["L"]), x(c["H"]), x(c["O"]), x(c["C"])
    bx, bw = min(xo, xc), max(abs(xc - xo), 1.5)
    tip = (f"시 {c['O']:,.0f} / 고 {c['H']:,.0f} / 저 {c['L']:,.0f} / 종 {c['C']:,.0f}\n"
           + (f"⚠ 데이터 {c['days']}거래일뿐 (기준가=첫날 시가)\n" if c.get("short") else "")
           + f"기준가 {c['base']:,.0f}  ({pct(c['C']):+.2f}%)  고 {pct(c['H']):+.2f}% 저 {pct(c['L']):+.2f}%")
    return (f'<svg width="{w}" height="{h}"><title>{html.escape(tip)}</title>'
            f'<line x1="{w/2}" y1="1" x2="{w/2}" y2="{h-1}" stroke="#bbb" stroke-dasharray="2,2"/>'
            f'<line x1="{xl:.1f}" y1="{h/2}" x2="{xh:.1f}" y2="{h/2}" stroke="{col}" stroke-width="1.2"/>'
            f'<rect x="{bx:.1f}" y="{h/2-4}" width="{bw:.1f}" height="8" fill="{col}"/></svg>'
            f'<div class="pct" style="color:{UP if pct(c["C"]) > 0 else DOWN if pct(c["C"]) < 0 else FLAT}">'
            f'{pct(c["C"]):+.2f}%</div>')


def build_html(rows, missing, refresh=None, next_run=None, demo=False) -> str:
    # 기간별 공통 스케일: 해당 컬럼 전체 종목의 최대 |고/저 %| 기준
    spans = {}
    for p, _ in PERIODS:
        m = [max(abs(r["candles"][p]["H"] / r["candles"][p]["base"] - 1),
                 abs(r["candles"][p]["L"] / r["candles"][p]["base"] - 1)) * 100
             for r in rows if p in r["candles"]]
        spans[p] = max(max(m, default=1) * 1.05, 0.5)

    def color(v): return UP if v > 0 else DOWN if v < 0 else FLAT

    body = []
    for r in rows:
        tds = "".join(f'<td class="cd">{candle_svg(r["candles"].get(p, {}), spans[p])}</td>' for p, _ in PERIODS)
        body.append(
            f'<tr><td class="nm">{html.escape(r["name"])}<span class="code">{r["code"]}</span></td>'
            f'<td class="num" style="color:{color(r["chg"])}">{r["price"]:,.0f}</td>'
            f'<td class="num" style="color:{color(r["chg"])}">{r["chg"]:+.2f}</td>'
            f'{tds}<td class="num">{r["mcap"]:,.0f}</td></tr>')

    head = "".join(f"<th>{t}<div class='sub'>±{spans[p]:.1f}%</div></th>" for p, t in PERIODS)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    nxt_str = f" · 다음 자동 갱신: {next_run:%Y-%m-%d(%a) %H:%M}" if next_run else ""
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    warn = ""
    if demo:
        warn += '<p class="warn">⚠ DEMO 모드 — 무작위로 생성한 가짜 데이터입니다. 실제 시세가 아닙니다.</p>'
    if missing:
        warn += f'<p class="warn">종목명 매칭 실패: {html.escape(", ".join(missing))}</p>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">{meta}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>섹터별 대표 ETF</title>
<style>
body{{font-family:-apple-system,"Malgun Gothic","Apple SD Gothic Neo","Noto Sans CJK KR","NanumGothic",sans-serif;margin:12px;color:#222}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;font-size:13px;white-space:nowrap}}
th{{background:#eef1f6;border:1px solid #cfd5df;padding:4px 6px;font-weight:600}}
th .sub{{font-size:10px;color:#888;font-weight:400}}
td{{border:1px solid #e1e4ea;padding:2px 6px}} tr:nth-child(even){{background:#fafbfc}}
.cap{{background:#fbe3ee;text-align:center;font-weight:600}}
.nm{{min-width:150px}} .code{{color:#aaa;font-size:10px;margin-left:4px}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}
.cd{{text-align:center;padding:1px 4px}} .cd svg{{display:block;margin:auto}}
.pct{{font-size:10px;line-height:1}} .warn{{color:#b00;font-size:12px}}
.foot{{font-size:11px;color:#777;margin-top:8px}}
</style></head><body>
{warn}
<div class="wrap"><table>
<tr><th>종목명</th><th>현재가</th><th>등락률</th>{head}<th>시가총액(억)</th></tr>
<tr><td class="cap" colspan="{4 + len(PERIODS)}">섹터별 대표 ETF</td></tr>
{''.join(body)}
</table></div>
<div class="foot">갱신 {now}{nxt_str} · 출처: 네이버 금융(FinanceDataReader) · 장중 지연 가능<br>
캔들 가로축 = 직전 기간 종가 대비 등락률(점선 = 기준가). 각 컬럼은 전 종목 공통 스케일(헤더의 ±%)이라 종목 간 비교 가능.
롤링 기준: 일봉=당일, 주봉=최근 5거래일, 월봉=최근 20거래일, 연봉=최근 240거래일 (기준가=각 구간 직전 거래일 종가). 캔들에 마우스를 올리면(모바일은 길게 누르기) 시/고/저/종 표시.</div>
</body></html>"""


# ───────────────────────── PNG 변환, Google Drive 업로드 & 스케줄러 ─────────────────────────
def _find_browser_bin() -> str | None:
    """Windows 및 Linux(GitHub Actions)에 설치된 Chrome/Edge 실행 파일 경로를 탐색."""
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


def _trim_png_whitespace(png_path: str, pad: int = 20):
    """Pillow가 설치되어 있으면 스크린샷 하단/우측의 불필요한 여백을 깔끔하게 자름."""
    try:
        from PIL import Image, ImageChops
        with Image.open(png_path) as im:
            rgb = im.convert("RGB")
            bg = Image.new("RGB", rgb.size, (255, 255, 255))
            diff = ImageChops.difference(rgb, bg)
            bbox = diff.getbbox()
            if bbox:
                w, h = im.size
                crop_box = (0, 0, min(w, bbox[2] + pad), min(h, bbox[3] + pad))
                cropped = im.crop(crop_box)
                cropped.save(png_path)
    except Exception:
        pass


def html_to_png(html_path: str, png_path: str, row_count: int = 25) -> bool:
    """HTML 파일을 고해상도 PNG 이미지로 렌더링 (Chrome/Edge 헤드리스 사용)."""
    browser = _find_browser_bin()
    if not browser:
        raise RuntimeError("Chrome 또는 Edge 브라우저를 찾을 수 없어 PNG를 생성할 수 없습니다.")

    abs_html = os.path.abspath(html_path).replace("\\", "/")
    file_url = f"file://{abs_html}" if abs_html.startswith("/") else f"file:///{abs_html}"
    abs_png = os.path.abspath(png_path)
    height = max(700, 180 + row_count * 34)

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
            f"--user-data-dir={tmp_profile}",
            f"--window-size=920,{height}",
            f"--screenshot={abs_png}",
            file_url,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)

    if os.path.exists(abs_png) and os.path.getsize(abs_png) > 0:
        _trim_png_whitespace(abs_png)
        return True
    raise RuntimeError("PNG 스크린샷 파일이 생성되지 않았습니다.")


def get_gdrive_service(creds_path: str, token_path: str):
    """
    OAuth 클라이언트(credentials.json) 또는 서비스 계정 JSON을 자동 판별해 Drive v3 서비스 반환.
    GitHub Actions 등 클라우드 환경을 위해 GDRIVE_CREDENTIALS_JSON / GDRIVE_TOKEN_JSON 환경변수도 지원.
    """
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
        raise FileNotFoundError(
            f"인증 파일을 찾을 수 없습니다: {creds_path}\n"
            "Google Cloud Console에서 OAuth 2.0 클라이언트 ID(데스크톱 앱) 또는 서비스 계정 JSON 키를 다운로드해 저장하세요."
        )

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


def upload_to_gdrive(local_path: str, creds_path: str = "credentials.json",
                     token_path: str = "token.json", folder_id: str | None = None,
                     service=None) -> dict:
    """Google Drive에 파일을 업로드(동일 파일명이 있으면 덮어쓰기 업데이트)."""
    from googleapiclient.http import MediaFileUpload

    if service is None:
        service = get_gdrive_service(creds_path, token_path)
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
        file_id = files[0]["id"]
        updated = service.files().update(
            fileId=file_id,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
        return updated
    else:
        meta = {"name": filename, "mimeType": mime_type}
        if folder_id:
            meta["parents"] = [folder_id]
        created = service.files().create(
            body=meta,
            media_body=media,
            fields="id, name, webViewLink",
        ).execute()
        return created


def next_scheduled_run(now: dt.datetime | None = None) -> dt.datetime:
    """
    다음 평일(월~금) 08:00, 13:00, 20:30 중 가장 빠른 시각을 반환.
    토요일(5), 일요일(6)은 건너뜀.
    """
    if now is None:
        now = dt.datetime.now()
    for day_offset in range(8):
        target_date = now.date() + dt.timedelta(days=day_offset)
        if target_date.weekday() >= 5:  # 5=토요일, 6=일요일 제외
            continue
        for hour, minute in SCHEDULE_TIMES:
            candidate = dt.datetime.combine(target_date, dt.time(hour, minute))
            if candidate > now:
                return candidate
    raise RuntimeError("다음 스케줄 시각을 계산할 수 없습니다.")


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="가짜 데이터로 화면만 확인")
    ap.add_argument("--once", action="store_true", help="스케줄 대기 없이 1회만 실행 후 종료")
    ap.add_argument("--loop", type=float, default=0, help="지정 시 고정 주기(N시간)마다 갱신 (미지정 시 평일 08:00/13:00/20:30 스케줄)")
    ap.add_argument("--out", default=os.path.join(base_dir, "etf_dashboard.html"), help="로컬 HTML 저장 경로")
    ap.add_argument("--png", default=None, help="로컬 PNG 저장 경로 (기본값: --out과 동일한 이름의 .png)")
    ap.add_argument("--creds", default=os.path.join(base_dir, "credentials.json"), help="Google OAuth 또는 서비스 계정 JSON 경로")
    ap.add_argument("--token", default=os.path.join(base_dir, "token.json"), help="Google OAuth 토큰 캐시 파일 경로")
    ap.add_argument("--gdrive-folder", default=os.environ.get("GDRIVE_FOLDER_ID"), help="업로드할 Google Drive 폴더 ID (선택)")
    ap.add_argument("--no-gdrive", action="store_true", help="Google Drive 업로드 건너뛰기")
    ap.add_argument("--no-open", action="store_true", help="최초 실행 시 브라우저 자동 열기 비활성화")
    a = ap.parse_args()

    png_path = a.png or (os.path.splitext(a.out)[0] + ".png")

    opened = False
    while True:
        now = dt.datetime.now()
        if a.once:
            nxt = None
            wait_sec = None
        elif a.loop > 0:
            wait_sec = int(a.loop * 3600)
            nxt = now + dt.timedelta(seconds=wait_sec)
        else:
            nxt = next_scheduled_run(now)
            wait_sec = max(int((nxt - now).total_seconds()), 1)

        # 브라우저 탭이 열려 있을 때 다음 스케줄 갱신 직후(+5초 여유) 새로고침되도록 meta refresh 설정
        refresh_meta = (wait_sec + 5) if wait_sec else None

        rows, missing = fetch_demo() if a.demo else fetch_live()
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(build_html(rows, missing, refresh=refresh_meta, next_run=nxt, demo=a.demo))
        print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {a.out} 생성 ({len(rows)}종목, 매칭실패 {len(missing)})")
        if missing:
            print("  매칭 실패:", ", ".join(missing))

        upload_targets = [a.out]
        try:
            html_to_png(a.out, png_path, row_count=len(rows) + 3)
            print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {png_path} 생성 완료")
            upload_targets.append(png_path)
        except Exception as e:
            print(f"  [PNG 경고] PNG 변환 실패: {e}", file=sys.stderr)

        if not a.no_gdrive:
            try:
                service = get_gdrive_service(a.creds, a.token)
                for target in upload_targets:
                    info = upload_to_gdrive(
                        target,
                        creds_path=a.creds,
                        token_path=a.token,
                        folder_id=a.gdrive_folder,
                        service=service,
                    )
                    link = info.get("webViewLink", f"fileId={info.get('id')}")
                    print(f"  [Google Drive] 업로드 완료: {info.get('name')} ({link})")
            except Exception as e:
                print(f"  [Google Drive 경고] 업로드 실패: {e}", file=sys.stderr)

        if not opened and not a.no_open:
            webbrowser.open("file://" + os.path.abspath(a.out))
            opened = True

        if a.once:
            break

        # 시스템 절전 복귀 등으로 시간 오차가 생길 수 있으므로 목표 시각까지 안전하게 대기
        print(f"  다음 갱신 예약: {nxt:%Y-%m-%d(%a) %H:%M:%S} (주말 제외)")
        while True:
            rem = (nxt - dt.datetime.now()).total_seconds()
            if rem <= 0:
                break
            time.sleep(min(rem, 60))


if __name__ == "__main__":
    main()
