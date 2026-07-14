# 歐盟資安法制官方新聞爬蟲

本專案抓取歐盟、法國、德國與愛爾蘭的官方機關、法定監理機構、行政法人、公私協力組織、公共研究機構及政策智庫新聞，分類器與主管機關矩陣使用相同的 15 項觀測議題。

設計承接既有 `UK-news-scraper` 的實務做法：優先使用 RSS／Atom，找不到 feed 時才解析 HTML；每個來源獨立失敗、併發執行、穩定去重、輸出 Excel 與 JSON 執行摘要，並保留來源健康狀態。程式只設定官方或公共研究來源，不以商業媒體或 Google News 作為預設備援。

## 快速開始

需要 Python 3.11 以上。macOS 可在終端機執行：

```bash
cd eu-cyber-news-scraper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m eu_cyber_news_scraper --days 14
```

預設會抓取臺北時區最近 14 天，將新聞標題翻譯為繁體中文，並在專案的 `新聞放置區` 資料夾產生：

- `歐盟資安法制新聞_YYYYMMDD-YYYYMMDD.xlsx`
- 同名 `.run.json`：來源成功、失敗、筆數、耗時與整體狀態

標題翻譯採多引擎備援，依序嘗試 `googletrans`、`translate` 及 `translatepy` 三個免費模組，支援英文、法文及德文自動辨識。每個引擎可重試一次，只有含中文字且不同於原文的結果才會採用；全部失敗時保留原文，不中斷 Excel 產出。單次引擎預設逾時 10 秒，連續失敗 3 次且尚無成功時會在本次執行開啟斷路器；`.run.json` 會記錄各引擎嘗試、成功、失敗、跳過、耗時及停用狀態。成功快取採 schema v2，另存引擎及快取時間，舊快取仍可讀取。可用 `EU_CYBER_NEWS_TRANSLATION_TIMEOUT`、`EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES`、`EU_CYBER_NEWS_TRANSLATION_CACHE` 與 `EU_CYBER_NEWS_TRANSLATION_WORKERS` 調整，或使用 `--no-translate` 完全不呼叫外部翻譯服務。

`translatepy` 若回傳簡體中文，會再以 OpenCC 轉成臺灣繁體用字後才寫入工作簿。

如需機器可讀資料：

```bash
python -m eu_cyber_news_scraper --days 30 --jsonl
```

## 常用指令

```bash
# 指定西元日期（起訖日皆包含）
python -m eu_cyber_news_scraper --since 2026-06-01 --until 2026-06-30

# 指定民國日期；也接受 113-04-05、113/04/05、民國1130405
python -m eu_cyber_news_scraper --since 1130405 --until 1130430

# 只抓歐盟、法國與德國
python -m eu_cyber_news_scraper --country EU --country FR --country DE

# 只輸出產品資安、資安認證、NIS2 或量子技術
python -m eu_cyber_news_scraper --topic PRODUCT --topic CERT --topic NIS2 --topic QUANTUM

# 只抓 ANSSI、BSI 與愛爾蘭 NCSC
python -m eu_cyber_news_scraper --source fr_anssi --source de_bsi_news --source ie_ncsc

# 列出全部來源代碼；星號代表必要來源
python -m eu_cyber_news_scraper --list-sources

# 保留所有官方新聞，不限於命中主題者
python -m eu_cyber_news_scraper --all

# 來源版型快速變動時，可暫時不進入新聞內頁
python -m eu_cyber_news_scraper --no-detail

# 不呼叫外部翻譯服務
python -m eu_cyber_news_scraper --no-translate

# 限制每個來源總抓取時間，並指定跨次執行狀態目錄
python -m eu_cyber_news_scraper --days 14 --source-budget 60 --state-dir .state
```

`--days` 與 `--since/--until` 是互斥模式；指定期間時起訖值必須同時提供。日期支援西元
`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYYMMDD`，以及民國 `YYY-MM-DD`、`YYY/MM/DD`、
`YYYMMDD` 和帶有「民國」前綴的相同格式。民國日期會先轉為西元，再以臺北時區完整涵蓋起訖日。
輸出檔名一律使用正規化後的西元日期。

可用的主題代碼為：`AI`、`DATA`、`PRIVACY`、`IDENTITY`、`COPYRIGHT`、`PLATFORM`、`INFO`、`COMPETITION`、`NIS2`、`PRODUCT`、`SUPPLY`、`CERT`、`HYBRID`、`CHIPS`、`QUANTUM`。

## Excel 工作表

| 工作表 | 內容 |
| --- | --- |
| 全部命中新聞 | 國家、機關、機關屬性、日期、原文標題、繁體中文標題、摘要、主題、關鍵字、可信度、原文連結；高可信為深黃、中可信為淺黃、低可信為淡黃 |
| CRA_CSA_NIS2_CER | 四項核心歐盟資安法制的專表 |
| 官方規範與執法 | 立法、主管／監理及法定機構發布內容 |
| 研究智庫與公私協力 | 研究機構、智庫與產學公私協力發布內容 |
| 來源健康狀態 | 抓取健康、期間內與命中筆數、新鮮度、日期完整率、唯一標題比例、歷史中位數；抓取警示與內容零命中分欄顯示 |
| 官方來源清單 | 本次使用的官方／公共研究來源與新聞入口 |
| 議題主管機關覆蓋 | 15 個議題在 EU、FR、DE、IE 的主管機關、行政法人／法定機構、公私協力、智庫、角色、官方證據網址與最後查核日期 |

