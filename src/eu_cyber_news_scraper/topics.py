from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import Article

OBSERVATION_TOPICS = (
    "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
    "跨境資料流通、資料主權、資料開放與再利用",
    "隱私框架（含個人資料保護）",
    "數位身份",
    "著作權",
    "平台責任、內容審查、推薦演算法",
    "媒體多元與資訊操縱",
    "競爭規範面向（平台責任的市場結構面）",
    "NIS2、關鍵基礎設施保護",
    "產品資安、漏洞揭露義務、SBOM",
    "供應鏈安全",
    "資安產品認證",
    "關鍵基礎設施的實體與數位融合保護",
    "半導體",
    "量子技術",
)


@dataclass(frozen=True)
class TopicRule:
    name: str
    keywords: tuple[str, ...]
    weight: int = 1


TOPIC_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        "CRA／產品資安",
        (
            "cyber resilience act",
            "regulation (eu) 2024/2847",
            "règlement sur la cyberrésilience",
            "règlement sur la cyber-résilience",
            "règlement européen sur la cyberrésilience",
            "législation sur la cyberrésilience",
            "cyberresilienzverordnung",
            "cyber-resilienz-verordnung",
            "cyberresilienzgesetz",
            "eu-verordnung zur cyberresilienz",
            "produits comportant des éléments numériques",
            "produit comportant des éléments numériques",
            "produits avec des éléments numériques",
            "products with digital elements",
            "produkte mit digitalen elementen",
            "produkt mit digitalen elementen",
            "horizontale cybersicherheitsanforderungen",
            "secure by design",
            "security by design",
            "sécurité dès la conception",
            "cybersécurité dès la conception",
            "sicherheit durch technikgestaltung",
            "security-by-default",
            "sécurité par défaut",
            "sicherheit als standardeinstellung",
            "obligations des fabricants en matière de cybersécurité",
            "cybersicherheitspflichten für hersteller",
        ),
        4,
    ),
    TopicRule(
        "CSA／資安認證",
        (
            "cybersecurity act",
            "cyber security act",
            "regulation (eu) 2019/881",
            "règlement sur la cybersécurité",
            "législation sur la cybersécurité",
            "rechtsakt zur cybersicherheit",
            "cybersicherheitsgesetz",
            "cybersecurity certification",
            "certification de cybersécurité",
            "cybersicherheitszertifizierung",
            "eucc",
            "eucs",
            "eccf",
            "european cybersecurity certification scheme",
            "schéma européen de certification de cybersécurité",
            "schéma de certification de cybersécurité",
            "certification de sécurité des tic",
            "europäisches cybersicherheitszertifizierungsschema",
            "europäischer cybersicherheitszertifizierungsrahmen",
            "zertifizierung der cybersicherheit von ikt-produkten",
            "ict cybersecurity certification",
            "ict products services and processes",
        ),
        4,
    ),
    TopicRule(
        "NIS2／組織資安治理",
        (
            "nis2",
            "nis 2",
            "nis-2",
            "directive (eu) 2022/2555",
            "directive sri 2",
            "directive nis 2",
            "directive sur la sécurité des réseaux et des systèmes d'information",
            "transposition de la directive nis 2",
            "transposition de nis 2",
            "nis2umscug",
            "nis-2-umsetzungsgesetz",
            "nis2-umsetzungsgesetz",
            "nis-2-richtlinie",
            "umsetzung der nis-2-richtlinie",
            "nis2-regulierung",
            "nis2-registrierung",
            "nis2-meldepflicht",
            "cybersicherheitsstärkungsgesetz",
            "nis-2-regulierte",
            "référentiel cyber france",
            "recyf",
            "essential entities",
            "important entities",
            "entités essentielles",
            "entités importantes",
            "wesentliche einrichtungen",
            "wichtige einrichtungen",
            "obligations de gestion des risques cyber",
            "mesures de gestion des risques en matière de cybersécurité",
            "mesures de sécurité nis2",
            "registrierungspflichtige einrichtungen",
            "risikomanagementmaßnahmen für cybersicherheit",
        ),
        4,
    ),
    TopicRule(
        "CER／關鍵基礎設施韌性",
        (
            "critical entities resilience",
            "critical entities resilience directive",
            "directive (eu) 2022/2557",
            "directive sur la résilience des entités critiques",
            "directive relative à la résilience des entités critiques",
            "richtlinie über die resilienz kritischer einrichtungen",
            "resilienz kritischer einrichtungen",
            "critical infrastructure",
            "critical infrastructures",
            "infrastructures critiques",
            "entités critiques",
            "kritische infrastrukturen",
            "kritische anlagen",
            "kritische einrichtungen",
            "kritis",
            "cyber resilience",
            "résilience cyber",
            "cyberresilienz",
            "résilience des infrastructures critiques",
            "resilienz kritischer infrastrukturen",
            "évaluation des risques des entités critiques",
            "risikobewertung kritischer einrichtungen",
        ),
        2,
    ),
    TopicRule(
        "漏洞、SBOM與供應鏈",
        (
            "software bill of materials",
            "sbom",
            "vulnerability disclosure",
            "vulnerability",
            "vulnerabilities",
            "coordinated vulnerability disclosure",
            "vulnerability management",
            "vulnerability handling",
            "divulgation coordonnée des vulnérabilités",
            "vulnérabilité",
            "vulnérabilités",
            "divulgation responsable des vulnérabilités",
            "gestion des vulnérabilités",
            "traitement des vulnérabilités",
            "avis de vulnérabilité",
            "schwachstellenmanagement",
            "schwachstelle",
            "schwachstellen",
            "schwachstellenmeldung",
            "koordinierte offenlegung von schwachstellen",
            "schwachstellenbehandlung",
            "sicherheitslücke",
            "supply chain security",
            "sécurité de la chaîne d'approvisionnement",
            "sécurité de la chaîne logistique",
            "lieferkettensicherheit",
            "sicherheit der lieferkette",
            "nomenclature logicielle",
            "nomenclature des composants logiciels",
            "liste des composants logiciels",
            "software-stückliste",
            "softwarestückliste",
            "european vulnerability database",
            "euvd",
            "csaf",
        ),
        2,
    ),
    TopicRule(
        "資安事件、威脅與通報",
        (
            "cyber incident",
            "cyber attack",
            "cyberattack",
            "incident reporting",
            "cyber threat",
            "threat landscape",
            "ransomware",
            "malware",
            "security advisory",
            "alerte de sécurité",
            "bulletin de sécurité",
            "menace cyber",
            "menace informatique",
            "attaque informatique",
            "rançongiciel",
            "logiciel malveillant",
            "signalement d'incident",
            "notification d'incident",
            "incident de cybersécurité",
            "cyberattaque",
            "cyberangriff",
            "sicherheitsvorfall",
            "cyberbedrohung",
            "cyberattacke",
            "schadsoftware",
            "erpressungssoftware",
            "sicherheitswarnung",
            "vorfallmeldung",
            "meldepflicht",
            "bedrohungslage",
        ),
        1,
    ),
    TopicRule(
        "AI治理與模型安全",
        (
            "artificial intelligence",
            "intelligence artificielle",
            "künstliche intelligenz",
            "foundation model",
            "frontier model",
            "generative ai",
            "ai safety",
            "model evaluation",
            "automated decision-making",
            "explainable ai",
            "explainability",
            "algorithmic fairness",
            "model access",
            "compute capacity",
            "automated decision",
            "algorithmic accountability",
            "algorithmic transparency",
            "décision automatisée",
            "responsabilité algorithmique",
            "transparence algorithmique",
            "automatisierte entscheidung",
            "algorithmische rechenschaftspflicht",
            "ai act",
            "artificial intelligence act",
            "règlement sur l'intelligence artificielle",
            "législation sur l'intelligence artificielle",
            "système d'intelligence artificielle",
            "modèle d'intelligence artificielle à usage général",
            "ia générative",
            "sécurité de l'ia",
            "évaluation des modèles",
            "verordnung über künstliche intelligenz",
            "ki-verordnung",
            "ki-system",
            "generative künstliche intelligenz",
            "allzweck-ki-modell",
            "modellsicherheit",
            "algorithmische transparenz",
        ),
        1,
    ),
    TopicRule(
        "資料治理、隱私與數位身分",
        (
            "data protection",
            "gdpr",
            "protection des données",
            "datenschutz",
            "cross-border data",
            "data governance",
            "data sovereignty",
            "open data",
            "data reuse",
            "free flow of data",
            "souveraineté des données",
            "données ouvertes",
            "réutilisation des données",
            "libre circulation des données",
            "datensouveränität",
            "offene daten",
            "weiterverwendung von daten",
            "freier datenverkehr",
            "digital identity",
            "identité numérique",
            "digitale identität",
            "eidas",
            "data breach",
            "violation de données",
            "datenpanne",
            "règlement général sur la protection des données",
            "autorité de protection des données",
            "données à caractère personnel",
            "violation de données à caractère personnel",
            "identité électronique",
            "portefeuille européen d'identité numérique",
            "datenverarbeitung",
            "personenbezogene daten",
            "datenschutzverletzung",
            "elektronische identität",
            "europäische digitale identität",
            "datenraum",
        ),
        1,
    ),
    TopicRule(
        "數位平台與競爭",
        (
            "digital services act",
            "digital markets act",
            "règlement sur les services numériques",
            "règlement sur les marchés numériques",
            "législation sur les services numériques",
            "législation sur les marchés numériques",
            "très grande plateforme en ligne",
            "modération des contenus",
            "online platform",
            "online safety",
            "content moderation",
            "recommender system",
            "recommendation algorithm",
            "platform accountability",
            "competition law",
            "gatekeeper",
            "market power",
            "désinformation",
            "algorithme de recommandation",
            "responsabilité des plateformes",
            "droit de la concurrence",
            "contrôleur d'accès",
            "disinformation",
            "digitale märkte",
            "gesetz über digitale dienste",
            "gesetz über digitale märkte",
            "sehr große online-plattform",
            "inhaltsmoderation",
            "empfehlungssystem",
            "empfehlungsalgorithmus",
            "plattformverantwortung",
            "wettbewerbsrecht",
            "torwächter",
            "online-plattform",
            "platform regulation",
        ),
        1,
    ),
    TopicRule(
        "半導體與量子技術",
        (
            "semiconductor",
            "semi-conducteur",
            "semi-conducteurs",
            "halbleiter",
            "chips act",
            "règlement européen sur les semi-conducteurs",
            "législation européenne sur les semi-conducteurs",
            "eu-chip-gesetz",
            "eu-chips-verordnung",
            "quantum",
            "quantique",
            "technologies quantiques",
            "informatique quantique",
            "ordinateur quantique",
            "quantentechnologie",
            "quantencomputer",
            "post-quantum",
            "post-quantique",
            "post-quanten",
            "cryptographie post-quantique",
            "post-quanten-kryptografie",
        ),
        1,
    ),
    TopicRule(
        "著作權與AI訓練資料",
        (
            "copyright",
            "copyright law",
            "copyright infringement",
            "authors' rights",
            "neighbouring rights",
            "text and data mining",
            "tdm exception",
            "training data licensing",
            "ai training data",
            "droit d'auteur",
            "droits voisins",
            "fouille de textes et de données",
            "données d'entraînement",
            "contenu généré par ia",
            "urheberrecht",
            "leistungsschutzrecht",
            "text- und data-mining",
            "text und data mining",
            "ki-trainingsdaten",
            "trainingsdaten für ki",
            "ki-generierte inhalte",
        ),
        1,
    ),
    TopicRule(
        "媒體多元、資訊操縱與選舉",
        (
            "media plurality",
            "media pluralism",
            "information manipulation",
            "foreign information manipulation",
            "foreign interference",
            "election integrity",
            "electoral interference",
            "recommender system transparency",
            "misinformation",
            "disinformation",
            "pluralisme des médias",
            "pluralisme de l'information",
            "manipulation de l'information",
            "ingérence numérique étrangère",
            "ingérences numériques étrangères",
            "intégrité électorale",
            "désinformation",
            "diversité des médias",
            "medienvielfalt",
            "medienpluralismus",
            "informationsmanipulation",
            "ausländische einflussnahme",
            "wahlbeeinflussung",
            "wahlintegrität",
            "desinformation",
        ),
        1,
    ),
    TopicRule(
        "實體與數位融合安全",
        (
            "physical and cyber security",
            "physical-cyber security",
            "cyber-physical security",
            "hybrid threat",
            "hybrid threats",
            "critical entity protection",
            "protective security",
            "physical resilience",
            "sécurité physique et numérique",
            "sécurité cyber-physique",
            "menace hybride",
            "menaces hybrides",
            "protection des entités critiques",
            "résilience physique",
            "physische und digitale sicherheit",
            "cyber-physische sicherheit",
            "hybride bedrohung",
            "hybride bedrohungen",
            "schutz kritischer einrichtungen",
            "physische resilienz",
        ),
        2,
    ),
)

