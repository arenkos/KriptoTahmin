import time
import ccxt
import pandas as pd
import numpy as np
import struct
from datetime import datetime
import ta
import math
import sqlite3
import requests
import os
import argparse

# Web sunucusu bilgileri
# DB_URL = 'https://www.aryazilimdanismanlik.com/kripto/crypto_data.db'
LOCAL_DB_PATH = 'crypto_data.db'

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
        response.raise_for_status()
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
    conn = sqlite3.connect(LOCAL_DB_PATH)
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
            df["timestamp"].iloc[i],
            timeframe,
            df["open"].iloc[i],
            df["high"].iloc[i],
            df["low"].iloc[i],
            df["close"].iloc[i],
            df["volume"].iloc[i]
        ))
    conn.commit()


# Analiz sonuçlarını veritabanına kaydetme
def save_results_to_db(symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
                       atr_period, atr_multiplier, successful_trades, unsuccessful_trades,
                       final_balance, optimization_type='balance'):
    try:
        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()

        total_trades = successful_trades + unsuccessful_trades
        success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0

        # Önce eski sonucu sil
        cursor.execute('''
        DELETE FROM analysis_results 
        WHERE symbol = ? AND timeframe = ? AND optimization_type = ?
        ''', (symbol, timeframe, optimization_type))

        # Yeni sonucu ekle
        cursor.execute('''
        INSERT INTO analysis_results 
        (symbol, timeframe, leverage, stop_percentage, kar_al_percentage, 
         atr_period, atr_multiplier, successful_trades, unsuccessful_trades, 
         final_balance, success_rate, optimization_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
              atr_period, atr_multiplier, successful_trades, unsuccessful_trades,
              final_balance, success_rate, optimization_type))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Veritabanı hatası: {str(e)}")


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


def calculateATR(high_array, low_array, close_array, period):
    """
    Manuel ATR (Average True Range) hesaplama fonksiyonu
    """
    atr = []
    tr_list = []

    for i in range(len(close_array)):
        if i == 0:
            tr = high_array[i] - low_array[i]
        else:
            tr1 = high_array[i] - low_array[i]
            tr2 = abs(high_array[i] - close_array[i - 1])
            tr3 = abs(low_array[i] - close_array[i - 1])
            tr = max(tr1, tr2, tr3)

        tr_list.append(tr)

        if i < period - 1:
            atr.append(float('nan'))
        elif i == period - 1:
            atr.append(sum(tr_list[:period]) / period)
        else:
            atr.append(((period - 1) * atr[-1] + tr) / period)

    return atr


def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    try:
        atr = calculateATR(high_array, low_array, close_array, atr_period)
    except Exception as Error:
        print("[ERROR] ", Error)
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
        if np.isnan(close_array[i]) or np.isnan(atr[i]):
            supertrend.append(float('nan'))
            continue

        highc = high_array[i]
        lowc = low_array[i]
        atrc = atr[i]
        closec = close_array[i]

        if math.isnan(atrc):
            atrc = 0

        basic_upperband = (highc + lowc) / 2 + atr_multiplier * atrc
        basic_lowerband = (highc + lowc) / 2 - atr_multiplier * atrc

        if i == 0:
            final_upperband = basic_upperband
            final_lowerband = basic_lowerband
            supertrendc = basic_upperband
        else:
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
            elif previous_supertrend == previous_final_upperband and closec > final_upperband:
                supertrendc = final_lowerband
            elif previous_supertrend == previous_final_lowerband and closec >= final_lowerband:
                supertrendc = final_lowerband
            elif previous_supertrend == previous_final_lowerband and closec < final_lowerband:
                supertrendc = final_upperband

        supertrend.append(supertrendc)

        previous_close = closec
        previous_final_upperband = final_upperband
        previous_final_lowerband = final_lowerband
        previous_supertrend = supertrendc

    return supertrend


def deneme(zamanAraligi, df, lim):
    print(f"Supertrend ve Hacim BOT - {zamanAraligi}\n")

    if df.empty or len(df) < 50:
        print(f"Yetersiz veri: {len(df)} satır")
        return {
            'balance': {'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
                        'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
                        'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0},
            'success_rate': {'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
                             'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
                             'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0}
        }

    # Veri türlerini kontrol et ve dönüştür
    df = df.copy()
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['close'] = pd.to_numeric(df['close'], errors='coerce')

    # NaN değerleri kontrol et
    if df[['open', 'high', 'low', 'close']].isnull().any().any():
        print("NaN değerler bulundu, temizleniyor...")
        df = df.dropna(subset=['open', 'high', 'low', 'close'])

    if len(df) < 50:
        print("Temizleme sonrası yetersiz veri")
        return {
            'balance': {'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
                        'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
                        'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0},
            'success_rate': {'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
                             'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
                             'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0}
        }

    # Reset index after cleaning
    df = df.reset_index(drop=True)
    lim = len(df)

    close_array = df["close"].values.astype(float)
    high_array = df["high"].values.astype(float)
    low_array = df["low"].values.astype(float)
    open_array = df["open"].values.astype(float)

    # En iyi sonuçları takip etmek için
    best_balance_result = {
        'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
        'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
        'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0
    }

    best_success_rate_result = {
        'leverage': 1, 'stop_percentage': 0.5, 'kar_al_percentage': 0.5,
        'atr_period': 10, 'atr_multiplier': 3, 'successful_trades': 0,
        'unsuccessful_trades': 0, 'final_balance': 100.0, 'success_rate': 0
    }

    # Optimizasyon döngüleri
    for atr_period in [7, 10, 14]:  # ATR dönemleri
        for atr_multiplier in [2.0, 2.5, 3.0, 3.5]:  # ATR çarpanları
            # Supertrend hesapla
            supertrend = generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier)

            # NaN kontrolü
            supertrend_series = pd.Series(supertrend)
            if supertrend_series.isnull().any():
                continue

            for leverage in range(1, 11):  # 1-10 kaldıraç
                for stop_pct in [i * 0.5 for i in range(1, 21)]:  # 0.5-10% stop
                    for kar_al_pct in [i * 0.5 for i in range(1, 21)]:  # 0.5-10% kar al

                        initial_balance = 100.0
                        balance = initial_balance
                        successful_trades = 0
                        unsuccessful_trades = 0

                        i = atr_period + 3  # Başlangıç indeksi

                        while i < lim - 3:
                            if balance <= 0:
                                break

                            # Supertrend sinyali kontrolü
                            current_close = close_array[i]
                            prev_close = close_array[i - 1]
                            current_st = supertrend[i]
                            prev_st = supertrend[i - 1]

                            trade_direction = None
                            entry_price = None

                            # Long sinyal - Renk yeşile dönüyor
                            if current_close > current_st and prev_close <= prev_st:
                                trade_direction = "LONG"
                                entry_price = open_array[i + 1] if i + 1 < len(open_array) else current_close

                            # Short sinyal - Renk kırmızıya dönüyor
                            elif current_close < current_st and prev_close >= prev_st:
                                trade_direction = "SHORT"
                                entry_price = open_array[i + 1] if i + 1 < len(open_array) else current_close

                            if trade_direction and entry_price:
                                # İşlem açıldı
                                j = i + 1
                                trade_closed = False

                                while j < lim and not trade_closed:
                                    current_high = high_array[j]
                                    current_low = low_array[j]
                                    current_close_j = close_array[j]
                                    current_st_j = supertrend[j]
                                    prev_close_j = close_array[j - 1] if j > 0 else current_close_j
                                    prev_st_j = supertrend[j - 1] if j > 0 else current_st_j

                                    if trade_direction == "LONG":
                                        # Likit kontrolü
                                        loss_pct = (current_low - entry_price) / entry_price * 100
                                        if loss_pct <= -90 / leverage:
                                            balance = 0
                                            unsuccessful_trades += 1
                                            trade_closed = True
                                            break

                                        # Stop loss kontrolü
                                        elif loss_pct <= -stop_pct:
                                            balance += balance * (-stop_pct / 100) * leverage
                                            unsuccessful_trades += 1
                                            trade_closed = True

                                        # Kar al kontrolü
                                        profit_pct = (current_high - entry_price) / entry_price * 100
                                        if profit_pct >= kar_al_pct:
                                            balance += balance * (kar_al_pct / 100) * leverage
                                            successful_trades += 1
                                            trade_closed = True

                                        # Sinyal ile çıkış - Short sinyali
                                        elif current_close_j < current_st_j and prev_close_j >= prev_st_j:
                                            exit_price = open_array[j + 1] if j + 1 < len(
                                                open_array) else current_close_j
                                            profit_pct = (exit_price - entry_price) / entry_price * 100
                                            balance += balance * (profit_pct / 100) * leverage
                                            if profit_pct > 0:
                                                successful_trades += 1
                                            else:
                                                unsuccessful_trades += 1
                                            trade_closed = True

                                    elif trade_direction == "SHORT":
                                        # Likit kontrolü
                                        loss_pct = (current_high - entry_price) / entry_price * 100
                                        if loss_pct >= 90 / leverage:
                                            balance = 0
                                            unsuccessful_trades += 1
                                            trade_closed = True
                                            break

                                        # Stop loss kontrolü
                                        elif loss_pct >= stop_pct:
                                            balance += balance * (-stop_pct / 100) * leverage
                                            unsuccessful_trades += 1
                                            trade_closed = True

                                        # Kar al kontrolü
                                        profit_pct = (entry_price - current_low) / entry_price * 100
                                        if profit_pct >= kar_al_pct:
                                            balance += balance * (kar_al_pct / 100) * leverage
                                            successful_trades += 1
                                            trade_closed = True

                                        # Sinyal ile çıkış - Long sinyali
                                        elif current_close_j > current_st_j and prev_close_j <= prev_st_j:
                                            exit_price = open_array[j + 1] if j + 1 < len(
                                                open_array) else current_close_j
                                            profit_pct = (entry_price - exit_price) / entry_price * 100
                                            balance += balance * (profit_pct / 100) * leverage
                                            if profit_pct > 0:
                                                successful_trades += 1
                                            else:
                                                unsuccessful_trades += 1
                                            trade_closed = True

                                    j += 1

                                i = j if trade_closed else i + 1
                            else:
                                i += 1

                        # Sonuçları değerlendir
                        total_trades = successful_trades + unsuccessful_trades
                        success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0

                        # En iyi bakiye sonucunu güncelle
                        if balance > best_balance_result['final_balance']:
                            best_balance_result = {
                                'leverage': leverage,
                                'stop_percentage': stop_pct,
                                'kar_al_percentage': kar_al_pct,
                                'atr_period': atr_period,
                                'atr_multiplier': atr_multiplier,
                                'successful_trades': successful_trades,
                                'unsuccessful_trades': unsuccessful_trades,
                                'final_balance': balance,
                                'success_rate': success_rate
                            }

                        # En iyi başarı oranı sonucunu güncelle
                        if success_rate > best_success_rate_result['success_rate'] and total_trades >= 10:
                            best_success_rate_result = {
                                'leverage': leverage,
                                'stop_percentage': stop_pct,
                                'kar_al_percentage': kar_al_pct,
                                'atr_period': atr_period,
                                'atr_multiplier': atr_multiplier,
                                'successful_trades': successful_trades,
                                'unsuccessful_trades': unsuccessful_trades,
                                'final_balance': balance,
                                'success_rate': success_rate
                            }

    return {
        'balance': best_balance_result,
        'success_rate': best_success_rate_result
    }


async def main():
    # Veritabanı bağlantısı oluştur
    conn = create_db_connection()

    for symbol in symbols:
        s = symbols.index(symbol)
        a = 0
        # Bugünün tarihini al ve ondan geriye doğru git
        end_date = int(datetime.now().timestamp() * 1000)
        # Belirtilen gün sayısı kadar geriye git
        start_date = end_date - (ANALYSIS_DAYS * 86400 * 1000)

        print(f"\n{symbol} için veri çekme işlemi başlıyor...")
        print(f"Başlangıç Tarihi: {datetime.fromtimestamp(start_date / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Bitiş Tarihi: {datetime.fromtimestamp(end_date / 1000).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Toplam {ANALYSIS_DAYS} gün için veri çekilecek\n")

        # Boş DataFrame'leri oluştur
        timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
        dataframes = {}

        for tf in timeframes:
            dataframes[tf] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        while a < ANALYSIS_DAYS:
            try:
                progress = (a / ANALYSIS_DAYS) * 100
                print(f"İlerleme: %{progress:.1f} - Gün {a + 1}/{ANALYSIS_DAYS} - {symbol} için veri çekiliyor...")

                current_date = start_date + (a * 86400 * 1000)

                # Her timeframe için veri çek
                timeframe_limits = {
                    "1m": 1440, "3m": 480, "5m": 288, "15m": 96, "30m": 48,
                    "1h": 24, "2h": 12, "4h": 6, "1d": 1
                }

                for tf, limit in timeframe_limits.items():
                    try:
                        bars = exchange.fetch_ohlcv(symbol, timeframe=tf, since=current_date, limit=limit)
                        if bars:
                            temp_df = pd.DataFrame(bars,
                                                   columns=["timestamp", "open", "high", "low", "close", "volume"])
                            dataframes[tf] = pd.concat([dataframes[tf], temp_df], ignore_index=True)
                    except Exception as e:
                        print(f"{tf} veri çekilirken hata: {e}")

                time.sleep(0.5)

            except Exception as e:
                print(f"Gün {a + 1} için veri çekilirken genel hata oluştu: {e}")

            a += 1

        print(f"\n{symbol} için tüm veriler çekildi. Analiz başlıyor...")

        # 1w verisini ayrıca çek
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe="1w", since=start_date, limit=int(lim_olustur("1w")))
            dataframes["1w"] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        except Exception as e:
            print(f"1w veri çekme hatası: {e}")

        # Verileri veritabanına kaydet
        for tf, df in dataframes.items():
            if not df.empty:
                try:
                    save_to_db(conn, symbolName[s], df, tf)
                except Exception as e:
                    print(f"{tf} veritabanına kaydetme hatası: {e}")

        # Analiz yap
        for tf, df in dataframes.items():
            if not df.empty and len(df) > 50:
                try:
                    print(f"\n{tf} timeframe için analiz yapılıyor...")
                    results = deneme(tf, df, len(df))

                    # Bakiye optimizasyonu sonuçlarını kaydet
                    balance_result = results['balance']
                    save_results_to_db(
                        symbolName[s], tf,
                        balance_result['leverage'],
                        balance_result['stop_percentage'],
                        balance_result['kar_al_percentage'],
                        balance_result['atr_period'],
                        balance_result['atr_multiplier'],
                        balance_result['successful_trades'],
                        balance_result['unsuccessful_trades'],
                        balance_result['final_balance'],
                        'balance'
                    )

                    # Başarı oranı optimizasyonu sonuçlarını kaydet
                    success_result = results['success_rate']
                    save_results_to_db(
                        symbolName[s], tf,
                        success_result['leverage'],
                        success_result['stop_percentage'],
                        success_result['kar_al_percentage'],
                        success_result['atr_period'],
                        success_result['atr_multiplier'],
                        success_result['successful_trades'],
                        success_result['unsuccessful_trades'],
                        success_result['final_balance'],
                        'success_rate'
                    )

                    print(f"{tf} - BAKIYE OPTİMİZASYONU:")
                    print(f"  Kaldıraç: {balance_result['leverage']}, Stop: {balance_result['stop_percentage']}%, "
                          f"Kar Al: {balance_result['kar_al_percentage']}%")
                    print(f"  ATR: {balance_result['atr_period']}/{balance_result['atr_multiplier']}")
                    print(
                        f"  Başarılı: {balance_result['successful_trades']}, Başarısız: {balance_result['unsuccessful_trades']}")
                    print(
                        f"  Son Bakiye: {balance_result['final_balance']:.2f}, Başarı Oranı: %{balance_result['success_rate']:.2f}")

                    print(f"{tf} - BAŞARI ORANI OPTİMİZASYONU:")
                    print(f"  Kaldıraç: {success_result['leverage']}, Stop: {success_result['stop_percentage']}%, "
                          f"Kar Al: {success_result['kar_al_percentage']}%")
                    print(f"  ATR: {success_result['atr_period']}/{success_result['atr_multiplier']}")
                    print(
                        f"  Başarılı: {success_result['successful_trades']}, Başarısız: {success_result['unsuccessful_trades']}")
                    print(
                        f"  Son Bakiye: {success_result['final_balance']:.2f}, Başarı Oranı: %{success_result['success_rate']:.2f}")

                except Exception as e:
                    print(f"{tf} analiz hatası: {e}")

    # Veritabanı bağlantısını kapat
    conn.close()
    print("\nTüm analizler tamamlandı!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())