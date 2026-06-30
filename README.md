# amazon_beyblade

Amazon.co.jp 的 Beyblade X 搜尋結果監控器。

不需要 Playwright。新版會優先使用 `curl_cffi` 模擬 Chrome 連線，降低 VM / VPS 上被 Amazon 回 503 的機率。

監控網址：

<https://www.amazon.co.jp/s?k=takara+tomy+beyblade+x&i=toys&rh=n%3A13299531%2Cp_123%3A1432576&dc&language=zh&ref=sr_nr_p_123_1>

## 通知 topic

這個專案使用獨立 ntfy topic，不跟原本 TheWatcher 共用：

```text
amazon-beyblade-x-tw-9q4m7z2k
```

請在手機 ntfy App 訂閱這組 topic。

如果你想改成自己的 topic，執行時設定 `NTFY_TOPIC` 即可。

## 安裝

Linux / VM：

```bash
cd amazon_beyblade
python3 -m pip install -r requirements.txt
python3 amazon_beyblade_watcher.py
```

Windows PowerShell：

```powershell
cd amazon_beyblade
py -m pip install -r requirements.txt
py .\amazon_beyblade_watcher.py
```

第一次執行只會建立基準，不會發通知；之後有新商品、重新出現、降價、消失才會通知。

## 排程

Linux cron 每 5 分鐘執行一次：

```cron
*/5 * * * * cd /home/USER/amazon_beyblade && /usr/bin/python3 amazon_beyblade_watcher.py >> watcher-$(date +\%F).log 2>&1
```

如果要指定自己的 topic：

```cron
*/5 * * * * cd /home/USER/amazon_beyblade && NTFY_TOPIC="你的-topic" /usr/bin/python3 amazon_beyblade_watcher.py >> watcher-$(date +\%F).log 2>&1
```

## GitHub Actions

已內建 `.github/workflows/watch.yml`，預設每 15 分鐘執行一次。

如果你想用 GitHub Secret 覆蓋預設 topic：

1. 到 repository `Settings` → `Secrets and variables` → `Actions`
2. 新增 `NTFY_TOPIC`
3. 值填入你自己的 ntfy topic

## 環境變數

- `NTFY_TOPIC`：ntfy topic；未設定時使用 `amazon-beyblade-x-tw-9q4m7z2k`
- `NTFY_SERVER`：預設 `https://ntfy.sh`
- `AMAZON_SEARCH_URL`：要監控的 Amazon 搜尋網址
- `AMAZON_HTTP_CLIENT`：HTTP 客戶端，預設 `auto`；可設 `curl_cffi` 或 `requests`
- `CURL_CFFI_IMPERSONATE`：curl_cffi 模擬的瀏覽器，預設 `chrome120`
- `AMAZON_COOKIE`：可選；若 VM IP 被 Amazon 擋，可貼你瀏覽器 Amazon.co.jp 的 Cookie 作為最後手段
- `MISSING_RUNS_BEFORE_DELIST`：商品連續幾次沒出現在搜尋結果才通知消失，預設 `2`，可降低 Amazon 搜尋排序抖動造成的誤報
- `NOTIFY_PRICE_DROP`：`1` 開啟降價通知，`0` 關閉
- `HISTORY_RETENTION_HOURS`：歷史保留小時數，預設 `24`
- `FAIL_ALERT_THRESHOLD`：連續失敗幾次後警告，預設 `3`
- `DEBUG`：設為 `1` 時輸出解析到的商品樣本

## VM 上遇到 503

如果本機可以跑，但 VM 上看到：

```text
503 Server Error: Service Unavailable
```

請先在 VM 更新程式與依賴：

```bash
cd ~/amazon_beyblade
git pull
python3 -m pip install -r requirements.txt
python3 amazon_beyblade_watcher.py
```

原因通常是 Amazon 對 VM / VPS IP 或 Python requests 的連線指紋比較敏感。本專案新版會優先用 `curl_cffi` 模擬 Chrome；如果更新後仍然 503，代表 Amazon 可能擋的是 VM 出口 IP，建議改在家用網路、本機、或換一台出口 IP 較乾淨的 VM 執行。
