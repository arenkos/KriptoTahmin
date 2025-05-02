import time
import sqlite3 # Veritabanı bağlantısı için eklendi
import pandas as pd
import numpy as np
from datetime import datetime, timedelta # timedelta eklendi
import talib as ta
import math
import ccxt
import logging
from telegram import Bot
import os
import threading
import traceback

# --- Logging ayarları ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trade_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("trade_bot")

# --- CONFIGURATION ---
db_name = 'crypto_data.db'
table_name = 'ohlcv_data'
log_file_name = "trade_bot_detailed.log"
atr_period = 10         # Supertrend ATR periyodu
atr_multiplier = 3      # Supertrend ATR çarpanı

# --- Telegram settings ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')

# --- DATABASE FUNCTIONS ---
def get_user_settings():
    """Kullanıcının trading ayarlarını veritabanından çek"""
    conn = None
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Aktif trading ayarlarını çek
        query = """
        SELECT u.id, u.username, u.api_key, u.api_secret, u.telegram_chat_id, 
               ts.symbol, ts.timeframe, ts.leverage, ts.stop_loss, ts.take_profit 
        FROM user u
        JOIN trading_settings ts ON u.id = ts.user_id
        WHERE ts.is_active = 1 AND u.is_active = 1
        """
        
        cursor.execute(query)
        user_settings = []
        
        for row in cursor.fetchall():
            user_settings.append({
                'user_id': row[0],
                'username': row[1],
                'api_key': row[2],
                'api_secret': row[3],
                'telegram_chat_id': row[4],
                'symbol': row[5],
                'timeframe': row[6],
                'leverage': row[7],
                'stop_loss': row[8],
                'take_profit': row[9]
            })
            
        return user_settings
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def fetch_data_from_db(symbol, timeframe):
    """Veritabanından OHLCV verilerini çeker ve DataFrame olarak döndürür."""
    conn = None
    try:
        logger.info(f"Connecting to database: {db_name}")
        conn = sqlite3.connect(db_name)
        # Son 2 haftaya ait veriyi çekmek için zaman hesaplaması
        two_weeks_ago = datetime.now() - timedelta(days=14)
        timestamp_ms = int(two_weeks_ago.timestamp() * 1000)
        
        # Veritabanından veri çekme
        query = f"SELECT timestamp, open, high, low, close, volume FROM {table_name} WHERE symbol = ? AND timeframe = ? AND timestamp >= ? ORDER BY timestamp ASC"
        params = (symbol, timeframe, timestamp_ms)

        logger.info(f"Executing query for {symbol} {timeframe}")
        df = pd.read_sql_query(query, conn, params=params)
        logger.info(f"Fetched {len(df)} records.")

        if df.empty:
            logger.error(f"No data fetched from the database for {symbol} {timeframe}")
            return None

        # Zaman damgasını datetime nesnesine çevir ve index yap
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # Veri tiplerini float yap
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Eksik veri varsa temizle
        df.dropna(inplace=True)
        logger.info(f"Data cleaned. {len(df)} records remaining.")

        return df

    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return None
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return None
    finally:
        if conn:
            conn.close()
            logger.info("Database connection closed.")

