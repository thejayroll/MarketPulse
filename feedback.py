import os
import sqlite3
import logging
import pandas as pd
from datetime import datetime, timedelta

logger = logging.getLogger("feedback")

DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "pulse.db")

def init_db():
    """Initializes SQLite database and tables if they don't exist."""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR, exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        
        # Create predictions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT,
                signal_type TEXT,
                direction TEXT,
                confidence REAL,
                timestamp TEXT,
                price_at_prediction REAL,
                actual_outcome TEXT DEFAULT 'pending',
                pct_change REAL DEFAULT NULL
            )
        """)
        
        # Create rolling accuracy table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rolling_accuracy (
                signal_type TEXT PRIMARY KEY,
                accuracy_30d REAL,
                outcome_count INTEGER
            )
        """)
        
        conn.commit()
    finally:
        conn.close()

def log_prediction(ticker, signal_type, direction, confidence, timestamp, price_at_prediction):
    """Logs a new prediction to the database."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO predictions 
                (ticker, signal_type, direction, confidence, timestamp, price_at_prediction)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (ticker, signal_type, direction, float(confidence), timestamp, float(price_at_prediction) if price_at_prediction is not None else None))
            conn.commit()
            logger.info(f"Logged prediction: {ticker} | {signal_type} | {direction} | Price: {price_at_prediction}")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error logging prediction: {e}")

def update_pending_predictions(ohlcv_data):
    """Evaluates pending predictions using newly fetched close prices.
    
    ohlcv_data: dict of {ticker: DataFrame} with latest OHLCV data.
    """
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            
            # Fetch pending predictions
            cursor.execute("SELECT id, ticker, signal_type, direction, timestamp, price_at_prediction FROM predictions WHERE actual_outcome = 'pending'")
            pending = cursor.fetchall()
            
            if not pending:
                return
                
            logger.info(f"Found {len(pending)} pending predictions to evaluate.")
            
            updated_count = 0
            for row in pending:
                pred_id, ticker, signal_type, direction, timestamp_str, price_at_pred = row
                
                if ticker not in ohlcv_data or ohlcv_data[ticker].empty:
                    continue
                    
                df = ohlcv_data[ticker].copy()
                # Ensure the index is datetime objects
                df.index = pd.to_datetime(df.index)
                
                # Convert prediction timestamp to date for date-only comparison
                pred_date = datetime.strptime(timestamp_str[:10], "%Y-%m-%d").date()
                
                # Find the first closing price on a trading day AFTER the prediction date
                sub_df = df[df.index.date > pred_date]
                if sub_df.empty:
                    continue # No subsequent trading days fetched yet
                    
                # Get the closing price of the next trading day
                next_close = float(sub_df['Close'].iloc[0])
                
                if price_at_pred is None:
                    # If price_at_pred was missing, fall back to the price at prediction date or closest preceding
                    pre_df = df[df.index.date <= pred_date]
                    if not pre_df.empty:
                        price_at_pred = float(pre_df['Close'].iloc[-1])
                    else:
                        price_at_pred = next_close # Absolute fallback
                        
                pct_change = (next_close - price_at_pred) / price_at_pred
                
                # Determine outcome against 0.5% threshold
                is_correct = False
                if direction == "bullish":
                    is_correct = pct_change >= 0.005
                elif direction == "bearish":
                    is_correct = pct_change <= -0.005
                elif direction == "neutral":
                    is_correct = abs(pct_change) < 0.005
                    
                outcome = "correct" if is_correct else "incorrect"
                
                # Update prediction row
                cursor.execute("""
                    UPDATE predictions 
                    SET actual_outcome = ?, pct_change = ?
                    WHERE id = ?
                """, (outcome, pct_change, pred_id))
                updated_count += 1
                logger.info(f"Updated prediction {pred_id} ({ticker} {signal_type}): {direction} was {outcome} (change: {pct_change:.2%})")
                
            if updated_count > 0:
                conn.commit()
                # Recalculate rolling accuracies
                recalculate_rolling_accuracies(cursor)
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error updating pending predictions: {e}")

def recalculate_rolling_accuracies(cursor):
    """Helper to compute 30-day accuracy per signal_type."""
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    # Find all outcomes in the last 30 days
    cursor.execute("""
        SELECT signal_type, actual_outcome 
        FROM predictions 
        WHERE actual_outcome != 'pending' 
          AND timestamp >= ?
    """, (thirty_days_ago,))
    
    outcomes = cursor.fetchall()
    if not outcomes:
        return
        
    # Group by signal_type
    stats = {}
    for signal_type, outcome in outcomes:
        if signal_type not in stats:
            stats[signal_type] = {"correct": 0, "total": 0}
        stats[signal_type]["total"] += 1
        if outcome == "correct":
            stats[signal_type]["correct"] += 1
            
    # Update rolling_accuracy table
    for signal_type, stat in stats.items():
        accuracy = stat["correct"] / stat["total"]
        cursor.execute("""
            INSERT INTO rolling_accuracy (signal_type, accuracy_30d, outcome_count)
            VALUES (?, ?, ?)
            ON CONFLICT(signal_type) DO UPDATE SET
                accuracy_30d = excluded.accuracy_30d,
                outcome_count = excluded.outcome_count
        """, (signal_type, accuracy, stat["total"]))

def get_signal_weight(signal_type) -> float:
    """Returns normalized weight (0.5 - 1.5) for a signal_type based on rolling accuracy.
    
    Defaults to 1.0 if fewer than 10 outcomes exist.
    """
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT accuracy_30d, outcome_count FROM rolling_accuracy WHERE signal_type = ?", (signal_type,))
            row = cursor.fetchone()
            if row:
                accuracy, count = row
                if count >= 10:
                    weight = 0.5 + accuracy
                    return float(max(0.5, min(1.5, weight)))
        finally:
            conn.close()
            
        return 1.0
    except Exception as e:
        logger.error(f"Error fetching signal weight for {signal_type}: {e}")
        return 1.0

def get_yesterday_accuracy_summary():
    """Gets a one-line summary of predictions evaluated in the last run or yesterday."""
    try:
        init_db()
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            one_day_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            cursor.execute("""
                SELECT actual_outcome 
                FROM predictions 
                WHERE actual_outcome != 'pending' 
                  AND timestamp >= ?
            """, (one_day_ago,))
            
            rows = cursor.fetchall()
            if not rows:
                return "No previous trading day predictions evaluated yet."
                
            total = len(rows)
            correct = sum(1 for r in rows if r[0] == "correct")
            accuracy = (correct / total) * 100
            
            return f"Yesterday's morning call accuracy was {accuracy:.1f}% based on {total} tracked signals."
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Error fetching yesterday accuracy: {e}")
        return "Could not retrieve yesterday's morning call accuracy."
