# 歐盟資安法制官方新聞爬蟲

本專案抓取歐洲官方機關、法定監理機構、行政法人與公共研究機構新聞。來源清單涵蓋歐盟 27 個成員國、歐盟機構及既有挪威來源。原有 EU、FR、DE、IE 來源維持每週排程；新增來源先供手動查詢與驗證。分類器與主管機關矩陣使用相同的 15 項觀測議題。

設計承接既有 `UK-news-scraper` 的實務做法：優先使用 RSS／Atom，找不到 feed 時才解析 HTML；每個來源獨立失敗、併發執行、穩定去重、輸出 Excel 與 JSON 執行摘要，並保留來源健康狀態。程式只設定官方或公共研究來源，不以商業媒體或 Google News 作為預設備援。

## 機關 Registry

機關模組位於 [`organisation_registry/`](organisation_registry/)，148 個新聞來源各有一份 schema v2 JSON（PR #37 的 101 個來源，加上 24 個原未登錄歐盟國家來源與 23 個既有歐盟國家補充來源）。每個模組包含來源 URL 與解析設定、主題白名單、健康門檻、機關沿革、官方證據及驗證狀態；預設執行直接由這些 JSON 建立來源清單。新增或覆寫模組可放在 macOS 的 `~/Library/Application Support/EUCyberNewsScraper/organisations.d`，或使用 `EU_CYBER_ORGANISATION_DIR` 指定目錄，重啟後載入。外部模組驗證失敗會保留同 ID 的內建模組；無內建版本的新模組會略過，並讓 `.run.json` 的 `organisation_audit_status` 成為 `degraded`。

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

來源設定集中於 `organisation_registry/*.json`（預設）及 `src/eu_cyber_news_scraper/sources.toml`（`--config` 時）。每個來源可設定：

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
目前共 148 個來源；本 PR 新增的 47 個候選來源均為 `schedule_enabled = false`，只有明確指定 `--country` 或 `--source` 才會手動抓取。其中 24 個原未登錄歐盟國家來源完成首輪手動抓取：12 個健康，其他來源依 `verification.status` 與 `last_smoke` 記錄日期不完整、過舊、版型無法解析或網站拒絕存取等原因。研究機構、大學與公私協力單位只作為政策研究、技術評估及生態系觀測來源，不視為具有監理權限的主管機關。

`.source-health.json` 使用 schema v2，以執行 profile 與每來源設定 fingerprint 分隔基線，最多保留每個來源最近 12 個獨立 observation；同一期間重跑會取代既有 observation，不會累積成連續異常。舊 v1 會保存在 `legacy`，但不參與新基線。`--health-write auto` 只讓完整 rolling 且啟用內頁的標準執行寫入；固定歷史期間預設唯讀，也可明確使用 `always` 或 `never`。健康 state 只在 Excel、JSONL 與 manifest 完整驗證並發布後寫入。

來源另有新鮮度門檻：必要來源預設 45 天、其他來源預設 90 天，可在 `sources.toml` 以 `freshness_days` 個別調整。超過門檻的必要來源不會因仍抓得到舊文章而誤判為正常。內容期間內沒有命中議題只會記錄在「內容結果」，不會混入抓取故障。

來源以 `asyncio` 與共享 `httpx.AsyncClient` 執行，預設最多同時處理 8 個來源，可用 `--workers` 調整；全域最多 16 個 HTTP 請求、同網域最多 2 個，連線逾時上限 8 秒、最多一次冪等重試、單一回應上限 5 MiB。`--source-budget` 以 `asyncio.timeout` 包住來源的 feed、列表與內頁完整流程，期限到達會取消未完成請求。相同輸出檔同一時間只允許一個工作執行，健康資料與翻譯快取另共用狀態鎖，避免遺失更新。新增來源後應同步：

1. 更新 `sources.toml` 與 `SOURCES.md`。
2. 先執行 `--source 新代碼 --days 60 --include-undated` 人工檢查。
3. 為特殊 HTML 版型補 fixture 測試，避免把導覽、徵才或活動頁誤當新聞。
4. 至少累積三次健康紀錄，且連續觀察兩週後，再將來源標記為 `critical = true`。

## GitHub Actions

`.github/workflows/scrape.yml` 會在每週一 00:00 UTC（臺灣時間 08:00）執行，將 Excel、入選 JSONL、篩選前 JSONL 與執行摘要保存為 30 天的 workflow artifact；必要來源由同一次完整抓取結果檢查，不另做重複網路 smoke。新聞輸出不提交到 `main`；健康 state v2 與翻譯快取保存於公開孤立 `state` 分支，分支不存在時 workflow 直接失敗。必要來源進入 `degraded` 或正式品質 gate 失敗時，會建立或更新單一 `EU cyber news source health` Issue，恢復後自動關閉；其他來源的 `degraded` 與單次 `attention` 僅寫入 Actions Job Summary。所有第三方 Actions 均固定到完整 commit SHA。推送符合 `v*` 的版本標籤時，Release workflow 會重新驗證測試、建置 wheel／sdist、產生 SHA-256、建立 provenance attestation 並發布 GitHub Release。

手動觸發 `Weekly official cyber news` 時，可填 `source` 指定一個候選來源在 GitHub runner 上驗證；未填時維持原有全量執行。手動執行不會寫入耐久 `state`，也不能取代正式排程的同一 run observation 驗收。

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

測試採本地 RSS／HTML fixtures，不依賴即時網站；原 55 個排程來源各保存實際官方 URL、來源入口、擷取日與 SHA-256 合約，並保存可執行的精簡 parser fixture。新增候選來源仍需逐一完成同等驗證，通過前不加入排程。議題輔助回歸集包含 240 筆獨立官方英、法、德項目，每種語言 80 筆，並區分 dev 與 locked test、hard negative 及 provenance；目前全部標示為 `assisted`，尚未完成具名人工覆核，因此不宣稱為人工 gold set。回歸門檻為整體 precision、recall 均至少 0.90，每個主題 recall 至少 0.75。翻譯另有 60 筆英、法、德審核資料，驗證繁體中文輸出與必要法制／資安術語；新語言仍須另做人工覆核。CI 會在 Python 3.11、3.12、3.13 執行，要求至少 92% 覆蓋率、Ruff、mypy strict、`pip-audit`、`uv.lock` 一致性及 wheel／sdist 安裝測試；每週工作的必要來源由同一次完整抓取結果檢查。

## 已知限制

- 通用 HTML 解析器無法保證涵蓋所有動態載入網站；遇到 JavaScript-only 頁面應新增官方 API／feed 或專用解析器。
- 翻譯會將新聞標題送往外部服務；若有資料治理限制，可預先提供翻譯快取或另行替換翻譯器。
- `.run.json` 與 JSONL 使用 schema v6；公開 schema 位於 `schemas/`。v5 常用欄位仍保留，並新增完整日期候選 provenance、日期衝突率與高信心日期率。來源狀態分為 `fetch_status`、`parse_status`、`freshness_status`、`content_status` 與彙總 `health_status`。
- `complete` 代表必要來源與品質門檻均正常；非必要來源失敗、單次健康基線警示或翻譯成功率低於 95% 會標示 `attention`；必要來源抓取失敗或連續健康異常則為 `degraded`。
- 已設定分頁或年度模板的來源會依日期範圍抓取存檔頁；尚未提供穩定分頁規則的網站仍可能受其首頁顯示筆數限制。
- 公共研究中心的內容屬研究資訊，不等同主管機關的正式法律解釋。
