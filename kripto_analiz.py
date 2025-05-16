import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import talib as ta
import math
import sqlite3
import argparse
import concurrent.futures
from itertools import product
import sys

# Komut satırı argümanlarını tanımla
parser = argparse.ArgumentParser(description='Kripto para analizi')
parser.add_argument('--days', type=int, default=730, help='Veri çekilecek gün sayısı (geçmişe doğru)')
parser.add_argument('--mode', type=str, choices=['collect', 'analyze'], required=True,
                    help='Çalışma modu: collect (veri toplama) veya analyze (analiz)')
parser.add_argument('--batch', type=int, choices=[1, 2, 3], help='Analiz grubu (1-3)')
args = parser.parse_args()

# Kaç gün geriye gideceğimiz
ANALYSIS_DAYS = args.days

# Sembol listelerini gruplara böl
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "SOL/USDT", "DOT/USDT", "AVAX/USDT", "1000SHIB/USDT",
    "LINK/USDT", "UNI/USDT", "ATOM/USDT", "LTC/USDT", "ETC/USDT"
]

SYMBOL_NAMES = [s.split('/')[0] for s in SYMBOLS]

# Sembolleri 3 gruba böl
SYMBOL_GROUPS = [
    SYMBOLS[0:5],
    SYMBOLS[5:10],
    SYMBOLS[10:15]
]

SYMBOL_NAME_GROUPS = [
    SYMBOL_NAMES[0:5],
    SYMBOL_NAMES[5:10],
    SYMBOL_NAMES[10:15]
]

TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]

# ATR parametreleri için aralıklar
ATR_PERIODS = range(10, 31, 2)  # 10'dan 30'a 2'şer artarak
ATR_MULTIPLIERS = [x / 10 for x in range(10, 31, 2)]  # 1.0'dan 3.0'a 0.2'şer artarak


# Veritabanı bağlantısı oluşturma
def create_db_connection():
    conn = sqlite3.connect('crypto_data.db')
    cursor = conn.cursor()

    # Gerekli tabloları oluşturma
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
        volume REAL,
        UNIQUE(symbol, timestamp, timeframe)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        leverage REAL NOT NULL,
        stop_percentage REAL NOT NULL,
        kar_al_percentage REAL NOT NULL,
        atr_period INTEGER NOT NULL,
        atr_multiplier REAL NOT NULL,
        successful_trades INTEGER NOT NULL,
        unsuccessful_trades INTEGER NOT NULL,
        final_balance REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(symbol, timeframe)
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
def save_results_to_db(symbol, timeframe, leverage, stop_percentage, kar_al_percentage, atr_period, atr_multiplier,
                       successful_trades, unsuccessful_trades, final_balance):
    try:
        conn = sqlite3.connect('crypto_data.db')
        cursor = conn.cursor()

        # Önce eski sonucu sil
        cursor.execute('''
        DELETE FROM analysis_results 
        WHERE symbol = ? AND timeframe = ?
        ''', (symbol, timeframe))

        # Yeni sonucu ekle
        cursor.execute('''
        INSERT INTO analysis_results 
        (symbol, timeframe, leverage, stop_percentage, kar_al_percentage, atr_period, atr_multiplier, successful_trades, unsuccessful_trades, final_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
        symbol, timeframe, leverage, stop_percentage, kar_al_percentage, atr_period, atr_multiplier, successful_trades,
        unsuccessful_trades, final_balance))

        conn.commit()
    except Exception as e:
        print(f"Veritabanı hatası: {str(e)}")
    finally:
        conn.close()


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
        # initialization of string to ""
        new = ""

        # traverse in the string
        for x in s:
            new += x

            # return string
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


def collect_data_for_symbol(symbol):
    """Tek bir sembol için tüm timeframe'lerde veri topla"""
    print(f"\n{symbol} için veri toplama başlıyor...")

    end_date = int(datetime.now().timestamp() * 1000)
    start_date = end_date - (ANALYSIS_DAYS * 86400 * 1000)

    conn = create_db_connection()
    cursor = conn.cursor()

    for timeframe in TIMEFRAMES:
        try:
            print(f"{symbol} - {timeframe} verisi çekiliyor...")
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=start_date, limit=1000)

            if bars:
                for bar in bars:
                    cursor.execute('''
                    INSERT OR REPLACE INTO ohlcv_data 
                    (symbol, timestamp, timeframe, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        symbol.split('/')[0],
                        bar[0],
                        timeframe,
                        bar[1],
                        bar[2],
                        bar[3],
                        bar[4],
                        bar[5]
                    ))

                conn.commit()
                print(f"{symbol} - {timeframe}: {len(bars)} mum verisi kaydedildi")

            time.sleep(1)  # Rate limit için bekle

        except Exception as e:
            print(f"Hata ({symbol} - {timeframe}): {str(e)}")
            continue

    conn.close()


