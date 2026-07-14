from __future__ import annotations

from .models import Article, Source


def annotate_authority(article: Article, source: Source) -> Article:
    kind = source.institution_type
    if any(value in kind for value in ("立法", "議會")):
        article.authority_level = "立法機關"
    elif any(value in kind for value in ("監理", "主管機關", "政策主管", "行政機關", "中央政策")):
        article.authority_level = "主管／監理機關"
    elif any(value in kind for value in ("法定", "聯合事業", "行政法人")):
        article.authority_level = "法定機構／行政法人"
    elif any(value in kind for value in ("公私協力", "產學", "產業群聚")):
        article.authority_level = "公私協力／產學平台"
    elif "智庫" in kind:
        article.authority_level = "政策智庫"
    else:
        article.authority_level = "研究／支援機構"
    article.content_kind = classify_content_kind(f"{article.title} {article.summary}")
    return article


def classify_content_kind(value: str) -> str:
    text = value.casefold()
    groups = (
        ("執法／裁罰", ("fine", "penalty", "sanction", "enforcement", "amende", "sanction", "bußgeld")),
        ("法規／指引", ("regulation", "directive", "law", "guideline", "règlement", "directive", "loi", "leitlinie", "gesetz")),
        ("公開諮詢", ("consultation", "call for evidence", "consultation publique", "konsultation")),
        ("研究／評估", ("study", "report", "research", "evaluation", "étude", "rapport", "forschung", "studie")),
        ("資安公告", ("advisory", "vulnerability", "incident", "alerte", "vulnérabilité", "schwachstelle", "warnung")),
    )
    for label, keywords in groups:
        if any(keyword in text for keyword in keywords):
            return label
    return "政策／一般新聞"
