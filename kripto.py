import time
import ccxt
import pandas as pd
import numpy as np
import struct
from datetime import datetime
import ta
import math
import mysql.connector
import requests
import os
import argparse
import traceback

# MySQL bağlantı fonksiyonu
def get_mysql_connection():
    try:
        return mysql.connector.connect(
            host="193.203.168.175",
            user="u162605596_kripto2",
            password="Arenkos1.",
            database="u162605596_kripto2",
            connection_timeout=60,
            autocommit=True,
            buffered=True
        )
    except mysql.connector.Error as err:
        print(f"MySQL bağlantı hatası: {err}")
        return None

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
    conn = get_mysql_connection()
    if not conn:
        print("MySQL bağlantısı kurulamadı!")
        return None
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ohlcv_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(50),
        timestamp BIGINT,
        timeframe VARCHAR(10),
        open DECIMAL(20,8),
        high DECIMAL(20,8),
        low DECIMAL(20,8),
        close DECIMAL(20,8),
        volume DECIMAL(20,8),
        UNIQUE KEY unique_symbol_timeframe_timestamp (symbol, timeframe, timestamp)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INT AUTO_INCREMENT PRIMARY KEY,
        symbol VARCHAR(50) NOT NULL,
        timeframe VARCHAR(10) NOT NULL,
        leverage DECIMAL(10,4) NOT NULL,
        stop_percentage DECIMAL(10,4) NOT NULL,
        kar_al_percentage DECIMAL(10,4) NOT NULL,
        atr_period INT NOT NULL,
        atr_multiplier DECIMAL(10,4) NOT NULL,
        successful_trades INT NOT NULL,
        unsuccessful_trades INT NOT NULL,
        final_balance DECIMAL(20,8) NOT NULL,
        success_rate DECIMAL(10,4) NOT NULL,
        optimization_type VARCHAR(20) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY unique_symbol_timeframe_optimization (symbol, timeframe, optimization_type)
    )
    ''')

    # İşlem geçmişi için yeni tablo
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS backtest_transactions (
        id INT AUTO_INCREMENT PRIMARY KEY,
        analysis_id INT NOT NULL,
        trade_type VARCHAR(10) NOT NULL,
        entry_price DECIMAL(20,8) NOT NULL,
        entry_time BIGINT NOT NULL,
        entry_balance DECIMAL(20,8) NOT NULL,
        exit_price DECIMAL(20,8),
        exit_time BIGINT,
        exit_balance DECIMAL(20,8),
        profit_loss DECIMAL(20,8),
        trade_closed TINYINT NOT NULL,
        FOREIGN KEY (analysis_id) REFERENCES analysis_results(id)
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

        conn = get_mysql_connection()
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

        analysis_id = cursor.lastrowid
        print(f"DEBUG: Yeni kayıt eklendi - ID: {analysis_id}")

        # Backtest işlem geçmişini kaydet
        if 'transactions' in locals():
            for transaction in transactions:
                cursor.execute('''
                INSERT INTO backtest_transactions (
                    analysis_id, trade_type, entry_price, entry_time,
                    entry_balance, exit_price, exit_time, exit_balance,
                    profit_loss, trade_closed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    analysis_id,
                    transaction['trade_type'],
                    transaction['entry_price'],
                    transaction['entry_time'],
                    transaction['entry_balance'],
                    transaction.get('exit_price'),
                    transaction.get('exit_time'),
                    transaction.get('exit_balance'),
                    transaction.get('profit_loss'),
                    1 if transaction['trade_closed'] else 0
                ))

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
                            print(
                                f"Optimizasyon ilerlemesi: %{progress:.1f} ({optimization_count}/{total_optimizations})")

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
                                if close_array[i - 1] > supertrend[i - 1] and close_array[i - 2] <= supertrend[i - 2]:
                                    position = 'LONG'
                                    entry_price = open_array[i]  # Bir sonraki mumun açılışında işleme gir
                                    entry_balance = balance
                                    transactions.append({
                                        'trade_type': 'LONG',
                                        'entry_price': entry_price,
                                        'entry_time': df['timestamp'].iloc[i],
                                        'entry_balance': entry_balance,
                                        'trade_closed': False
                                    })

                                # SHORT sinyali (önceki mumda SHORT sinyali varsa ve şu anki mumun açılışında işleme gir)
                                elif close_array[i - 1] < supertrend[i - 1] and close_array[i - 2] >= supertrend[i - 2]:
                                    position = 'SHORT'
                                    entry_price = open_array[i]  # Bir sonraki mumun açılışında işleme gir
                                    entry_balance = balance
                                    transactions.append({
                                        'trade_type': 'SHORT',
                                        'entry_price': entry_price,
                                        'entry_time': df['timestamp'].iloc[i],
                                        'entry_balance': entry_balance,
                                        'trade_closed': False
                                    })

                            # Eğer pozisyon varsa
                            elif position is not None:
                                # LONG pozisyonu için
                                if position == 'LONG':
                                    # Stop loss kontrolü (mevcut mumda)
                                    if stop_pct > 0 and low_array[i] <= entry_price * (1 - stop_pct / 100):
                                        exit_price = entry_price * (1 - stop_pct / 100)
                                        profit_loss = (exit_price - entry_price) * leverage
                                        balance += profit_loss
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df['timestamp'].iloc[i],
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
                                            'exit_time': df['timestamp'].iloc[i],
                                            'exit_balance': 0,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })
                                        break

                                    # Take profit kontrolü (mevcut mumda)
                                    elif kar_al_pct > 0 and high_array[i] >= entry_price * (1 + kar_al_pct / 100):
                                        exit_price = entry_price * (1 + kar_al_pct / 100)
                                        profit_loss = (exit_price - entry_price) * leverage
                                        balance += profit_loss
                                        successful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df['timestamp'].iloc[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Trend değişimi kontrolü (bir sonraki mumun açılışında)
                                    elif close_array[i] < supertrend[i] and close_array[i - 1] >= supertrend[i - 1]:
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
                                                'exit_time': df['timestamp'].iloc[i + 1],
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
                                                    'entry_time': df['timestamp'].iloc[i + 1],
                                                    'entry_balance': entry_balance,
                                                    'trade_closed': False
                                                })
                                            else:
                                                position = None

                                # SHORT pozisyonu için
                                elif position == 'SHORT':
                                    # Stop loss kontrolü (mevcut mumda)
                                    if stop_pct > 0 and high_array[i] >= entry_price * (1 + stop_pct / 100):
                                        exit_price = entry_price * (1 + stop_pct / 100)
                                        profit_loss = (entry_price - exit_price) * leverage
                                        balance += profit_loss
                                        unsuccessful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df['timestamp'].iloc[i],
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
                                            'exit_time': df['timestamp'].iloc[i],
                                            'exit_balance': 0,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })
                                        break

                                    # Take profit kontrolü (mevcut mumda)
                                    elif kar_al_pct > 0 and low_array[i] <= entry_price * (1 - kar_al_pct / 100):
                                        exit_price = entry_price * (1 - kar_al_pct / 100)
                                        profit_loss = (entry_price - exit_price) * leverage
                                        balance += profit_loss
                                        successful_trades += 1
                                        position = None
                                        transactions[-1].update({
                                            'exit_price': exit_price,
                                            'exit_time': df['timestamp'].iloc[i],
                                            'exit_balance': balance,
                                            'profit_loss': profit_loss,
                                            'trade_closed': True
                                        })

                                    # Trend değişimi kontrolü (bir sonraki mumun açılışında)
                                    elif close_array[i] > supertrend[i] and close_array[i - 1] <= supertrend[i - 1]:
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
                                                'exit_time': df['timestamp'].iloc[i + 1],
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
                                                    'entry_time': df['timestamp'].iloc[i + 1],
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
                                'exit_time': df['timestamp'].iloc[-1],
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
                            print(
                                f"Yeni en iyi bakiye: {balance:.2f} (Kaldıraç: {leverage}, Stop: {stop_pct}%, Kar Al: {kar_al_pct}%)")

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