GUARDED_ACRONYMS = {
    "cra": ("cyber", "security", "digital product", "logiciel", "produit numérique", "software", "hardware"),
    "csa": ("cyber", "security", "certification", "sécurité", "sicherheit", "enisa"),
    "ai": ("model", "algorithm", "artificial", "intelligence", "modèle", "algorith", "künstliche"),
    "ia": ("modèle", "algorith", "intelligence", "générative", "système", "sécurité"),
    "ki": ("modell", "algorithm", "künstliche", "generativ", "system", "sicherheit"),
}


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", value).strip()


def _contains(text: str, keyword: str) -> bool:
    normalized_keyword = normalize_text(keyword)
    if len(normalized_keyword) <= 4 and normalized_keyword.isalnum():
        return bool(re.search(rf"(?<!\w){re.escape(normalized_keyword)}(?!\w)", text))
    return normalized_keyword in text


def classify_article(article: Article) -> Article:
    text = normalize_text(f"{article.title} {article.summary}")
    topics: list[str] = []
    keywords: list[str] = []
    score = 0
    for rule in TOPIC_RULES:
        hits = [keyword for keyword in rule.keywords if _contains(text, keyword)]
        if hits:
            topics.extend(_output_topics(rule.name, hits, text))
            keywords.extend(hits)
            score += rule.weight + min(len(hits) - 1, 2)

    for acronym, contexts in GUARDED_ACRONYMS.items():
        if not _contains(text, acronym) or not any(_contains(text, context) for context in contexts):
            continue
        topic = {
            "cra": "產品資安、漏洞揭露義務、SBOM",
            "csa": "資安產品認證",
            "ai": "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
            "ia": "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
            "ki": "AI法、模型評估、演算法問責、自動化決策、AI與著作權",
        }[acronym]
        if topic not in topics:
            topics.append(topic)
            score += 2 if acronym in {"cra", "csa"} else 1
        keywords.append(acronym.upper())

    article.matched_topics = list(dict.fromkeys(topics))
    article.matched_keywords = list(dict.fromkeys(keywords))
    article.relevance_score = score
    article.confidence_level = confidence_level(score)
    return article


