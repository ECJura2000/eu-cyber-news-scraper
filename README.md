# 歐盟資安法制官方新聞爬蟲

本專案抓取歐洲官方機關、法定監理機構、行政法人與公共研究機構新聞。來源清單涵蓋歐盟 27 個成員國、歐盟機構及既有挪威來源。原有 EU、FR、DE、IE 來源維持每週排程；新增來源先供手動查詢與驗證。分類器與主管機關矩陣使用相同的 15 項觀測議題。

設計承接既有 `UK-news-scraper` 的實務做法：優先使用 RSS／Atom，找不到 feed 時才解析 HTML；每個來源獨立失敗、併發執行、穩定去重、輸出 Excel 與 JSON 執行摘要，並保留來源健康狀態。程式只設定官方或公共研究來源，不以商業媒體或 Google News 作為預設備援。

## 機關 Registry

v1.8.0 整合 EU27 部會擴充與當地語言百科複查，新聞來源共 448 個；部會名錄共 460 個、已登錄 306 個、154 個候選依使用者決定保留為可追溯排除，名錄不是全部可搜尋的宣稱。新增芬蘭教育署與司法彙整入口使用獨立機關 ID，保留實際發布機關，不冒充原部會。新驗證機關先供手動查詢，正式未暫停排程仍為 50。不同 RSS、HTML 與公開 API 的分工、robots 例外及加入標準見 [抓取方法說明](CRAWLER_METHODS.md)。

v1.7.0 依使用者指示移除 `fr_institut_montaigne`、`eu_enisa_publications`、`ie_insight` 三個新聞入口。該版來源共 145 個，其中 52 個設定排程、50 個未暫停；ENISA 新聞與認證仍保留，歐洲議會及 CEA 的暫停不變。更新後預設線上抓取與離線查詢不再使用這三個來源；既存文章與 240 筆歷史分類回歸資料不刪除，外部自訂模組仍可由使用者明確提供。完整更新內容見 [CHANGELOG.md](CHANGELOG.md)。

新聞表使用英國新聞專案的三階黃色：高 `FFD966`、中 `FFE699`、低 `FFF2CC`。只標示標題、繁中標題、摘要、命中主題／詞與關聯分數，不把日期、來源健康或官方網址塗黃。沿用 EU 的 Boolean 關聯程度（4 分以上為高，2～3 分為中，1 分為低），BM25 仍是另列的主題排序分數；黃色不代表日期可信度或百分比。線上四個新聞工作表與離線查詢均採相同配色，規則未變重查仍可沿用結果；程式版本更新會重建查詢 Excel 快取，以套用新版格式。

機關模組位於 [`organisation_registry/`](organisation_registry/)，各來源使用 schema v2 JSON（v1.7.0 的 145 個來源，再加本版部會與獨立機關擴充）。每個模組包含來源 URL 與解析設定、主題白名單、健康門檻、機關沿革、官方證據及驗證狀態；預設執行直接由這些 JSON 建立來源清單。新增或覆寫模組可放在 macOS 的 `~/Library/Application Support/EUCyberNewsScraper/organisations.d`，或使用 `EU_CYBER_ORGANISATION_DIR` 指定目錄，重啟後載入。外部模組驗證失敗會保留同 ID 的內建模組；無內建版本的新模組會略過，並讓 `.run.json` 的 `organisation_audit_status` 成為 `degraded`。

內建 `organisation_registry/*.json` 是正式設定的唯一來源；`src/eu_cyber_news_scraper/sources.toml` 是由 JSON 匯出的相容設定，仍可透過 `--config` 使用。修改內建來源時應先編輯 JSON，再匯出 TOML，不可反向從 TOML 重建機關 metadata。產生器只讀取內建模組，不納入環境變數或使用者覆寫；不帶參數與 `--check` 都只檢查，不寫檔。檢查依來源 ID 比對所有欄位與型別，不要求文字格式或排列順序相同；重複 ID、無效模組或設定不同均會失敗。

```bash
# 唯讀檢查 JSON 與相容 TOML 是否一致
python scripts/generate_organisation_registry.py --check

# 明確匯出至預設 sources.toml；不修改 JSON 的證據、沿革或驗證紀錄
python scripts/generate_organisation_registry.py --export-sources

# 也可指定另一個匯出檔，再唯讀檢查該檔
python scripts/generate_organisation_registry.py --export-sources /tmp/eu-sources.toml
python scripts/generate_organisation_registry.py --check --sources-path /tmp/eu-sources.toml
```

原未登錄的 12 個歐盟國家現均有手動來源，2026-09-26 首輪檢查如下；各模組 `verification.last_smoke` 保留原始筆數、日期筆數及錯誤原因。

