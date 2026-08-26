import os
import shutil
import sqlite3
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

import analysis
import feedback

# Temporary database path for testing
TEST_DB_DIR = "test_data"
TEST_DB_PATH = os.path.join(TEST_DB_DIR, "pulse.db")

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Sets up a clean test database directory and overrides DB path in feedback module."""
    if os.path.exists(TEST_DB_DIR):
        try:
            shutil.rmtree(TEST_DB_DIR)
        except Exception:
            pass
    os.makedirs(TEST_DB_DIR, exist_ok=True)
    
    # Monkeypatch the DB path in feedback
    monkeypatch.setattr(feedback, "DB_DIR", TEST_DB_DIR)
    monkeypatch.setattr(feedback, "DB_PATH", TEST_DB_PATH)
    
    yield
    
    # Explicitly clear the DB file in teardown
    if os.path.exists(TEST_DB_DIR):
        try:
            shutil.rmtree(TEST_DB_DIR)
        except Exception:
            pass

def create_dummy_ohlcv_data(length=60, base_price=100.0, trend=0.0):
    """Creates a dummy pandas DataFrame representing OHLCV data."""
    dates = pd.date_range(end=datetime.now(), periods=length, freq='D')
    
    close = [base_price + i * trend for i in range(length)]
    # Add a bit of noise
    np.random.seed(42)
    noise = np.random.normal(0, 1.0, length)
    close = [max(10.0, c + n) for c, n in zip(close, noise)]
    
    high = [c + 2.0 for c in close]
    low = [c - 2.0 for c in close]
    open_p = [c - 0.5 for c in close]
    volume = [1000 + int(abs(n) * 100) for n in noise]
    
    df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume
    }, index=dates)
    
    return df

def test_technical_indicators():
    """Verifies that technical indicators compute successfully and match column schemas."""
    df = create_dummy_ohlcv_data(length=60)
    
    # Compute indicators
    df_ind = analysis.get_indicators(df)
    
    assert "RSI" in df_ind.columns
    assert "MACD" in df_ind.columns
    assert "SMA_20" in df_ind.columns
    assert "SMA_50" in df_ind.columns
    assert "BBU" in df_ind.columns
    assert "BBL" in df_ind.columns
    assert "Vol_Avg_20" in df_ind.columns
    
    # Check that tail values are not NaN
    assert not pd.isna(df_ind["RSI"].iloc[-1])
    assert not pd.isna(df_ind["MACD"].iloc[-1])
    assert not pd.isna(df_ind["SMA_50"].iloc[-1])

def test_volume_anomaly_detection():
    """Verifies that volume anomaly is detected when volume is > 2x 20-day average."""
    df = create_dummy_ohlcv_data(length=60)
    
    # Standard check: should be False
    res_normal = analysis.analyze_ticker(df, "MOCK.NS")
    assert res_normal["signals"]["volume_anomaly"] is False
    
    # Inject volume anomaly in the last row
    df.loc[df.index[-1], "Volume"] = 10000.0
    res_anomaly = analysis.analyze_ticker(df, "MOCK.NS")
    assert res_anomaly["signals"]["volume_anomaly"] is True

def test_breakout_resistance_pattern():
    """Verifies breakout pattern detection heuristic."""
    # Create standard upward sloping data to avoid flat double-bottom triggers
    df = create_dummy_ohlcv_data(length=60, base_price=100.0, trend=0.1)
    
    # Set a single high peak in the past (e.g. index 30) at 120.0
    df.loc[df.index[30], "High"] = 120.0
    
    # Ensure other historical highs are well below 120
    for i in range(len(df) - 3):
        if i != 30:
            df.loc[df.index[i], "High"] = min(df.loc[df.index[i], "High"], 115.0)
            df.loc[df.index[i], "Close"] = min(df.loc[df.index[i], "Close"], 113.0)

    # Set the prior day below resistance
    df.loc[df.index[-2], "Close"] = 110.0
    
    # Set the latest close way above resistance (122.0)
    df.loc[df.index[-1], "Close"] = 122.0
    df.loc[df.index[-1], "High"] = 123.0
    
    # Set volume anomaly to guarantee highest confidence (0.9)
    df.loc[df.index[-1], "Volume"] = 50000.0
    df.loc[df.index[-20:-1], "Volume"] = 1000.0 # Make average volume low
    
    # Analyze
    df_ind = analysis.get_indicators(df)
    pattern, conf = analysis.detect_chart_patterns(df_ind)
    
    assert pattern == "breakout_resistance"
    assert conf >= 0.7

def test_feedback_accuracy_calculation():
    """Verifies SQLite prediction logging, outcomes updates, and rolling accuracy calculations."""
    # 1. Initialize DB
    feedback.init_db()
    
    # Ensure tables are empty using a connection context manager
    with sqlite3.connect(TEST_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM predictions")
        assert cursor.fetchone()[0] == 0
    
    # 2. Log mock predictions
    pred_date_str = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Log a bullish prediction for RELIANCE at price 100
    feedback.log_prediction("RELIANCE.NS", "rsi", "bullish", 0.8, pred_date_str, 100.0)
    # Log a bearish prediction for TCS at price 200
    feedback.log_prediction("TCS.NS", "rsi", "bearish", 0.7, pred_date_str, 200.0)
    
    # 3. Simulate subsequent price changes to evaluate outcomes
    # For RELIANCE: close of first subsequent day is 101.5 (change = 1.5%, which is >= 0.5% -> correct)
    dates_rel = [datetime.now() - timedelta(days=2), datetime.now() - timedelta(days=1), datetime.now()]
    df_rel = pd.DataFrame({"Close": [100.0, 101.5, 102.0]}, index=dates_rel)
    
    # For TCS: close of first subsequent day is 201.0 (change = 0.5%, positive but bearish prediction -> incorrect)
    df_tcs = pd.DataFrame({"Close": [200.0, 201.0, 202.0]}, index=dates_rel)
    
    ohlcv_data = {
        "RELIANCE.NS": df_rel,
        "TCS.NS": df_tcs
    }
    
    # 4. Run update
    feedback.update_pending_predictions(ohlcv_data)
    
    # 5. Check outcome values in DB
    with sqlite3.connect(TEST_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ticker, actual_outcome, pct_change FROM predictions ORDER BY ticker")
        rows = cursor.fetchall()
        
        assert len(rows) == 2
        # RELIANCE prediction should be correct
        assert rows[0][0] == "RELIANCE.NS"
        assert rows[0][1] == "correct"
        assert pytest.approx(rows[0][2]) == 0.015
        
        # TCS prediction should be incorrect
        assert rows[1][0] == "TCS.NS"
        assert rows[1][1] == "incorrect"
        assert pytest.approx(rows[1][2]) == 0.005
        
        # 6. Verify accuracy was recalculated and stored
        cursor.execute("SELECT signal_type, accuracy_30d, outcome_count FROM rolling_accuracy WHERE signal_type = 'rsi'")
        acc_row = cursor.fetchone()
        assert acc_row is not None
        assert acc_row[1] == 0.5 # 1 correct, 1 incorrect -> 50% accuracy
        assert acc_row[2] == 2   # 2 outcomes
        
    # 7. Check weight scaling fallback (since count is < 10, should default to 1.0)
    weight = feedback.get_signal_weight("rsi")
    assert weight == 1.0
    
    # 8. Check weight scaling computation when count is >= 10
    # Manually delete and insert outcomes
    with sqlite3.connect(TEST_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM predictions")
        cursor.execute("DELETE FROM rolling_accuracy")
        conn.commit()
    
    # Log 10 predictions
    for i in range(8):
        feedback.log_prediction("MOCK.NS", "rsi", "bullish", 0.9, pred_date_str, 100.0)
    for i in range(2):
        feedback.log_prediction("MOCK.NS", "rsi", "bearish", 0.9, pred_date_str, 100.0)
        
    # Update outcomes manually
    with sqlite3.connect(TEST_DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE predictions SET actual_outcome = 'correct' WHERE direction = 'bullish'")
        cursor.execute("UPDATE predictions SET actual_outcome = 'incorrect' WHERE direction = 'bearish'")
        conn.commit()
        
        # Recalculate
        feedback.recalculate_rolling_accuracies(cursor)
        conn.commit()
        
        # Count should be 10, accuracy should be 0.8
        cursor.execute("SELECT accuracy_30d, outcome_count FROM rolling_accuracy WHERE signal_type = 'rsi'")
        acc_row_10 = cursor.fetchone()
        assert acc_row_10[0] == 0.8
        assert acc_row_10[1] == 10
    
    # Weight should be 0.5 + 0.8 = 1.3
    weight_10 = feedback.get_signal_weight("rsi")
    assert pytest.approx(weight_10) == 1.3