# --- INDICATOR CALCULATION ---
def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    """Supertrend indikatörünü hesaplar."""
    # Ensure arrays are float type for TA-Lib
    high_array = high_array.astype(float)
    low_array = low_array.astype(float)
    close_array = close_array.astype(float)

    # Calculate ATR
    try:
        atr = ta.ATR(high_array, low_array, close_array, timeperiod=atr_period)
    except Exception as e:
        logger.error(f"Error calculating ATR: {e}")
        # Return NaNs or raise error depending on desired handling
        return np.full(close_array.shape, np.nan)

    # Initialize bands and supertrend arrays
    final_upperband = np.full(close_array.shape, np.nan)
    final_lowerband = np.full(close_array.shape, np.nan)
    supertrend = np.full(close_array.shape, np.nan)

    # Calculate Basic Upper and Lower Bands
    basic_upperband = (high_array + low_array) / 2 + atr_multiplier * atr
    basic_lowerband = (high_array + low_array) / 2 - atr_multiplier * atr

    # Compute Final Bands and Supertrend
    for i in range(atr_period, len(close_array)):
        # Final Upper Band
        if basic_upperband[i] < final_upperband[i-1] or close_array[i-1] > final_upperband[i-1]:
            final_upperband[i] = basic_upperband[i]
        else:
            final_upperband[i] = final_upperband[i-1]

        # Final Lower Band
        if basic_lowerband[i] > final_lowerband[i-1] or close_array[i-1] < final_lowerband[i-1]:
            final_lowerband[i] = basic_lowerband[i]
        else:
            final_lowerband[i] = final_lowerband[i-1]

        # Supertrend
        if supertrend[i-1] == final_upperband[i-1]: # If previous was upper band
            if close_array[i] <= final_upperband[i]:
                supertrend[i] = final_upperband[i]
            else: # Cross above
                supertrend[i] = final_lowerband[i]
        elif supertrend[i-1] == final_lowerband[i-1]: # If previous was lower band
            if close_array[i] >= final_lowerband[i]:
                supertrend[i] = final_lowerband[i]
            else: # Cross below
                supertrend[i] = final_upperband[i]
        else: # Initial case (use lower band first or based on price direction)
            if i > atr_period:
                supertrend[i] = final_lowerband[i] if close_array[i] > (high_array[i] + low_array[i])/2 else final_upperband[i]
            else:
                supertrend[i] = final_lowerband[i] # Default start

    return supertrend

# --- TELEGRAM NOTIFICATION ---
def send_telegram_message(chat_id, message):
    """Telegram bot ile bildirim gönderme"""
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token or chat ID is missing. Message not sent.")
        return False
    
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')
        return True
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False

def send_trade_signal(user_settings, signal_type, price, timestamp):
    """İşlem sinyali gönder"""
    if not user_settings.get('telegram_chat_id'):
        return False
    
    symbol = user_settings['symbol'].replace('/', '')
    
    # Sinyal mesajı oluştur
    message = f"""
<b>🔔 YENİ İŞLEM SİNYALİ</b>

<b>Kripto:</b> {symbol}
<b>İşlem Tipi:</b> {'🟢 LONG (AL)' if signal_type == 'BUY' else '🔴 SHORT (SAT)'}
<b>Giriş Fiyatı:</b> {price:.4f} USDT
<b>Periyot:</b> {user_settings['timeframe']}
<b>Kaldıraç:</b> {user_settings['leverage']}x
<b>Stop Yüzdesi:</b> %{user_settings['stop_loss']}
<b>Tarih/Saat:</b> {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

<i>Bu otomatik bir bildirimdir. İşlem yapmadan önce kendi analizinizi yapınız.</i>
"""
    
    return send_telegram_message(user_settings['telegram_chat_id'], message)

# --- TRADING FUNCTION ---
def execute_trade(user_settings, signal_type, price):
    """Binance API ile işlem yap"""
    if not user_settings.get('api_key') or not user_settings.get('api_secret'):
        logger.warning(f"API credentials missing for user {user_settings.get('username')}. Trade not executed.")
        return False
    
    try:
        # Initialize Binance API
        exchange = ccxt.binance({
            "apiKey": user_settings['api_key'],
            "secret": user_settings['api_secret'],
            'options': {
                'defaultType': 'future'
            },
            'enableRateLimit': True
        })
        
        symbol = user_settings['symbol']
        leverage = float(user_settings['leverage'])
        
        # Leverage ayarla
        exchange.fapiPrivate_post_leverage({
            'symbol': symbol.replace('/', ''),
            'leverage': leverage
        })
        
        # Hesap bakiyesini kontrol et
        balance = exchange.fetch_balance()
        usdt_balance = balance['USDT']['free']
        
        # Pozisyon büyüklüğünü hesapla - bakiyenin %95'ini kullan
        amount_usdt = usdt_balance * 0.95
        current_price = exchange.fetch_ticker(symbol)['last']
        amount = amount_usdt / current_price
        
        # İşlem yap
        if signal_type == 'BUY':
            order = exchange.create_market_buy_order(symbol, amount)
        else:  # SELL
            order = exchange.create_market_sell_order(symbol, amount)
        
        logger.info(f"Trade executed for {user_settings['username']}: {signal_type} {symbol} at {price}")
        return order
        
    except Exception as e:
        logger.error(f"Error executing trade: {str(e)}")
        logger.error(traceback.format_exc())
        return False