| 國家 | 新來源 | 首輪結果 |
| --- | --- | --- |
| 奧地利 AT | `at_cert`、`at_dsb`、`at_rtr` | 前二者健康；RTR 列表日期不足 |
| 比利時 BE | `be_apd`、`be_bipt`、`be_ccb` | APD 健康；BIPT 日期不足；CCB 回傳 HTTP 403 |
| 保加利亞 BG | `govcert_bg` | 健康 |
| 賽普勒斯 CY | `cy_dsa` | 可抓取，部分文章無日期 |
| 捷克 CZ | `cz_nukib` | 健康 |
| 希臘 GR | `gr_ncsa`、`gr_dpa`、`gr_grnet` | NCSA 健康；另二者日期不足 |
| 克羅埃西亞 HR | `cert_hr` | 健康 |
| 匈牙利 HU | `hu_nmhh`、`hu_nki` | NMHH 健康；NKI 列表目前解析為空 |
| 盧森堡 LU | `lu_list`、`lu_cnpd`、`lu_govcert`、`lu_ilr` | LIST 健康；其他來源日期不足或過舊 |
| 馬爾他 MT | `mt_idpc`、`mt_ncc` | IDPC 健康；NCC 回傳 HTTP 403 |
| 斯洛維尼亞 SI | `si_ursiv`、`si_sicert` | URSIV 健康；SI-CERT 英文新聞頁過舊 |
| 斯洛伐克 SK | `sk_nbu_cra` | 健康 |

篩選流程採 Boolean 候選判定後接 BM25 主題評分，標題權重 2、摘要權重 1、`k1=1.2`、`b=0.75`，分數固定四位小數。機關模組的 `filter.topics` 是正式白名單；Excel 的「篩選設定」及新聞欄位會記錄 Boolean/BM25 分數、命中同義詞、實際發布機關與責任機關，JSONL 與 `.run.json` 也保留相同稽核資訊。

```bash
# 檢視載入來源、覆寫、錯誤及 registry hash
python -m eu_cyber_news_scraper --organisation-status

# 匯出範例，或開啟外部模組資料夾
python -m eu_cyber_news_scraper --export-organisation-example organisation.example.json
python -m eu_cyber_news_scraper --open-organisation-dir
```

## 自訂主題與離線重查

詞項可用字串（舊格式），或用 `{ "term": "inteligencia artificial", "language": "es", "concept": "ai" }`；加權詞另需 `weight`。`language` 可為來源使用的語言代碼（包括 bg／hr／el／hu 等新增語言）、en／fr／de，或 `*`（明確跨語言縮寫）。同一 `concept` 的譯名與詞形只取最高權重一次；比對原文、保留重音與詞界，不使用繁中標題反推命中。`penalties`、`excludes` 也可指定語言，且只作用於所屬主題。

內建 [`topic_profile.json`](src/eu_cyber_news_scraper/topic_profile.json) 是 schema v2 完整替換範例，列出原有 15 個主題及各國原文同義詞。複製後可用 `--topics-json 路徑` 隨時換檔、重跑；舊 schema v1 仍可讀取。`mode: "replace"` 表示整份替換；`mode: "merge"` 表示以內建 15 主題為基礎，同名主題整筆取代、新名稱新增，`remove_topics` 才會刪除主題。增補格式見 [`multilingual-merge.json`](examples/topics/multilingual-merge.json)。改名時填 `legacy_name` 指向原名稱；新主題預設搜尋所有來源，舊主題沿用來源白名單。

`schedule.days` 設每週回溯天數；`manual` 可設 `days` 或 `since` 加 `until`。命令列日期優先於 JSON，日期仍支援西元／民國及臺北時區起訖日含當日。JSON 無效時在抓取前停止。每次執行會在摘要與事件紀錄保存規則 SHA-256；規則變更會分開健康觀察基線。

```bash
python -m eu_cyber_news_scraper --jsonl --topics-json my-topics.json
python -m eu_cyber_news_scraper search --corpus-dir 新聞放置區 --topics-json my-topics.json --since 1150901 --until 1150930 --output results.xlsx
python -m eu_cyber_news_scraper --country ES --topics-json examples/topics/multilingual-merge.json --days 30
python -m eu_cyber_news_scraper search --corpus-dir 新聞放置區 --country ES --topics-json my-topics.json --output spain.xlsx
python -m eu_cyber_news_scraper --country NL --country PT --country RO --country FI --days 30 --no-translate
python -m eu_cyber_news_scraper --country GR --country HR --days 30 --no-translate
```

離線搜尋會在資料夾建立 `.offline-search.sqlite3` 增量索引；相同規則、日期、來源與文章資料時重用既有結果。只有正式 manifest 顯示該日期期間、所選來源、產物與品質門檻均完整時，結果才標為「資料涵蓋完整」；否則輸出部分結果並明示缺口。每週 artifact 同時提供入選 `.jsonl` 與篩選前 `.corpus.jsonl`，驗證器重算兩者與 Excel 的筆數、SHA-256。

## 快速開始

需要 Python 3.11 以上。macOS 與 Windows 均可從終端機執行；以下分別列出建立環境及啟動程式的指令。

macOS（終端機）：

```bash
cd eu-cyber-news-scraper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install uv
uv sync --frozen
python -m eu_cyber_news_scraper --days 14
```

Windows（PowerShell）：

