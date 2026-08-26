import logging
import pandas as pd
import numpy as np
import pandas_ta as ta

logger = logging.getLogger("analysis")

def get_indicators(df):
    """Computes technical indicators for a given dataframe with pandas-ta and fallback.
    
    Returns:
        DataFrame: DF with indicators appended.
    """
    df = df.copy()
    if len(df) < 50:
        logger.warning("Dataframe too short to compute indicators (< 50 rows)")
        return df

    # Make sure we are working with 1D series of close, volume, etc.
    # Sometimes yfinance downloads have MultiIndex columns. Clean them.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Convert columns to float just in case
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = df[col].astype(float)

    close_series = df['Close']
    volume_series = df['Volume']

    # 1. RSI (14)
    try:
        rsi = ta.rsi(close_series, length=14)
        df['RSI'] = rsi
    except Exception as e:
        logger.warning(f"pandas-ta RSI failed: {e}. Calculating manually.")
        # Manual fallback
        delta = close_series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ema_gain = gain.ewm(com=13, adjust=False).mean()
        ema_loss = loss.ewm(com=13, adjust=False).mean()
        rs = ema_gain / ema_loss.replace(0, 1e-10)
        df['RSI'] = 100 - (100 / (1 + rs))

    # 2. MACD (12, 26, 9)
    try:
        macd_df = ta.macd(close_series, fast=12, slow=26, signal=9)
        if macd_df is not None and not macd_df.empty:
            df['MACD'] = macd_df.iloc[:, 0]
            df['MACD_signal'] = macd_df.iloc[:, 1]
            df['MACD_hist'] = macd_df.iloc[:, 2]
        else:
            raise ValueError("Empty MACD df")
    except Exception as e:
        logger.warning(f"pandas-ta MACD failed: {e}. Calculating manually.")
        ema12 = close_series.ewm(span=12, adjust=False).mean()
        ema26 = close_series.ewm(span=26, adjust=False).mean()
        df['MACD'] = ema12 - ema26
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_hist'] = df['MACD'] - df['MACD_signal']

    # 3. SMAs (20 & 50)
    try:
        df['SMA_20'] = ta.sma(close_series, length=20)
        df['SMA_50'] = ta.sma(close_series, length=50)
    except Exception as e:
        logger.warning(f"pandas-ta SMAs failed: {e}. Calculating manually.")
        df['SMA_20'] = close_series.rolling(window=20).mean()
        df['SMA_50'] = close_series.rolling(window=50).mean()

    # 4. Bollinger Bands (20, 2)
    try:
        bbands = ta.bbands(close_series, length=20, std=2)
        if bbands is not None and not bbands.empty:
            df['BBL'] = bbands.iloc[:, 0] # Lower
            df['BBM'] = bbands.iloc[:, 1] # Middle
            df['BBU'] = bbands.iloc[:, 2] # Upper
        else:
            raise ValueError("Empty BB df")
    except Exception as e:
        logger.warning(f"pandas-ta BB failed: {e}. Calculating manually.")
        sma20 = close_series.rolling(window=20).mean()
        std20 = close_series.rolling(window=20).std()
        df['BBM'] = sma20
        df['BBU'] = sma20 + 2 * std20
        df['BBL'] = sma20 - 2 * std20

    # 5. Volume Average (20)
    df['Vol_Avg_20'] = volume_series.rolling(window=20).mean()

    return df

def find_peaks_valleys(df, window=3):
    """Finds local peaks and valleys in the dataframe."""
    highs = df['High'].values
    lows = df['Low'].values
    indices = df.index
    
    peaks = []    # list of (index, row_position, price)
    valleys = []  # list of (index, row_position, price)
    
    for i in range(window, len(df) - window):
        # A high is a peak if it is greater than or equal to all highs in the window
        if highs[i] == max(highs[i - window : i + window + 1]):
            peaks.append((indices[i], i, highs[i]))
        # A low is a valley if it is less than or equal to all lows in the window
        if lows[i] == min(lows[i - window : i + window + 1]):
            valleys.append((indices[i], i, lows[i]))
            
    return peaks, valleys

