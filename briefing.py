import logging
from datetime import datetime
from feedback import get_signal_weight, get_yesterday_accuracy_summary

logger = logging.getLogger("briefing")

def map_rsi_direction(rsi_val):
    """Maps RSI value to direction and confidence."""
    if rsi_val < 30:
        return "bullish", (30 - rsi_val) / 30
    elif rsi_val > 70:
        return "bearish", (rsi_val - 70) / 30
    else:
        return "neutral", 0.0

def map_bb_direction(bb_pos):
    """Maps Bollinger Band position to direction."""
    if bb_pos == "below_lower":
        return "bullish", 0.8
    elif bb_pos == "above_upper":
        return "bearish", 0.8
    else:
        return "neutral", 0.0

def map_pattern_direction(pattern):
    """Maps chart patterns to direction."""
    bullish_patterns = ["breakout_resistance", "double_bottom", "ascending_triangle"]
    bearish_patterns = ["breakdown_support", "double_top", "head_and_shoulders", "descending_triangle"]
    
    if pattern in bullish_patterns:
        return "bullish"
    elif pattern in bearish_patterns:
        return "bearish"
    else:
        return "neutral"

def compile_briefing_payload(analysis_results, sentiment_results, news_results, ohlcv_data, mode="morning"):
    """Combines analysis + sentiment + feedback-weighted scores into the JSON briefing.
    
    analysis_results: dict {ticker: analysis_payload}
    sentiment_results: dict {ticker: sentiment_payload}
    news_results: dict {ticker: [news_items]}
    ohlcv_data: dict {ticker: DataFrame}
    mode: "morning" or "evening"
    """
    logger.info(f"Compiling briefing payload for mode: {mode}")
    
    watchlist_briefings = []
    
    # We want to process all tickers except indices for the watchlist part,
    # but include index summaries for the market-wide part.
    indices = ["^NSEI", "^BSESN"]
    watchlist_tickers = [t for t in analysis_results.keys() if t not in indices]
    
    for ticker in watchlist_tickers:
        an = analysis_results.get(ticker, {})
        se = sentiment_results.get(ticker, {})
        ticker_news = news_results.get(ticker, [])
        
        if not an:
            continue
            
        signals = an.get("signals", {})
        
        # We will collect all active signal inputs, convert them to direction (-1, 0, +1),
        # apply feedback weights, and combine them.
        weighted_scores = []
        weight_sum = 0.0
        active_signals_descriptions = []
        
        direction_val = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
        
        # 1. RSI Signal
        rsi_dir, rsi_conf = map_rsi_direction(signals.get("rsi", 50))
        rsi_weight = get_signal_weight("rsi")
        weighted_scores.append(direction_val[rsi_dir] * rsi_conf * rsi_weight)
        weight_sum += rsi_weight
        if rsi_dir != "neutral":
            active_signals_descriptions.append(f"RSI is {rsi_dir} ({signals['rsi']:.1f})")
            
        # 2. MACD Crossover Signal
        macd_cross = signals.get("macd_cross", "none")
        macd_dir = "neutral"
        if macd_cross == "bullish_cross":
            macd_dir = "bullish"
        elif macd_cross == "bearish_cross":
            macd_dir = "bearish"
        macd_weight = get_signal_weight("macd_cross")
        weighted_scores.append(direction_val[macd_dir] * 0.8 * macd_weight)
        weight_sum += macd_weight
        if macd_dir != "neutral":
            active_signals_descriptions.append(f"MACD {macd_cross.replace('_', ' ')}")

        # 3. SMA Crossover Signal
        sma_cross = signals.get("sma_cross", "none")
        sma_dir = "neutral"
        if sma_cross == "golden_cross":
            sma_dir = "bullish"
        elif sma_cross == "death_cross":
            sma_dir = "bearish"
        sma_weight = get_signal_weight("sma_cross")
        weighted_scores.append(direction_val[sma_dir] * 0.9 * sma_weight)
        weight_sum += sma_weight
        if sma_dir != "neutral":
            active_signals_descriptions.append(f"SMA {sma_cross.replace('_', ' ')}")

        # 4. Bollinger Bands Position
        bb_pos = signals.get("bb_position", "middle")
        bb_dir, bb_conf = map_bb_direction(bb_pos)
        bb_weight = get_signal_weight("bb_position")
        weighted_scores.append(direction_val[bb_dir] * bb_conf * bb_weight)
        weight_sum += bb_weight
        if bb_dir != "neutral":
            active_signals_descriptions.append(f"Price is {bb_pos.replace('_', ' ')} Bollinger Bands")

        # 5. Chart Pattern Signal
        pattern = signals.get("pattern", "none")
        pattern_dir = "neutral"
        pattern_conf = signals.get("pattern_confidence", 0.0)
        if pattern != "none":
            pattern_dir = map_pattern_direction(pattern)
            pattern_weight = get_signal_weight("chart_pattern")
            weighted_scores.append(direction_val[pattern_dir] * pattern_conf * pattern_weight)
            weight_sum += pattern_weight
            active_signals_descriptions.append(f"Chart Pattern: {pattern.replace('_', ' ')}")
            
        # 6. News Sentiment Signal
        news_dir = se.get("label", "neutral")
        news_conf = se.get("confidence", 0.0)
        news_weight = get_signal_weight("news_sentiment")
        weighted_scores.append(direction_val[news_dir] * news_conf * news_weight)
        weight_sum += news_weight
        if news_dir != "neutral" and news_conf > 0:
            active_signals_descriptions.append(f"News Sentiment is {news_dir} (conf: {news_conf:.2f})")
            
        # 7. Volume Anomaly
        if signals.get("volume_anomaly", False):
            active_signals_descriptions.append("High trading volume anomaly detected (>2x avg)")

        # Calculate final combined score
        if weight_sum > 0:
            combined_score = sum(weighted_scores) / weight_sum
        else:
            combined_score = 0.0
            
        # Classify final combined sentiment
        # Threshold: 0.15 for direction
        if combined_score >= 0.15:
            final_sentiment = "bullish"
            final_conf = min(1.0, combined_score * 1.5)
        elif combined_score <= -0.15:
            final_sentiment = "bearish"
            final_conf = min(1.0, abs(combined_score) * 1.5)
        else:
            final_sentiment = "neutral"
            final_conf = 1.0 - abs(combined_score)
            
        # Round confidence
        final_conf = round(final_conf, 2)
        
        # Sort news by confidence and select top 3
        sorted_news = sorted(ticker_news, key=lambda x: x['confidence'], reverse=True)[:3]
        top_news = []
        for n in sorted_news:
            top_news.append({
                "title": n["title"],
                "url": n["url"],
                "inference": n["inference"]
            })
            
        # Fetch last 30 days of closes for charting
        df_ticker = ohlcv_data.get(ticker)
        history_closes = []
        if df_ticker is not None and not df_ticker.empty:
            history_closes = [
                {"date": str(date)[:10], "close": round(float(row["Close"]), 2)}
                for date, row in df_ticker.iloc[-30:].iterrows()
            ]
            
        watchlist_briefings.append({
            "ticker": ticker,
            "sentiment": final_sentiment,
            "confidence": final_conf,
            "top_signals": active_signals_descriptions[:3] if active_signals_descriptions else ["No significant technical or sentiment signals."],
            "news": top_news,
            "history": history_closes,
            "pattern_dates": signals.get("pattern_dates", [])
        })

    # Compile market-wide sentiment
    # We aggregate from the indices ^NSEI and ^BSESN
    market_sent_list = []
    for idx in indices:
        if idx in sentiment_results:
            market_sent_list.append(sentiment_results[idx])
            
    # Default fallback
    market_sentiment_label = "neutral"
    market_sentiment_conf = 0.5
    
    if market_sent_list:
        scores = []
        for ms in market_sent_list:
            lbl = ms.get("label", "neutral")
            conf = ms.get("confidence", 0.0)
            if lbl == "bullish":
                scores.append(conf)
            elif lbl == "bearish":
                scores.append(-conf)
            else:
                scores.append(0.0)
        avg_score = sum(scores) / len(scores)
        
        if avg_score >= 0.15:
            market_sentiment_label = "bullish"
            market_sentiment_conf = round(avg_score, 2)
        elif avg_score <= -0.15:
            market_sentiment_label = "bearish"
            market_sentiment_conf = round(abs(avg_score), 2)
        else:
            market_sentiment_label = "neutral"
            market_sentiment_conf = round(1.0 - abs(avg_score), 2)

    # Core morning payload
    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "market_wide_sentiment": {
            "label": market_sentiment_label,
            "confidence": market_sentiment_conf
        },
        "watchlist": watchlist_briefings
    }
    
    # Evening extensions
    if mode == "evening":
        # Calculate daily gainers/losers from watchlist
        perf_list = []
        for ticker in watchlist_tickers:
            if ticker in ohlcv_data and not ohlcv_data[ticker].empty:
                df = ohlcv_data[ticker]
                if len(df) >= 2:
                    close_latest = float(df['Close'].iloc[-1])
                    close_prior = float(df['Close'].iloc[-2])
                    pct_change = (close_latest - close_prior) / close_prior
                    perf_list.append((ticker, pct_change))
                    
        # Sort to get top 5 gainers & losers
        perf_list.sort(key=lambda x: x[1], reverse=True)
        top_gainers = [{"ticker": t, "change": f"{c:+.2%}"} for t, c in perf_list[:5]]
        
        perf_list.sort(key=lambda x: x[1], reverse=False)
        top_losers = [{"ticker": t, "change": f"{c:+.2%}"} for t, c in perf_list[:5]]
        
        payload["top_gainers"] = top_gainers
        payload["top_losers"] = top_losers
        
        # Yesterday's morning call accuracy summary
        payload["accuracy_note"] = get_yesterday_accuracy_summary()
        
    return payload