```powershell
cd C:\你的路徑\eu-cyber-news-scraper
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install uv
uv sync --frozen
python -m eu_cyber_news_scraper --days 14
```

若 PowerShell 因執行原則而不允許啟用 `Activate.ps1`，可略過啟用步驟，改用虛擬環境的 Python：

```powershell
.\.venv\Scripts\python.exe -m pip install uv
.\.venv\Scripts\python.exe -m uv sync --frozen
.\.venv\Scripts\python.exe -m eu_cyber_news_scraper --days 14
```

目前自動化 CI 在 Linux 上驗證 Python 3.11、3.12、3.13；尚未加入 Windows 執行環境測試。

預設會抓取臺北時區最近 14 天，將新聞標題翻譯為繁體中文，並在專案的 `新聞放置區` 資料夾產生：

- `歐盟資安法制新聞_YYYYMMDD-YYYYMMDD.xlsx`
- 同名 `.run.json`：來源成功、失敗、筆數、耗時與整體狀態

標題翻譯採多引擎備援，依序嘗試 `googletrans`、`translate` 及 `translatepy` 三個免費模組，支援英文、法文及德文自動辨識。每個引擎可重試一次，只有含中文字且不同於原文的結果才會採用；全部失敗時保留原文，不中斷 Excel 產出。單次引擎預設逾時 10 秒，連續失敗 3 次且尚無成功時會在本次執行開啟斷路器；`.run.json` 會記錄各引擎嘗試、成功、失敗、跳過、耗時及停用狀態。成功快取採 schema v3，鍵包含來源語言與原文，另存引擎、建立時間及最近使用時間，最多保留最近 10,000 筆。翻譯由持久 `spawn` worker pool 執行，逾時後會終止並重建該 worker，不使用 `fork` 或背景 daemon thread。可用 `EU_CYBER_NEWS_TRANSLATION_TIMEOUT`、`EU_CYBER_NEWS_TRANSLATION_CIRCUIT_FAILURES`、`EU_CYBER_NEWS_TRANSLATION_CACHE` 與 `EU_CYBER_NEWS_TRANSLATION_WORKERS` 調整，或使用 `--no-translate` 完全不呼叫外部翻譯服務。

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

# 固定歷史期間預設不寫健康基線；需要強制寫入時明確指定
python -m eu_cyber_news_scraper --days 14 --health-write always --state-dir .state

