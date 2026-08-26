import re
import logging

logger = logging.getLogger("sentiment")

# Try importing HuggingFace transformers
try:
    from transformers import pipeline
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    logger.warning("transformers package not available. Will use VADER fallback.")

# Try importing VADER
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
except ImportError:
    HAS_VADER = False
    logger.warning("vaderSentiment package not available.")

# Load FinBERT or fallback to VADER
sentiment_pipeline = None
vader_analyzer = None

def init_sentiment_engine():
    """Initializes the sentiment models (lazy loading)."""
    global sentiment_pipeline, vader_analyzer
    
    if HAS_TRANSFORMERS and sentiment_pipeline is None:
        try:
            logger.info("Initializing FinBERT sentiment analysis pipeline...")
            # ProsusAI/finbert is a standard CPU-friendly sentiment model
            sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=-1 # force CPU
            )
            logger.info("FinBERT pipeline loaded successfully.")
            return
        except Exception as e:
            logger.error(f"Failed to load FinBERT pipeline: {e}. Falling back to VADER.")
            sentiment_pipeline = None

    if HAS_VADER and vader_analyzer is None:
        try:
            logger.info("Initializing VADER Sentiment Intensity Analyzer...")
            vader_analyzer = SentimentIntensityAnalyzer()
            logger.info("VADER analyzer loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load VADER analyzer: {e}")

# Call init immediately
init_sentiment_engine()

# Default keyword dictionary for popular Indian tickers
TICKER_KEYWORDS = {
    "RELIANCE.NS": ["reliance", "ambani", "jio", "retail"],
    "TCS.NS": ["tcs", "tata consultancy"],
    "INFY.NS": ["infosys", "infy"],
    "HDFCBANK.NS": ["hdfc"],
    "ICICIBANK.NS": ["icici"],
    "BHARTIARTL.NS": ["bharti", "airtel"],
    "SBIN.NS": ["sbi", "state bank", "sbin"],
    "ITC.NS": ["itc"],
    "HINDUNILVR.NS": ["hul", "hindustan unilever", "unilever"],
    "LTIM.NS": ["ltim", "ltimindtree"],
    "^NSEI": ["nifty", "nse", "market-wide", "index", "indian market"],
    "^BSESN": ["sensex", "bse", "market-wide", "index", "indian market"]
}

def clean_text(text):
    """Cleans text for keyword matching."""
    return re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())

def match_ticker_to_headline(ticker, headline):
    """Checks if a headline is relevant to a ticker using keyword matches."""
    cleaned_headline = clean_text(headline)
    
    # Get keywords for ticker
    keywords = TICKER_KEYWORDS.get(ticker, [])
    if not keywords:
        # Dynamic fallback: extract base symbol
        base = ticker.replace(".NS", "").replace(".BO", "").replace("^", "")
        keywords = [base.lower()]
        
    for kw in keywords:
        # Use regex to match word boundaries
        pattern = r'\b' + re.escape(clean_text(kw)) + r'\b'
        if re.search(pattern, cleaned_headline):
            return True
    return False

def score_headline(text):
    """Scores a single headline sentiment.
    
    Returns:
        dict: {label: 'bullish'/'bearish'/'neutral', confidence: float}
    """
    init_sentiment_engine()
    
    # Try FinBERT
    if sentiment_pipeline is not None:
        try:
            result = sentiment_pipeline(text)[0]
            label = result['label'].lower() # positive, negative, neutral
            score = float(result['score'])
            
            # Map labels
            if label == 'positive':
                mapped_label = 'bullish'
            elif label == 'negative':
                mapped_label = 'bearish'
            else:
                mapped_label = 'neutral'
                
            return {"label": mapped_label, "confidence": score}
        except Exception as e:
            logger.warning(f"FinBERT scoring failed: {e}. Falling back to VADER.")
            
    # Try VADER fallback
    if vader_analyzer is not None:
        try:
            scores = vader_analyzer.polarity_scores(text)
            compound = scores['compound']
            
            if compound >= 0.05:
                label = 'bullish'
                confidence = abs(compound)
            elif compound <= -0.05:
                label = 'bearish'
                confidence = abs(compound)
            else:
                label = 'neutral'
                confidence = 1.0 - abs(compound)
                
            return {"label": label, "confidence": confidence}
        except Exception as e:
            logger.error(f"VADER scoring failed: {e}")
            
    # Absolute default fallback
    return {"label": "neutral", "confidence": 0.5}

