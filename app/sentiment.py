# app/sentiment.py
import json
import os
import re
from typing import Dict, Any, Optional

# Embedded default fallback sets
_DEFAULT_POSITIVE = {
    # English terms
    "attentive", "kind", "knowledgeable", "excellent", "great", "friendly",
    "wonderful", "good", "best", "helpful", "clean", "care", "caring",
    "phenomenal", "super", "efficient", "amazing", "love", "fast", "happy", "fine",
    "gentle", "polite", "respectful", "courteous", "skilled", "competent", "expert",
    "effective", "safe", "smooth", "comfortable", "spacious", "spotless", "honest",
    "fair", "affordable", "worth", "grateful", "satisfied", "relieved",
    # Filipino / Tagalog terms
    "mabait", "napakabait", "bait", "malumanay", "mapagkalinga",
    "maasikaso", "napakaasikaso", "asikaso",
    "magalang", "napakagalang", "galang",
    "palakaibigan", "magiliw",
    "maalaga", "alaga",
    "magaling", "napakagaling", "galing", "mahusay", "napakahusay",
    "bihasa", "marunong", "eksperto",
    "mabisa", "nakagaling", "nakatulong",
    "ligtas", "panatag", "tiwala",
    "mabilis", "napakabilis", "bilis", "maagap",
    "maayos", "napakaayos", "ayos", "pulido", "swabe",
    "malinis", "napakalinis", "linis",
    "komportable", "maaliwalas", "presko", "maluwag", "tahimik",
    "abot-kaya", "sulit", "napakasulit", "tapat", "makatwiran",
    "masaya", "natutuwa", "salamat", "kuntento", "ginhawa",
}

_DEFAULT_NEGATIVE = {
    # English terms
    "terrible", "rude", "dismissive", "horrible", "painful", "dreadful",
    "worst", "bad", "slow", "poor", "awful", "unpleasant", "dirty",
    "hostile", "arrogant", "disrespectful", "impatient", "harsh", "snobbish",
    "incompetent", "careless", "negligent", "delayed", "sluggish", "chaotic",
    "disorganized", "filthy", "stinking", "crowded", "cramped", "noisy",
    "overpriced", "scam", "disappointed", "frustrated", "angry", "annoyed", "stressful",
    # Filipino / Tagalog terms
    "masungit", "napakasungit", "sungit", "mataray", "suplada", "suplado",
    "bastos", "napakabastos", "walang-galang",
    "mayabang", "mapagmataas", "snob", "isnabero", "isnabera", "dedma",
    "pabaya", "tamad",
    "palpak", "napakapalpak", "bano",
    "masakit", "napakasakit", "sakit", "kirot", "mahapdi",
    "mabagal", "napakabagal", "bagal", "makupad",
    "matagal", "napakatagal", "tagal", "naantala", "antala",
    "magulo", "napakagulo", "gulo", "watak-watak",
    "marumi", "madumi", "napakarumi", "dumi", "burara",
    "mabaho", "baho", "kulob",
    "masikip", "sikip", "siksikan", "mainit", "maingay",
    "mahal", "napakamahal", "taga", "ginto",
    "panloloko", "mandaraya",
    "dismayado", "nakakainis", "inis", "nakakastress", "bwisit", "asar",
    "galit", "sayang", "bulok", "pangit",
}

_POSITIVE = set(_DEFAULT_POSITIVE)
_NEGATIVE = set(_DEFAULT_NEGATIVE)
_CROSS_REFERENCE: Dict[str, Dict[str, Any]] = {}

# Load exhaustive external lexicon if present
_LEXICON_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "sentiment_lexicon.json")
try:
    if os.path.exists(_LEXICON_FILE):
        with open(_LEXICON_FILE, "r", encoding="utf-8") as _f:
            _lexicon_data = json.load(_f)
            if "positive_words" in _lexicon_data:
                _POSITIVE.update(_lexicon_data["positive_words"])
            if "negative_words" in _lexicon_data:
                _NEGATIVE.update(_lexicon_data["negative_words"])
            if "cross_reference_mappings" in _lexicon_data:
                _CROSS_REFERENCE = _lexicon_data["cross_reference_mappings"]
except Exception:
    pass


def get_cross_reference(word: str) -> Optional[Dict[str, Any]]:
    """Lookup English VADER lemma and valence alignment for a Tagalog/Filipino clinical word."""
    return _CROSS_REFERENCE.get(word.lower())


def analyze_sentiment(text: str, rating: int) -> dict:
    """Analyze sentiment of clinical feedback across English, Filipino (Tagalog), and Taglish."""
    raw_tokens = re.findall(r"\b[\w\-]+\b", text.lower())
    words = set(raw_tokens)

    # Calculate matches with support for Filipino intensifiers ('napaka-')
    pos = 0
    neg = 0
    for w in words:
        if w in _POSITIVE:
            pos += 1
        elif w.startswith("napaka") and len(w) > 6 and (w[6:] in _POSITIVE or ("ma" + w[6:]) in _POSITIVE):
            pos += 1

        if w in _NEGATIVE:
            neg += 1
        elif w.startswith("napaka") and len(w) > 6 and (w[6:] in _NEGATIVE or ("ma" + w[6:]) in _NEGATIVE):
            neg += 1

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