# 正式品質 gate；產物仍會在 gate 失敗時完整發布供診斷
python -m eu_cyber_news_scraper --days 14 --jsonl --min-source-success-rate 0.95 --min-parse-success-rate 0.95 --max-empty-sources 0 --min-overall-date-rate 0.75 --min-critical-date-rate 0.95 --min-high-confidence-date-rate 0.75 --max-date-conflict-rate 0.05 --max-unexplained-future-dates 0 --require-complete-artifacts
```

`--days` 與 `--since/--until` 是互斥模式；指定期間時起訖值必須同時提供。日期支援西元
`YYYY-MM-DD`、`YYYY/MM/DD`、`YYYYMMDD`，以及民國 `YYY-MM-DD`、`YYY/MM/DD`、
`YYYMMDD` 和帶有「民國」前綴的相同格式。民國日期會先轉為西元，再以臺北時區完整涵蓋起訖日。
輸出檔名一律使用正規化後的西元日期。

可用的主題代碼為：`AI`、`DATA`、`PRIVACY`、`IDENTITY`、`COPYRIGHT`、`PLATFORM`、`INFO`、`COMPETITION`、`NIS2`、`PRODUCT`、`SUPPLY`、`CERT`、`HYBRID`、`CHIPS`、`QUANTUM`。

## Excel 工作表

| 工作表 | 內容 |
| --- | --- |
| 全部命中新聞 | 國家、機關、機關屬性、UTC 日期、原始日期文字、來源時區、當地發布日、日期來源／信心／衝突、原文與繁中標題、摘要、主題、關鍵字、可信度及官方連結；高可信為深黃、中可信為中黃、低可信為淺黃 |
| CRA_CSA_NIS2_CER | 四項核心歐盟資安法制的專表 |
| 官方規範與執法 | 立法、主管／監理及法定機構發布內容 |
| 研究智庫與公私協力 | 研究機構、智庫與產學公私協力發布內容 |
| 來源健康狀態 | 抓取健康、期間內與命中筆數、新鮮度、日期完整率、唯一標題比例、歷史中位數；抓取警示與內容零命中分欄顯示 |
| 官方來源清單 | 本次使用的官方／公共研究來源與新聞入口 |
| 議題主管機關覆蓋 | 15 個議題在歐盟機構、27 個成員國及挪威的主管機關或研究機構、角色、官方證據網址與最後查核日期；未查證權責明示「未設定」 |

## 主題判斷方式

分類器同時支援英文、法文與德文，詞庫包含法規正式名稱、各國轉置／執行用語及官方新聞常見詞形，而不只依賴英文直譯。例如法文的 `transposition de la directive NIS 2`、`résilience des entités critiques`，以及德文的 `NIS-2-Umsetzungsgesetz`、`Resilienz kritischer Einrichtungen` 都會辨識。`CRA`、`CSA`、`AI`、法文 `IA`、德文 `KI` 這類容易產生誤判的短縮語，只有在同一標題或摘要中另有 cyber、security、certification、model、modèle、Modell 等脈絡詞時才會成立。這不是法律意見或最終人工編碼；研究使用時仍應點回官方原文確認規範性質、法制階段與適用範圍。

## 來源治理

來源設定集中於 `organisation_registry/*.json`（正式設定）及由它匯出的 `src/eu_cyber_news_scraper/sources.toml`（相容設定，供 `--config` 使用）。每個來源可設定：

- 國家、中文與原文機關名稱、機關屬性、語言
- 官方首頁、新聞列表、已知 RSS／Atom
- 允許網域、文章網址規則、排除規則
- IANA 時區、卡片／連結／標題／日期／摘要 CSS selector、具名 parser adapter
- 僅限官方伺服器缺漏鏈結時使用的公開 issuer intermediate bundle；仍維持 hostname 與憑證驗證
- `required`、`best_effort`、`unavailable` 日期政策及例外理由、證據、查核日與複查期限
- 是否為必要來源、最多補抓多少篇內頁
- 跨年度新聞網址、分頁格式、最多頁數及健康基線觀察次數

主管機關覆蓋矩陣集中於 `src/eu_cyber_news_scraper/authority_coverage.toml`。目前固定驗證
原 15 個議題 × 4 個法域共 60 格仍需完整；另外 25 國共列 375 格，未有可信來源的格子明示「未覆蓋」，有來源但未查證權責則為「未設定」。
目前共 145 個來源；新增的 47 個候選來源均為 `schedule_enabled = false`，只有明確指定 `--country` 或 `--source` 才會手動抓取。其中 24 個原未登錄歐盟國家來源完成首輪手動抓取：12 個健康，其他來源依 `verification.status` 與 `last_smoke` 記錄日期不完整、過舊、版型無法解析或網站拒絕存取等原因。研究機構、大學與公私協力單位只作為政策研究、技術評估及生態系觀測來源，不視為具有監理權限的主管機關。

`.source-health.json` 使用 schema v2，以執行 profile 與每來源設定 fingerprint 分隔基線，最多保留每個來源最近 12 個獨立 observation；同一期間重跑會取代既有 observation，不會累積成連續異常。舊 v1 會保存在 `legacy`，但不參與新基線。`--health-write auto` 只讓完整 rolling 且啟用內頁的標準執行寫入；固定歷史期間預設唯讀，也可明確使用 `always` 或 `never`。健康 state 只在 Excel、JSONL 與 manifest 完整驗證並發布後寫入。

來源另有新鮮度門檻：必要來源預設 45 天、其他來源預設 90 天，可在 JSON 模組的來源設定以 `freshness_days` 個別調整，再匯出相容 TOML。超過門檻的必要來源不會因仍抓得到舊文章而誤判為正常。內容期間內沒有命中議題只會記錄在「內容結果」，不會混入抓取故障。

來源以 `asyncio` 與共享 `httpx.AsyncClient` 執行，預設最多同時處理 8 個來源，可用 `--workers` 調整；全域最多 16 個 HTTP 請求、同網域最多 2 個，連線逾時上限 8 秒、最多一次冪等重試、單一回應上限 5 MiB。`--source-budget` 以 `asyncio.timeout` 包住來源的 feed、列表與內頁完整流程，期限到達會取消未完成請求。相同輸出檔同一時間只允許一個工作執行，健康資料與翻譯快取另共用狀態鎖，避免遺失更新。

正式抓取、URL 稽核與目錄探索均啟用 `robots.txt` 檢查，重新導向的每一跳也會檢查；同主機請求至少間隔 0.5 秒，若有較長 `Crawl-delay` 則採較長值。robots 規則在同一 client 內快取 24 小時；401／403 視為禁止存取，429、伺服器錯誤、連線失敗或回傳 HTML／challenge 時停止該請求，其他 4xx 視為無 robots 規則。HTTP 429／500／502／503／504 與網路逾時可重試一次；`Retry-After` 支援秒數與 HTTP 日期，並共用同主機冷卻時間。所需等待超過上限時回報延後請求，不縮短伺服器指定等待；一般上限 30 秒，目錄探索為 2 秒。HTTPS 重新導向不得降為 HTTP，TLS 憑證與主機名稱仍需驗證。

正式抓取另在 state 目錄的 `.http-cache/responses.sqlite3` 保存條件式 HTTP 快取：優先使用 ETag／`If-None-Match`，其次使用 Last-Modified／`If-Modified-Since`，每次仍向伺服器重新驗證，只有 304 才重用內容。快取包含內容 SHA-256 檢查，保留最多 30 天、本文合計最多 100 MiB；`no-store`、`Set-Cookie`、不支援的 `Vary` 或沒有驗證標頭的回應不保存。URL 稽核與目錄探索目前未配置持久 HTTP 本文快取。

有效來源預算取 `--source-budget` 與 JSON 的 `minimum_budget_seconds` 較大值；來源下限僅接受 0～900 秒整數，預設 0。Bundeskartellamt 的[官方 robots](https://www.bundeskartellamt.de/robots.txt) 指定每次間隔 30 秒，因此單獨設定 600 秒下限，保留最多 12 篇內頁的日期及摘要查證；其他來源仍維持基本 60 秒。這是等待時間預算，不改變日期、來源健康或 state 寫入門檻，較短的命令列基本預算也不會覆蓋此下限。BNetzA 的純文字 robots 雖被官網標成 HTML，仍依實際規則解析；真正的 HTML／驗證頁繼續阻擋，`/SiteGlobals` 也仍禁止存取。首頁採用不會降至 HTTP 的已驗證 HTTPS 入口。

BMI 近期新聞使用[官方 RSS](https://www.bmi.bund.de/DE/service/rss-newsfeed/function/rssnewsfeed-pressemitteilungen.xml)，不再存取 robots 禁止的搜尋表單。設定 `feed_archive_fallback: true` 時，feed 失敗、沒有文章、缺乏日期，或查詢起日早於 feed 最舊日期，仍會查允許的新聞列表；ComReg 保留既有較早期間回查行為。列表回查不保證完整歷史覆蓋，未設定歷史分頁的來源不能因此宣稱已找齊較早期間新聞。此旗標與時間預算變更都會改變來源 fingerprint，重新累積該設定的健康觀察。

新增正式來源應依序完成：

1. 更新內建 JSON 模組與 `SOURCES.md`，明確匯出 `sources.toml` 後執行 `--check`。
2. 先執行 `--source 新代碼 --days 60 --include-undated` 人工檢查。
3. 為特殊 HTML 版型補 fixture 測試，避免把導覽、徵才或活動頁誤當新聞。
4. 累積下述三次連續合格解析觀察，並完成完整品質、翻譯、產物與同一次執行的 state observation 驗收，才人工審查是否加入排程；必要來源 `critical = true` 的設定另須至少連續觀察兩週。

## URL 稽核與候選機關目錄

### EU27 中央部會名錄與新聞查詢

新增的 [中央部會追蹤名錄](MINISTRIES.md) 按 27 個會員國列出所有中央部會、政府首長辦公室及制度相當機關。權威名單保存在 `ministry_inventory/` 的逐國 JSON，可維護部會名稱、官方名錄與查核日期、新聞入口、對應來源 ID 及缺口原因。

[剩餘入口逐項複查](REMAINING_MINISTRIES.md) 公開起始 201 個未完成入口的歷次檢查結果與後續處理；每一輪涵蓋前一輪全部仍待處理 ID，各輪原始觀察保留，CI 驗證最新處置與名錄一致，不因成功新增其他來源就漏掉未完成項目。使用者明確排除的候選入口不會被自動重開。

第五輪從維基百科條目尋找剩餘部會的官方網站線索，再到官網驗證新聞入口、發布機關與原文日期。百科條目可能過時，也可能沒有獨立條目，不能直接作為來源升級或部會不存在的證據。確認 404／410 或原文內容確實不是新聞的候選路徑才清理 `news_url`；首頁、部會名錄與歷史證據保留。robots、TLS、驗證頁、逾時或百科搜尋失敗不當成「沒有新聞」。新來源仍先供手動查詢，正式排程需另行驗收。

第六輪依使用者指示，改以原文部會名稱搜尋當地語言維基百科，再驗證其官網新聞。仍未通過者移除目前的候選 `news_url`，狀態為 `user_excluded`，不再自動稽核或列入待處理入口；這是使用者排除決定，不是網站不存在的判定。`user_exclusion` 保存原因、時間及原候選網址，歷次官網與百科查核紀錄仍可追溯。名錄仍保留部會與官網；`registered_ministries`、`pending_ministries`、`user_excluded_ministries` 分別統計已登錄、待處理、使用者排除，`unresolved_ministries` 仍包含所有未通過者，不能將排除當成可搜尋完整覆蓋。若要恢復候選入口，須明確覆核與重新驗證，不會自動啟用正式排程。

```console
python -m eu_cyber_news_scraper ministries --country AT
python -m eu_cyber_news_scraper ministries --json --country FI
python -m eu_cyber_news_scraper ministries --check
python -m eu_cyber_news_scraper ministries --country PL --audit-urls
```

`existing_source` 是已登錄部會，並不重新宣稱其解析已合格；`manual_verified` 是本次已完成 live 解析及原文樣本驗證、可明確指定 `--source` 或 `--country` 查詢的新來源。其他狀態只保留在名錄，列出待解析、網站阻擋、缺少獨立新聞入口或待查證原因，不會自行加入抓取來源。沒有命中現有 15 個主題時，仍可用 `--all` 查閱指定來源在期間內的官方新聞。

`--check` 只驗證 JSON、日期與來源參照，完整名錄不等於全部新聞都可抓取。JSON 摘要另外提供 `registered_ministries`（已登錄）、`unresolved_ministries`（未完成）及 `searchable_inventory_complete`（名錄內是否全部已登錄）；最後一項仍不是即時網站或正式排程品質保證。`--audit-urls` 才即時檢查未登錄部會的網址，使用既有 robots、TLS、公網 DNS、重新導向與間隔限制，不驗證解析器、不自動登錄。每次對相同 URL 只檢查一次，來源共用的入口不會推定其發布部會。

既有 15 個主題與可替換 JSON 保留，補充捷克語、斯洛伐克語原文詞；各概念的不同語言譯名仍只計一次，來源責任機關未查證時顯示「未設定」。

葡萄牙動態新聞列表採官網公開前端同一個匿名內容查詢，不使用 API 金鑰、認證標頭或受保護後台。每次先讀官方列表的當屆新聞根節點與部會篩選，再獨立檢查回傳文章的新聞模板及部會標記；不以全站新聞代替單一部會。公開前端路由值僅在記憶體內使用，不寫入 JSON、HTTP 快取或診斷。共用前端程式每次執行只下載一次；仍遵循 robots、TLS 與每站間隔。查詢超過設定分頁上限會明示期間可能不完整，不沿用失效設定或改用認證查詢。

特殊格式使用來源限定解析器：保加利亞國防部只讀取新聞卡片中的文字與固定文章路徑，不執行 onclick；勞動部保留保加利亞語文章與官網原始英文月份日期。保加利亞司法部與義大利國防部只解析已確認的公開新聞 JSON，保留發布時間原文並排除非該機關文章網址。網站回傳成功或具有日期，仍不能單獨證明可搜尋；每個登錄來源另有原文 fixture、獨立 SHA-256 與實際執行證據。

新增 `EU27 central ministry source audit` 在每週三臺北時間 09:15 分國檢測，最多四國同時執行，每國最多八來源併行。逐國 artifact 保存解析觀察與未登錄入口的 URL 診斷，保留 90 天；首次執行可復原舊的共同診斷 history，若不可復原則明示重新累積。原網址稽核改查 EU 層級及挪威，繼續智庫候選探索。工作完成只代表診斷完成，失敗入口、待解析與排程升級證據均需檢視 artifact；正式來源仍須三次連續合格觀察及完整翻譯／artifact／state 驗收。


`audit-sources` 讀取目前 registry，分別檢查官方首頁、新聞列表與所有已設定 feed 的 HTTP 狀態、重新導向、內容型別及錯誤原因；可辨識 TLS／DNS／逾時、robots、challenge page、feed 回傳 HTML、無效 XML 與過小列表等問題。URL 僅接受公開 HTTPS、443 port 及來源設定允許的網域；每一跳、探索出的 feed 與文章內頁也檢查網域與公開 DNS。HTTP 200 本身不代表能正確解析新聞。

```bash
# 預設檢查所有未暫停的登錄來源，包含尚未加入排程的來源
python -m eu_cyber_news_scraper audit-sources --output-dir source-audit --history-dir source-audit-history

# 選擇來源並執行解析及日期品質檢查；--source、--country 可重複指定
python -m eu_cyber_news_scraper audit-sources --source fr_anssi --parse --days 30 --timeout 15 --workers 4

# 限量檢查一國來源，另保存經敏感內容檢查的證據片段（每份最多 32 KiB）
python -m eu_cyber_news_scraper.source_audit --country FR --limit 3 --capture-fixtures
```

稽核 JSON 與 history 是獨立診斷資料，不寫入正式 `.source-health.json`、翻譯快取、排程設定或孤立 `state` 分支。預設跳過暫停來源；明確指定 `--source <id>` 可複查該來源，但不解除暫停。正常退出碼為健康 0、不健康 1、參數或執行錯誤 2；`--allow-unhealthy` 只讓不健康診斷以 0 結束，JSON 中的故障仍保留。

只有加上 `--parse`，且所有設定端點健康、解析成功且新鮮、原始筆數大於零、所有原始文章均完成評估、高信心日期比例至少 0.75、日期衝突比例至多 0.05、未來日期為零、必要日期無缺漏，且探索／內頁等請求無失敗，才算一次合格觀察。同一來源須有三次連續合格、不同 `run_id` 且設定 `config_hash` 一致的觀察；重複 run 不累計，失敗、只查 URL 或設定變更會中斷連續紀錄。`promotion_eligible=true` 與 `review_for_promotion` 只代表可進入人工審查，仍不足以加入正式排程：完整 workflow 品質門檻、翻譯、Excel／JSONL／manifest 交叉驗證及同一次執行的 state observation 都必須通過。任何稽核結果都不會自動登錄來源、啟用排程或解除暫停。

候選機關目錄 [`source_catalog/eu27.seed.json`](source_catalog/eu27.seed.json) 與正式 registry 分開，以 [`catalog.schema.json`](source_catalog/catalog.schema.json) 定義可整份替換或增補的 JSON；也可用 `--catalog 自訂檔.json` 換檔，不必修改程式。每筆包含機關完整名稱、國家、語言、機關屬性、官方網域、首頁、新聞／出版入口、職掌證據、觀測議題與查核紀錄。目前十二個機關均為 `directory_only`、`searchable=false`，只完成機關自有網站證據的人工／agent 查閱，尚未驗證新聞解析器，因此不能以 `--source` 查詢其新聞，也不計入 145 個正式來源。

```bash
# 離線檢查 schema、既存證據紀錄、URL 與 registry／目錄重複項目
python -m eu_cyber_news_scraper catalog --check
python -m eu_cyber_news_scraper catalog --check --catalog my-catalog.json

# 額外即時檢查目錄機關的首頁／新聞 URL，不驗證新聞解析器
python -m eu_cyber_news_scraper catalog --check --audit-urls --output source-audit/catalog-url-report.json

# 從宣告的官方目錄找候選連結，保留前次累積清單，另寫新報告
python -m eu_cyber_news_scraper catalog --check --discover --previous source-audit/catalog-report.json --output source-audit/catalog-report.next.json
```

`catalog --check` 是離線檢查已記錄證據，不重新查證網站，不宣稱已驗證解析器或法定主管權責；退出碼為完成 0、需注意 1、無效 2。探索的官方目錄種子、允許網域、候選網域與國別均由 JSON 宣告；目前上限為 2 個種子頁、每頁 350 個連結、每次 30 個候選。探索只擷取一層目錄連結與 robots，不遞迴、不抓取候選網站，也不自動登錄。新連結保留 `unverified`、`candidate_only`、`searchable=false`，仍須獨立查證身分、國別、職掌與新聞解析器。

`--previous` 會按正規化主機／路徑去重，保留最多 1,000 筆歷次候選及 `first_seen_at`、`last_seen_at`、發現來源；本次未再看到的項目仍保留，以 `seen_this_run=false` 表示。零候選可能來自已知網域、排除條件、上限、robots 或抓取失敗，不代表沒有機關。報告中的國家／議題缺口只描述此部分目錄，不能推論全歐盟機關不存在或正式新聞涵蓋不足。

2026-09-30 本次即時稽核回報：十二個目錄機關中八個 URL 檢查健康；`de_dfki` 為 `robots_denied`，`at_oeaw_ita` 與 `it_fbk` 為 HTTP 403，`se_rise` 為 `robots_unavailable`。官方目錄探索的 JRC 種子回傳 HTTP 403；ECCC 種子成功，保留 `nc3.lu` 的未驗證候選連結。這些是當次存取結果，八個 URL 健康也不代表新聞解析器已驗證，十二個目錄機關仍全部不可查詢新聞。

2026-09-30 的歷史診斷（來源異動前）曾對 53 個當日啟用排程來源執行完整診斷：48 個解析成功，42 個同時通過所有設定 URL 與解析請求健康檢查。這不是正式 GitHub 排程驗收，也未檢驗翻譯、正式 artifact 或同一 run 的 `state` observation；URL／解析健康仍不代表各來源日期品質或升級條件合格。

當時 BNetzA 的 `robots.txt` 回傳 HTML，無法驗證規則；BMI 列表、Institut Montaigne 與 ANSSI 的分頁請求受 robots 限制；BfDI、Bundeskartellamt 達到 60 秒來源預算。ComReg feed 被 robots 禁止，改抓列表雖解析出 20 筆、日期完整率 100%，仍不能消除被禁止的 feed 請求或視為已通過完整品質門檻。Press Corner 與 Cyber Ireland 的 feed 未通過結構檢查，ADAPT 與 Tyndall 首頁／列表回傳 HTTP 403。這些問題須個別查證官方允許入口、feed 格式或延遲原因，不能以忽略 robots、解除暫停或降低品質門檻處理。網站可能拒絕請求、要求互動驗證或變更 robots 規則，本專案不保證持續可存取，也不會因替代入口成功而自動加入排程或解除暫停。

## GitHub Actions

`.github/workflows/scrape.yml` 會在每週一 00:00 UTC（臺灣時間 08:00）執行，將 Excel、入選 JSONL、篩選前 JSONL 與執行摘要保存為 30 天的 workflow artifact；必要來源由同一次完整抓取結果檢查，不另做重複網路 smoke。新聞輸出不提交到 `main`；健康 state v2 與翻譯快取保存於公開孤立 `state` 分支，分支不存在時 workflow 直接失敗。必要來源進入 `degraded` 或正式品質 gate 失敗時，會建立或更新單一 `EU cyber news source health` Issue，恢復後自動關閉；其他來源的 `degraded` 與單次 `attention` 僅寫入 Actions Job Summary。所有第三方 Actions 均固定到完整 commit SHA。推送符合 `v*` 的版本標籤時，Release workflow 會重新驗證測試、建置 wheel／sdist、產生 SHA-256、建立 provenance attestation 並發布 GitHub Release。

手動觸發 `Weekly official cyber news` 時，可填 `source` 指定一個候選來源在 GitHub runner 上驗證；未填時維持原有全量執行。手動執行不會寫入耐久 `state`，也不能取代正式排程的同一 run observation 驗收。

獨立的 [`source-audit.yml`](.github/workflows/source-audit.yml) 定義 `Institution URL audit and discovery`，每週三 01:00 UTC（臺北時間 09:00）執行，也支援手動觸發；只有合併至預設分支後才會啟用每週排程，共享工作樹中的檔案不表示排程已上線。工作先檢查 JSON／TOML 一致性及候選目錄，再對未暫停登錄來源執行 30 天解析稽核，並檢查目錄 URL、探索及累積候選；結果寫入 Job Summary，無自動登錄或解除暫停。

此 workflow 僅有 `contents: read`、`actions: read` 權限，透過 artifact 保存診斷資料，不寫入正式 `state` 分支。`source-inventory-state` 保存 `.source-inventory/` 中的解析觀察 history、候選報告與目錄 URL 診斷；`institution-url-audit-<run_id>` 保存 `source-audit/` 報告，兩者均保留 90 天。下次執行由新到舊嘗試下載 `main` 最近 15 次已完成執行的 `source-inventory-state`，失敗的下載不混入復原資料；全部不可用時才明示重新建立診斷基線。缺少 history 時三次觀察必須重新累積，缺少候選報告時也無法延續舊清單。當次候選檢查無法完成或設定無效時，摘要會明確區分當次失敗與保留供重試的歷史清單，不把舊結果當成最新成功。artifact 不是永久備份，更不能以退出碼 0 或 Job Summary 取代正式品質驗收。

來源可用 `paused_until`、`pause_reason` 與 `pause_evidence_url` 暫停到指定複查日；一般全量執行會跳過並在 `.run.json` 留下稽核資料，明確使用 `--source <id>` 時仍可強制複查。目前 CEA LIST 因官方端點 TLS 連線持續超時，暫停至 2026-10-31；歐洲議會官方 RSS 與列表因 GitHub-hosted runner 收到 HTTP 202 JavaScript challenge，暫停排程至 2026-10-31，本機仍可用 `--source eu_parliament_press` 複查。

## 測試

```bash
python3 -m pip install --user uv==0.11.29  # 尚未安裝 uv 時
uv sync --frozen --all-extras
uv run ruff check .
uv run mypy src/eu_cyber_news_scraper
uv run pytest --cov=eu_cyber_news_scraper --cov-report=term-missing --cov-fail-under=92
uv run pip-audit
```

既有專案 `.venv` 可直接執行 `scripts/check`，不依賴 shell 的 `uv` PATH；`scripts/live-audit`
會在 `/tmp` 以正式品質門檻執行 rolling 14 天全量驗收，且固定使用 `--health-write never`。

測試採本地 RSS／HTML fixtures，不依賴即時網站；目前 52 個排程來源各保存實際官方 URL、來源入口、擷取日與 SHA-256 合約，並保存可執行的精簡 parser fixture。新增候選來源仍需逐一完成同等驗證，通過前不加入排程。議題輔助回歸集包含 240 筆獨立官方英、法、德項目，每種語言 80 筆，並區分 dev 與 locked test、hard negative 及 provenance；目前全部標示為 `assisted`，尚未完成具名人工覆核，因此不宣稱為人工 gold set。回歸門檻為整體 precision、recall 均至少 0.90，每個主題 recall 至少 0.75。翻譯另有 60 筆英、法、德審核資料，驗證繁體中文輸出與必要法制／資安術語；新語言仍須另做人工覆核。CI 會在 Python 3.11、3.12、3.13 執行，要求至少 92% 覆蓋率、Ruff、mypy strict、`pip-audit`、`uv.lock` 一致性及 wheel／sdist 安裝測試；每週工作的必要來源由同一次完整抓取結果檢查。

## 已知限制

- 通用 HTML 解析器無法保證涵蓋所有動態載入網站；遇到 JavaScript-only 頁面應新增官方 API／feed 或專用解析器。
- 翻譯會將新聞標題送往外部服務；若有資料治理限制，可預先提供翻譯快取或另行替換翻譯器。
- `.run.json` 與 JSONL 使用 schema v6；公開 schema 位於 `schemas/`。v5 常用欄位仍保留，並新增完整日期候選 provenance、日期衝突率與高信心日期率。來源狀態分為 `fetch_status`、`parse_status`、`freshness_status`、`content_status` 與彙總 `health_status`。
- `complete` 代表必要來源與品質門檻均正常；非必要來源失敗、單次健康基線警示或翻譯成功率低於 95% 會標示 `attention`；必要來源抓取失敗或連續健康異常則為 `degraded`。
- 已設定分頁或年度模板的來源會依日期範圍抓取存檔頁；尚未提供穩定分頁規則的網站仍可能受其首頁顯示筆數限制。
- 公共研究中心的內容屬研究資訊，不等同主管機關的正式法律解釋。