## 主題判斷方式

分類器同時支援英文、法文與德文，詞庫包含法規正式名稱、各國轉置／執行用語及官方新聞常見詞形，而不只依賴英文直譯。例如法文的 `transposition de la directive NIS 2`、`résilience des entités critiques`，以及德文的 `NIS-2-Umsetzungsgesetz`、`Resilienz kritischer Einrichtungen` 都會辨識。`CRA`、`CSA`、`AI`、法文 `IA`、德文 `KI` 這類容易產生誤判的短縮語，只有在同一標題或摘要中另有 cyber、security、certification、model、modèle、Modell 等脈絡詞時才會成立。這不是法律意見或最終人工編碼；研究使用時仍應點回官方原文確認規範性質、法制階段與適用範圍。

## 來源治理

來源設定集中於 `src/eu_cyber_news_scraper/sources.toml`。每個來源可設定：

- 國家、中文與原文機關名稱、機關屬性、語言
- 官方首頁、新聞列表、已知 RSS／Atom
- 允許網域、文章網址規則、排除規則
- 是否為必要來源、最多補抓多少篇內頁
- 跨年度新聞網址、分頁格式、最多頁數及健康基線觀察次數

主管機關覆蓋矩陣集中於 `src/eu_cyber_news_scraper/authority_coverage.toml`。目前固定驗證
15 個議題 × 4 個法域共 60 格；任一格缺少機關或監測來源，測試即會失敗。
目前共 55 個來源；研究機構與智庫只作為政策研究、技術評估及生態系觀測來源，不視為具有監理權限的主管機關。

每次成功執行會在狀態目錄更新 `.source-health.json`，最多保留每個來源最近 12 次紀錄。累積指定觀察次數後，若筆數低於歷史中位數 25%、無日期比例過高或標題重複異常，會在 Excel 與 `.run.json` 顯示健康警示。必要來源的抓取失敗會立即使執行狀態降為 `degraded`；新鮮度或基線異常第一次為 `attention`，連續兩次才為 `degraded`。

來源另有新鮮度門檻：必要來源預設 45 天、其他來源預設 90 天，可在 `sources.toml` 以 `freshness_days` 個別調整。超過門檻的必要來源不會因仍抓得到舊文章而誤判為正常。內容期間內沒有命中議題只會記錄在「內容結果」，不會混入抓取故障。

來源預設以 8 個工作執行緒併發抓取，可用 `--workers` 調整；來源與內頁的總 HTTP 請求另受全域 16 條上限保護。相同輸出檔同一時間只允許一個工作執行，避免覆寫 Excel、摘要或翻譯快取。新增來源後應同步：

1. 更新 `sources.toml` 與 `SOURCES.md`。
2. 先執行 `--source 新代碼 --days 60 --include-undated` 人工檢查。
3. 為特殊 HTML 版型補 fixture 測試，避免把導覽、徵才或活動頁誤當新聞。
4. 至少累積三次健康紀錄，且連續觀察兩週後，再將來源標記為 `critical = true`。

## GitHub Actions

`.github/workflows/scrape.yml` 會在每週一 00:00 UTC（臺灣時間 08:00）執行，將 Excel、JSONL 與執行摘要保存為 30 天的 workflow artifact。它不會自動提交新聞資料回儲存庫，避免讓產出檔污染版本歷史。

## 測試

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest --cov=eu_cyber_news_scraper --cov-report=term-missing --cov-fail-under=90
pip-audit
```

測試採本地 RSS／HTML fixtures，不依賴即時網站；7 個必要來源各有版型合約 fixture，另有 120 筆多語議題原始及文字擾動評估案例與 precision／recall 門檻。CI 會在 Python 3.11、3.12、3.13 執行，要求至少 90% 覆蓋率並執行 `pip-audit`；每週工作另會先對必要來源執行不翻譯的 smoke test。

## 已知限制

- 通用 HTML 解析器無法保證涵蓋所有動態載入網站；遇到 JavaScript-only 頁面應新增官方 API／feed 或專用解析器。
- 翻譯會將新聞標題送往外部服務；若有資料治理限制，可預先提供翻譯快取或另行替換翻譯器。
- `.run.json` 使用 schema v4，分開記錄 `fetch_status` 與 `health_status`，並保存原始日期輸入、辨識紀年、正規化期間、無效日期、逾時及去重統計。
- `complete` 代表必要來源與品質門檻均正常；非必要來源失敗、單次健康基線警示或翻譯成功率低於 95% 會標示 `attention`；必要來源抓取失敗或連續健康異常則為 `degraded`。
- 已設定分頁或年度模板的來源會依日期範圍抓取存檔頁；尚未提供穩定分頁規則的網站仍可能受其首頁顯示筆數限制。
- 公共研究中心的內容屬研究資訊，不等同主管機關的正式法律解釋。