def detect_chart_patterns(df):
    """Detects chart patterns over the last 30-60 candles.
    
    Returns:
        tuple: (pattern_name, confidence, pattern_dates)
    """
    # Keep last 60 rows for analysis
    sub_df = df.iloc[-60:]
    if len(sub_df) < 30:
        return "none", 0.0, []

    peaks, valleys = find_peaks_valleys(sub_df, window=3)
    
    latest_close = sub_df['Close'].iloc[-1]
    prior_close = sub_df['Close'].iloc[-2]
    latest_vol_anomaly = sub_df['Volume'].iloc[-1] > 2 * sub_df['Vol_Avg_20'].iloc[-1] if 'Vol_Avg_20' in sub_df else False
    
    # Store candidates
    patterns = [] # list of (pattern_name, confidence, pattern_dates)
    
    # 1. Breakout above resistance
    # Look at peaks excluding the last 3 candles
    historical_peaks = [p[2] for p in peaks if p[1] < len(sub_df) - 3]
    if historical_peaks:
        resistance = max(historical_peaks)
        if prior_close <= resistance and latest_close > resistance:
            confidence = 0.9 if latest_vol_anomaly else 0.7
            breakout_date = str(sub_df.index[-1])[:10]
            patterns.append(("breakout_resistance", confidence, [breakout_date]))

    # 2. Breakdown below support
    # Look at valleys excluding the last 3 candles
    historical_valleys = [v[2] for v in valleys if v[1] < len(sub_df) - 3]
    if historical_valleys:
        support = min(historical_valleys)
        if prior_close >= support and latest_close < support:
            confidence = 0.9 if latest_vol_anomaly else 0.7
            breakdown_date = str(sub_df.index[-1])[:10]
            patterns.append(("breakdown_support", confidence, [breakdown_date]))

    # 3. Double Top
    # Look at the last two peaks
    if len(peaks) >= 2:
        p1, p2 = peaks[-2], peaks[-1]
        # Check if they are similar in price (within 3%)
        if abs(p1[2] - p2[2]) / p1[2] <= 0.03:
            # Find the valley between them
            between_valleys = [v for v in valleys if p1[1] < v[1] < p2[1]]
            if between_valleys:
                neckline = min(v[2] for v in between_valleys)
                # Breakout below neckline
                if prior_close >= neckline and latest_close < neckline:
                    p1_date = str(p1[0])[:10]
                    p2_date = str(p2[0])[:10]
                    patterns.append(("double_top", 0.85 if latest_vol_anomaly else 0.75, [p1_date, p2_date]))

    # 4. Double Bottom
    # Look at the last two valleys
    if len(valleys) >= 2:
        v1, v2 = valleys[-2], valleys[-1]
        # Check if they are similar in price (within 3%)
        if abs(v1[2] - v2[2]) / v1[2] <= 0.03:
            # Find the peak between them
            between_peaks = [p for p in peaks if v1[1] < p[1] < v2[1]]
            if between_peaks:
                neckline = max(p[2] for p in between_peaks)
                # Breakout above neckline
                if prior_close <= neckline and latest_close > neckline:
                    v1_date = str(v1[0])[:10]
                    v2_date = str(v2[0])[:10]
                    patterns.append(("double_bottom", 0.85 if latest_vol_anomaly else 0.75, [v1_date, v2_date]))

    # 5. Head and Shoulders
    if len(peaks) >= 3:
        p1, p2, p3 = peaks[-3], peaks[-2], peaks[-1] # Left Shoulder, Head, Right Shoulder
        # Head (p2) must be higher than shoulders
        if p2[2] > p1[2] and p2[2] > p3[2]:
            # Shoulders must be close to each other (within 4%)
            if abs(p1[2] - p3[2]) / p1[2] <= 0.04:
                # Find valleys between p1-p2 and p2-p3
                v1_list = [v for v in valleys if p1[1] < v[1] < p2[1]]
                v2_list = [v for v in valleys if p2[1] < v[1] < p3[1]]
                if v1_list and v2_list:
                    v1_price = min(v[2] for v in v1_list)
                    v2_price = min(v[2] for v in v2_list)
                    neckline = (v1_price + v2_price) / 2
                    # Breakdown below neckline
                    if prior_close >= neckline and latest_close < neckline:
                        p1_date = str(p1[0])[:10]
                        p2_date = str(p2[0])[:10]
                        p3_date = str(p3[0])[:10]
                        patterns.append(("head_and_shoulders", 0.85, [p1_date, p2_date, p3_date]))

    # 6. Ascending / Descending Triangle
    if len(peaks) >= 3 and len(valleys) >= 3:
        peak_prices = [p[2] for p in peaks[-3:]]
        valley_prices = [v[2] for v in valleys[-3:]]
        peak_idx = [p[1] for p in peaks[-3:]]
        valley_idx = [v[1] for v in valleys[-3:]]
        
        # Slopes
        peak_slope = np.polyfit(peak_idx, peak_prices, 1)[0]
        valley_slope = np.polyfit(valley_idx, valley_prices, 1)[0]
        
        # Ascending Triangle: Flat peaks (standard deviation < 2% of mean), rising valleys (slope > 0)
        peak_std_pct = np.std(peak_prices) / np.mean(peak_prices)
        if peak_std_pct < 0.02 and valley_slope > 0.01:
            # Check if breakout above flat resistance occurred or is close
            resistance = np.mean(peak_prices)
            if prior_close <= resistance and latest_close > resistance * 0.98:
                tri_dates = [str(p[0])[:10] for p in peaks[-3:]] + [str(v[0])[:10] for v in valleys[-3:]]
                patterns.append(("ascending_triangle", 0.75, tri_dates))
                
        # Descending Triangle: Flat valleys (std < 2%), falling peaks (slope < 0)
        valley_std_pct = np.std(valley_prices) / np.mean(valley_prices)
        if valley_std_pct < 0.02 and peak_slope < -0.01:
            # Check if breakdown below support occurred or is close
            support = np.mean(valley_prices)
            if prior_close >= support and latest_close < support * 1.02:
                tri_dates = [str(p[0])[:10] for p in peaks[-3:]] + [str(v[0])[:10] for v in valleys[-3:]]
                patterns.append(("descending_triangle", 0.75, tri_dates))

    if patterns:
        # Sort by confidence descending and return top pattern
        patterns.sort(key=lambda x: x[1], reverse=True)
        return patterns[0][0], patterns[0][1], patterns[0][2]
        
    return "none", 0.0, []