def is_relevant(article: Article) -> bool:
    return article.relevance_score > 0


def confidence_level(score: int) -> str:
    if score >= 4:
        return "高"
    if score >= 2:
        return "中"
    if score == 1:
        return "低"
    return "未命中"


def _output_topics(rule_name: str, hits: list[str], text: str) -> list[str]:
    if rule_name == "CRA／產品資安":
        return ["產品資安、漏洞揭露義務、SBOM"]
    if rule_name == "CSA／資安認證":
        return ["資安產品認證"]
    if rule_name in {"NIS2／組織資安治理", "CER／關鍵基礎設施韌性", "資安事件、威脅與通報"}:
        return ["NIS2、關鍵基礎設施保護"]
    if rule_name == "漏洞、SBOM與供應鏈":
        supply = (
            "supply chain", "chaîne d'approvisionnement", "chaîne logistique", "lieferkette"
        )
        result = ["供應鏈安全"] if any(any(signal in normalize_text(hit) for signal in supply) for hit in hits) else []
        if any(not any(signal in normalize_text(hit) for signal in supply) for hit in hits):
            result.append("產品資安、漏洞揭露義務、SBOM")
        return result
    if rule_name == "AI治理與模型安全":
        return ["AI法、模型評估、演算法問責、自動化決策、AI與著作權"]
    if rule_name == "資料治理、隱私與數位身分":
        result = []
        if _has_any(text, ("identity", "identité", "identität", "eidas", "franceconnect", "wallet", "portefeuille")):
            result.append("數位身份")
        if _has_any(text, ("gdpr", "data protection", "protection des données", "datenschutz", "personal data", "données à caractère personnel", "personenbezogene daten", "data breach", "violation de données", "datenpanne")):
            result.append("隱私框架（含個人資料保護）")
        if _has_any(text, ("cross-border data", "data governance", "data sovereignty", "open data", "data reuse", "datenraum")):
            result.append("跨境資料流通、資料主權、資料開放與再利用")
        return result or ["跨境資料流通、資料主權、資料開放與再利用"]
    if rule_name == "數位平台與競爭":
        result = []
        if _has_any(text, ("digital markets act", "marchés numériques", "digitale märkte", "competition", "concurrence", "wettbewerb", "gatekeeper", "contrôleur d'accès", "torwächter", "market power")):
            result.append("競爭規範面向（平台責任的市場結構面）")
        if _has_any(text, ("digital services act", "services numériques", "digitale dienste", "content moderation", "modération des contenus", "inhaltsmoderation", "online platform", "online safety", "recommender", "recommendation algorithm", "algorithme de recommandation", "empfehlungssystem")):
            result.append("平台責任、內容審查、推薦演算法")
        return result or ["平台責任、內容審查、推薦演算法"]
    if rule_name == "半導體與量子技術":
        result = []
        if _has_any(text, ("semiconductor", "semi-conducteur", "halbleiter", "chips act", "chip-gesetz")):
            result.append("半導體")
        if _has_any(text, ("quantum", "quantique", "quanten")):
            result.append("量子技術")
        return result
    if rule_name == "著作權與AI訓練資料":
        return ["著作權"]
    if rule_name == "媒體多元、資訊操縱與選舉":
        return ["媒體多元與資訊操縱"]
    if rule_name == "實體與數位融合安全":
        return ["關鍵基礎設施的實體與數位融合保護"]
    return []


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(normalize_text(value) in text for value in values)
