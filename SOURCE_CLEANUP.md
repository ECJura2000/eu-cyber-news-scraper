# 無法抓取來源清理（2026-10-04）

對 v1.8.0 的 448 個來源檢查 446 個未暫停來源，再以正式抓取方式複查首輪失敗入口。已複查 72 個，移除 39 個，現有 409 個可選來源。

移除原因代表本次兩輪抓取失敗，不代表機關或網站不存在。零筆且解析失敗、robots 拒絕、robots 無法取得及驗證頁均依使用者要求移出可查詢設定。只在備用端點失敗、但正式抓取成功的來源保留。

正式每週未暫停來源仍為 50，品質門檻與歐洲議會／CEA 暫停設定維持原設定。這些未被移除的來源並非全部已通過正式排程升級驗收。

原機關 JSON 與網址保留在 [排除檔案](source_exclusions/modules/)，兩輪觀察見 [機器可讀清理紀錄](source_exclusions/manifest.json)。該目錄不在預設 registry 掃描範圍，不參與手動抓取或排程；如要重新加入，需重新驗證後移回權威清單。

| 國家 | 機關 | 原入口 | 移除原因 |
| --- | --- | --- | --- |
| BE | 比利時網路安全中心（`be_ccb`） | [原新聞入口](https://ccb.belgium.be/en/news) | `ROBOTS_DENIED` |
| BG | 保加利亞內政部（`bg_interior`） | [原新聞入口](https://mvr.bg/press/%D0%B0%D0%BA%D1%82%D1%83%D0%B0%D0%BB%D0%BD%D0%B0-%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F/%D0%B0%D0%BA%D1%82%D1%83%D0%B0%D0%BB%D0%BD%D0%B0-%D0%B8%D0%BD%D1%84%D0%BE%D1%80%D0%BC%D0%B0%D1%86%D0%B8%D1%8F/%D0%B0%D0%BA%D1%82%D1%83%D0%B0%D0%BB%D0%BD%D0%BE/%2A) | `HTTP_CHALLENGE` |
| DK | 丹麥環境部（`dk_environment`） | [原新聞入口](https://mim.dk/nyheder/pressemeddelelser) | `PARSE_EMPTY` |
| DK | 丹麥國會（`dk_folketing`） | [原新聞入口](https://www.ft.dk/da/aktuelt/nyheder) | `ROBOTS_DENIED` |
| EE | 愛沙尼亞資料保護監察局（`ee_aki`） | [原新聞入口](https://www.aki.ee/otsing?f%5B0%5D=type%3Anews) | `HTTP_CHALLENGE` |
| EE | 愛沙尼亞資訊系統局（`ee_ria`） | [原新聞入口](https://www.ria.ee/otsing?type=Uudis) | `HTTP_CHALLENGE` |
| EE | 愛沙尼亞國會（`ee_riigikogu`） | [原新聞入口](https://www.riigikogu.ee/info-ja-meedia/uudised-ja-pressiteated/) | `ROBOTS_UNAVAILABLE` |
| EE | 愛沙尼亞塔林理工大學（`ee_taltech`） | [原新聞入口](https://taltech.ee/en/news) | `HTTP_CHALLENGE` |
| ES | 巴塞隆納超級運算中心（`es_bsc`） | [原新聞入口](https://www.bsc.es/es/noticias) | `PARSE_EMPTY` |
| ES | 西班牙眾議院（`es_congreso`） | [原新聞入口](https://www.congreso.es/es/notas-de-prensa) | `ROBOTS_DENIED` |
| FI | 芬蘭商務署（`fi_business_finland`） | [原新聞入口](https://www.businessfinland.fi/en/whats-new/news/) | `PARSE_EMPTY` |
| FI | 芬蘭資料保護監察官辦公室（`fi_tietosuoja`） | [原新聞入口](https://tietosuoja.fi/uutiset-tiedotteet) | `ROBOTS_DENIED` |
| HU | 匈牙利國家網路安全研究所（`hu_nki`） | [原新聞入口](https://nki.gov.hu/figyelmeztetesek/tajekoztatas/) | `PARSE_EMPTY` |
| IT | 義大利國家網路安全局（`it_acn`） | [原新聞入口](https://www.acn.gov.it/portale/comunicazione) | `ROBOTS_DENIED` |
| IT | 義大利教育暨功績部（`it_education`） | [原新聞入口](https://www.mim.gov.it/web/guest/comunicati) | `ROBOTS_DENIED` |
| IT | 義大利大學及研究部（`it_mur`） | [原新聞入口](https://www.mur.gov.it/it/news) | `ROBOTS_DENIED` |
| LT | 立陶宛國家網路安全中心（`lt_nksc`） | [原新聞入口](https://nksc.lrv.lt/lt/naujienos/) | `ROBOTS_DENIED` |
| LT | 立陶宛國家資料保護監察局（`lt_vdai`） | [原新聞入口](https://vdai.lrv.lt/lt/naujienos/) | `ROBOTS_DENIED` |
| MT | 馬爾他外交暨歐洲事務部（`mt_foreign_affairs`） | [原新聞入口](https://foreign.gov.mt/press-releases-media/) | `ROBOTS_DENIED` |
| MT | 馬爾他國家網路安全協調中心（`mt_ncc`） | [原新聞入口](https://ncc-mita.gov.mt/category/news/) | `ROBOTS_DENIED` |
| NL | 荷蘭數位基礎設施監察局（`nl_rdi`） | [原新聞入口](https://www.rdi.nl/actueel/nieuws) | `PARSE_EMPTY` |
| NO | 挪威資料保護局（`no_datatilsynet`） | [原新聞入口](https://www.datatilsynet.no/aktuelt/) | `ROBOTS_UNAVAILABLE` |
| NO | 挪威國家安全局（`no_nsm`） | [原新聞入口](https://nsm.no/aktuelt/) | `HTTP_CHALLENGE` |
| PL | 波蘭眾議院（`pl_sejm`） | [原新聞入口](https://www.sejm.gov.pl/Sejm10.nsf/wydarzenia.xsp) | `ROBOTS_DENIED` |
| PT | 葡萄牙國家通訊管理局（`pt_anacom`） | [原新聞入口](https://www.anacom.pt/render.jsp?categoryId=166043) | `ROBOTS_DENIED` |
| PT | 葡萄牙國家網路安全中心（`pt_cncs`） | [原新聞入口](https://dyn.cncs.gov.pt/pt/noticias/) | `ROBOTS_UNAVAILABLE` |
| RO | 羅馬尼亞國家網路安全局（`ro_dnsc`） | [原新聞入口](https://www.dnsc.ro/) | `ROBOTS_DENIED` |
| RO | 羅馬尼亞布加勒斯特資訊研究發展院（`ro_ici`） | [原新聞入口](https://ici.ro/) | `ROBOTS_UNAVAILABLE` |
| SE | 瑞典氣候與企業部（`se_climate_enterprise`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/klimat--och-naringslivsdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典文化部（`se_culture`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/kulturdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典國防部（`se_defence`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/forsvarsdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典教育與研究部（`se_education_research`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/utbildningsdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典勞動部（`se_employment`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/arbetsmarknadsdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典財政部（`se_finance`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/finansdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典外交部（`se_foreign_affairs`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/utrikesdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典衛生與社會事務部（`se_health_social`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/socialdepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典司法部（`se_justice`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/justitiedepartementet/) | `HTTP_CHALLENGE` |
| SE | 瑞典首相辦公室（`se_prime_minister`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/statsradsberedningen/) | `HTTP_CHALLENGE` |
| SE | 瑞典農村事務與基礎建設部（`se_rural_infrastructure`） | [原新聞入口](https://www.regeringen.se/sveriges-regering/landsbygds--och-infrastrukturdepartementet/) | `HTTP_CHALLENGE` |