# --- TRADING LOGIC ---
def process_user_data(user_settings):
    """Her kullanıcı için trading işlemlerini yürüt"""
    user_id = user_settings['user_id']
    username = user_settings['username']
    symbol = user_settings['symbol']
    timeframe = user_settings['timeframe']
    
    logger.info(f"Processing data for user {username}, symbol: {symbol}, timeframe: {timeframe}")
    
    # Veri çek
    df = fetch_data_from_db(symbol, timeframe)
    if df is None or df.empty:
        logger.error(f"No data available for {symbol} {timeframe}")
        return
    
    # Supertrend hesapla
    close_array = df['close'].values
    high_array = df['high'].values
    low_array = df['low'].values
    df['supertrend'] = generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier)
    
    # Son iki mumun verilerine bak
    if len(df) < 3:
        logger.warning(f"Insufficient data for analysis of {symbol} {timeframe}")
        return
    
    # En son iki kapanış ve supertrend değerlerini al
    prev_close = df['close'].iloc[-3]
    curr_close = df['close'].iloc[-2]
    prev_supertrend = df['supertrend'].iloc[-3]
    curr_supertrend = df['supertrend'].iloc[-2]
    current_price = df['close'].iloc[-1]  # Son kapanış fiyatı
    timestamp = df.index[-1]
    
    # Sinyal kontrolü
    signal = None
    
    # LONG sinyali: Fiyat supertrend'in üstüne çıktı
    if prev_close <= prev_supertrend and curr_close > curr_supertrend:
        signal = 'BUY'
        logger.info(f"BUY signal detected for {symbol} {timeframe} at {current_price}")
        
        # Telegram bildirimi gönder
        if send_trade_signal(user_settings, signal, current_price, timestamp):
            logger.info(f"Telegram notification sent for BUY signal to user {username}")
        
        # API key ve secret varsa işlem yap
        if user_settings.get('api_key') and user_settings.get('api_secret'):
            if execute_trade(user_settings, signal, current_price):
                logger.info(f"Trade executed for {username}: BUY {symbol} at {current_price}")
            else:
                logger.error(f"Failed to execute trade for {username}")
    
    # SHORT sinyali: Fiyat supertrend'in altına düştü
    elif prev_close >= prev_supertrend and curr_close < curr_supertrend:
        signal = 'SELL'
        logger.info(f"SELL signal detected for {symbol} {timeframe} at {current_price}")
        
        # Telegram bildirimi gönder
        if send_trade_signal(user_settings, signal, current_price, timestamp):
            logger.info(f"Telegram notification sent for SELL signal to user {username}")
        
        # API key ve secret varsa işlem yap
        if user_settings.get('api_key') and user_settings.get('api_secret'):
            if execute_trade(user_settings, signal, current_price):
                logger.info(f"Trade executed for {username}: SELL {symbol} at {current_price}")
            else:
                logger.error(f"Failed to execute trade for {username}")
    
    else:
        logger.info(f"No trading signal for {symbol} {timeframe} at this time")

# --- MAIN EXECUTION ---
def main():
    try:
        logger.info("Starting trading bot...")
        
        # Kullanıcı ayarlarını çek
        user_settings_list = get_user_settings()
        
        if not user_settings_list:
            logger.info("No active user settings found. Exiting.")
            return
        
        logger.info(f"Found {len(user_settings_list)} active user settings")
        
        # Her kullanıcı için trading işlemlerini yürüt
        for user_settings in user_settings_list:
            process_user_data(user_settings)
        
        logger.info("Trading bot cycle completed successfully")
    
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    main()