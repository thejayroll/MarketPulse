import os
import sys
import json
import argparse
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("send_notification")

# Try importing firebase_admin
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    HAS_FIREBASE = True
except ImportError:
    HAS_FIREBASE = False
    logger.warning("firebase-admin package is not installed. Notifications will be mocked.")

def get_morning_content(data):
    """Generates notification title and body for morning mode."""
    market_wide = data.get("market_wide_sentiment", {})
    market_label = market_wide.get("label", "neutral").capitalize()
    market_conf = market_wide.get("confidence", 0.5)
    
    title = f"Morning Market Pulse - {market_label}"
    
    # Extract top watchlist mover (highest confidence non-neutral stock)
    watchlist = data.get("watchlist", [])
    top_mover = None
    max_conf = -1.0
    
    for item in watchlist:
        ticker = item.get("ticker", "Unknown")
        sentiment = item.get("sentiment", "neutral")
        confidence = item.get("confidence", 0.0)
        
        if sentiment != "neutral" and confidence > max_conf:
            max_conf = confidence
            top_mover = f"{ticker.replace('.NS', '')} ({sentiment} at {confidence:.0%})"
            
    if not top_mover:
        top_mover = "Watchlist is consolidating neutrally."
        
    line1 = f"Index Outlook: {market_label} (Confidence: {market_conf:.0%})"
    line2 = f"Top Watchlist Mover: {top_mover}"
    body = f"{line1}\n{line2}"
    
    return title, body

def get_evening_content(data):
    """Generates notification title and body for evening mode."""
    title = "Evening Wrap - Top Movers"
    
    # Extract top gainer/loser
    top_gainers = data.get("top_gainers", [])
    top_losers = data.get("top_losers", [])
    market_wide = data.get("market_wide_sentiment", {})
    market_label = market_wide.get("label", "neutral").capitalize()
    
    gainer_str = "None"
    if top_gainers:
        tg = top_gainers[0]
        gainer_str = f"{tg.get('ticker', '').replace('.NS', '')} ({tg.get('change', '')})"
        
    loser_str = "None"
    if top_losers:
        tl = top_losers[0]
        loser_str = f"{tl.get('ticker', '').replace('.NS', '')} ({tl.get('change', '')})"
        
    line1 = f"Top Gainer: {gainer_str} | Top Loser: {loser_str}"
    line2 = f"Market Close: Index closed {market_label}."
    body = f"{line1}\n{line2}"
    
    return title, body

def send_fcm_notification(title, body, service_account_json, device_token):
    """Sends notification via FCM using firebase-admin SDK."""
    if not HAS_FIREBASE:
        logger.error("Cannot send notification: firebase-admin package is missing.")
        return False
        
    try:
        # Load credentials
        cred_dict = json.loads(service_account_json)
        cred = credentials.Certificate(cred_dict)
        
        # Initialize firebase app if not already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            
        # Construct message
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            token=device_token
        )
        
        logger.info(f"Sending FCM message: Title='{title}', Body='{body}'")
        response = messaging.send(message)
        logger.info(f"Successfully sent FCM notification. Message ID: {response}")
        return True
    except Exception as e:
        logger.error(f"Failed to send FCM notification: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Send Firebase Cloud Messaging Push Notification")
    parser.add_argument(
        "--mode",
        choices=["morning", "evening"],
        required=True,
        help="Specify the briefing mode to send"
    )
    args = parser.parse_args()
    
    # File paths
    json_path = f"data/latest_{args.mode}.json"
    if not os.path.exists(json_path):
        logger.error(f"Briefing payload file not found at {json_path}. Cannot send notification.")
        sys.exit(0) # Exit cleanly, do not crash pipeline
        
    # Read payload
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to parse briefing payload JSON: {e}")
        sys.exit(0) # Exit cleanly
        
    # Extract notification content
    if args.mode == "morning":
        title, body = get_morning_content(data)
    else:
        title, body = get_evening_content(data)
        
    # Read secrets from environment variables
    service_account_json = os.environ.get("FCM_SERVICE_ACCOUNT")
    device_token = os.environ.get("FCM_DEVICE_TOKEN")
    
    if not service_account_json or not device_token:
        logger.warning(
            "FCM credentials missing. Set FCM_SERVICE_ACCOUNT (JSON string) and "
            "FCM_DEVICE_TOKEN in environment variables to send notifications."
        )
        logger.info(f"[MOCK NOTIFICATION]\nTitle: {title}\nBody:\n{body}")
        sys.exit(0) # Exit cleanly
        
    # Send notification
    success = send_fcm_notification(title, body, service_account_json, device_token)
    if not success:
        logger.warning("FCM notification failed, but pipeline execution is marked successful.")
        
    sys.exit(0) # Guarantee clean exit so pipeline doesn't break

if __name__ == "__main__":
    main()
