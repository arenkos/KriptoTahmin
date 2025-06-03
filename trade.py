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
from app import create_app
from app.models.database import db, User, TradingSettings
import websocket
import json
import threading
from binance.client import Client
from binance.websockets import BinanceSocketManager
from concurrent.futures import ThreadPoolExecutor
import argparse

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

# --- WebSocket ayarları ---
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', '')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET', '')

# Desteklenen semboller ve zaman dilimleri
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
]

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]

class TradingStrategy:
    def __init__(self, symbol, timeframe):
        self.symbol = symbol
        self.timeframe = timeframe
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self.last_signal = None
        self.last_check_time = 0
        
    def check_signals(self):
        """Belirli bir sembol ve timeframe için sinyal kontrolü yap"""
        try:
            current_time = time.time()
            # Her timeframe için uygun kontrol aralığı
            check_interval = {
                "1m": 60,
                "3m": 180,
                "5m": 300,
                "15m": 900,
                "30m": 1800,
                "1h": 3600,
                "2h": 7200,
                "4h": 14400,
                "1d": 86400,
                "1w": 604800
            }
            
            # Son kontrol zamanından bu yana yeterli süre geçmediyse kontrol etme
            if current_time - self.last_check_time < check_interval[self.timeframe]:
                return
                
            self.last_check_time = current_time
            
            # Son 100 mumu al
            self.cursor.execute('''
            SELECT timestamp, open, high, low, close, volume
            FROM ohlcv_data
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT 100
            ''', (self.symbol, self.timeframe))
            
            rows = self.cursor.fetchall()
            if not rows:
                return
                
            # DataFrame oluştur
            df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Teknik analiz göstergelerini hesapla
            df['ATR'] = ta.ATR(df['high'], df['low'], df['close'], timeperiod=atr_period)
            df['Supertrend'] = generateSupertrend(df['close'], df['high'], df['low'], atr_period, atr_multiplier)
            
            # Son sinyali kontrol et
            current_signal = None
            if df['Supertrend'].iloc[-1] > df['close'].iloc[-1]:
                current_signal = 'SELL'
            elif df['Supertrend'].iloc[-1] < df['close'].iloc[-1]:
                current_signal = 'BUY'
                
            # Sinyal değiştiyse bildirim gönder
            if current_signal and current_signal != self.last_signal:
                signal = {
                    'symbol': self.symbol,
                    'timeframe': self.timeframe,
                    'signal': current_signal,
                    'price': df['close'].iloc[-1],
                    'timestamp': df['timestamp'].iloc[-1]
                }
                notify_users(signal)
                self.last_signal = current_signal
                
        except Exception as e:
            logger.error(f"Sinyal kontrolü hatası ({self.symbol} {self.timeframe}): {str(e)}")
            
    def close(self):
        """Veritabanı bağlantısını kapat"""
        if self.conn:
            self.conn.close()

