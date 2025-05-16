import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import ta
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

        # Boş DataFrame'leri oluştur
        df_1m = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_3m = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_5m = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_15m = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_30m = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_1h = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_2h = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_4h = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_1d = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        df_1w = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        # Dizileri doğru boyutlandır
        adf_1m = [[0 for x in range(1441)] for y in range(ANALYSIS_DAYS)]
        adf_3m = [[0 for x in range(481)] for y in range(ANALYSIS_DAYS)]
        adf_5m = [[0 for x in range(289)] for y in range(ANALYSIS_DAYS)]
        adf_15m = [[0 for x in range(97)] for y in range(ANALYSIS_DAYS)]
        adf_30m = [[0 for x in range(49)] for y in range(ANALYSIS_DAYS)]
        adf_1h = [[0 for x in range(25)] for y in range(ANALYSIS_DAYS)]
        adf_2h = [[0 for x in range(13)] for y in range(ANALYSIS_DAYS)]
        adf_4h = [[0 for x in range(7)] for y in range(ANALYSIS_DAYS)]
        adf_1d = [[0 for x in range(2)] for y in range(ANALYSIS_DAYS)]

        while a < ANALYSIS_DAYS:
            try:
                # İlerleme yüzdesi
                progress = (a / ANALYSIS_DAYS) * 100
                print(f"İlerleme: %{progress:.1f} - Gün {a + 1}/{ANALYSIS_DAYS} - {symbol} için veri çekiliyor...")

                # Her döngüde 1 gün ekleyerek ilerle
                current_date = start_date + (a * 86400 * 1000)

                # Veri çekme işlemleri
                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="1m", since=current_date, limit=1440)
                    adf_1m[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"1m veri çekilirken hata: {e}")
                    adf_1m[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="3m", since=current_date, limit=480)
                    adf_3m[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"3m veri çekilirken hata: {e}")
                    adf_3m[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="5m", since=current_date, limit=288)
                    adf_5m[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"5m veri çekilirken hata: {e}")
                    adf_5m[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="15m", since=current_date, limit=96)
                    adf_15m[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"15m veri çekilirken hata: {e}")
                    adf_15m[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="30m", since=current_date, limit=48)
                    adf_30m[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"30m veri çekilirken hata: {e}")
                    adf_30m[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="1h", since=current_date, limit=24)
                    adf_1h[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"1h veri çekilirken hata: {e}")
                    adf_1h[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="2h", since=current_date, limit=12)
                    adf_2h[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"2h veri çekilirken hata: {e}")
                    adf_2h[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="4h", since=current_date, limit=6)
                    adf_4h[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"4h veri çekilirken hata: {e}")
                    adf_4h[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                try:
                    bars = exchange.fetch_ohlcv(symbol, timeframe="1d", since=current_date, limit=1)
                    adf_1d[a] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                except Exception as e:
                    print(f"1d veri çekilirken hata: {e}")
                    adf_1d[a] = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

                # API limit aşımını önlemek için kısa bir bekleme
                time.sleep(0.5)

            except Exception as e:
                print(f"Gün {a + 1} için veri çekilirken genel hata oluştu: {e}")

            a = a + 1

        print(f"\n{symbol} için tüm veriler çekildi. Veriler birleştiriliyor...")

        a = 0
        while a < ANALYSIS_DAYS:
            # Boş DataFrame'leri kontrol et, boşsa atla
            if isinstance(adf_1m[a], pd.DataFrame) and not adf_1m[a].empty:
                df_1m = pd.concat([df_1m, adf_1m[a]], ignore_index=True)
            if isinstance(adf_3m[a], pd.DataFrame) and not adf_3m[a].empty:
                df_3m = pd.concat([df_3m, adf_3m[a]], ignore_index=True)
            if isinstance(adf_5m[a], pd.DataFrame) and not adf_5m[a].empty:
                df_5m = pd.concat([df_5m, adf_5m[a]], ignore_index=True)
            if isinstance(adf_15m[a], pd.DataFrame) and not adf_15m[a].empty:
                df_15m = pd.concat([df_15m, adf_15m[a]], ignore_index=True)
            if isinstance(adf_30m[a], pd.DataFrame) and not adf_30m[a].empty:
                df_30m = pd.concat([df_30m, adf_30m[a]], ignore_index=True)
            if isinstance(adf_1h[a], pd.DataFrame) and not adf_1h[a].empty:
                df_1h = pd.concat([df_1h, adf_1h[a]], ignore_index=True)
            if isinstance(adf_2h[a], pd.DataFrame) and not adf_2h[a].empty:
                df_2h = pd.concat([df_2h, adf_2h[a]], ignore_index=True)
            if isinstance(adf_4h[a], pd.DataFrame) and not adf_4h[a].empty:
                df_4h = pd.concat([df_4h, adf_4h[a]], ignore_index=True)
            if isinstance(adf_1d[a], pd.DataFrame) and not adf_1d[a].empty:
                df_1d = pd.concat([df_1d, adf_1d[a]], ignore_index=True)
            a = a + 1

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

        def deneme(zamanAraligi, df, lim):
            print("Supertrend ve Hacim BOT\n\n")
            bakiye = 100.0
            leverage_ust = 50
            lev_ust = 50
            yuzde_ust = 50
            yuzde = 0  # Döngü başlangıç değeri
            kar_al_ust = 50
            kar_al = 0  # Döngü başlangıç değeri
            yuz_ust = 50
            kar_ust = 50
            islemsonu = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
            basarili_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
            basarisiz_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
            a = 0  # Matris için indeks değişkeni ilk başta tanımlanmalı
            
            en_iyi_bakiye = {
                'leverage': 0,
                'yuzde': 0,
                'basarili': 0,
                'basarisiz': 0,
                'bakiye': 0,
                'basari_orani': 0
            }
            
            en_iyi_oran = {
                'leverage': 0,
                'yuzde': 0,
                'basarili': 0,
                'basarisiz': 0,
                'bakiye': 0,
                'basari_orani': 0
            }

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
            atr_period = 10
            atr_multiplier = 3
            tahmin = []  # Tahmin listesi bir kez tanımlanmalı
            
            if atr_period == 10:
                if atr_multiplier == 3:
                    supertrend = generateSupertrend(close_array, high_array, low_array, atr_period=atr_period,
                                                   atr_multiplier=atr_multiplier)
                    kar_al = 0
                    while kar_al < kar_al_ust:
                        yuzde = 0
                        # Yüzde döngüsü
                        while yuzde <= yuzde_ust:
                            stop = 0
                            kar_stop = 0
                            likit = 0
                            leverage = 1

                            # Kaldıraç döngüsü
                            while leverage <= leverage_ust:
                                bakiye = 100.0
                                x = 3
                                stop = 0
                                kar_stop = 0
                                likit = 0
                                islem = 0       # İşlem sayısı
                                basarili = 0    # Başarılı işlem sayısı
                                basarisiz = 0   # Başarısız işlem sayısı
                                
                                # Supertrend indikatörü ve hacim kullanılarak girilen işlemler ana kısım
                                while x < lim:
                                    depo = 0
                                    son_kapanis = close_array[x - 2]
                                    onceki_kapanis = close_array[x - 3]
                                    son_supertrend_deger = supertrend[x - 2]
                                    onceki_supertrend_deger = supertrend[x - 3]
                                    # Renk yeşile dönüyor, Supertrend yükselişe geçti
                                    if son_kapanis > son_supertrend_deger and onceki_kapanis < onceki_supertrend_deger:
                                        islem = islem + 1
                                        print("")
                                        print("Sinyal Long")
                                        print("Bakiye = " + str(bakiye))
                                        print("Kaldıraç = " + str(leverage))
                                        print("Stop = " + str(yuzde))
                                        print("Kar al = " + str(kar_al))
                                        print(datetime.fromtimestamp(int(df['timestamp'][x]) / 1000))
                                        print("")
                                        giris = float(df["open"][x])
                                        y = 0
                                        while True:
                                            # While True döngüsünün içindeki değişkenlerin doğru yerleştirilmesi
                                            son_kapanis = close_array[x + y - 2]
                                            onceki_kapanis = close_array[x + y - 3]
                                            son_supertrend_deger = supertrend[x + y - 2]
                                            onceki_supertrend_deger = supertrend[x + y - 3]

                                            # Likit olma durumu
                                            if ((float(df["low"][x + y]) - giris) / giris * 100 <= (-1) * (
                                                    90 / float(leverage))):
                                                print("Likit")
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                bakiye = 0
                                                likit = 1
                                                basarisiz = basarisiz + 1
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Stop olma durumu
                                            if ((float(
                                                    df["high"][x + y]) - giris) / giris * 100 >= yuzde) and yuzde != 0:
                                                basarili = basarili + 1
                                                bakiye = bakiye - bakiye * yuzde / 100 * leverage
                                                stop = 1
                                                print("Stop ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Kar alma durumu
                                            if ((float(df["low"][x + y]) - giris) / giris * 100 >= kar_al * (
                                            -1)) and kar_al != 0:
                                                basarili = basarili + 1
                                                bakiye = bakiye + bakiye * kar_al / 100 * leverage
                                                kar_stop = 1
                                                print("Kar al ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Sinyal ile çıkış durumu
                                            if son_kapanis < son_supertrend_deger and onceki_kapanis > onceki_supertrend_deger:
                                                son = bakiye + bakiye * (
                                                            float(df["open"][x + y]) - giris) / giris * leverage
                                                if son < bakiye:
                                                    basarisiz = basarisiz + 1
                                                else:
                                                    basarili = basarili + 1
                                                bakiye = bakiye + bakiye * (
                                                            float(df["open"][x + y]) - giris) / giris * leverage
                                                print("Sinyal ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            y = y + 1

                                            # Dizi sonunda döngüden çıkılsın
                                            if (x + y) == lim:
                                                depo = x + y - 2
                                                break

                                                # Renk kırmızıya dönüyor, Supertrend düşüşe geçti
                                    elif son_kapanis < son_supertrend_deger and onceki_kapanis > onceki_supertrend_deger:
                                        islem = islem + 1
                                        print("")
                                        print("Sinyal Short")
                                        print("Bakiye = " + str(bakiye))
                                        print("Kaldıraç = " + str(leverage))
                                        print("Stop = " + str(yuzde))
                                        print("Kar Al = " + str(kar_al))
                                        print(datetime.fromtimestamp(int(df['timestamp'][x]) / 1000))
                                        print("")
                                        giris = float(df["open"][x])
                                        y = 0
                                        while True:
                                            # While True döngüsünün içindeki değişkenlerin doğru yerleştirilmesi
                                            son_kapanis = close_array[x + y - 2]
                                            onceki_kapanis = close_array[x + y - 3]
                                            son_supertrend_deger = supertrend[x + y - 2]
                                            onceki_supertrend_deger = supertrend[x + y - 3]

                                            # Likit olma durumu
                                            if ((float(df["high"][x + y]) - giris) / giris * 100 >= (
                                                    90 / float(leverage))):
                                                print("Likit")
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                bakiye = 0
                                                likit = 1
                                                basarisiz = basarisiz + 1
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Stop olma durumu
                                            if ((float(df["low"][x + y]) - giris) / giris * 100 <= yuzde * (
                                            -1)) and yuzde != 0:
                                                basarili = basarili + 1
                                                bakiye = bakiye - bakiye * yuzde / 100 * leverage
                                                stop = 1
                                                print("Stop ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Kar alma durumu
                                            if ((float(df["high"][
                                                           x + y]) - giris) / giris * 100 <= kar_al) and kar_al != 0:
                                                basarili = basarili + 1
                                                bakiye = bakiye + bakiye * yuzde / 100 * leverage
                                                kar_stop = 1
                                                print("Kar al ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            # Sinyal ile çıkış durumu
                                            if son_kapanis > son_supertrend_deger and onceki_kapanis < onceki_supertrend_deger:
                                                son = bakiye + bakiye * (float(df["open"][x + y]) - giris) / giris * (
                                                    -1) * leverage
                                                if son < bakiye:
                                                    basarisiz = basarisiz + 1
                                                else:
                                                    basarili = basarili + 1
                                                bakiye = bakiye + bakiye * (
                                                            float(df["open"][x + y]) - giris) / giris * (-1) * leverage
                                                print("Sinyal ile kapandı. Bakiye = " + str(bakiye))
                                                print(datetime.fromtimestamp(int(df['timestamp'][x + y]) / 1000))
                                                print("")
                                                if y == 0:
                                                    x = x + y
                                                else:
                                                    x = x + y - 1
                                                break

                                            y = y + 1

                                            # Dizi sonunda döngüden çıkılsın
                                            if (x + y) == lim:
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

                                # Kar Stop çalışmadıysa yüzde döngüsünden çıkılsın
                                if kar_stop == 0:
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

                            # Kar Stop çalışmadıysa yüzde döngüsünden çıkılsın
                            if kar_stop == 0:
                                kar_al_ust = kar_al
                                while leverage_ust < lev_ust:
                                    b = a
                                    while b < kar_ust * 2:
                                        islemsonu[int(leverage_ust)][b] = 0
                                        basarili_islem[int(leverage_ust)][b] = 0
                                        basarisiz_islem[int(leverage_ust)][b] = 0
                                        b = b + 1
                                    leverage_ust = leverage_ust + 1
                                break
                            yuzde = yuzde + 0.5
                            a = a + 1  # a değişkeni her yüzde artışında güncellenmeli
                            leverage_ust = lev - 1
                        kar_al = kar_al + 0.5
                    leverage = 0
                    while leverage < lev_ust:
                        tahmin.append(max(islemsonu[leverage]))
                        leverage = leverage + 1
                    leverage = 0
                    while leverage < lev_ust:
                        k = 1
                        while k <= len(islemsonu[leverage]):
                            if islemsonu[int(leverage)][int(k - 1)] == max(tahmin):
                                return str(leverage + 1), str(k / 2), basarili_islem[leverage][k - 1], \
                                basarisiz_islem[leverage][
                                    k - 1], str(islemsonu[int(leverage)][int(k - 1)])
                            k = k + 1
                        leverage = leverage + 1
                    atr_multiplier = atr_multiplier + 0.5
                atr_period = atr_period + 1

        m1 = deneme("1m", df_1m, len(df_1m))
        m3 = deneme("3m", df_3m, len(df_3m))
        m5 = deneme("5m", df_5m, len(df_5m))
        m15 = deneme("15m", df_15m, len(df_15m))
        m30 = deneme("30m", df_30m, len(df_30m))
        h1 = deneme("1h", df_1h, len(df_1h))
        h2 = deneme("2h", df_2h, len(df_2h))
        h4 = deneme("4h", df_4h, len(df_4h))
        d1 = deneme("1d", df_1d, len(df_1d))
        w1 = deneme("1w", df_1w, len(df_1w))

        lev_1m = m1[0]
        lev_3m = m3[0]
        lev_5m = m5[0]
        lev_15m = m15[0]
        lev_30m = m30[0]
        lev_1h = h1[0]
        lev_2h = h2[0]
        lev_4h = h4[0]
        lev_1d = d1[0]
        lev_1w = w1[0]

        yuz_1m = m1[1]
        yuz_3m = m3[1]
        yuz_5m = m5[1]
        yuz_15m = m15[1]
        yuz_30m = m30[1]
        yuz_1h = h1[1]
        yuz_2h = h2[1]
        yuz_4h = h4[1]
        yuz_1d = d1[1]
        yuz_1w = w1[1]

        kar_yuz_1m = m1[1]
        kar_yuz_3m = m3[1]
        kar_yuz_5m = m5[1]
        kar_yuz_15m = m15[1]
        kar_yuz_30m = m30[1]
        kar_yuz_1h = h1[1]
        kar_yuz_2h = h2[1]
        kar_yuz_4h = h4[1]
        kar_yuz_1d = d1[1]
        kar_yuz_1w = w1[1]

        bli_1m = m1[2]
        bli_3m = m3[2]
        bli_5m = m5[2]
        bli_15m = m15[2]
        bli_30m = m30[2]
        bli_1h = h1[2]
        bli_2h = h2[2]
        bli_4h = h4[2]
        bli_1d = d1[2]
        bli_1w = w1[2]

        bsiz_1m = m1[3]
        bsiz_3m = m3[3]
        bsiz_5m = m5[3]
        bsiz_15m = m15[3]
        bsiz_30m = m30[3]
        bsiz_1h = h1[3]
        bsiz_2h = h2[3]
        bsiz_4h = h4[3]
        bsiz_1d = d1[3]
        bsiz_1w = w1[3]

        bky_1m = m1[4]
        bky_3m = m3[4]
        bky_5m = m5[4]
        bky_15m = m15[4]
        bky_30m = m30[4]
        bky_1h = h1[4]
        bky_2h = h2[4]
        bky_4h = h4[4]
        bky_1d = d1[4]
        bky_1w = w1[4]

        # Analiz sonuçlarını veritabanına kaydet
        save_results_to_db(symbolName[s], "1m", float(lev_1m), float(yuz_1m), float(kar_yuz_1m), bli_1m, bsiz_1m,
                           float(bky_1m), 'balance')
        save_results_to_db(symbolName[s], "1m", float(lev_1m), float(yuz_1m), float(kar_yuz_1m), bli_1m, bsiz_1m,
                           float(bky_1m), 'success_rate')
        save_results_to_db(symbolName[s], "3m", float(lev_3m), float(yuz_3m), float(kar_yuz_3m), bli_3m, bsiz_3m,
                           float(bky_3m), 'balance')
        save_results_to_db(symbolName[s], "3m", float(lev_3m), float(yuz_3m), float(kar_yuz_3m), bli_3m, bsiz_3m,
                           float(bky_3m), 'success_rate')
        save_results_to_db(symbolName[s], "5m", float(lev_5m), float(yuz_5m), float(kar_yuz_5m), bli_5m, bsiz_5m,
                           float(bky_5m), 'balance')
        save_results_to_db(symbolName[s], "5m", float(lev_5m), float(yuz_5m), float(kar_yuz_5m), bli_5m, bsiz_5m,
                           float(bky_5m), 'success_rate')
        save_results_to_db(symbolName[s], "15m", float(lev_15m), float(yuz_15m), float(kar_yuz_15m), bli_15m, bsiz_15m,
                           float(bky_15m), 'balance')
        save_results_to_db(symbolName[s], "15m", float(lev_15m), float(yuz_15m), float(kar_yuz_15m), bli_15m, bsiz_15m,
                           float(bky_15m), 'success_rate')
        save_results_to_db(symbolName[s], "30m", float(lev_30m), float(yuz_30m), float(kar_yuz_30m), bli_30m, bsiz_30m,
                           float(bky_30m), 'balance')
        save_results_to_db(symbolName[s], "30m", float(lev_30m), float(yuz_30m), float(kar_yuz_30m), bli_30m, bsiz_30m,
                           float(bky_30m), 'success_rate')
        save_results_to_db(symbolName[s], "1h", float(lev_1h), float(yuz_1h), float(kar_yuz_1h), bli_1h, bsiz_1h,
                           float(bky_1h), 'balance')
        save_results_to_db(symbolName[s], "1h", float(lev_1h), float(yuz_1h), float(kar_yuz_1h), bli_1h, bsiz_1h,
                           float(bky_1h), 'success_rate')
        save_results_to_db(symbolName[s], "2h", float(lev_2h), float(yuz_2h), float(kar_yuz_2h), bli_2h, bsiz_2h,
                           float(bky_2h), 'balance')
        save_results_to_db(symbolName[s], "2h", float(lev_2h), float(yuz_2h), float(kar_yuz_2h), bli_2h, bsiz_2h,
                           float(bky_2h), 'success_rate')
        save_results_to_db(symbolName[s], "4h", float(lev_4h), float(yuz_4h), float(kar_yuz_4h), bli_4h, bsiz_4h,
                           float(bky_4h), 'balance')
        save_results_to_db(symbolName[s], "4h", float(lev_4h), float(yuz_4h), float(kar_yuz_4h), bli_4h, bsiz_4h,
                           float(bky_4h), 'success_rate')
        save_results_to_db(symbolName[s], "1d", float(lev_1d), float(yuz_1d), float(kar_yuz_1d), bli_1d, bsiz_1d,
                           float(bky_1d), 'balance')
        save_results_to_db(symbolName[s], "1d", float(lev_1d), float(yuz_1d), float(kar_yuz_1d), bli_1d, bsiz_1d,
                           float(bky_1d), 'success_rate')
        save_results_to_db(symbolName[s], "1w", float(lev_1w), float(yuz_1w), float(kar_yuz_1w), bli_1w, bsiz_1w,
                           float(bky_1w), 'balance')
        save_results_to_db(symbolName[s], "1w", float(lev_1w), float(yuz_1w), float(kar_yuz_1w), bli_1w, bsiz_1w,
                           float(bky_1w), 'success_rate')

    # Veritabanı bağlantısını kapat
    conn.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())