# Yardımcı fonksiyon: timestamp'i int'e çevir
def to_int_timestamp(val):
    if isinstance(val, (int, np.integer)):
        return int(val)
    elif isinstance(val, float):
        return int(val)
    elif isinstance(val, bytes):
        return int.from_bytes(val, byteorder='little', signed=False)
    elif isinstance(val, str) and val.isdigit():
        return int(val)
    else:
        raise ValueError(f"Geçersiz timestamp formatı: {val}")


def backtest_strategy(df, initial_balance, leverage, stop_loss_percentage, take_profit_percentage, atr_period, atr_multiplier):
    """
    Stratejiyi backtest eder ve sonuçları döndürür.
    İşleme girişleri bir sonraki mumun açılışında yapılır.
    Bakiyeyi yüzdeyle günceller (kripto_test.py'deki deneme fonksiyonu gibi).
    Giriş ve çıkış zamanları gerçek timestamp olarak kaydedilir.
    """
    # Veri hazırlığı
    df = df.copy()
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df.reset_index(drop=True)

    if 'timestamp' not in df.columns:
        raise ValueError('DataFrame içinde timestamp sütunu yok!')

    supertrend = generateSupertrend(df['close'].values, df['high'].values, df['low'].values, atr_period, atr_multiplier)

    balance = initial_balance
    successful_trades = 0
    unsuccessful_trades = 0
    transactions = []

    lim = len(df)
    i = atr_period + 1
    while i < lim - 3:
        if balance <= 0:
            break
        if (math.isnan(supertrend[i]) or math.isnan(supertrend[i - 1]) or i - 1 < 0 or i >= len(df)):
            i += 1
            continue
        current_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i - 1]
        current_st = supertrend[i]
        prev_st = supertrend[i - 1]
        trade_direction = None
        entry_price = None
        # Long sinyal
        if current_close > current_st and prev_close <= prev_st:
            trade_direction = "LONG"
            entry_price = df['open'].iloc[i + 1] if i + 1 < len(df) else current_close
        # Short sinyal
        elif current_close < current_st and prev_close >= prev_st:
            trade_direction = "SHORT"
            entry_price = df['open'].iloc[i + 1] if i + 1 < len(df) else current_close
        if trade_direction and entry_price:
            entry_balance = balance
            entry_time = to_int_timestamp(df['timestamp'].iloc[i])
            transactions.append({
                'trade_type': trade_direction,
                'entry_price': entry_price,
                'entry_time': entry_time,
                'entry_balance': entry_balance,
                'trade_closed': False
            })
            j = i + 1
            trade_closed = False
            while j < lim and not trade_closed:
                if (j >= len(supertrend) or math.isnan(supertrend[j]) or j - 1 < 0 or math.isnan(supertrend[j - 1])):
                    j += 1
                    continue
                current_high = df['high'].iloc[j]
                current_low = df['low'].iloc[j]
                current_close_j = df['close'].iloc[j]
                current_st_j = supertrend[j]
                prev_close_j = df['close'].iloc[j - 1] if j > 0 else current_close_j
                prev_st_j = supertrend[j - 1] if j > 0 else current_st_j
                if trade_direction == "LONG":
                    loss_pct = (current_low - entry_price) / entry_price * 100
                    # Stop loss
                    if loss_pct <= -stop_loss_percentage and not stop_loss_percentage <= -90 / leverage:
                        balance += balance * (-stop_loss_percentage / 100) * leverage
                        unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': entry_price * (1 - stop_loss_percentage / 100),
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                    # Likit
                    elif loss_pct <= -90 / leverage:
                        balance = 0
                        unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': current_low,
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': 0,
                            'profit_loss': -entry_balance,
                            'trade_closed': True
                        })
                        break
                    # Kar al
                    profit_pct = (current_high - entry_price) / entry_price * 100
                    if profit_pct >= take_profit_percentage:
                        balance += balance * (take_profit_percentage / 100) * leverage
                        successful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': entry_price * (1 + take_profit_percentage / 100),
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                    # Sinyal ile çıkış - Short sinyali
                    elif current_close_j < current_st_j and prev_close_j >= prev_st_j:
                        exit_price = df['open'].iloc[j + 1] if j + 1 < len(df) else current_close_j
                        profit_pct = (exit_price - entry_price) / entry_price * 100
                        balance += balance * (profit_pct / 100) * leverage
                        if profit_pct > 0:
                            successful_trades += 1
                        else:
                            unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': exit_price,
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j + 1]) if j + 1 < len(df) else to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                elif trade_direction == "SHORT":
                    loss_pct = (current_high - entry_price) / entry_price * 100
                    # Stop loss
                    if loss_pct >= stop_loss_percentage and not stop_loss_percentage >= 90 / leverage:
                        balance += balance * (-stop_loss_percentage / 100) * leverage
                        unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': entry_price * (1 + stop_loss_percentage / 100),
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                    # Likit
                    elif loss_pct >= 90 / leverage:
                        balance = 0
                        unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': current_high,
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': 0,
                            'profit_loss': -entry_balance,
                            'trade_closed': True
                        })
                        break
                    # Kar al
                    profit_pct = (entry_price - current_low) / entry_price * 100
                    if profit_pct >= take_profit_percentage:
                        balance += balance * (take_profit_percentage / 100) * leverage
                        successful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': entry_price * (1 - take_profit_percentage / 100),
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                    # Sinyal ile çıkış - Long sinyali
                    elif current_close_j > current_st_j and prev_close_j <= prev_st_j:
                        exit_price = df['open'].iloc[j + 1] if j + 1 < len(df) else current_close_j
                        profit_pct = (entry_price - exit_price) / entry_price * 100
                        balance += balance * (profit_pct / 100) * leverage
                        if profit_pct > 0:
                            successful_trades += 1
                        else:
                            unsuccessful_trades += 1
                        trade_closed = True
                        transactions[-1].update({
                            'exit_price': exit_price,
                            'exit_time': to_int_timestamp(df['timestamp'].iloc[j + 1]) if j + 1 < len(df) else to_int_timestamp(df['timestamp'].iloc[j]),
                            'exit_balance': balance,
                            'profit_loss': balance - entry_balance,
                            'trade_closed': True
                        })
                j += 1
            i = j if trade_closed else i + 1
        else:
            i += 1
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


