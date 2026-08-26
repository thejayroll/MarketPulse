import os
import json
import argparse
import logging
from datetime import datetime

import data_fetch
import analysis
import sentiment
import feedback
import briefing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main")

def run_pipeline(mode):
    logger.info(f"Starting market-pulse pipeline in '{mode}' mode.")
    
    # 1. Initialize SQLite Database
    logger.info("Initializing database...")
    feedback.init_db()
    
    # 2. Load watchlist
    watchlist_path = "watchlist.json"
    logger.info(f"Loading watchlist from {watchlist_path}...")
    watchlist = data_fetch.load_watchlist(watchlist_path)
    if not watchlist:
        logger.error("Empty watchlist. Cannot proceed.")
        return
    logger.info(f"Loaded {len(watchlist)} watchlist tickers.")

    # 3. Fetch daily OHLCV and news
    logger.info("Fetching daily OHLCV data (last 60 days)...")
    ohlcv_data = data_fetch.fetch_all_ohlcv(watchlist, period="60d")
    
    logger.info("Fetching news headlines from RSS feeds...")
    headlines = data_fetch.fetch_all_headlines()

    # 4. Update pending predictions from prior trading days
    logger.info("Evaluating prior pending predictions...")
    feedback.update_pending_predictions(ohlcv_data)

    # 5. Run technical and chart pattern analysis
    logger.info("Running technical indicators and chart pattern analysis...")
    analysis_results = {}
    for ticker, df in ohlcv_data.items():
        try:
            analysis_results[ticker] = analysis.analyze_ticker(df, ticker)
        except Exception as e:
            logger.error(f"Error analyzing ticker {ticker}: {e}")

    # 6. Score news headlines and map to tickers
    logger.info("Scoring headline sentiments and mapping to tickers...")
    try:
        sentiment_results, news_results = sentiment.analyze_headlines_sentiment(headlines, watchlist)
    except Exception as e:
        logger.error(f"Error scoring news sentiment: {e}")
        sentiment_results = {}
        news_results = {}

    # 7. Compile the briefing payload
    logger.info("Compiling briefing payload...")
    try:
        payload = briefing.compile_briefing_payload(
            analysis_results, 
            sentiment_results, 
            news_results, 
            ohlcv_data, 
            mode=mode
        )
    except Exception as e:
        logger.error(f"Error compiling briefing: {e}")
        return

    # 8. Write the briefing JSON file
    output_dir = "data"
    os.makedirs(output_dir, exist_ok=True)
    output_filename = f"latest_{mode}.json"
    output_path = os.path.join(output_dir, output_filename)
    
    try:
        with open(output_path, "w") as f:
            json.dump(payload, f, indent=2)
        logger.info(f"Briefing payload successfully written to {output_path}")
    except Exception as e:
        logger.error(f"Failed to write briefing payload: {e}")

    # 9. Log new predictions generated in this run to SQLite for the next evaluation
    logger.info("Logging new predictions to SQLite database...")
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # We log predictions for watchlist tickers only (not indices, unless wanted, but indices are good too)
    for item in payload.get("watchlist", []):
        ticker = item["ticker"]
        final_sentiment = item["sentiment"]
        final_conf = item["confidence"]
        
        # Get the closing price of the latest candle to record as price_at_prediction
        price_at_pred = None
        if ticker in ohlcv_data and not ohlcv_data[ticker].empty:
            price_at_pred = float(ohlcv_data[ticker]['Close'].iloc[-1])
            
        # A. Log overall sentiment prediction
        feedback.log_prediction(
            ticker=ticker,
            signal_type="overall_sentiment",
            direction=final_sentiment,
            confidence=final_conf,
            timestamp=timestamp_str,
            price_at_prediction=price_at_pred
        )
        
        # B. Log individual component signals (only if they are non-neutral, so we can track their accuracy)
        an = analysis_results.get(ticker, {})
        signals = an.get("signals", {})
        
        # 1. RSI Signal
        rsi_dir, rsi_conf = briefing.map_rsi_direction(signals.get("rsi", 50))
        if rsi_dir != "neutral":
            feedback.log_prediction(ticker, "rsi", rsi_dir, rsi_conf, timestamp_str, price_at_pred)
            
        # 2. MACD Crossover Signal
        macd_cross = signals.get("macd_cross", "none")
        if macd_cross != "none":
            macd_dir = "bullish" if macd_cross == "bullish_cross" else "bearish"
            feedback.log_prediction(ticker, "macd_cross", macd_dir, 0.8, timestamp_str, price_at_pred)
            
        # 3. SMA Crossover Signal
        sma_cross = signals.get("sma_cross", "none")
        if sma_cross != "none":
            sma_dir = "bullish" if sma_cross == "golden_cross" else "bearish"
            feedback.log_prediction(ticker, "sma_cross", sma_dir, 0.9, timestamp_str, price_at_pred)

        # 4. Bollinger Bands Position
        bb_pos = signals.get("bb_position", "middle")
        bb_dir, bb_conf = briefing.map_bb_direction(bb_pos)
        if bb_dir != "neutral":
            feedback.log_prediction(ticker, "bb_position", bb_dir, bb_conf, timestamp_str, price_at_pred)

        # 5. Chart Pattern Signal
        pattern = signals.get("pattern", "none")
        if pattern != "none":
            pattern_dir = briefing.map_pattern_direction(pattern)
            pattern_conf = signals.get("pattern_confidence", 0.0)
            if pattern_dir != "neutral":
                feedback.log_prediction(ticker, "chart_pattern", pattern_dir, pattern_conf, timestamp_str, price_at_pred)

        # 6. News Sentiment Signal
        se = sentiment_results.get(ticker, {})
        news_dir = se.get("label", "neutral")
        news_conf = se.get("confidence", 0.0)
        if news_dir != "neutral" and news_conf > 0:
            feedback.log_prediction(ticker, "news_sentiment", news_dir, news_conf, timestamp_str, price_at_pred)

    logger.info("Pipeline run finished successfully.")

def main():
    parser = argparse.ArgumentParser(description="Market Pulse CLI Engine")
    parser.add_argument(
        "--mode",
        choices=["morning", "evening"],
        required=True,
        help="Specify the pipeline mode: morning briefing or evening wrap-up"
    )
    args = parser.parse_args()
    
    try:
        run_pipeline(args.mode)
    except Exception as e:
        logger.fatal(f"Unhandled exception in pipeline execution: {e}", exc_info=True)
        # We catch the exception and exit cleanly with code 0 as requested,
        # so scheduled actions don't crash or trigger build failure notifications
        # unless it is a severe system-level issue.
        os._exit(0)

if __name__ == "__main__":
    main()
