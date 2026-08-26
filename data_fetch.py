import os
import json
import time
import logging
import shutil
import requests
import feedparser
import pandas as pd
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("data_fetch")

def setup_ssl_certificates():
    """Copies certifi's cacert.pem to a safe emoji-free path and sets env variables.
    
    This avoids Windows cp1252 path encoding issues when the workspace path contains emojis.
    """
    try:
        import certifi
        orig_path = certifi.where()
        home_dir = os.path.expanduser("~")
        safe_cert_dir = os.path.join(home_dir, ".market_pulse")
        os.makedirs(safe_cert_dir, exist_ok=True)
        safe_cert_path = os.path.join(safe_cert_dir, "cacert.pem")
        
        # Copy file if it doesn't exist or size is different
        if not os.path.exists(safe_cert_path) or os.path.getsize(safe_cert_path) != os.path.getsize(orig_path):
            shutil.copy(orig_path, safe_cert_path)
            
        os.environ["REQUESTS_CA_BUNDLE"] = safe_cert_path
        os.environ["SSL_CERT_FILE"] = safe_cert_path
        logger.info(f"SSL certificate redirected to safe path: {safe_cert_path}")
    except Exception as e:
        logger.warning(f"Failed to setup SSL certificate redirect: {e}")

# Run SSL setup immediately
setup_ssl_certificates()

def load_watchlist(watchlist_path="watchlist.json"):
    """Loads watchlist from JSON file."""
    if not os.path.exists(watchlist_path):
        # Return default if not found
        default_watchlist = [
            "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", 
            "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "ITC.NS", 
            "HINDUNILVR.NS", "LTIM.NS"
        ]
        logger.warning(f"Watchlist file not found at {watchlist_path}. Using default tickers.")
        return default_watchlist
    try:
        with open(watchlist_path, "r") as f:
            watchlist = json.load(f)
            if isinstance(watchlist, list):
                return watchlist
            else:
                logger.error(f"Invalid format in {watchlist_path}. Expected a list.")
                return []
    except Exception as e:
        logger.error(f"Error reading watchlist: {e}")
        return []

def fetch_ticker_ohlcv(ticker, period="60d"):
    """Fetches historical daily OHLCV data for a ticker with 1 retry on failure."""
    for attempt in range(2):
        try:
            logger.info(f"Fetching OHLCV for {ticker} (attempt {attempt+1})")
            # Fetch daily data
            df = yf.download(ticker, period=period, progress=False)
            if not df.empty:
                # Clean MultiIndex columns
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                # Standardize capitalization of columns (Open, High, Low, Close, Volume)
                df.columns = [str(col).capitalize() for col in df.columns]
                return df
            else:
                logger.warning(f"Empty data returned for {ticker}")
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed to fetch OHLCV for {ticker}: {e}")
            if attempt == 0:
                time.sleep(1) # Wait before retry
    logger.error(f"Failed to fetch OHLCV for {ticker} after 2 attempts. Skipping.")
    return pd.DataFrame()

def fetch_all_ohlcv(watchlist, period="60d"):
    """Fetches historical daily OHLCV data for Nifty, Sensex, and all watchlist tickers."""
    tickers = ["^NSEI", "^BSESN"] + watchlist
    data = {}
    for ticker in tickers:
        df = fetch_ticker_ohlcv(ticker, period)
        if not df.empty:
            data[ticker] = df
    return data

def fetch_rss_feed_with_retry(feed_url, source_name):
    """Fetches headlines from an RSS feed with 1 retry on failure."""
    for attempt in range(2):
        try:
            logger.info(f"Fetching RSS feed for {source_name} (attempt {attempt+1})")
            # Using requests first to fetch content (helps set timeouts and user agent)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            }
            response = requests.get(feed_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Parse the content with feedparser
            feed = feedparser.parse(response.content)
            if feed.entries:
                return feed.entries
            else:
                # Fallback directly to feedparser parsing URL
                feed = feedparser.parse(feed_url)
                if feed.entries:
                    return feed.entries
                logger.warning(f"No entries found in feed for {source_name}")
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {source_name}: {e}")
            if attempt == 0:
                time.sleep(1) # Wait before retry
    logger.error(f"Failed to fetch RSS feed {source_name} after 2 attempts. Skipping source.")
    return []

def fetch_all_headlines():
    """Pulls and dedupes latest 20 headlines each from MC, ET, and LiveMint RSS feeds."""
    feeds = {
        "Moneycontrol": "http://www.moneycontrol.com/rss/latestnews.xml",
        "Economic Times": "https://economictimes.indiatimes.com/markets/rssfeeds/2146842.cms",
        "LiveMint": "https://www.livemint.com/rss/markets"
    }
    
    all_headlines = []
    seen_urls = set()
    
    for source, url in feeds.items():
        entries = fetch_rss_feed_with_retry(url, source)
        # Limit to top 20 from each feed
        count = 0
        for entry in entries:
            if count >= 20:
                break
            
            # Extract title and link
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            published = entry.get("published", "").strip()
            
            if not title or not link:
                continue
                
            # Deduplicate by URL
            if link not in seen_urls:
                seen_urls.add(link)
                all_headlines.append({
                    "title": title,
                    "url": link,
                    "source": source,
                    "published": published
                })
                count += 1
                
    logger.info(f"Fetched and deduplicated a total of {len(all_headlines)} headlines.")
    return all_headlines

if __name__ == "__main__":
    # Quick test
    wl = load_watchlist()
    print("Watchlist:", wl)
    print("Fetching historical data...")
    ohlcv = fetch_all_ohlcv(wl[:2], period="5d")
    for t, df in ohlcv.items():
        print(f"{t}: {df.shape[0]} rows fetched")
    print("Fetching news...")
    news = fetch_all_headlines()
    print(f"Fetched {len(news)} unique headlines.")
    if news:
        print("Sample:", news[0])
