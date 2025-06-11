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
import traceback

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
        print(f"DEBUG: Veritabanına kayıt yapılıyor - {symbol} {timeframe} {optimization_type}")

        # Veritabanı dosyasının var olup olmadığını kontrol et
        if not os.path.exists(LOCAL_DB_PATH):
            print(f"ERROR: Veritabanı dosyası bulunamadı: {LOCAL_DB_PATH}")
            return

        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()

        total_trades = successful_trades + unsuccessful_trades
        success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0

        print(
            f"DEBUG: Kayıt değerleri - Başarılı: {successful_trades}, Başarısız: {unsuccessful_trades}, Bakiye: {final_balance}")

        # Önce eski sonucu sil
        cursor.execute('''
        DELETE FROM analysis_results 
        WHERE symbol = ? AND timeframe = ? AND optimization_type = ?
        ''', (symbol, timeframe, optimization_type))

        deleted_rows = cursor.rowcount
        print(f"DEBUG: {deleted_rows} eski kayıt silindi")

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

        print(f"DEBUG: Yeni kayıt eklendi - ID: {cursor.lastrowid}")

        conn.commit()
        print(f"DEBUG: Veritabanı commit edildi")

        # Kayıt kontrol et
        cursor.execute("SELECT COUNT(*) FROM analysis_results WHERE symbol = ? AND timeframe = ?",
                       (symbol, timeframe))
        count = cursor.fetchone()[0]
        print(f"DEBUG: {symbol} {timeframe} için toplamda {count} kayıt var")

        conn.close()

    except Exception as e:
        print(f"Veritabanı hatası: {str(e)}")
        traceback.print_exc()


