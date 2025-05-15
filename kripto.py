import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import talib as ta
import math
import sqlite3
import requests
import os
import argparse  # Komut satırı argümanları için eklendi

# Web sunucusu bilgileri
DB_URL = 'https://www.aryazilimdanismanlik.com/kripto/crypto_data.db'
LOCAL_DB_PATH = 'temp_crypto_data.db'

# Komut satırı argümanlarını tanımla
parser = argparse.ArgumentParser(description='Kripto para analizi')
parser.add_argument('--days', type=int, default=730, help='Veri çekilecek gün sayısı (geçmişe doğru)')
args = parser.parse_args()

# Kaç gün geriye gideceğimiz
ANALYSIS_DAYS = args.days

# Ana sembol listesi - analiz edilecek semboller
symbols = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
]

# Sembol isimlerini USDT olmadan al (veritabanı kayıtları için)
symbolName = [
    "BTC", "ETH", "BNB", "XRP", "ADA",
    "DOGE", "SOL", "DOT", "AVAX", "1000SHIB",
    "LINK", "UNI", "ATOM", "LTC", "ETC"
]


def download_db():
    try:
        response = requests.get(DB_URL)
        response.raise_for_status()  # HTTP hatalarını kontrol et
        with open(LOCAL_DB_PATH, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Veritabanı indirme hatası: {str(e)}")
        return False


def upload_db():
    try:
        with open(LOCAL_DB_PATH, 'rb') as f:
            files = {'file': f}
            response = requests.post(DB_URL, files=files)
            response.raise_for_status()
        return True
    except Exception as e:
        print(f"Veritabanı yükleme hatası: {str(e)}")
        return False


# Veritabanı bağlantısı oluşturma
def create_db_connection():
    if not download_db():
        raise Exception("Veritabanı indirilemedi")

    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results_no_atr (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        leverage REAL NOT NULL,
        stop_percentage REAL NOT NULL,
        kar_al_percentage REAL NOT NULL,
        successful_trades INTEGER NOT NULL,
        unsuccessful_trades INTEGER NOT NULL,
        final_balance REAL NOT NULL,
        success_rate REAL NOT NULL,
        optimization_type TEXT NOT NULL,  -- 'balance' veya 'success_rate'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, timeframe, optimization_type)
    )
    ''')

    conn.commit()
    return conn


# Veritabanına veri ekleme fonksiyonu
def save_to_db(conn, symbol, df, timeframe):
    cursor = conn.cursor()
    for i in range(len(df)):
        cursor.execute('''
        INSERT INTO ohlcv_data (symbol, timestamp, timeframe, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol,
            df["timestamp"][i],
            timeframe,
            df["open"][i],
            df["high"][i],
            df["low"][i],
            df["close"][i],
            df["volume"][i]
        ))
    conn.commit()