class WebSocketManager:
    def __init__(self):
        self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
        self.bm = BinanceSocketManager(self.client)
        self.conn = None
        self.cursor = None
        self.strategies = {}
        self.timeframe_executors = {}
        self.initialize_database()
        
    def initialize_database(self):
        """Veritabanı bağlantısını başlat ve tabloları oluştur"""
        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        
        # OHLCV tablosunu oluştur
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS ohlcv_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            timeframe TEXT,
            timestamp INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            UNIQUE(symbol, timeframe, timestamp)
        )
        ''')
        
        # İndeksler oluştur
        self.cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_symbol_timeframe 
        ON ohlcv_data(symbol, timeframe)
        ''')
        
        self.conn.commit()
        
    def process_kline_data(self, msg):
        """WebSocket'ten gelen kline verilerini işle"""
        try:
            if msg['e'] == 'error':
                logger.error(f"WebSocket hatası: {msg}")
                return
                
            kline = msg['k']
            symbol = kline['s']
            timeframe = kline['i']
            timestamp = kline['t']
            open_price = float(kline['o'])
            high_price = float(kline['h'])
            low_price = float(kline['l'])
            close_price = float(kline['c'])
            volume = float(kline['v'])
            
            # Veritabanına kaydet
            self.cursor.execute('''
            INSERT OR REPLACE INTO ohlcv_data 
            (symbol, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (symbol, timeframe, timestamp, open_price, high_price, 
                  low_price, close_price, volume))
            
            self.conn.commit()
            
        except Exception as e:
            logger.error(f"Kline verisi işleme hatası: {str(e)}")
            
    def start_strategies(self):
        """Tüm stratejileri başlat"""
        # Her timeframe için ayrı bir thread havuzu oluştur
        for timeframe in TIMEFRAMES:
            # Her timeframe için maksimum 5 thread kullan
            self.timeframe_executors[timeframe] = ThreadPoolExecutor(max_workers=5)
            
        # Sembolleri timeframe'lere dağıt
        for symbol in SYMBOLS:
            symbol = symbol.replace('/', '').lower()
            for timeframe in TIMEFRAMES:
                strategy = TradingStrategy(symbol, timeframe)
                self.strategies[f"{symbol}_{timeframe}"] = strategy
                # Her stratejiyi kendi timeframe'inin thread havuzuna gönder
                self.timeframe_executors[timeframe].submit(self.run_strategy, strategy)
                
    def run_strategy(self, strategy):
        """Stratejiyi sürekli çalıştır"""
        while True:
            try:
                strategy.check_signals()
                time.sleep(1)  # CPU kullanımını azaltmak için kısa bekleme
            except Exception as e:
                logger.error(f"Strateji çalıştırma hatası ({strategy.symbol} {strategy.timeframe}): {str(e)}")
                time.sleep(5)  # Hata durumunda biraz daha uzun bekle
                
    def start(self):
        """WebSocket bağlantılarını başlat"""
        try:
            # Her sembol ve timeframe için kline stream başlat
            for symbol in SYMBOLS:
                symbol = symbol.replace('/', '').lower()
                for timeframe in TIMEFRAMES:
                    # Binance timeframe formatına dönüştür
                    binance_timeframe = timeframe
                    if timeframe == '1m':
                        binance_timeframe = '1m'
                    elif timeframe == '3m':
                        binance_timeframe = '3m'
                    elif timeframe == '5m':
                        binance_timeframe = '5m'
                    elif timeframe == '15m':
                        binance_timeframe = '15m'
                    elif timeframe == '30m':
                        binance_timeframe = '30m'
                    elif timeframe == '1h':
                        binance_timeframe = '1h'
                    elif timeframe == '2h':
                        binance_timeframe = '2h'
                    elif timeframe == '4h':
                        binance_timeframe = '4h'
                    elif timeframe == '1d':
                        binance_timeframe = '1d'
                    elif timeframe == '1w':
                        binance_timeframe = '1w'
                        
                    # Kline stream başlat
                    self.bm.start_kline_socket(
                        f"{symbol}@{binance_timeframe}",
                        self.process_kline_data
                    )
                    
            # WebSocket manager'ı başlat
            self.bm.start()
            
            # Stratejileri başlat
            self.start_strategies()
            
        except Exception as e:
            logger.error(f"WebSocket başlatma hatası: {str(e)}")
            
    def stop(self):
        """WebSocket bağlantılarını kapat"""
        try:
            self.bm.close()
            # Tüm thread havuzlarını kapat
            for executor in self.timeframe_executors.values():
                executor.shutdown(wait=True)
            # Tüm stratejileri kapat
            for strategy in self.strategies.values():
                strategy.close()
            if self.conn:
                self.conn.close()
        except Exception as e:
            logger.error(f"WebSocket kapatma hatası: {str(e)}")

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
        logger.warning(f"API credentials missing for settings {user_settings.get('symbol')} {user_settings.get('timeframe')}. Trade not executed.")
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
        
        # İşlem miktarını hesapla (bakiye * kaldıraç)
        amount = user_settings['balance'] * leverage
        
        # İşlem yap
        if signal_type == 'BUY':
            order = exchange.create_market_buy_order(symbol, amount)
        else:  # SELL
            order = exchange.create_market_sell_order(symbol, amount)
        
        logger.info(f"Trade executed for {user_settings['symbol']} {user_settings['timeframe']}: {signal_type} {symbol} at {price}")
        return order
        
    except Exception as e:
        logger.error(f"Error executing trade: {str(e)}")
        logger.error(traceback.format_exc())
        return False

# --- TRADING LOGIC ---
def process_user_data(user_settings):
    """Her kullanıcı için trading işlemlerini yürüt"""
    symbol = user_settings['symbol']
    timeframe = user_settings['timeframe']
    
    logger.info(f"Processing data for symbol: {symbol}, timeframe: {timeframe}")
    
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
            logger.info(f"Telegram notification sent for BUY signal")
        
        # API key ve secret varsa işlem yap
        if user_settings.get('api_key') and user_settings.get('api_secret'):
            if execute_trade(user_settings, signal, current_price):
                logger.info(f"Trade executed: BUY {symbol} at {current_price}")
            else:
                logger.error(f"Failed to execute trade")
    
    # SHORT sinyali: Fiyat supertrend'in altına düştü
    elif prev_close >= prev_supertrend and curr_close < curr_supertrend:
        signal = 'SELL'
        logger.info(f"SELL signal detected for {symbol} {timeframe} at {current_price}")
        
        # Telegram bildirimi gönder
        if send_trade_signal(user_settings, signal, current_price, timestamp):
            logger.info(f"Telegram notification sent for SELL signal")
        
        # API key ve secret varsa işlem yap
        if user_settings.get('api_key') and user_settings.get('api_secret'):
            if execute_trade(user_settings, signal, current_price):
                logger.info(f"Trade executed: SELL {symbol} at {current_price}")
            else:
                logger.error(f"Failed to execute trade")
    
    else:
        logger.info(f"No trading signal for {symbol} {timeframe} at this time")

def get_signal(symbol, timeframe):
    """Belirli bir sembol ve timeframe için sinyal üret"""
    try:
        # OHLCV verilerini al
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        query = '''
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = ? AND timeframe = ?
        ORDER BY timestamp DESC
        LIMIT 100
        '''
        
        cursor.execute(query, (symbol, timeframe))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None
            
        # Veriyi DataFrame'e dönüştür
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Teknik analiz göstergelerini hesapla
        df['ATR'] = ta.ATR(df['high'], df['low'], df['close'], timeperiod=atr_period)
        df['Supertrend'] = generateSupertrend(df['close'], df['high'], df['low'], atr_period, atr_multiplier)
        
        # Son sinyali kontrol et
        last_signal = None
        if df['Supertrend'].iloc[-1] > df['close'].iloc[-1]:
            last_signal = 'SELL'
        elif df['Supertrend'].iloc[-1] < df['close'].iloc[-1]:
            last_signal = 'BUY'
            
        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'signal': last_signal,
            'price': df['close'].iloc[-1],
            'timestamp': df['timestamp'].iloc[-1]
        }
    except Exception as e:
        logger.error(f"Sinyal üretme hatası: {str(e)}")
        return None

def notify_users(signal):
    """Sinyali alan kullanıcılara bildirim gönder"""
    if not signal:
            return
        
    app = create_app()
    with app.app_context():
        # Sinyal ile eşleşen kullanıcı ayarlarını bul
        matching_settings = TradingSettings.query.filter_by(
            symbol=signal['symbol'],
            timeframe=signal['timeframe'],
            binance_active=True
        ).all()
        
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        for setting in matching_settings:
            user = User.query.get(setting.user_id)
            if not user or not user.telegram_chat_id:
                continue
                
            # Mesaj oluştur
            message = (
                f"🚨 Yeni Sinyal!\n"
                f"Sembol: {signal['symbol']}\n"
                f"Zaman Dilimi: {signal['timeframe']}\n"
                f"Sinyal: {signal['signal']}\n"
                f"Fiyat: {signal['price']}\n"
                f"Kaldıraç: {setting.leverage}x\n"
                f"Stop Loss: %{setting.stop_loss}\n"
                f"Take Profit: %{setting.take_profit}"
            )
            
            try:
                bot.send_message(chat_id=user.telegram_chat_id, text=message)
        
                # Eğer API bilgileri varsa işlem yap
                if user.api_key and user.api_secret and user.balance > 0:
                    execute_trade(user, signal, setting)
                    
            except Exception as e:
                logger.error(f"Bildirim gönderme hatası: {str(e)}")

def execute_trade(user, signal, settings):
    """Binance üzerinde işlem yap"""
    try:
        # Binance API bağlantısı
        exchange = ccxt.binance({
            'apiKey': user.api_key,
            'secret': user.api_secret,
            'enableRateLimit': True
        })
        
        # İşlem miktarını hesapla (bakiye * kaldıraç)
        amount = user.balance * settings.leverage
        
        if signal['signal'] == 'BUY':
            # Alış işlemi
            order = exchange.create_market_buy_order(
                symbol=signal['symbol'],
                amount=amount
            )
            
            # Stop loss ve take profit emirlerini yerleştir
            stop_price = order['price'] * (1 - settings.stop_loss/100)
            take_profit_price = order['price'] * (1 + settings.take_profit/100)
            
            exchange.create_order(
                symbol=signal['symbol'],
                type='stop_loss_limit',
                side='sell',
                amount=amount,
                price=stop_price,
                params={'stopPrice': stop_price}
            )
            
            exchange.create_order(
                symbol=signal['symbol'],
                type='limit',
                side='sell',
                amount=amount,
                price=take_profit_price
            )
            
        elif signal['signal'] == 'SELL':
            # Satış işlemi
            order = exchange.create_market_sell_order(
                symbol=signal['symbol'],
                amount=amount
            )
            
            # Stop loss ve take profit emirlerini yerleştir
            stop_price = order['price'] * (1 + settings.stop_loss/100)
            take_profit_price = order['price'] * (1 - settings.take_profit/100)
            
            exchange.create_order(
                symbol=signal['symbol'],
                type='stop_loss_limit',
                side='buy',
                amount=amount,
                price=stop_price,
                params={'stopPrice': stop_price}
            )
            
            exchange.create_order(
                symbol=signal['symbol'],
                type='limit',
                side='buy',
                amount=amount,
                price=take_profit_price
            )
    
    except Exception as e:
        logger.error(f"İşlem hatası: {str(e)}")

def run_binance(settings_id):
    app = create_app()
    with app.app_context():
        settings = TradingSettings.query.get(settings_id)
        if not settings or not settings.binance_active:
            logger.info(f"Binance işlemleri aktif değil veya ayar bulunamadı (id={settings_id})")
            return
        user = User.query.get(settings.user_id)
        if not user or not user.api_key or not user.api_secret or not user.balance:
            logger.info(f"Kullanıcı API bilgileri eksik (id={settings.user_id})")
            return
        # PID dosyasına yaz
        with open(f"binance_pid_{settings_id}.txt", "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"Binance işlemleri başlatıldı (settings_id={settings_id})")
        # Burada sürekli işlem/sinyal döngüsü başlatabilirsin
        while settings.binance_active:
            # Sinyal ve trade işlemleri burada
            process_user_data({
                'user_id': user.id,
                'username': user.username,
                'api_key': user.api_key,
                'api_secret': user.api_secret,
                'telegram_chat_id': user.telegram_chat_id,
                'symbol': settings.symbol,
                'timeframe': settings.timeframe,
                'leverage': settings.leverage,
                'stop_loss': settings.stop_loss,
                'take_profit': settings.take_profit,
                'balance': user.balance
            })
            time.sleep(60)  # Her dakikada bir kontrol
            db.session.refresh(settings)
        logger.info(f"Binance işlemleri durduruldu (settings_id={settings_id})")


def run_telegram(settings_id):
    app = create_app()
    with app.app_context():
        settings = TradingSettings.query.get(settings_id)
        if not settings or not settings.telegram_active:
            logger.info(f"Telegram sinyali aktif değil veya ayar bulunamadı (id={settings_id})")
            return
        user = User.query.get(settings.user_id)
        if not user or not user.telegram_chat_id:
            logger.info(f"Kullanıcı telegram chat id eksik (id={settings.user_id})")
            return
        # PID dosyasına yaz
        with open(f"telegram_pid_{settings_id}.txt", "w") as f:
            f.write(str(os.getpid()))
        logger.info(f"Telegram sinyali başlatıldı (settings_id={settings_id})")
        # Burada sürekli sinyal döngüsü başlatabilirsin
        while settings.telegram_active:
            # Sinyal işlemleri burada
            process_user_data({
                'user_id': user.id,
                'username': user.username,
                'api_key': user.api_key,
                'api_secret': user.api_secret,
                'telegram_chat_id': user.telegram_chat_id,
                'symbol': settings.symbol,
                'timeframe': settings.timeframe,
                'leverage': settings.leverage,
                'stop_loss': settings.stop_loss,
                'take_profit': settings.take_profit,
                'balance': user.balance
            })
            time.sleep(60)
            db.session.refresh(settings)
        logger.info(f"Telegram sinyali durduruldu (settings_id={settings_id})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['binance', 'telegram'], required=True)
    parser.add_argument('--settings_id', type=int, required=True)
    args = parser.parse_args()

    if args.mode == 'binance':
        run_binance(args.settings_id)
    elif args.mode == 'telegram':
        run_telegram(args.settings_id)

if __name__ == "__main__":
    main()