# API CONNECT - API bilgileri kaldırıldı (güvenlik için)
exchange = ccxt.binance({
    'options': {
        'defaultType': 'future'
    },
    'enableRateLimit': True,
    'sandbox': False  # Test ortamı için True yapabilirsiniz
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
    İlk period kadar değer için NaN döndürür, sonrasında gerçek ATR değerlerini hesaplar
    """
    atr = []
    tr_list = []

    for i in range(len(close_array)):
        if i == 0:
            # İlk değer için sadece High-Low
            tr = high_array[i] - low_array[i]
        else:
            # True Range hesaplama
            tr1 = high_array[i] - low_array[i]
            tr2 = abs(high_array[i] - close_array[i - 1])
            tr3 = abs(low_array[i] - close_array[i - 1])
            tr = max(tr1, tr2, tr3)

        tr_list.append(tr)

        # İlk period-1 değer için NaN döndür
        if i < period - 1:
            atr.append(float('nan'))
        elif i == period - 1:
            # İlk ATR değeri: ilk period kadar TR'nin ortalaması
            atr.append(sum(tr_list[:period]) / period)
        else:
            # Exponential Moving Average hesabı
            previous_atr = atr[-1]
            if not math.isnan(previous_atr):
                atr.append(((period - 1) * previous_atr + tr) / period)
            else:
                atr.append(float('nan'))

    return atr


def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    """
    Düzeltilmiş Supertrend hesaplama fonksiyonu
    ATR period'u dikkate alarak ilk geçerli değerden itibaren hesaplama yapar
    """
    try:
        atr = calculateATR(high_array, low_array, close_array, atr_period)
    except Exception as Error:
        print(f"[ERROR] ATR hesaplama hatası: {Error}")
        return [float('nan')] * len(close_array)

    supertrend = []

    # İlk atr_period kadar değer için NaN döndür
    for i in range(atr_period):
        supertrend.append(float('nan'))

    if len(close_array) <= atr_period:
        return supertrend

    # İlk geçerli indeksten başla
    start_index = atr_period

    # İlk değerler için başlangıç hesaplaması
    i = start_index
    if i < len(close_array):
        highc = high_array[i]
        lowc = low_array[i]
        atrc = atr[i]
        closec = close_array[i]

        if math.isnan(atrc):
            atrc = 0

        basic_upperband = (highc + lowc) / 2 + atr_multiplier * atrc
        basic_lowerband = (highc + lowc) / 2 - atr_multiplier * atrc

        # İlk supertrend değeri: fiyat hangi band'a yakınsa o band
        if closec <= basic_upperband:
            supertrend.append(basic_upperband)
        else:
            supertrend.append(basic_lowerband)

    # Geri kalan değerler için hesaplama
    for i in range(start_index + 1, len(close_array)):
        try:
            highc = high_array[i]
            lowc = low_array[i]
            atrc = atr[i]
            closec = close_array[i]
            previous_close = close_array[i - 1]
            previous_supertrend = supertrend[i - 1]

            if math.isnan(atrc):
                atrc = 0

            # Basic bands hesaplama
            basic_upperband = (highc + lowc) / 2 + atr_multiplier * atrc
            basic_lowerband = (highc + lowc) / 2 - atr_multiplier * atrc

            # Önceki değerlerden final bands hesaplama
            if i >= 2:
                prev_final_upperband = None
                prev_final_lowerband = None

                # Önceki final band'ları bul
                prev_highc = high_array[i - 1]
                prev_lowc = low_array[i - 1]
                prev_atrc = atr[i - 1]
                if math.isnan(prev_atrc):
                    prev_atrc = 0

                prev_basic_upperband = (prev_highc + prev_lowc) / 2 + atr_multiplier * prev_atrc
                prev_basic_lowerband = (prev_highc + prev_lowc) / 2 - atr_multiplier * prev_atrc

                # Final upperband hesaplama
                if i >= 3:
                    prev_prev_close = close_array[i - 2]
                    if basic_upperband < prev_basic_upperband or prev_prev_close > prev_basic_upperband:
                        final_upperband = basic_upperband
                    else:
                        final_upperband = prev_basic_upperband

                    if basic_lowerband > prev_basic_lowerband or prev_prev_close < prev_basic_lowerband:
                        final_lowerband = basic_lowerband
                    else:
                        final_lowerband = prev_basic_lowerband
                else:
                    final_upperband = basic_upperband
                    final_lowerband = basic_lowerband
            else:
                final_upperband = basic_upperband
                final_lowerband = basic_lowerband

            # Supertrend direction belirleme
            if math.isnan(previous_supertrend):
                if closec <= final_upperband:
                    supertrendc = final_upperband
                else:
                    supertrendc = final_lowerband
            else:
                # Trend yönü belirleme
                if (previous_supertrend == supertrend[i - 1] and
                        previous_supertrend > final_lowerband and
                        closec >= final_lowerband):
                    supertrendc = final_lowerband
                elif (previous_supertrend == supertrend[i - 1] and
                      previous_supertrend < final_upperband and
                      closec <= final_upperband):
                    supertrendc = final_upperband
                elif closec > final_upperband:
                    supertrendc = final_lowerband
                else:
                    supertrendc = final_upperband

            supertrend.append(supertrendc)

        except Exception as e:
            print(f"Supertrend hesaplamasında hata (indeks {i}): {e}")
            supertrend.append(float('nan'))

    return supertrend


def deneme(zamanAraligi, df, lim):
    print(f"Supertrend ve Hacim BOT - {zamanAraligi} - Analiz başlıyor...")

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
    
    # Veri tiplerini kontrol et
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

    print(f"Veri hazırlığı tamamlandı. {lim} satır veri ile optimizasyon başlıyor...")

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

    print(f"Optimizasyon başlıyor... Toplam {len(df)} veri noktası")

    # Optimizasyon döngüleri
    optimization_count = 0
    total_optimizations = 3 * 3 * 20 * 11 * 11  # ATR dönemleri * ATR çarpanları * Kaldıraç * Stop * Take profit

    for atr_period in [10, 14, 20]:  # ATR dönemleri
        for atr_multiplier in [2.0, 2.5, 3.0]:  # ATR çarpanları
            print(f"ATR parametreleri: period={atr_period}, multiplier={atr_multiplier}")

            # Minimum veri kontrolü - ATR period'undan fazla veri olmalı
            if len(df) < atr_period + 10:
                print(f"ATR period ({atr_period}) için yetersiz veri. Atlanıyor...")
                continue

            # Supertrend hesapla
            supertrend = generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier)

            # NaN kontrolü - sadece geçerli değerler var mı?
            valid_supertrend_count = sum(1 for x in supertrend if not math.isnan(x))
            print(f"Geçerli Supertrend değer sayısı: {valid_supertrend_count}/{len(supertrend)}")

            if valid_supertrend_count < 20:  # Minimum geçerli değer kontrolü
                print("Çok az geçerli Supertrend değeri, atlanıyor...")
                continue

            for leverage in range(1, 21):  # 1-20 kaldıraç
                for stop_pct in [i * 0.5 for i in range(0, 11)]:  # 0-5% stop
                    for kar_al_pct in [i * 0.5 for i in range(0, 11)]:  # 0-5% kar al
                        optimization_count += 1
                        if optimization_count % 1000 == 0:
                            progress = (optimization_count / total_optimizations) * 100
                            print(f"Optimizasyon ilerlemesi: %{progress:.1f} ({optimization_count}/{total_optimizations})")

                        initial_balance = 100.0
                        balance = initial_balance
                        successful_trades = 0
                        unsuccessful_trades = 0
                        position = None
                        entry_price = 0
                        entry_balance = 0
                        transactions = []  # İşlem geçmişi listesi

                        # ATR period'dan sonra başla
                        i = atr_period + 1

                        while i < lim - 1:  # Son mumu atla çünkü bir sonraki mumun verilerine ihtiyacımız var
                            if balance <= 0:
                                break

                            # NaN kontrolü
                            if (math.isnan(supertrend[i]) or math.isnan(supertrend[i - 1]) or
                                    i - 1 < 0 or i >= len(close_array)):
                                i += 1
                                continue

                            # Eğer pozisyon yoksa ve sinyal varsa
                            if position is None:
                                # LONG sinyali (önceki mumda LONG sinyali varsa ve şu anki mumun açılışında işleme gir)
                                if close_array[i-1] > supertrend[i-1] and close_array[i-2] <= supertrend[i-2]:
                                    position = 'LONG'
                                    entry_price = open_array[i]  # Bir sonraki mumun açılışında işleme gir
                                    entry_balance = balance
                                    transactions.append({
                                        'trade_type': 'LONG',
                                        'entry_price': entry_price,
                                        'entry_time': df.index[i],
                                        'entry_balance': entry_balance,
                                        'trade_closed': False
                                    })

                                # SHORT sinyali (önceki mumda SHORT sinyali varsa ve şu anki mumun açılışında işleme gir)
                                elif close_array[i-1] < supertrend[i-1] and close_array[i-2] >= supertrend[i-2]:
                                    position = 'SHORT'
                                    entry_price = open_array[i]  # Bir sonraki mumun açılışında işleme gir
                                    entry_balance = balance
                                    transactions.append({
                                        'trade_type': 'SHORT',
                                        'entry_price': entry_price,
                                        'entry_time': df.index[i],
                                        'entry_balance': entry_balance,
                                        'trade_closed': False
                                    })

                            # Eğer pozisyon varsa
                            elif position is not None:
                                # LONG pozisyonu için
                                if position == 'LONG':
                                    # Stop loss kontrolü (mevcut mumda)
                                    if stop_pct > 0 and low_array[i] <= entry_price * (1 - stop_pct/100):
                                        exit_price = entry_price * (1 - stop_pct/100)
                                        profit_loss = (exit_price - entry_price) * leverage
                                        balance += profit_loss
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Likit olma kontrolü (mevcut mumda)
                                    elif (entry_price - low_array[i]) * leverage >= entry_balance * 0.9:
                                        exit_price = low_array[i]
                                        profit_loss = (exit_price - entry_price) * leverage
                                        balance = 0
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': 0,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })
                                        break

                                    # Take profit kontrolü (mevcut mumda)
                                    elif kar_al_pct > 0 and high_array[i] >= entry_price * (1 + kar_al_pct/100):
                                        exit_price = entry_price * (1 + kar_al_pct/100)
                                        profit_loss = (exit_price - entry_price) * leverage
                                        balance += profit_loss
                                        successful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Trend değişimi kontrolü (bir sonraki mumun açılışında)
                                    elif close_array[i] < supertrend[i] and close_array[i-1] >= supertrend[i-1]:
                                        if i + 1 < len(open_array):
                                            # Mevcut LONG pozisyonunu kapat
                                            exit_price = open_array[i + 1]  # Bir sonraki mumun açılışında çık
                                            profit_loss = (exit_price - entry_price) * leverage
                                            balance += profit_loss
                                            if profit_loss > 0:
                                                successful_trades += 1
                                            else:
                                                unsuccessful_trades += 1
                                            
                                            # İşlemi güncelle
                                            transactions[-1].update({
                                                'exit_price': exit_price,
                                                'exit_time': df.index[i + 1],
                                                'exit_balance': balance,
                                                'profit_loss': profit_loss,
                                                'trade_closed': True
                                            })
                                            
                                            # Ters yönde yeni pozisyon aç (SHORT)
                                            if balance > 0:  # Bakiye kontrolü
                                                position = 'SHORT'
                                                entry_price = open_array[i + 1]
                                                entry_balance = balance
                                                transactions.append({
                                                    'trade_type': 'SHORT',
                                                    'entry_price': entry_price,
                                                    'entry_time': df.index[i + 1],
                                                    'entry_balance': entry_balance,
                                                    'trade_closed': False
                                                })
                                            else:
                                                position = None

                                # SHORT pozisyonu için
                                elif position == 'SHORT':
                                    # Stop loss kontrolü (mevcut mumda)
                                    if stop_pct > 0 and high_array[i] >= entry_price * (1 + stop_pct/100):
                                        exit_price = entry_price * (1 + stop_pct/100)
                                        profit_loss = (entry_price - exit_price) * leverage
                                        balance += profit_loss
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Likit olma kontrolü (mevcut mumda)
                                    elif (high_array[i] - entry_price) * leverage >= entry_balance * 0.9:
                                        exit_price = high_array[i]
                                        profit_loss = (entry_price - exit_price) * leverage
                                        balance = 0
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': 0,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })
                                        break

                                    # Take profit kontrolü (mevcut mumda)
                                    elif kar_al_pct > 0 and low_array[i] <= entry_price * (1 - kar_al_pct/100):
                                        exit_price = entry_price * (1 - kar_al_pct/100)
                                        profit_loss = (entry_price - exit_price) * leverage
                                        balance += profit_loss
                                        successful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df.index[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Trend değişimi kontrolü (bir sonraki mumun açılışında)
                                    elif close_array[i] > supertrend[i] and close_array[i-1] <= supertrend[i-1]:
                                        if i + 1 < len(open_array):
                                            # Mevcut SHORT pozisyonunu kapat
                                            exit_price = open_array[i + 1]  # Bir sonraki mumun açılışında çık
                                            profit_loss = (entry_price - exit_price) * leverage
                                            balance += profit_loss
                                            if profit_loss > 0:
                                                successful_trades += 1
                                            else:
                                                unsuccessful_trades += 1
                                            
                                            # İşlemi güncelle
                                            transactions[-1].update({
                                                'exit_price': exit_price,
                                                'exit_time': df.index[i + 1],
                                                'exit_balance': balance,
                                                'profit_loss': profit_loss,
                                                'trade_closed': True
                                            })
                                            
                                            # Ters yönde yeni pozisyon aç (LONG)
                                            if balance > 0:  # Bakiye kontrolü
                                                position = 'LONG'
                                                entry_price = open_array[i + 1]
                                                entry_balance = balance
                                                transactions.append({
                                                    'trade_type': 'LONG',
                                                    'entry_price': entry_price,
                                                    'entry_time': df.index[i + 1],
                                                    'entry_balance': entry_balance,
                                                    'trade_closed': False
                                                })
                                            else:
                                                position = None

                            i += 1

                        # Son işlem hala açıksa kapat
                        if position is not None:
                            exit_price = close_array[-1]
                            if position == 'LONG':
                                profit_loss = (exit_price - entry_price) * leverage
                            else:
                                profit_loss = (entry_price - exit_price) * leverage
                            balance += profit_loss
                            if profit_loss > 0:
                                successful_trades += 1
                            else:
                                unsuccessful_trades += 1
                            transactions[-1].update({
                                'exit_price': exit_price,
                                'exit_time': df.index[-1],
                                'exit_balance': balance,
                                'profit_loss': profit_loss,
                                'trade_closed': True
                            })

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
                            print(f"Yeni en iyi bakiye: {balance:.2f} (Kaldıraç: {leverage}, Stop: {stop_pct}%, Kar Al: {kar_al_pct}%)")

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
                            print(f"Yeni en iyi başarı oranı: %{success_rate:.2f} (İşlem sayısı: {total_trades})")

    print(f"Optimizasyon tamamlandı! {zamanAraligi} için analiz bitti.")
    return {
        'balance': best_balance_result,
        'success_rate': best_success_rate_result
    }


def backtest_strategy(df, initial_balance, leverage, stop_loss_percentage, take_profit_percentage, atr_period,
                      atr_multiplier):
    """
    Stratejiyi backtest eder ve sonuçları döndürür.
    İşleme girişleri bir sonraki mumun açılışında yapılır.
    """
    # Supertrend hesapla
    df = generateSupertrend(df['close'].values, df['high'].values, df['low'].values, atr_period, atr_multiplier)

    balance = initial_balance
    position = None
    entry_price = 0
    entry_balance = 0
    successful_trades = 0
    unsuccessful_trades = 0
    transactions = []

    # İlk mumu atla çünkü bir önceki mumun verilerine ihtiyacımız var
    for i in range(1, len(df)):
        current_row = df.iloc[i]
        previous_row = df.iloc[i - 1]

        # Eğer pozisyon yoksa ve sinyal varsa
        if position is None:
            # LONG sinyali (önceki mumda LONG sinyali varsa ve şu anki mumun açılışında işleme gir)
            if previous_row['supertrend'] == 1 and previous_row['supertrend_prev'] == -1:
                position = 'LONG'
                entry_price = current_row['open']  # Bir sonraki mumun açılışında işleme gir
                entry_balance = balance
                transactions.append({
                    'trade_type': 'LONG',
                    'entry_price': entry_price,
                    'entry_time': current_row.name,
                    'entry_balance': entry_balance,
                    'trade_closed': False
                })

            # SHORT sinyali (önceki mumda SHORT sinyali varsa ve şu anki mumun açılışında işleme gir)
            elif previous_row['supertrend'] == -1 and previous_row['supertrend_prev'] == 1:
                position = 'SHORT'
                entry_price = current_row['open']  # Bir sonraki mumun açılışında işleme gir
                entry_balance = balance
                transactions.append({
                    'trade_type': 'SHORT',
                    'entry_price': entry_price,
                    'entry_time': current_row.name,
                    'entry_balance': entry_balance,
                    'trade_closed': False
                })

        # Eğer pozisyon varsa
        elif position is not None:
            # LONG pozisyonu için
            if position == 'LONG':
                # Stop loss kontrolü
                if current_row['low'] <= entry_price * (1 - stop_loss_percentage / 100):
                    exit_price = entry_price * (1 - stop_loss_percentage / 100)
                    profit_loss = (exit_price - entry_price) * leverage
                    balance += profit_loss
                    unsuccessful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

                # Take profit kontrolü
                elif current_row['high'] >= entry_price * (1 + take_profit_percentage / 100):
                    exit_price = entry_price * (1 + take_profit_percentage / 100)
                    profit_loss = (exit_price - entry_price) * leverage
                    balance += profit_loss
                    successful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

                # Trend değişimi kontrolü
                elif current_row['supertrend'] == -1:
                    exit_price = current_row['close']
                    profit_loss = (exit_price - entry_price) * leverage
                    balance += profit_loss
                    if profit_loss > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

            # SHORT pozisyonu için
            elif position == 'SHORT':
                # Stop loss kontrolü
                if current_row['high'] >= entry_price * (1 + stop_loss_percentage / 100):
                    exit_price = entry_price * (1 + stop_loss_percentage / 100)
                    profit_loss = (entry_price - exit_price) * leverage
                    balance += profit_loss
                    unsuccessful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

                # Take profit kontrolü
                elif current_row['low'] <= entry_price * (1 - take_profit_percentage / 100):
                    exit_price = entry_price * (1 - take_profit_percentage / 100)
                    profit_loss = (entry_price - exit_price) * leverage
                    balance += profit_loss
                    successful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

                # Trend değişimi kontrolü
                elif current_row['supertrend'] == 1:
                    exit_price = current_row['close']
                    profit_loss = (entry_price - exit_price) * leverage
                    balance += profit_loss
                    if profit_loss > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    position = None

                    # İşlemi güncelle
                    transactions[-1].update({
                        'exit_price': exit_price,
                        'exit_time': current_row.name,
                        'exit_balance': balance,
                        'profit_loss': profit_loss,
                        'trade_closed': True
                    })

        # Bakiye kontrolü
        if balance <= 0:
            # Açık işlemleri kapat
            if position is not None:
                exit_price = current_row['close']
                if position == 'LONG':
                    profit_loss = (exit_price - entry_price) * leverage
                else:
                    profit_loss = (entry_price - exit_price) * leverage

                transactions[-1].update({
                    'exit_price': exit_price,
                    'exit_time': current_row.name,
                    'exit_balance': 0,
                    'profit_loss': profit_loss,
                    'trade_closed': True
                })

            balance = 0
            break

    # Son işlem hala açıksa kapat
    if position is not None:
        last_row = df.iloc[-1]
        exit_price = last_row['close']
        if position == 'LONG':
            profit_loss = (exit_price - entry_price) * leverage
        else:
            profit_loss = (entry_price - exit_price) * leverage

        transactions[-1].update({
            'exit_price': exit_price,
            'exit_time': last_row.name,
            'exit_balance': balance,
            'profit_loss': profit_loss,
            'trade_closed': True
        })

    total_trades = successful_trades + unsuccessful_trades
    success_rate = (successful_trades / total_trades * 100) if total_trades > 0 else 0
    profit_rate = ((balance / initial_balance) - 1) * 100

    return {
        'successful_trades': successful_trades,
        'unsuccessful_trades': unsuccessful_trades,
        'success_rate': success_rate,
        'final_balance': balance,
        'profit_rate': profit_rate,
        'trade_closed': balance <= 0,
        'transactions': transactions
    }


def main():
    print("Program başlıyor...")
    try:
        conn = create_db_connection()
        cursor = conn.cursor()
        print("Veritabanı bağlantısı kuruldu.")

        if os.path.exists("crypto_data.db"):
            print("Veritabanı bulundu. Mevcut verilerle analiz yapılacak.")

            # HATA DÜZELTİLDİ: fetchone() parantez eklendi
            cursor.execute("SELECT COUNT(*) FROM ohlcv_data")
            data_count = cursor.fetchone()[0]  # [0] eklenmiş
            print(f"Veritabanında {data_count} adet veri bulundu.")

            if data_count == 0:
                print("Veritabanı boş. API'den veri çekilecek.")
                fetch_data_from_api(conn)
            else:
                analyze_existing_data(conn)
        else:
            print("Veritabanı bulunamadı. API'den veri çekilecek.")
            fetch_data_from_api(conn)

        conn.close()
        print("\nTüm analizler tamamlandı!")

    except Exception as e:
        print(f"Ana program hatası: {str(e)}")
        traceback.print_exc()


def fetch_data_from_api(conn):
    print("API'den veri çekme işlemi başlıyor...")

    for symbol in symbols:
        print(f"\n{symbol} için veri çekme işlemi başlıyor...")
        try:
            dataframes = {tf: pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
                          for tf in ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]}

            end_date = int(datetime.now().timestamp() * 1000)
            start_date = end_date - (ANALYSIS_DAYS * 86400 * 1000)

            # Basit veri çekme - tüm günleri tek seferde çekmeye çalış
            timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]  # Daha az timeframe ile test

            for tf in timeframes:
                try:
                    print(f"{symbol} - {tf} timeframe verisi çekiliyor...")
                    bars = exchange.fetch_ohlcv(symbol, timeframe=tf, since=start_date, limit=1000)
                    if bars:
                        dataframes[tf] = pd.DataFrame(bars,
                                                      columns=["timestamp", "open", "high", "low", "close", "volume"])
                        print(f"{symbol} - {tf}: {len(bars)} veri noktası çekildi")

                        # Veritabanına kaydet
                        save_to_db(conn, symbol, dataframes[tf], tf)

                    time.sleep(1)  # Rate limit için bekle
                except Exception as e:
                    print(f"{symbol} - {tf} veri çekme hatası: {e}")

            # Analiz yap
            analyze_symbol(symbol, dataframes)

        except Exception as e:
            print(f"{symbol} işlemi sırasında hata: {e}")
            traceback.print_exc()


def analyze_existing_data(conn):
    print("Mevcut verilerle analiz yapılıyor...")

    for symbol in symbolName:
        print(f"\n{symbol} için analiz başlıyor...")
        try:
            dataframes = {}

            # Mevcut timeframe'leri kontrol et
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT timeframe FROM ohlcv_data WHERE symbol = ?", (symbol,))
            available_tfs = [row[0] for row in cursor.fetchall()]

            print(f"{symbol} için mevcut timeframe'ler: {available_tfs}")

            for tf in available_tfs:
                try:
                    df = pd.read_sql_query(
                        "SELECT * FROM ohlcv_data WHERE symbol = ? AND timeframe = ? ORDER BY timestamp",
                        conn,
                        params=(symbol, tf)
                    )
                    if not df.empty:
                        dataframes[tf] = df
                        print(f"{symbol} - {tf}: {len(df)} veri noktası yüklendi")
                except Exception as e:
                    print(f"{symbol} - {tf} verisi yüklenirken hata: {e}")

            if dataframes:
                analyze_symbol(symbol, dataframes)
            else:
                print(f"{symbol} için analiz edilecek veri bulunamadı")

        except Exception as e:
            print(f"{symbol} analizi sırasında hata: {e}")
            traceback.print_exc()


def analyze_symbol(symbol, dataframes):
    print(f"{symbol} analizi başlıyor...")

    for tf, df in dataframes.items():
        if not df.empty and len(df) > 50:
            try:
                print(f"\n{symbol} - {tf} timeframe için analiz yapılıyor... ({len(df)} veri noktası)")

                results = deneme(tf, df, len(df))

                print(f"DEBUG: Analiz sonuçları alındı:")
                print(f"  Balance optimizasyonu: {results['balance']}")
                print(f"  Success rate optimizasyonu: {results['success_rate']}")

                for metric in ['balance', 'success_rate']:
                    result = results[metric]

                    print(f"DEBUG: {metric} için kayıt yapılacak:")
                    print(f"  Symbol: {symbol}, Timeframe: {tf}")
                    print(f"  Başarılı işlem: {result['successful_trades']}")
                    print(f"  Başarısız işlem: {result['unsuccessful_trades']}")
                    print(f"  Final balance: {result['final_balance']}")

                    save_results_to_db(
                        symbol, tf,
                        result['leverage'],
                        result['stop_percentage'],
                        result['kar_al_percentage'],
                        result['atr_period'],
                        result['atr_multiplier'],
                        result['successful_trades'],
                        result['unsuccessful_trades'],
                        result['final_balance'],
                        metric
                    )

                    print(f"\n{tf} - {metric.upper()} OPTİMİZASYONU:")
                    print(f"  Kaldıraç: {result['leverage']}, Stop: {result['stop_percentage']}%, "
                          f"Kar Al: {result['kar_al_percentage']}%")
                    print(f"  ATR: {result['atr_period']}/{result['atr_multiplier']}")
                    print(f"  Başarılı: {result['successful_trades']}, Başarısız: {result['unsuccessful_trades']}")
                    print(f"  Son Bakiye: {result['final_balance']:.2f}, Başarı Oranı: %{result['success_rate']:.2f}")

            except Exception as e:
                print(f"{symbol} - {tf} analiz hatası: {e}")
                traceback.print_exc()


def check_database_status():
    """Veritabanı durumunu kontrol eden fonksiyon"""
    try:
        if not os.path.exists(LOCAL_DB_PATH):
            print(f"ERROR: Veritabanı dosyası mevcut değil: {LOCAL_DB_PATH}")
            return

        conn = sqlite3.connect(LOCAL_DB_PATH)
        cursor = conn.cursor()

        # Tabloları listele
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Mevcut tablolar: {[table[0] for table in tables]}")

        # analysis_results tablosundaki kay sayısı
        cursor.execute("SELECT COUNT(*) FROM analysis_results")
        count = cursor.fetchone()[0]
        print(f"analysis_results tablosunda {count} kayıt var")

        if count > 0:
            cursor.execute("SELECT symbol, timeframe, optimization_type FROM analysis_results LIMIT 5")
            samples = cursor.fetchall()
            print("Örnek kayıtlar:")
            for sample in samples:
                print(f"  {sample}")

        conn.close()

    except Exception as e:
        print(f"Veritabanı kontrol hatası: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    print("=== VERİTABANI DURUM KONTROLÜ ===")
    check_database_status()
    print("=== ANA PROGRAM BAŞLIYOR ===")
    main()
    print("=== VERİTABANI SON DURUM ===")
    check_database_status()