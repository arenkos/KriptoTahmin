import sqlite3
import ccxt
import time
import pandas as pd

# --- Sembol listesi ---
symbols = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
]

# --- Timeframe limitleri ---
timeframes = {
    "1m": 1440, "3m": 480, "5m": 288, "15m": 96,
    "30m": 48, "1h": 24, "2h": 12, "4h": 6, "1d": 1
}

# --- DB bağlantısı ve tablo oluşturma ---
def create_db_connection():
    conn = sqlite3.connect('crypto_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ohlcv_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            timestamp INTEGER,
            timeframe TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL
        )
    ''')
    conn.commit()
    return conn

# --- Binance API bağlantısı ---
exchange = ccxt.binance({
    "apiKey": 'G2dI1suDiH3bCKo1lpx1Ho4cdTjmWh9eQEUSajcshC1rcQ0T1yATZnKukHiqo6IN',
    "secret": 'ow4J1QLRTXhzuhtBcFNOUSPq2uRYhrkqHaLri0zdAiMhoDCfJgEfXz0mSwvgpnPx',
    'options': {
        'defaultType': 'future'
    },
    'enableRateLimit': True
})

# --- Son kaydedilen timestamp'i getir ---
def get_last_timestamp(conn, symbol, timeframe):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT MAX(timestamp) FROM ohlcv_data
        WHERE symbol = ? AND timeframe = ?
    ''', (symbol, timeframe))
    result = cursor.fetchone()
    return result[0] if result and result[0] else None

# --- Veriyi DB'ye ekle ---
def insert_ohlcv_data(conn, symbol, timeframe, data):
    cursor = conn.cursor()
    for row in data:
        cursor.execute('''
            INSERT INTO ohlcv_data (symbol, timestamp, timeframe, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, row[0], timeframe, row[1], row[2], row[3], row[4], row[5]))
    conn.commit()

# --- Tüm verileri çek ve kaydet ---
def update_data():
    conn = create_db_connection()
    now = int(time.time() * 1000)

    for symbol in symbols:
        for timeframe, limit in timeframes.items():
            print(f"\n⏳ {symbol} - {timeframe} verileri kontrol ediliyor...")

            last_ts = get_last_timestamp(conn, symbol, timeframe)
            since = last_ts + 1 if last_ts else now - 30 * 24 * 60 * 60 * 1000  # 30 gün öncesinden başla

            while since < now:
                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
                    if not bars:
                        break

                    insert_ohlcv_data(conn, symbol, timeframe, bars)
                    since = bars[-1][0] + 1  # Son timestamp'ten devam et
                    print(f"✔ {symbol} - {timeframe} - {len(bars)} kayıt eklendi.")

                    time.sleep(0.4)  # API sınırı için bekleme

                except Exception as e:
                    print(f"⚠ {symbol} - {timeframe} veri çekilirken hata: {e}")
                    break

    conn.close()
    print("\n✅ Tüm veriler başarıyla güncellendi.")

# --- Çalıştır ---
update_data()