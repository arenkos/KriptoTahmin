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
def save_results_to_db(symbol, timeframe, leverage, stop_percentage, atr_period, atr_multiplier,
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
        (symbol, timeframe, leverage, stop_percentage, atr_period, atr_multiplier, successful_trades, unsuccessful_trades, final_balance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
        symbol, timeframe, leverage, stop_percentage, atr_period, atr_multiplier, successful_trades,
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


def calculateATR(high_array, low_array, close_array, period):
    """
    Manuel ATR (Average True Range) hesaplama fonksiyonu
    """
    atr = []
    tr_list = []
    
    for i in range(len(close_array)):
        if i == 0:
            # İlk eleman için True Range sadece High - Low
            tr = high_array[i] - low_array[i]
        else:
            # Diğer elemanlar için True Range hesabı
            tr1 = high_array[i] - low_array[i]
            tr2 = abs(high_array[i] - close_array[i-1])
            tr3 = abs(low_array[i] - close_array[i-1])
            tr = max(tr1, tr2, tr3)
        
        tr_list.append(tr)
        
        if i < period:
            # İlk period-1 eleman için ATR hesabı yapılmaz
            atr.append(float('nan'))
        elif i == period:
            # period. eleman için ilk ATR hesabı (basit ortalama)
            atr.append(sum(tr_list[:period]) / period)
        else:
            # Diğer elemanlar için ATR hesabı (Wilder's smoothing method)
            atr.append(((period - 1) * atr[-1] + tr) / period)
    
    return atr


def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    try:
        # ta modülü yerine kendi ATR hesaplama fonksiyonumuzu kullanıyoruz
        atr = calculateATR(high_array, low_array, close_array, atr_period)
    except Exception as Error:
        print("[ERROR] ", Error)
        # Hata durumunda boş bir liste döndür
        return [0] * len(close_array)

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
    # Değişkenlerin doğru yerlerinde tanımlanması
    bakiye = 100.0
    leverage_ust = 50
    lev_ust = 50
    yuzde_ust = 50
    yuzde = 0
    yuz_ust = 50
    islemsonu = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    basarili_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    basarisiz_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    
    opn = df["open"]
    high = df["high"]
    low = df["low"]
    clse = df["close"]

    close_array = np.asarray(clse)
    high_array = np.asarray(high)
    low_array = np.asarray(low)

    close_array = close_array.astype(float)
    high_array = high_array.astype(float)
    low_array = low_array.astype(float)
    
    supertrend = generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier)
    
    yuzde = 0
    while yuzde <= yuzde_ust:
        stop = 0
        likit = 0
        leverage = 1
        a = 0
        
        # Kaldıraç döngüsü
        while leverage <= leverage_ust:
            bakiye = 100.0
            x = atr_period + 2 + 3
            stop = 0
            likit = 0
            islem = 0
            basarili = 0
            basarisiz = 0
            
            # Ana işlem döngüsü
            while x < len(df) - (atr_period + 2 + 3):
                depo = 0
                son_kapanis = close_array[x - 2]
                onceki_kapanis = close_array[x - 3]
                son_supertrend_deger = supertrend[x - 2]
                onceki_supertrend_deger = supertrend[x - 3]
                
                # Renk yeşile dönüyor, Supertrend yükselişe geçti
                if son_kapanis > son_supertrend_deger and onceki_kapanis < onceki_supertrend_deger:
                    islem = islem + 1
                    giris = float(df["open"][x])
                    y = 0
                    
                    while True:
                        son_kapanis = close_array[x + y - 2]
                        onceki_kapanis = close_array[x + y - 3]
                        son_supertrend_deger = supertrend[x + y - 2]
                        onceki_supertrend_deger = supertrend[x + y - 3]

                        # Likit olma durumu
                        if ((float(df["low"][x + y]) - giris) / giris * 100 <= (-1) * (90 / float(leverage))):
                            bakiye = 0
                            likit = 1
                            basarisiz = basarisiz + 1
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        # Stop olma durumu
                        if ((float(df["high"][x + y]) - giris) / giris * 100 >= yuzde) and yuzde != 0:
                            basarili = basarili + 1
                            bakiye = bakiye - bakiye * yuzde / 100 * leverage
                            stop = 1
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        # Sinyal ile çıkış durumu
                        if son_kapanis < son_supertrend_deger and onceki_kapanis > onceki_supertrend_deger:
                            son = bakiye + bakiye * (float(df["open"][x + y]) - giris) / giris * leverage
                            if son < bakiye:
                                basarisiz = basarisiz + 1
                            else:
                                basarili = basarili + 1
                            bakiye = bakiye + bakiye * (float(df["open"][x + y]) - giris) / giris * leverage
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        y = y + 1

                        # Dizi sonunda döngüden çıkılsın
                        if (x + y) == len(df):
                            depo = x + y - 2
                            break

                # Renk kırmızıya dönüyor, Supertrend düşüşe geçti
                elif son_kapanis < son_supertrend_deger and onceki_kapanis > onceki_supertrend_deger:
                    islem = islem + 1
                    giris = float(df["open"][x])
                    y = 0
                    
                    while True:
                        son_kapanis = close_array[x + y - 2]
                        onceki_kapanis = close_array[x + y - 3]
                        son_supertrend_deger = supertrend[x + y - 2]
                        onceki_supertrend_deger = supertrend[x + y - 3]

                        # Likit olma durumu
                        if ((float(df["high"][x + y]) - giris) / giris * 100 >= (90 / float(leverage))):
                            bakiye = 0
                            likit = 1
                            basarisiz = basarisiz + 1
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        # Stop olma durumu
                        if ((float(df["low"][x + y]) - giris) / giris * 100 <= yuzde * (-1)) and yuzde != 0:
                            basarili = basarili + 1
                            bakiye = bakiye - bakiye * yuzde / 100 * leverage
                            stop = 1
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        # Sinyal ile çıkış durumu
                        if son_kapanis > son_supertrend_deger and onceki_kapanis < onceki_supertrend_deger:
                            son = bakiye + bakiye * (float(df["open"][x + y]) - giris) / giris * (-1) * leverage
                            if son < bakiye:
                                basarisiz = basarisiz + 1
                            else:
                                basarili = basarili + 1
                            bakiye = bakiye + bakiye * (float(df["open"][x + y]) - giris) / giris * (-1) * leverage
                            if y == 0:
                                x = x + y
                            else:
                                x = x + y - 1
                            break

                        y = y + 1

                        # Dizi sonunda döngüden çıkılsın
                        if (x + y) == len(df):
                            depo = x + y - 2
                            break

                x = x + 1

                # Likit durumu dizi döngüsünden çıkılsın
                if likit == 1:
                    leverage_ust = leverage
                    break

            islemsonu[int(leverage - 1)][a] = bakiye
            basarili_islem[int(leverage - 1)][a] = basarili
            basarisiz_islem[int(leverage - 1)][a] = basarisiz

            # Likit olduysa kaldıraç döngüsünden çıkılsın
            if likit == 1:
                leverage_ust = leverage
                while leverage < lev_ust:
                    islemsonu[int(leverage)][a] = 0
                    basarili_islem[int(leverage)][a] = 0
                    basarisiz_islem[int(leverage)][a] = 0
                    leverage = leverage + 1
                break
            basarili = 0
            basarisiz = 0
            leverage = leverage + 1

            # Stop çalışmadıysa yüzde döngüsünden çıkılsın
            if stop == 0:
                break

        lev = leverage_ust

        # Stop çalışmadıysa yüzde döngüsünden çıkılsın
        if stop == 0:
            yuzde_ust = yuzde
            while leverage_ust < lev_ust:
                b = a
                while b < yuz_ust * 2:
                    islemsonu[int(leverage_ust)][b] = 0
                    basarili_islem[int(leverage_ust)][b] = 0
                    basarisiz_islem[int(leverage_ust)][b] = 0
                    b = b + 1
                leverage_ust = leverage_ust + 1
            break

        yuzde = yuzde + 0.5
        a = a + 1
        leverage_ust = lev - 1

    # En iyi sonucu bul
    tahmin = []
    leverage = 0
    while leverage < lev_ust:
        tahmin.append(max(islemsonu[leverage]))
        leverage = leverage + 1

    leverage = 0
    while leverage < lev_ust:
        k = 1
        while k <= len(islemsonu[leverage]):
            if islemsonu[int(leverage)][int(k - 1)] == max(tahmin):
                return {
                    'leverage': leverage + 1,
                    'stop_percentage': k / 2,
                    'atr_period': atr_period,
                    'atr_multiplier': atr_multiplier,
                    'successful_trades': basarili_islem[leverage][k - 1],
                    'unsuccessful_trades': basarisiz_islem[leverage][k - 1],
                    'final_balance': islemsonu[int(leverage)][int(k - 1)]
                }
            k = k + 1
        leverage = leverage + 1


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
                  f"Stop: {best_result['stop_percentage']}, ATR Period: {best_result['atr_period']}, "
                  f"ATR Multiplier: {best_result['atr_multiplier']}")

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