def analyze_ticker(df, ticker):
    """Computes technical indicators and pattern signals for a ticker.
    
    Returns:
        dict: The signal payload.
    """
    if df.empty or len(df) < 20:
        logger.warning(f"Insufficient data to analyze ticker {ticker}")
        return {}

    # Clean index (some yfinance runs might have timezone metadata)
    df.index = pd.to_datetime(df.index)
    latest_timestamp = df.index[-1].strftime("%Y-%m-%dT%H:%M:%S")

    df_ind = get_indicators(df)
    if len(df_ind) < 2:
        return {}

    # Latest close and calculations
    close_series = df_ind['Close']
    latest_close = close_series.iloc[-1]
    
    # 1. RSI
    rsi_val = float(df_ind['RSI'].dropna().iloc[-1]) if 'RSI' in df_ind and not df_ind['RSI'].dropna().empty else 50.0

    # 2. MACD cross
    macd_cross = "none"
    if 'MACD' in df_ind and 'MACD_signal' in df_ind:
        macd_l = df_ind['MACD']
        macd_s = df_ind['MACD_signal']
        if len(macd_l) >= 2:
            m_curr, m_prev = macd_l.iloc[-1], macd_l.iloc[-2]
            s_curr, s_prev = macd_s.iloc[-1], macd_s.iloc[-2]
            if m_prev <= s_prev and m_curr > s_curr:
                macd_cross = "bullish_cross"
            elif m_prev >= s_prev and m_curr < s_curr:
                macd_cross = "bearish_cross"

    # 3. SMA cross
    sma_cross = "none"
    if 'SMA_20' in df_ind and 'SMA_50' in df_ind:
        sma20 = df_ind['SMA_20']
        sma50 = df_ind['SMA_50']
        if len(sma20) >= 2:
            s20_curr, s20_prev = sma20.iloc[-1], sma20.iloc[-2]
            s50_curr, s50_prev = sma50.iloc[-1], sma50.iloc[-2]
            if s20_prev <= s50_prev and s20_curr > s50_curr:
                sma_cross = "golden_cross"
            elif s20_prev >= s50_prev and s20_curr < s50_curr:
                sma_cross = "death_cross"

    # 4. Bollinger Bands position
    bb_position = "middle"
    if 'BBU' in df_ind and 'BBL' in df_ind:
        bbu = df_ind['BBU'].iloc[-1]
        bbl = df_ind['BBL'].iloc[-1]
        if latest_close > bbu:
            bb_position = "above_upper"
        elif latest_close < bbl:
            bb_position = "below_lower"

    # 5. Volume anomaly
    volume_anomaly = False
    if 'Vol_Avg_20' in df_ind:
        vol = df_ind['Volume'].iloc[-1]
        vol_avg = df_ind['Vol_Avg_20'].iloc[-1]
        if vol > 2 * vol_avg:
            volume_anomaly = True

    # 6. Chart patterns
    pattern, pattern_conf, pattern_dates = detect_chart_patterns(df_ind)

    payload = {
        "ticker": ticker,
        "timestamp": latest_timestamp,
        "signals": {
            "rsi": rsi_val,
            "macd_cross": macd_cross,
            "sma_cross": sma_cross,
            "bb_position": bb_position,
            "volume_anomaly": volume_anomaly,
            "pattern": pattern,
            "pattern_confidence": pattern_conf,
            "pattern_dates": pattern_dates
        }
    }
    return payload
