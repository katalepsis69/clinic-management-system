# app/sentiment.py
import re

_POSITIVE = {
    "attentive", "kind", "knowledgeable", "excellent", "great", "friendly",
    "wonderful", "good", "best", "helpful", "clean", "care", "caring",
    "phenomenal", "super", "efficient", "amazing", "love", "fast", "happy", "fine",
}
_NEGATIVE = {
    "terrible", "rude", "dismissive", "horrible", "painful", "dreadful",
    "worst", "bad", "slow", "poor", "awful", "unpleasant", "dirty",
}


def analyze_sentiment(text: str, rating: int) -> dict:
    words = set(re.findall(r"\b\w+\b", text.lower()))
    pos = sum(1 for w in words if w in _POSITIVE)
    neg = sum(1 for w in words if w in _NEGATIVE)

    if pos > 0 and neg == 0:
        score = min(0.9, 0.4 + 0.15 * pos)
        label = "positive"
    elif neg > 0 and pos == 0:
        score = max(-0.9, -0.25 - 0.15 * neg)
        label = "negative"
    elif pos > neg:
        score = 0.3
        label = "positive"
    elif neg > pos:
        score = -0.3
        label = "negative"
    elif rating >= 4 and neg == 0:
        score = 0.5 if rating == 5 else 0.3
        label = "positive"
    elif rating <= 2 and pos == 0:
        score = -0.5 if rating == 1 else -0.3
        label = "negative"
    else:
        score = 0.0
        label = "neutral"

    flagged_critical = (score < -0.3) or (rating <= 2)

    return {
        "sentiment_label": label,
        "sentiment_score": round(score, 4),
        "flagged_critical": flagged_critical,
    }

