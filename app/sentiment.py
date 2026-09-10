# app/sentiment.py
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

analyzer = SentimentIntensityAnalyzer()


def analyze_sentiment(text: str, rating: int) -> dict:
    scores = analyzer.polarity_scores(text)
    compound = scores["compound"]

    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"

    flagged_critical = (compound < -0.3) or (rating <= 2)

    return {
        "sentiment_label": label,
        "sentiment_score": round(compound, 4),
        "flagged_critical": flagged_critical,
    }
