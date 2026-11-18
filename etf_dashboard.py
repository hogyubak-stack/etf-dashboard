name: Update ETF Dashboard

on:
  schedule:
    # 한국 시간(KST = UTC+9) 기준 평일(월~금) 자동 실행 (주말 제외)
    - cron: '4 23 * * 0-4'   # 평일 아침 08:04 KST (UTC 일~목 23:04) -> ETF 대시보드
    - cron: '4 4 * * 1-5'    # 평일 오후 13:04 KST (UTC 월~금 04:04) -> ETF 대시보드
    - cron: '34 11 * * 1-5'  # 평일 저녁 20:34 KST (UTC 월~금 11:34) -> ETF + MDD 대시보드
  workflow_dispatch:         # GitHub 웹페이지에서 수동 즉시 실행 시 둘 다 실행

permissions:
  contents: write

jobs:
  update-dashboard:
    runs-on: ubuntu-latest
    env:
      TZ: Asia/Seoul

    steps:
      - name: 저장소 코드 체크아웃
        uses: actions/checkout@v4

      - name: 한글 폰트 및 Chrome 래퍼 설정 (PNG 이미지 생성용)
        run: |
          sudo apt-get update
          sudo apt-get install -y fonts-nanum fonts-noto-cjk fontconfig
          fc-cache -fv
          cat << 'EOF' | sudo tee /usr/local/bin/chrome > /dev/null
          #!/bin/bash
          exec google-chrome --no-sandbox --disable-dev-shm-usage "$@"
          EOF
          sudo chmod +x /usr/local/bin/chrome

      - name: Python 3.11 설정
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: 필수 패키지 설치
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      - name: Google Drive 인증 파일 준비
        env:
          GDRIVE_CREDENTIALS_JSON: ${{ secrets.GDRIVE_CREDENTIALS_JSON }}
          GDRIVE_TOKEN_JSON: ${{ secrets.GDRIVE_TOKEN_JSON }}
        run: |
          if [ -n "$GDRIVE_CREDENTIALS_JSON" ]; then
            printf '%s' "$GDRIVE_CREDENTIALS_JSON" > credentials.json
          fi
          if [ -n "$GDRIVE_TOKEN_JSON" ]; then
            printf '%s' "$GDRIVE_TOKEN_JSON" > token.json
          fi

      - name: ETF 대시보드 생성 및 Google Drive 업로드 (08:04 / 13:04 / 20:34)
        env:
          GDRIVE_FOLDER_ID: ${{ secrets.GDRIVE_FOLDER_ID }}
        run: |
          python etf_dashboard.py --once --no-open

      - name: MDD 대시보드 생성 및 Google Drive 업로드 (평일 20:34 또는 수동 실행 시)
        if: github.event.schedule == '34 11 * * 1-5' || github.event_name == 'workflow_dispatch' || !hashFiles('mdd_dashboard.html')
        env:
          GDRIVE_FOLDER_ID: ${{ secrets.GDRIVE_FOLDER_ID }}
        run: |
          if [ -f "mdd_dashboard.py" ]; then
            python mdd_dashboard.py
          fi

      - name: GitHub Pages용 웹페이지(index.html) 생성 및 반영
        run: |
          rm -f credentials.json token.json
          cat << 'EOF' > index.html
          <!DOCTYPE html>
          <html lang="ko">
          <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>ETF & MDD 통합 대시보드</title>
            <style>
              * { box-sizing: border-box; margin: 0; padding: 0; }
              body, html { height: 100%; font-family: -apple-system, "Malgun Gothic", sans-serif; background: #f5f6f8; }
              .nav { display: flex; gap: 8px; padding: 8px 12px; background: #1a1d27; align-items: center; }
              .nav button { padding: 6px 14px; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; background: transparent; color: #aaa; font-size: 13px; font-weight: 600; cursor: pointer; }
              .nav button.active { background: #378add; color: #fff; border-color: #378add; }
              iframe { width: 100%; height: calc(100% - 46px); border: none; display: block; background: #fff; }
            </style>
          </head>
          <body>
            <div class="nav">
              <button id="btn-etf" class="active" onclick="show('etf_dashboard.html', this)">📊 섹터별 대표 ETF</button>
              <button id="btn-mdd" onclick="show('mdd_dashboard.html', this)">📉 KOSPI · KOSDAQ MDD</button>
            </div>
            <iframe id="viewer" src="etf_dashboard.html"></iframe>
            <script>
              function show(url, btn) {
                document.getElementById('viewer').src = url + '?t=' + Date.now();
                document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
              }
            </script>
          </body>
          </html>
          EOF
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add index.html etf_dashboard.html
          if [ -f "mdd_dashboard.py" ] && [ -f "mdd_dashboard.html" ]; then
            git add mdd_dashboard.html
          fi
          git diff --staged --quiet || (git commit -m "Auto-update dashboards" && git push)
