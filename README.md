# amazon_beyblade

Amazon.co.jp 的 Beyblade X 搜尋結果監控器。

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
- `NOTIFY_PRICE_DROP`：`1` 開啟降價通知，`0` 關閉
- `HISTORY_RETENTION_HOURS`：歷史保留小時數，預設 `24`
- `FAIL_ALERT_THRESHOLD`：連續失敗幾次後警告，預設 `3`
- `DEBUG`：設為 `1` 時輸出解析到的商品樣本
