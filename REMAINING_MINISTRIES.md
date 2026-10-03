# 剩餘中央部會入口逐項複查

起始剩餘 201 個；本批檢查 201 個。觀察日期：2026-10-02、2026-10-03。
累計新增可手動查詢 42 個；仍未完成新聞入口驗證 159 個。
最新第 4 輪涵蓋當輪起始全部 170 個未完成入口。各輪紀錄保留，不覆寫過往觀察。
全部檢查過不代表全部可以搜尋，也不代表正式排程已通過來源、日期、翻譯、artifact 與 state 驗收。
robots、TLS、網站阻擋及需要認證的入口不繞過；未建立發布機關歸屬或日期證據的入口不登錄。

逐項原始檢查紀錄：[第 3 輪／north](tests/fixtures/ministry_round3_north.json)、[第 3 輪／portugal](tests/fixtures/ministry_round3_portugal.json)、[第 3 輪／south](tests/fixtures/ministry_round3_south.json)、[第 4 輪／blocked](tests/fixtures/ministry_round4_blocked.json)、[第 4 輪／north](tests/fixtures/ministry_round4_north.json)、[第 4 輪／south](tests/fixtures/ministry_round4_south.json)。
完整 460 筆名錄見 [MINISTRIES.md](MINISTRIES.md)。