def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    try:
        atr = ta.ATR(high_array, low_array, close_array, atr_period)
    except Exception as Error:
        print("[ERROR] ", Error)

    previous_final_upperband = 0
    previous_final_lowerband = 0
    final_upperband = 0
    final_lowerband = 0
    previous_close = 0
    previous_supertrend = 0
    supertrend = []
    supertrendc = 0

    for i in range(0, len(close_array)):
        if np.isnan(close_array[i]):
            pass
        else:
            highc = high_array[i]
            lowc = low_array[i]
            atrc = atr[i]
            closec = close_array[i]

            if math.isnan(atrc):
                atrc = 0

            basic_upperband = (highc + lowc) / 2 + atr_multiplier * atrc
            basic_lowerband = (highc + lowc) / 2 - atr_multiplier * atrc

            if basic_upperband < previous_final_upperband or previous_close > previous_final_upperband:
                final_upperband = basic_upperband
            else:
                final_upperband = previous_final_upperband

            if basic_lowerband > previous_final_lowerband or previous_close < previous_final_lowerband:
                final_lowerband = basic_lowerband
            else:
                final_lowerband = previous_final_lowerband

            if previous_supertrend == previous_final_upperband and closec <= final_upperband:
                supertrendc = final_upperband
            else:
                if previous_supertrend == previous_final_upperband and closec >= final_upperband:
                    supertrendc = final_lowerband
                else:
                    if previous_supertrend == previous_final_lowerband and closec >= final_lowerband:
                        supertrendc = final_lowerband
                    elif previous_supertrend == previous_final_lowerband and closec <= final_lowerband:
                        supertrendc = final_upperband

            supertrend.append(supertrendc)

            previous_close = closec
            previous_final_upperband = final_upperband
            previous_final_lowerband = final_lowerband
            previous_supertrend = supertrendc

    return supertrend

def backtest_strategy(df, atr_period, atr_multiplier):
    """Stratejiyi test et ve sonuçları döndür"""
    bakiye = 100.0
    leverage_ust = 50
    yuzde_ust = 50
    yuzde = 0
    kar_al_ust = 50
    kar_al = 0
    basarili = 0
    basarisiz = 0
    en_iyi_sonuc = {
        'leverage': 0,
        'stop_percentage': 0,
        'kar_al_percentage': 0,
        'successful_trades': 0,
        'unsuccessful_trades': 0,
        'final_balance': 0
    }

    # DataFrame'i numpy array'e çevir
    close_array = np.asarray(df["close"]).astype(float)
    high_array = np.asarray(df["high"]).astype(float)
    low_array = np.asarray(df["low"]).astype(float)

    # Supertrend hesapla
    supertrend = generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier)

    # Kar al yüzdesi döngüsü
    kar_al = 0
    while kar_al < kar_al_ust:
        # Yüzde döngüsü
        yuzde = 0.5
        while yuzde <= yuzde_ust:
            # Kaldıraç döngüsü
            leverage = 1
            while leverage <= leverage_ust:
                bakiye = 100.0
                x = 3
                stop = 0
                kar_stop = 0
                likit = 0
                basarili = 0
                basarisiz = 0
                a = 0

                # Ana işlem döngüsü
                while x < len(close_array):
                    son_kapanis = close_array[x - 2]
                    onceki_kapanis = close_array[x - 3]
                    son_supertrend = supertrend[x - 2]
                    onceki_supertrend = supertrend[x - 3]

                    # Long pozisyon sinyali
                    if son_kapanis > son_supertrend and onceki_kapanis < onceki_supertrend:
                        giris = float(df["open"].iloc[x])
                        y = 0
                        while True:
                            if x + y >= len(close_array):
                                break

                            # Likit olma durumu
                            if ((float(df["low"].iloc[x + y]) - giris) / giris * 100 <= (-1) * (90 / float(leverage))):
                                bakiye = 0
                                likit = 1
                                basarisiz += 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Stop olma durumu
                            if ((float(df["high"].iloc[x + y]) - giris) / giris * 100 >= yuzde):
                                basarili += 1
                                bakiye = bakiye - bakiye * yuzde / 100 * leverage
                                stop = 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Kar alma durumu
                            if ((float(df["low"].iloc[x + y]) - giris) / giris * 100 >= kar_al * (-1)) and kar_al != 0:
                                basarili += 1
                                bakiye = bakiye + bakiye * kar_al / 100 * leverage
                                kar_stop = 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Sinyal ile çıkış
                            if close_array[x + y - 2] < supertrend[x + y - 2] and close_array[x + y - 3] > supertrend[
                                x + y - 3]:
                                son = bakiye + bakiye * (float(df["open"].iloc[x + y]) - giris) / giris * leverage
                                if son < bakiye:
                                    basarisiz += 1
                                else:
                                    basarili += 1
                                bakiye = son
                                x = x + y if y == 0 else x + y - 1
                                break

                            y += 1

                    # Short pozisyon sinyali
                    elif son_kapanis < son_supertrend and onceki_kapanis > onceki_supertrend:
                        giris = float(df["open"].iloc[x])
                        y = 0
                        while True:
                            if x + y >= len(close_array):
                                break

                            # Likit olma durumu
                            if ((float(df["high"].iloc[x + y]) - giris) / giris * 100 >= (90 / float(leverage))):
                                bakiye = 0
                                likit = 1
                                basarisiz += 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Stop olma durumu
                            if ((float(df["low"].iloc[x + y]) - giris) / giris * 100 <= yuzde * (-1)):
                                basarili += 1
                                bakiye = bakiye - bakiye * yuzde / 100 * leverage
                                stop = 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Kar alma durumu
                            if ((float(df["high"].iloc[x + y]) - giris) / giris * 100 <= kar_al) and kar_al != 0:
                                basarili += 1
                                bakiye = bakiye + bakiye * kar_al / 100 * leverage
                                kar_stop = 1
                                x = x + y if y == 0 else x + y - 1
                                break

                            # Sinyal ile çıkış
                            if close_array[x + y - 2] > supertrend[x + y - 2] and close_array[x + y - 3] < supertrend[
                                x + y - 3]:
                                son = bakiye + bakiye * (float(df["open"].iloc[x + y]) - giris) / giris * (
                                    -1) * leverage
                                if son < bakiye:
                                    basarisiz += 1
                                else:
                                    basarili += 1
                                bakiye = son
                                x = x + y if y == 0 else x + y - 1
                                break

                            y += 1

                    x += 1
                    if likit == 1:
                        break

                # En iyi sonucu güncelle
                if bakiye > en_iyi_sonuc['final_balance']:
                    en_iyi_sonuc = {
                        'leverage': leverage,
                        'stop_percentage': yuzde,
                        'kar_al_percentage': kar_al,
                        'successful_trades': basarili,
                        'unsuccessful_trades': basarisiz,
                        'final_balance': bakiye,
                        'atr_period': atr_period,
                        'atr_multiplier': atr_multiplier
                    }

                if likit == 1 or stop == 0 or kar_stop == 0:
                    break
                leverage += 1

            if stop == 0 or kar_stop == 0:
                break
            yuzde += 0.5

        if stop == 0 or kar_stop == 0:
            break
        kar_al += 0.5

    return en_iyi_sonuc


