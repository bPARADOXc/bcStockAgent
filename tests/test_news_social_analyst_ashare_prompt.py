import pytest

from tradingagents.agents.analysts.news_analyst import _build_news_system_message
from tradingagents.agents.analysts.social_media_analyst import _build_social_system_message


@pytest.mark.unit
def test_news_prompt_contains_ashare_regulatory_terms_and_schema_keys():
    msg = _build_news_system_message("", market_label="A股")

    # NOTE: lock A-share-specific regulation/policy vocabulary.
    assert "证监会" in msg
    assert "问询函" in msg
    assert "产业政策" in msg

    # NOTE: lock required JSON fields for downstream parser alignment.
    for key in (
        '"company_news"',
        '"macro_policy_news"',
        '"regulatory_news"',
        '"sentiment_score"',
        '"event_importance"',
        '"risk_flags"',
        '"evidence"',
    ):
        assert key in msg


@pytest.mark.unit
def test_social_prompt_contains_ashare_sentiment_sources_and_schema_keys():
    msg = _build_social_system_message("", market_label="A股")

    # NOTE: lock A-share social-source hints.
    assert "股吧" in msg
    assert "雪球" in msg
    assert "互动易" in msg

    # NOTE: lock required JSON fields for downstream parser alignment.
    for key in (
        '"sentiment_score"',
        '"attention_score"',
        '"main_topics"',
        '"rumor_risk"',
        '"evidence"',
    ):
        assert key in msg