# Analiz sonuçlarını veritabanına kaydetme
def save_results_to_db(symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
                       successful_trades, unsuccessful_trades, final_balance, optimization_type='balance'):
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()

        total_trades = successful_trades + unsuccessful_trades
        success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0

        # Önce eski sonucu sil
        cursor.execute('''
        DELETE FROM analysis_results_no_atr 
        WHERE symbol = ? AND timeframe = ? AND optimization_type = ?
        ''', (symbol, timeframe, optimization_type))

        # Yeni sonucu ekle
        cursor.execute('''
        INSERT INTO analysis_results_no_atr 
        (symbol, timeframe, leverage, stop_percentage, kar_al_percentage, 
         successful_trades, unsuccessful_trades, final_balance, success_rate, optimization_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
              successful_trades, unsuccessful_trades, final_balance, success_rate, optimization_type))

        conn.commit()
        conn.close()

        # Değişiklikleri sunucuya yükle
        if not upload_db():
            raise Exception("Veritabanı sunucuya yüklenemedi")

    except Exception as e:
        print(f"Veritabanı hatası: {str(e)}")
    finally:
        if os.path.exists(LOCAL_DB_PATH):
            os.remove(LOCAL_DB_PATH)


# API CONNECT
exchange = ccxt.binance({
    "apiKey": 'G2dI1suDiH3bCKo1lpx1Ho4cdTjmWh9eQEUSajcshC1rcQ0T1yATZnKukHiqo6IN',
    "secret": 'ow4J1QLRTXhzuhtBcFNOUSPq2uRYhrkqHaLri0zdAiMhoDCfJgEfXz0mSwvgpnPx',
    'options': {
        'defaultType': 'future'
    },
    'enableRateLimit': True
})


def lim_olustur(zamanAraligi):
    lst = []
    lim = 0
    for i in zamanAraligi:
        lst.append(i)

    def convert(s):
        new = ""
        for x in s:
            new += x
        return new

    periyot = ""
    mum = ""
    if lst[len(lst) - 1] == 'm':
        list = convert(lst)
        a = list.split("m")
        mum = a[0]
        lim = 2 * 365 * (float(mum) * 60 * 24)
        bekleme = int(a[0]) * 60
        periyot = "%M"
    elif lst[len(lst) - 1] == 'h':
        list = convert(lst)
        a = list.split("h")
        mum = a[0]
        lim = 2 * 365 * (float(mum) * 24)
        bekleme = int(a[0]) * 60 * 60
        periyot = "%H"
    elif lst[len(lst) - 1] == 'd':
        list = convert(lst)
        a = list.split("d")
        mum = a[0]
        lim = 2 * 365 * float(mum)
        bekleme = int(a[0]) * 60 * 60 * 24
        periyot = "%d"
    elif lst[len(lst) - 1] == 'w':
        list = convert(lst)
        a = list.split("w")
        mum = a[0]
        lim = 2 * 52 * float(mum)
        bekleme = int(a[0]) * 60 * 60 * 24 * 7
    lim = lim * 1
    return lim


async def main():
    # Veritabanı bağlantısı oluştur
    conn = create_db_connection()

    for symbol in symbols:
        s = symbols.index(symbol)  # Her sembol için doğru indeks değerini al
        a = 0
        # Bugünün tarihini al ve ondan geriye doğru git
        end_date = int(datetime.now().timestamp() * 1000)
        # Belirtilen gün sayısı kadar geriye git
        start_date = end_date - (ANALYSIS_DAYS * 86400 * 1000)  # Belirtilen gün * 86400 saniye * 1000 milisaniye

        print(f"\n{symbol} için veri çekme işlemi başlıyor...")
        print(f"Başlangıç Tarihi: {datetime.fromtimestamp(start_date / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Bitiş Tarihi: {datetime.fromtimestamp(end_date / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Toplam {ANALYSIS_DAYS} gün için veri çekilecek\n")

        # ... (mevcut kod devam ediyor)

        # Verileri veritabanına kaydet
        try:
            # Boş olmayan DataFrame'leri kontrol et
            if not df_1m.empty:
                save_to_db(conn, symbolName[s], df_1m, "1m")
            if not df_3m.empty:
                save_to_db(conn, symbolName[s], df_3m, "3m")
            if not df_5m.empty:
                save_to_db(conn, symbolName[s], df_5m, "5m")
            if not df_15m.empty:
                save_to_db(conn, symbolName[s], df_15m, "15m")
            if not df_30m.empty:
                save_to_db(conn, symbolName[s], df_30m, "30m")
            if not df_1h.empty:
                save_to_db(conn, symbolName[s], df_1h, "1h")
            if not df_2h.empty:
                save_to_db(conn, symbolName[s], df_2h, "2h")
            if not df_4h.empty:
                save_to_db(conn, symbolName[s], df_4h, "4h")
            if not df_1d.empty:
                save_to_db(conn, symbolName[s], df_1d, "1d")
        except Exception as e:
            print(f"Veritabanına kaydetme hatası: {e}")

        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe="1w", since=None, limit=int(lim_olustur("1w")))
            df_1w = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
            save_to_db(conn, symbolName[s], df_1w, "1w")
        except Exception as e:
            print(f"1w veri çekme ve kaydetme hatası: {e}")

        # Analiz sonuçlarını veritabanına kaydet
        save_results_to_db(symbolName[s], "1m", float(lev_1m), float(yuz_1m), float(kar_yuz_1m),
                           bli_1m, bsiz_1m, float(bky_1m), 'balance')
        save_results_to_db(symbolName[s], "1m", float(m1[1][0]), float(m1[1][1]), float(m1[1][1]),
                           m1[1][2], m1[1][3], float(m1[1][4]), 'success_rate')
        # ... (diğer timeframe'ler için de aynı şekilde devam ediyor)

    # Veritabanı bağlantısını kapat
    conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())