def analyze_symbol_timeframe(symbol, timeframe):
    """Tek bir sembol ve timeframe için analiz yap"""
    try:
        conn = sqlite3.connect('crypto_data.db')
        cursor = conn.cursor()

        # Verileri çek
        cursor.execute('''
        SELECT timestamp, open, high, low, close, volume 
        FROM ohlcv_data 
        WHERE symbol = ? AND timeframe = ? 
        ORDER BY timestamp
        ''', (symbol, timeframe))

        rows = cursor.fetchall()
        if not rows:
            print(f"Veri bulunamadı: {symbol} - {timeframe}")
            return None

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

        best_result = None
        # Her ATR kombinasyonu için test et
        for atr_period, atr_multiplier in product(ATR_PERIODS, ATR_MULTIPLIERS):
            print(f"Test ediliyor: {symbol} - {timeframe} - ATR({atr_period}, {atr_multiplier})")
            result = backtest_strategy(df, atr_period, atr_multiplier)
            if not best_result or result['final_balance'] > best_result['final_balance']:
                best_result = result
                best_result['symbol'] = symbol
                best_result['timeframe'] = timeframe

        if best_result:
            # En iyi sonucu veritabanına kaydet
            save_results_to_db(**best_result)
            print(f"En iyi sonuç kaydedildi: {symbol} - {timeframe}")
            print(f"Bakiye: {best_result['final_balance']}, Kaldıraç: {best_result['leverage']}, "
                  f"Stop: {best_result['stop_percentage']}, Kar Al: {best_result['kar_al_percentage']}")

        return best_result

    except Exception as e:
        print(f"Analiz hatası ({symbol} - {timeframe}): {str(e)}")
        return None
    finally:
        conn.close()


def parallel_analysis(symbol_group):
    """Bir grup sembol için paralel analiz yap"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for symbol in symbol_group:
            for timeframe in TIMEFRAMES:
                symbol_name = symbol.split('/')[0]
                futures.append(
                    executor.submit(analyze_symbol_timeframe, symbol_name, timeframe)
                )

        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if result:
                    print(f"Analiz tamamlandı: {result['symbol']} - {result['timeframe']}")
            except Exception as e:
                print(f"Analiz hatası: {str(e)}")


if __name__ == "__main__":
    if args.mode == 'collect':
        print("Veri toplama modu başlatılıyor...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            executor.map(collect_data_for_symbol, SYMBOLS)
        print("Veri toplama tamamlandı.")

    elif args.mode == 'analyze':
        if not args.batch:
            print("Analiz için --batch parametresi gerekli (1-3)")
            sys.exit(1)

        batch_idx = args.batch - 1
        print(f"Analiz modu başlatılıyor... (Grup {args.batch})")
        print(f"İşlenecek semboller: {SYMBOL_GROUPS[batch_idx]}")

        parallel_analysis(SYMBOL_GROUPS[batch_idx])
        print(f"Grup {args.batch} analizi tamamlandı.")