def generate_backtest_transactions(conn):
    """
    Analysis results tablosundaki kayıtlara göre işlem geçmişini oluşturur
    """
    try:
        cursor = conn.cursor()
        
        # Analysis results tablosundan tüm kayıtları al
        cursor.execute("""
        SELECT id, symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
               atr_period, atr_multiplier
        FROM analysis_results
        """)
        analysis_records = cursor.fetchall()
        
        print(f"Toplam {len(analysis_records)} adet analiz sonucu için işlem geçmişi oluşturulacak.")
        
        for record in analysis_records:
            analysis_id, symbol, timeframe, leverage, stop_loss, take_profit, atr_period, atr_multiplier = record
            
            print(f"\n{symbol} - {timeframe} için işlem geçmişi oluşturuluyor...")
            print(f"Parametreler: Kaldıraç={leverage}, Stop={stop_loss}%, Kar Al={take_profit}%, ATR={atr_period}/{atr_multiplier}")

            symbol_filter = f"%{symbol}%"

            cursor.execute("""
                SELECT timestamp, open, high, low, close
                FROM ohlcv_data
                WHERE symbol LIKE ? AND timeframe = ?
                ORDER BY timestamp
            """, (symbol_filter, timeframe))
            
            ohlcv_data = cursor.fetchall()
            
            if not ohlcv_data:
                print(f"Uyarı: {symbol} - {timeframe} için OHLCV verisi bulunamadı.")
                continue
            
            print(f"OHLCV verisi yüklendi: {len(ohlcv_data)} satır")
            
            # DataFrame oluştur
            df = pd.DataFrame(ohlcv_data, columns=['timestamp', 'open', 'high', 'low', 'close'])
            # df.set_index('timestamp', inplace=True)  # Bu satırı kaldırdık, timestamp sütunu kaybolmasın!
            
            # Backtest yap
            result = backtest_strategy(
                df,
                initial_balance=100,
                leverage=leverage,
                stop_loss_percentage=stop_loss,
                take_profit_percentage=take_profit,
                atr_period=atr_period,
                atr_multiplier=atr_multiplier
            )
            
            print(f"\nBacktest sonuçları:")
            print(f"Başarılı işlemler: {result['successful_trades']}")
            print(f"Başarısız işlemler: {result['unsuccessful_trades']}")
            print(f"Toplam işlem: {result['successful_trades'] + result['unsuccessful_trades']}")
            print(f"Başarı oranı: %{result['success_rate']:.2f}")
            print(f"Final bakiye: {result['final_balance']:.2f}")
            print(f"Kar/Zarar oranı: %{result['profit_rate']:.2f}")
            
            # İşlem geçmişini kaydet
            for transaction in result['transactions']:
                cursor.execute('''
                INSERT INTO backtest_transactions (
                    analysis_id, trade_type, entry_price, entry_time,
                    entry_balance, exit_price, exit_time, exit_balance,
                    profit_loss, trade_closed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    analysis_id,
                    transaction['trade_type'],
                    transaction['entry_price'],
                    transaction['entry_time'],
                    transaction['entry_balance'],
                    transaction.get('exit_price'),
                    transaction.get('exit_time'),
                    transaction.get('exit_balance'),
                    transaction.get('profit_loss'),
                    1 if transaction['trade_closed'] else 0
                ))
            
            conn.commit()
            print(f"{symbol} - {timeframe} için {len(result['transactions'])} adet işlem kaydedildi.")
        
        print("\nTüm işlem geçmişleri oluşturuldu ve kaydedildi.")
        
    except Exception as e:
        print(f"İşlem geçmişi oluşturma hatası: {str(e)}")
        traceback.print_exc()
        conn.rollback()


def main():
    print("Program başlıyor...")
    try:
        conn = create_db_connection()
        cursor = conn.cursor()
        print("Veritabanı bağlantısı kuruldu.")

        if os.path.exists("crypto_data.db"):
            print("Veritabanı bulundu. Kontroller yapılıyor...")

            # OHLCV veri kontrolü
            cursor.execute("SELECT COUNT(*) FROM ohlcv_data")
            data_count = cursor.fetchone()[0]
            print(f"Veritabanında {data_count} adet OHLCV verisi bulundu.")

            # Analysis results kontrolü
            cursor.execute("SELECT COUNT(*) FROM analysis_results")
            analysis_count = cursor.fetchone()[0]
            print(f"Veritabanında {analysis_count} adet analiz sonucu bulundu.")

            if analysis_count >= 300:
                print("Yeterli sayıda analiz sonucu bulundu. İşlem geçmişi oluşturuluyor...")
                generate_backtest_transactions(conn)
            else:
                if data_count == 0:
                    print("Veritabanı boş. API'den veri çekilecek.")
                    fetch_data_from_api(conn)
                else:
                    print("Mevcut verilerle analiz yapılacak.")
                    analyze_existing_data(conn)
        else:
            print("Veritabanı bulunamadı. API'den veri çekilecek.")
            fetch_data_from_api(conn)

        conn.close()
        print("\nTüm işlemler tamamlandı!")

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

                # DataFrame'i düzenle
                df = df.copy()
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                # df.set_index('timestamp', inplace=True)
                
                # Veri tiplerini kontrol et
                df['open'] = pd.to_numeric(df['open'], errors='coerce')
                df['high'] = pd.to_numeric(df['high'], errors='coerce')
                df['low'] = pd.to_numeric(df['low'], errors='coerce')
                df['close'] = pd.to_numeric(df['close'], errors='coerce')
                
                # NaN değerleri temizle
                df = df.dropna(subset=['open', 'high', 'low', 'close'])
                
                if len(df) < 50:
                    print(f"Uyarı: {symbol} - {tf} için yeterli veri yok ({len(df)} satır)")
                    continue

                print(f"Veri hazırlığı tamamlandı. {len(df)} satır veri ile analiz başlıyor...")
                
                # deneme fonksiyonunu çağır
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