| 國家 | 部會 | 本批結果 | 嘗試入口數 | 後續處理 |
| --- | --- | --- | --- | --- |
| AT | 奧地利聯邦總理府（`at_bka`） | 已驗證手動來源 | 8 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| AT | 奧地利歐洲與國際事務部（`at_bmeia`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| AT | 奧地利國防部（`at_bmlv`） | 待查證 | 3 | Official detail has article:modified_time only; feed dc:date matches modification while visible supplement is a location/event dateline. Require an explicit original publication field; do not promote or rewrite HTTP feed article URLs. |
| BE | 比利時首相府（`be_chancellery`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| BE | 比利時財政公共服務部（`be_finance`） | 已驗證手動來源 | 2 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| BE | 比利時衛生、食品鏈安全與環境公共服務部（`be_health`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| BE | 比利時內政公共服務部（`be_interior`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| BE | 比利時司法公共服務部（`be_justice`） | 已驗證手動來源 | 2 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| BE | 比利時科學政策規劃公共服務部（`be_science_policy`） | 已驗證手動來源 | 9 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| BG | 保加利亞國防部（`bg_defence`） | 已驗證手動來源 | 7 | Keep verified manual source disabled from scheduling; replay exact fixture and source-specific adapter tests before any later activation. |
| BG | 保加利亞教育與科學部（`bg_education`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| BG | 保加利亞環境與水資源部（`bg_environment`） | 已驗證手動來源 | 10 | Keep manual-only source disabled from scheduling; replay provenance fixture before any later activation. |
| BG | 保加利亞財政部（`bg_finance`） | 存取受阻 | 3 | The accessible government directory/shared portal does not establish ministry-specific news ownership. Recheck the recorded ministry access restriction; do not alias shared government content. |
| BG | 保加利亞司法部（`bg_justice`） | 已驗證手動來源 | 7 | Keep verified manual source disabled from scheduling; replay exact fixture and source-specific adapter tests before any later activation. |
| BG | 保加利亞勞動與社會政策部（`bg_labour`） | 已驗證手動來源 | 4 | Keep verified manual source disabled from scheduling; replay exact fixture and source-specific adapter tests before any later activation. |
| BG | 保加利亞區域發展與公共工程部（`bg_regional_development`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| BG | 保加利亞青年與體育部（`bg_youth_sport`） | 存取受阻 | 3 | Recheck the canonical portal only after robots policy permits retrieval or locate a separately published attributable ministry feed. |
| CY | 塞浦路斯農業、農村發展與環境部（`cy_agriculture`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯國防部（`cy_defence`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯教育、體育與青年部（`cy_education`） | 已驗證手動來源 | 1 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| CY | 塞浦路斯能源、商業與工業部（`cy_energy`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯財政部（`cy_finance`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯外交部（`cy_foreign_affairs`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯衛生部（`cy_health`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯內政部（`cy_interior`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯司法與公共秩序部（`cy_justice`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯勞動與社會保險部（`cy_labour`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CY | 塞浦路斯運輸、通信與工程部（`cy_transport`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CZ | 捷克農業部（`cz_agriculture`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CZ | 捷克財政部（`cz_finance`） | 已驗證手動來源 | 11 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| CZ | 捷克外交部（`cz_foreign_affairs`） | 已驗證手動來源 | 10 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| CZ | 捷克工業與貿易部（`cz_industry`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| CZ | 捷克內政部（`cz_interior`） | 已驗證手動來源 | 1 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| DE | 德國聯邦總理府（`de_bka`） | 待查證 | 1 | Fresh Chancellery organizational page provides office biographies and documents, without a ministry-specific dated news listing. Bundesregierung/Bundespresseamt news ownership remains insufficient; preserve review status. |
| DE | 德國財政部（`de_bmf`） | 待解析／歸屬驗證 | 3 | Original listing yields 10 dated articles, but two production attempts exceeded 60-second source budget. Investigate transport before enrollment; do not raise quality thresholds or declare success. |
| DE | 德國研究、科技與太空部（`de_bmftr`） | 已驗證手動來源 | 6 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| DE | 德國司法與消費者保護部（`de_bmjv`） | 已驗證手動來源 | 11 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| DE | 德國農業、糧食與家鄉部（`de_bmleh`） | 已驗證手動來源 | 10 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| DE | 德國交通部（`de_bmv`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| DE | 德國經濟與能源部（`de_bmwe`） | 存取受阻 | 2 | Wait for upstream challenge policy to change; HTTP 200 is not successful content access. |
| DK | 丹麥商業部（`dk_business`） | 已驗證手動來源 | 10 | Manual collection only; retain bounded-list truncation warning and verify archive completeness before any separately authorized scheduling decision. |
| DK | 丹麥兒童、高齡與住宅部（`dk_children`） | 待解析／歸屬驗證 | 9 | Resolve the recorded production API HTTP 400 or network timeout through a published, robots-permitted dated endpoint; do not bypass access policy. |
| DK | 丹麥氣候、能源與公用事業部（`dk_climate`） | 已驗證手動來源 | 8 | Manual collection only; retain bounded-list truncation warning and verify archive completeness before any separately authorized scheduling decision. |
| DK | 丹麥國防部（`dk_defence`） | 已驗證手動來源 | 6 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| DK | 丹麥就業與平等部（`dk_employment`） | 已驗證手動來源 | 7 | Manual collection only; retain bounded-list truncation warning and verify archive completeness before any separately authorized scheduling decision. |
| DK | 丹麥環境部（`dk_environment`） | 已驗證手動來源 | 2 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| DK | 丹麥外交部（`dk_foreign_affairs`） | 已驗證手動來源 | 7 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| DK | 丹麥自然與動物福利部（`dk_nature`） | 已驗證手動來源 | 7 | Manual collection only; retain bounded-list truncation warning and verify archive completeness before any separately authorized scheduling decision. |
| DK | 丹麥社會安全與應變部（`dk_resilience`） | 已驗證手動來源 | 2 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| DK | 丹麥首相府（`dk_stm`） | 已驗證手動來源 | 8 | Manual collection only. Review freshness and publisher ownership during later observations before any separate scheduling decision. |
| DK | 丹麥稅務與成長部（`dk_taxation`） | 已驗證手動來源 | 10 | Manual collection only; retain bounded-list truncation warning and verify archive completeness before any separately authorized scheduling decision. |
| DK | 丹麥城市、鄉村與交通部（`dk_transport`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| ES | 西班牙經濟、商業與企業部（`es_economy`） | 已驗證手動來源 | 12 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| ES | 西班牙外交、歐盟與合作部（`es_foreign_affairs`） | 已驗證手動來源 | 11 | Keep manual-only source disabled from scheduling; replay provenance fixture before any later activation. |
| ES | 西班牙社會包容、社會安全與移民部（`es_inclusion`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| ES | 西班牙產業與觀光部（`es_industry_tourism`） | 待解析／歸屬驗證 | 4 | Resolve the recorded production API HTTP 400 or network timeout through a published, robots-permitted dated endpoint; do not bypass access policy. |
| ES | 西班牙內政部（`es_interior`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| ES | 西班牙勞動與社會經濟部（`es_labour`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| ES | 西班牙政府首長辦公室（`es_presidency`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| ES | 西班牙政府主席事務、司法與國會關係部（`es_presidency_justice`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭農林部（`fi_agriculture_forestry`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭國防部（`fi_defence`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭經濟事務與就業部（`fi_economy_employment`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭教育與文化部（`fi_education_culture`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭環境部（`fi_environment`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭財政部（`fi_finance`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭外交部（`fi_foreign_affairs`） | 已驗證手動來源 | 5 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| FI | 芬蘭內政部（`fi_interior`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭司法部（`fi_justice`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭總理府（`fi_prime_minister`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭社會事務與衛生部（`fi_social_health`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FI | 芬蘭交通與通訊部（`fi_transport_communications`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國城市與住宅部（`fr_city_housing`） | 待查證 | 4 | Fresh shared press details contain original Publié le dates but no per-release publisher field; minister/body mentions and shared footer are insufficient attribution. Require an official ministry publisher identifier or ministry-specific feed before enrollment. |
| FR | 法國生態轉型、生物多樣性與氣候及自然國際談判部（`fr_ecological_transition`） | 待查證 | 4 | Fresh shared press details contain original Publié le dates but no per-release publisher field; minister/body mentions and shared footer are insufficient attribution. Require an official ministry publisher identifier or ministry-specific feed before enrollment. |
| FR | 法國經濟、財政與產業、能源及數位主權部（`fr_economy_finance`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國國民教育部（`fr_education`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國歐洲與外交部（`fr_foreign_affairs`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國衛生、家庭、自主生活與身心障礙事務部（`fr_health_family`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國高等教育、研究與太空部（`fr_higher_education_research`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國內政部（`fr_interior`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國勞動與團結部（`fr_labour_solidarity`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國海外領土部（`fr_overseas`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國總理府（`fr_prime_minister`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國公共行政與公共帳務部（`fr_public_accounts`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國中小企業、商業、工藝、觀光與購買力部（`fr_sme_commerce_tourism`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| FR | 法國國土規劃與地方分權部（`fr_territorial_decentralisation`） | 待查證 | 4 | Fresh shared press details contain original Publié le dates but no per-release publisher field; minister/body mentions and shared footer are insufficient attribution. Require an official ministry publisher identifier or ministry-specific feed before enrollment. |
| FR | 法國交通部（`fr_transport`） | 待查證 | 4 | Fresh shared press details contain original Publié le dates but no per-release publisher field; minister/body mentions and shared footer are insufficient attribution. Require an official ministry publisher identifier or ministry-specific feed before enrollment. |
| GR | 希臘農業發展與食品部（`gr_agriculture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘公民保護部（`gr_citizen_protection`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘氣候危機與民防部（`gr_climate_civil_protection`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘文化部（`gr_culture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘國防部（`gr_defence`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘數位治理部（`gr_digital`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘環境與能源部（`gr_environment_energy`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘國民經濟與財政部（`gr_finance`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘外交部（`gr_foreign_affairs`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘政府主席辦公室（`gr_government_presidency`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘基礎建設與交通部（`gr_infrastructure_transport`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘內政部（`gr_interior`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘司法部（`gr_justice`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘勞動與社會安全部（`gr_labour`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘航運與島嶼政策部（`gr_maritime`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘社會凝聚與家庭部（`gr_social_family`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| GR | 希臘觀光部（`gr_tourism`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞農業、林業與漁業部（`hr_agriculture`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞文化與媒體部（`hr_culture`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞國防部（`hr_defence`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞人口與移入事務部（`hr_demography`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞經濟部（`hr_economy`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞科學、教育與青年部（`hr_education_science`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞環境保護與綠色轉型部（`hr_environment`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞財政部（`hr_finance`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞外交與歐洲事務部（`hr_foreign_affairs`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞衛生部（`hr_health`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞內政部（`hr_interior`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞司法、行政與數位轉型部（`hr_justice_digital`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞勞動、退休金制度、家庭與社會政策部（`hr_labour_social`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞總理辦公室（`hr_prime_minister`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞區域發展與歐盟基金部（`hr_regional_eu`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞海洋、交通與基礎建設部（`hr_sea_transport`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞空間規劃、建設與國有資產部（`hr_spatial_construction`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞觀光與體育部（`hr_tourism_sport`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HR | 克羅埃西亞退伍軍人部（`hr_veterans`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| HU | 匈牙利國防部（`hu_defence`） | 待查證 | 18 | Require explicit ministry publisher metadata or an attributable dedicated current ministry news endpoint before promotion. |
| HU | 匈牙利總理府（`hu_prime_minister`） | 待查證 | 2 | Require explicit ministry publisher metadata or an attributable dedicated current ministry news endpoint before promotion. |
| IT | 義大利農業、糧食主權暨林業部（`it_agriculture`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利民防部門（`it_civil_protection`） | 已驗證手動來源 | 11 | 已驗證原文抓取與發布日期，僅供手動查詢；保留有界列表／內頁樣本的不完整警告。正式排程須另行完成升級驗收。 |
| IT | 義大利文化部（`it_culture`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利國防部（`it_defence`） | 已驗證手動來源 | 14 | Keep verified manual source disabled from scheduling; replay exact fixture and source-specific adapter tests before any later activation. |
| IT | 義大利環境暨能源安全部（`it_environment`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利平等機會部門（`it_equal_opportunities`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利歐洲事務部門（`it_european_affairs`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利衛生部（`it_health`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利制度改革部門（`it_institutional_reforms`） | 待解析／歸屬驗證 | 3 | Wait for explicit first-party publication metadata or a dated ministry publication feed; retain captured negative regression test. |
| IT | 義大利內政部（`it_interior`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利司法部（`it_justice`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利海洋政策部門（`it_maritime_policies`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利公共行政部門（`it_public_administration`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| IT | 義大利青年政策暨全民公民服務部門（`it_youth`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛農業部（`lt_agriculture`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛文化部（`lt_culture`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛國防部（`lt_defence`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛經濟暨創新部（`lt_economy`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛教育、科學暨體育部（`lt_education`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛能源部（`lt_energy`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛環境部（`lt_environment`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛財政部（`lt_finance`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛外交部（`lt_foreign_affairs`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛政府辦公室（`lt_government_office`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛衛生部（`lt_health`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛內政部（`lt_interior`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛司法部（`lt_justice`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛社會保障暨勞動部（`lt_social_security`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| LT | 立陶宛交通暨通訊部（`lt_transport`） | 存取受阻 | 4 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他住宅暨土地部（`mt_accommodation`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他農業、漁業暨食品供應部（`mt_agriculture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他藝術、文化暨國家文化遺產部（`mt_culture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他經濟、科技暨策略計畫部（`mt_economy`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他教育暨體育部（`mt_education`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他能源、環境暨大港再生部（`mt_energy`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他平等暨公民權利部（`mt_equality`） | 存取受阻 | 2 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他歐洲基金、社會對話暨消費者保護部（`mt_european_funds`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他財政部（`mt_finance`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他外交暨歐洲事務部（`mt_foreign_affairs`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他Gozo 部（`mt_gozo`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他副總理府暨衛生部（`mt_health`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他內政暨安全部（`mt_home_affairs`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他融合暨志願部門部（`mt_inclusion`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他基礎建設、規劃暨就業部（`mt_infrastructure`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他司法、研究暨創新部（`mt_justice`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他地方政府暨公共工程部（`mt_local_government`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他總理府（`mt_opm`） | 存取受阻 | 3 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他社會政策暨家庭部（`mt_social_policy`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他永續交通部（`mt_sustainable_mobility`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他旅遊部（`mt_tourism`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| MT | 馬爾他青年、福祉暨選舉政見實施部（`mt_youth`） | 存取受阻 | 2 | Locate an allowed official DOI news endpoint with explicit youth-ministry attribution, or wait for robots policy change. |
| PT | 葡萄牙農業與海洋部（`pt_agriculture_sea`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙部長會議主席府（含總理辦公室）（`pt_council_presidency`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙文化青年與體育部（`pt_culture_youth_sport`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙國防部（`pt_defence`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙經濟與領土凝聚部（`pt_economy_cohesion`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙教育科學與創新部（`pt_education_science`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙環境與能源部（`pt_environment_energy`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙財政部（`pt_finance`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙衛生部（`pt_health`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙基礎建設與住宅部（`pt_infrastructure_housing`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙內政部（`pt_interior`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| PT | 葡萄牙勞動團結與社會保障部（`pt_labour_social`） | 已驗證手動來源 | 4 | 可手動查詢；正式排程仍須連續觀察及日期、翻譯、artifact／state 驗收。 |
| RO | 羅馬尼亞農業與農村發展部（`ro_agriculture`） | 存取受阻 | 6 | The accessible government directory/shared portal does not establish ministry-specific news ownership. Recheck the recorded ministry access restriction; do not alias shared government content. |
| RO | 羅馬尼亞文化部（`ro_culture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞發展公共工程與行政部（`ro_development`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞經濟數位化創業與觀光部（`ro_economy_digital`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞能源部（`ro_energy`） | 存取受阻 | 6 | The accessible government directory/shared portal does not establish ministry-specific news ownership. Recheck the recorded ministry access restriction; do not alias shared government content. |
| RO | 羅馬尼亞投資與歐洲計畫部（`ro_european_investment`） | 存取受阻 | 6 | The accessible government directory/shared portal does not establish ministry-specific news ownership. Recheck the recorded ministry access restriction; do not alias shared government content. |
| RO | 羅馬尼亞外交部（`ro_foreign_affairs`） | 存取受阻 | 6 | The accessible government directory/shared portal does not establish ministry-specific news ownership. Recheck the recorded ministry access restriction; do not alias shared government content. |
| RO | 羅馬尼亞政府秘書處（`ro_government_secretariat`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞勞動家庭青年與社會團結部（`ro_labour_family_youth`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞總理辦公廳（`ro_prime_minister`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| RO | 羅馬尼亞交通與基礎建設部（`ro_transport`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| SK | 斯洛伐克農業與農村發展部（`sk_agriculture`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
| SK | 斯洛伐克外交與歐洲事務部（`sk_foreign_affairs`） | 存取受阻 | 1 | Wait for the recorded upstream access/TLS/robots restriction to change; no bypass or automatic removal. |