def generate_inference(headline, sentiment, ticker):
    """Generates a synthesized sentence explaining likely market impact in our own words."""
    cleaned = clean_text(headline)
    ticker_name = ticker.replace(".NS", "").replace("^", "")
    
    # Determine topical keywords
    is_earnings = any(k in cleaned for k in ["profit", "loss", "earnings", "revenue", "quarter", "results", "dividend"])
    is_expansion = any(k in cleaned for k in ["deal", "acquire", "merger", "partnership", "expansion", "launch", "order", "contract"])
    is_regulatory = any(k in cleaned for k in ["probe", "investigation", "fine", "penalty", "sebi", "rbi", "court", "lawsuit"])
    is_macro = any(k in cleaned for k in ["inflation", "rates", "fed", "rbi", "budget", "gdp", "economy"])

    if sentiment == 'bullish':
        if is_earnings:
            return f"Stronger financial performance or positive earnings news is likely to support buying momentum and investor trust in {ticker_name}."
        elif is_expansion:
            return f"New corporate agreements or expansion moves could enhance {ticker_name}'s market positioning and drive short-term upside."
        elif is_macro:
            return f"Favorable macroeconomic conditions or regulatory updates present a supportive backdrop for {ticker_name}'s price action."
        else:
            return f"Positive sentiment surrounding this development is expected to reinforce near-term upward price pressure for {ticker_name}."
            
    elif sentiment == 'bearish':
        if is_earnings:
            return f"Weak earnings details or profit margins may trigger defensive selling and drag on {ticker_name}'s stock valuation."
        elif is_regulatory:
            return f"Regulatory concerns or legal uncertainties are likely to create near-term resistance and downside risk for {ticker_name}."
        elif is_macro:
            return f"Adverse macro pressures or inflation worries could prompt defensive positioning and weigh on {ticker_name}'s performance."
        else:
            return f"Negative developments or rising overheads are likely to damp investor enthusiasm, leading to downward pressure on {ticker_name}."
            
    else: # neutral
        if is_earnings:
            return f"Mixed financial results are likely to keep {ticker_name} consolidating within a range as investors assess the full numbers."
        elif is_regulatory:
            return f"Minor regulatory announcements are expected to have a muted impact, with {ticker_name} remaining in steady sideways trading."
        else:
            return f"Balanced market commentary indicates stable fundamentals, pointing to standard rangebound trading for {ticker_name}."

def analyze_headlines_sentiment(headlines, watchlist):
    """Processes headlines, maps them to tickers, scores, and aggregates sentiment.
    
    Returns:
        tuple: (ticker_sentiment_dict, mapped_news_dict)
        - ticker_sentiment_dict: {ticker: {label, confidence}}
        - mapped_news_dict: {ticker: [{title, url, inference, sentiment, confidence}]}
    """
    tickers = ["^NSEI", "^BSESN"] + watchlist
    ticker_sentiment = {}
    mapped_news = {ticker: [] for ticker in tickers}
    
    # Store individual headline scores to avoid double computing
    scored_headlines = []
    for h in headlines:
        score = score_headline(h['title'])
        scored_headlines.append({
            "title": h['title'],
            "url": h['url'],
            "source": h['source'],
            "label": score['label'],
            "confidence": score['confidence']
        })
        
    for ticker in tickers:
        ticker_news = []
        # Find headlines matching this ticker
        for sh in scored_headlines:
            # For market indices, match index keywords or macro news
            is_match = match_ticker_to_headline(ticker, sh['title'])
            # Alternatively, if ticker is Nifty or Sensex and headline contains general market keywords, match it
            if not is_match and ticker in ["^NSEI", "^BSESN"]:
                if any(k in clean_text(sh['title']) for k in ["market", "stock", "shares", "investor", "trade"]):
                    is_match = True
                    
            if is_match:
                inference = generate_inference(sh['title'], sh['label'], ticker)
                ticker_news.append({
                    "title": sh['title'],
                    "url": sh['url'],
                    "source": sh['source'],
                    "sentiment": sh['label'],
                    "confidence": sh['confidence'],
                    "inference": inference
                })
        
        mapped_news[ticker] = ticker_news
        
        # Aggregate sentiment
        if ticker_news:
            # Map sentiment to numeric score
            sentiment_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
            scores = [sentiment_map[tn['sentiment']] * tn['confidence'] for tn in ticker_news]
            avg_score = sum(scores) / len(scores)
            
            # Aggregate label
            if avg_score >= 0.15:
                agg_label = "bullish"
            elif avg_score <= -0.15:
                agg_label = "bearish"
            else:
                agg_label = "neutral"
                
            # Average confidence of matched news
            agg_conf = sum(tn['confidence'] for tn in ticker_news) / len(ticker_news)
            
            ticker_sentiment[ticker] = {
                "label": agg_label,
                "confidence": round(agg_conf, 2)
            }
        else:
            # Default fallback when no news is matched
            ticker_sentiment[ticker] = {
                "label": "neutral",
                "confidence": 0.0
            }
            
    return ticker_sentiment, mapped_news
