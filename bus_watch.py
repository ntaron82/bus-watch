"""
発車オ～ライネットの空席を1回チェックし、空きがあればntfyでスマホに通知する
（GitHub Actionsで定期実行する前提。1回動いたら終了する）
"""
import os
import time
import datetime as dt
import requests
from playwright.sync_api import sync_playwright

# トピック名はGitHubのSecretsから読む
NTFY_TOPIC = os.environ["NTFY_TOPIC"]
BASE = "https://secure.j-bus.co.jp/hon/Route/ehime_osaka?dtym=202611&dtdd={day}"

# (日付, 発車時刻, 乗車地のキーワード)
TARGETS = [
    (13, "22:38", "松山支店"),
    (13, "22:55", "室町"),
    (14, "5:35",  "室町"),
]

# 時刻・乗車地・運賃（円）を含む、いちばん小さい要素＝その便のカード
FIND_JS = """
([time, stop]) => {
  let best = null;
  for (const el of document.querySelectorAll('li, tr, div, section, article')) {
    const t = el.innerText || '';
    if (t.includes(time) && t.includes(stop) && t.includes('円') && t.length < 5000) {
      if (!best || t.length < best.length) best = t;
    }
  }
  return best;
}
"""


def judge(text):
    """運賃の行ごとに残席を見て、1つでも満席以外があれば空きあり"""
    if text is None:
        return "not_found"
    if "予約に進む" not in text:
        return "unknown"
    # 「予約に進む」〜「詳細を閉じる」の間が運賃・残席の表
    table = text.split("予約に進む", 1)[1].split("詳細を閉じる", 1)[0]
    statuses = []
    for line in table.splitlines():
        if "\t" in line:
            s = line.split("\t")[1].strip()  # タブの後ろが残席の欄
            if s:
                statuses.append(s)
    if not statuses:
        return "unknown"
    if all(s == "満席" for s in statuses):
        return "full"
    return "available"


def notify(msg):
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Bus seat alert", "Priority": "high"}, timeout=10)


INTERVAL_SEC = 5 * 60      # チェック間隔（5分）
RUN_HOURS = 5.5            # 1回の起動で見張る時間（GitHubの上限6時間より短く）


def check_once(page, notified):
    for day in (13, 14):
        page.goto(BASE.format(day=day), timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(8000)  # 便一覧の読み込み待ち
        for d, tm, stop in TARGETS:
            if d != day:
                continue
            text = page.evaluate(FIND_JS, [tm, stop])
            status = judge(text)
            print(f"11/{d} {tm} {stop}: {status}", flush=True)
            if status == "unknown":
                print("  テキスト:", (text or "")[:1000], flush=True)
            key = (d, tm)
            if status == "available" and key not in notified:
                notify(f"空きあり！ 11/{d} {tm} {stop}発\n" + BASE.format(day=day))
                notified.add(key)
            elif status == "full":
                notified.discard(key)  # 満席に戻ったら、次の空きでまた通知


def main():
    notified = set()
    end = time.time() + RUN_HOURS * 3600
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        while time.time() < end:
            jst = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
            print("---", jst.strftime("%m/%d %H:%M JST"), flush=True)
            if 2 <= jst.hour < 5:
                print("サイト休止時間なのでスキップ", flush=True)
            else:
                try:
                    check_once(page, notified)
                except Exception as e:
                    print("エラー（次回また試す）:", e, flush=True)
            time.sleep(INTERVAL_SEC)
        browser.close()


if __name__ == "__main__":
    main()
