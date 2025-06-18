import time
import ccxt
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
import math
import os
from app import create_app
from app.models.database import TradingSettings
from app.extensions import db
from config import Config
import struct
from websocket import WebSocketManager

# --- Ayarlar ---
LOCAL_DB_PATH = 'crypto_data.db'
APP_DB_PATH = 'app.db'
USER_EMAIL = 'aren_32@hotmail.com'
SYMBOL = 'BTC/USDT'
TIMEFRAME = '1m'
ATR_PERIOD = 10
ATR_MULTIPLIER = 2.0
LEVERAGE = 7
STOP_LOSS_PCT = 4.5
TAKE_PROFIT_PCT = 3.5
INITIAL_BALANCE = 100.0

exchange = ccxt.binance({
    'options': {
        'defaultType': 'future'
    },
    'enableRateLimit': True
})


# --- ATR Hesaplama ---
def calculateATR(high, low, close, period):
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        tr.append(max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1])))
    atr = [np.nan] * (period - 1)
    atr.append(np.mean(tr[:period]))
    for i in range(period, len(tr)):
        atr.append((atr[-1] * (period - 1) + tr[i]) / period)
    return np.array(atr)


# --- Supertrend Hesaplama (deneme fonksiyonuyla uyumlu) ---
def generateSupertrend(close_array, high_array, low_array, atr_period, atr_multiplier):
    atr = calculateATR(high_array, low_array, close_array, atr_period)

    # Basic bands
    basic_upperband = (high_array + low_array) / 2 + atr_multiplier * atr
    basic_lowerband = (high_array + low_array) / 2 - atr_multiplier * atr

    # Final bands
    final_upperband = np.copy(basic_upperband)
    final_lowerband = np.copy(basic_lowerband)

    # Loop to adjust final bands based on previous values
    for i in range(atr_period + 1, len(basic_upperband)):
        if np.isnan(final_upperband[i - 1]):
            final_upperband[i] = basic_upperband[i]
        elif basic_upperband[i] < final_upperband[i - 1] or close_array[i - 1] > final_upperband[i - 1]:
            final_upperband[i] = basic_upperband[i]
        else:
            final_upperband[i] = final_upperband[i - 1]

        if np.isnan(final_lowerband[i - 1]):
            final_lowerband[i] = basic_lowerband[i]
        elif basic_lowerband[i] > final_lowerband[i - 1] or close_array[i - 1] < final_lowerband[i - 1]:
            final_lowerband[i] = basic_lowerband[i]
        else:
            final_lowerband[i] = final_lowerband[i - 1]

    # Supertrend hesaplama
    supertrend = np.zeros_like(close_array, dtype=float)
    supertrend[:atr_period] = np.nan

    # First valid Supertrend value
    if not np.isnan(close_array[atr_period]) and not np.isnan(final_upperband[atr_period]):
        if close_array[atr_period] > final_upperband[atr_period]:
            supertrend[atr_period] = final_lowerband[atr_period]
        else:
            supertrend[atr_period] = final_upperband[atr_period]
    else:
        supertrend[atr_period] = np.nan

    # Geri kalan değerler için
    for i in range(atr_period + 1, len(close_array)):
        if np.isnan(supertrend[i - 1]):
            if not np.isnan(close_array[i]) and not np.isnan(final_upperband[i]):
                if close_array[i] > final_upperband[i]:
                    supertrend[i] = final_lowerband[i]
                else:
                    supertrend[i] = final_upperband[i]
            else:
                supertrend[i] = np.nan
        elif supertrend[i - 1] == final_upperband[i - 1]:
            if close_array[i] > final_upperband[i]:
                supertrend[i] = final_lowerband[i]
            else:
                supertrend[i] = final_upperband[i]
        else:  # supertrend[i-1] == final_lowerband[i-1]
            if close_array[i] < final_lowerband[i]:
                supertrend[i] = final_upperband[i]
            else:
                supertrend[i] = final_lowerband[i]

    return supertrend


# --- app.db'de tabloyu oluştur ---
def create_appdb_table():
    conn = sqlite3.connect(APP_DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS realtime_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        symbol TEXT NOT NULL,
        trade_type TEXT NOT NULL,
        entry_price REAL NOT NULL,
        entry_time INTEGER NOT NULL,
        entry_balance REAL NOT NULL,
        exit_price REAL,
        exit_time INTEGER,
        exit_balance REAL,
        profit_loss REAL,
        trade_closed INTEGER NOT NULL
    )
    ''')
    conn.commit()
    conn.close()


# --- Eksik verileri Binance'ten çek ve kaydet ---
def fetch_and_save_ohlcv(symbol, timeframe, limit=1000):
    conn = sqlite3.connect(LOCAL_DB_PATH)
    cursor = conn.cursor()

    # Veritabanındaki en son timestamp'i al
    cursor.execute("SELECT MAX(timestamp) FROM ohlcv_data WHERE symbol = ? AND timeframe = ?", (symbol, timeframe))
    last_timestamp_db = cursor.fetchone()[0]

    since = None
    now_ms = int(datetime.now().timestamp() * 1000)
    print(f"[DEBUG] Current system time (ms): {now_ms} ({datetime.fromtimestamp(now_ms / 1000)})")

    if last_timestamp_db:
        # Son kaydın bir dakika sonrasından başlat (1m timeframe olduğu için)
        potential_since = last_timestamp_db + 60 * 1000

        # Ensure 'since' is not in the future or too close to future
        if potential_since > now_ms + 5 * 60 * 1000:
            print(
                f"UYARI: Veritabanındaki son timestamp ({datetime.fromtimestamp(last_timestamp_db / 1000)}) sistem zamanından 5 dakikadan fazla gelecekte. Veri çekmeye şimdiki zamandan 1 dakika öncesinden başlanıyor.")
            since = now_ms - 60 * 1000
        elif potential_since > now_ms - 1 * 60 * 1000:
            print(
                f"Bilgi: Veritabanındaki son timestamp ({datetime.fromtimestamp(last_timestamp_db / 1000)}) çok güncel. Sadece son 1 dakikayı çekmeye çalışılıyor.")
            since = now_ms - 60 * 1000
        else:
            since = potential_since
    else:
        # Veritabanı boşsa son 730 günlük veriyi çek
        print(f"Veritabanında {symbol} {timeframe} için veri bulunamadı. Son 730 günlük veri çekiliyor.")
        since = int((datetime.now() - timedelta(days=730)).timestamp() * 1000)

    all_ohlcv = []
    current_since = since

    # Sürekli olarak yeni veri çek
    while True:
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=current_since, limit=limit)

            if not bars:
                now_ms_inner = int(datetime.now().timestamp() * 1000)
                if current_since >= now_ms_inner - 5 * 60 * 1000:
                    print(f"{symbol} {timeframe} için en güncel veri bekleniyor veya çekme tamamlandı.")
                    break
                else:
                    print(
                        f"Uyarı: {symbol} {timeframe} için bars boş geldi ancak current_since geride ({datetime.fromtimestamp(current_since / 1000)}). 10 saniye bekleniyor ve tekrar deneniyor.")
                    time.sleep(10)
                    continue

            new_df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Zaman damgası zaten veritabanında olanları filtrele
            existing_timestamps = set()
            cursor.execute("SELECT timestamp FROM ohlcv_data WHERE symbol = ? AND timeframe = ? AND timestamp >= ?",
                           (symbol, timeframe, current_since))
            existing_timestamps = {row[0] for row in cursor.fetchall()}

            filtered_df = new_df[~new_df['timestamp'].isin(existing_timestamps)]

            if filtered_df.empty:
                now_ms_inner = int(datetime.now().timestamp() * 1000)
                if current_since >= now_ms_inner - 5 * 60 * 1000:
                    print(f"{symbol} {timeframe} için tüm yeni veriler zaten mevcut veya en güncel veri bekleniyor.")
                    break
                else:
                    print(
                        f"Uyarı: {symbol} {timeframe} için filtered_df boş geldi ancak current_since geride ({datetime.fromtimestamp(current_since / 1000)}). current_since şimdiki zamana ayarlanıyor.")
                    current_since = now_ms_inner - 60 * 1000
                    time.sleep(1)
                    continue

            # Veritabanına kaydet
            for _, row in filtered_df.iterrows():
                try:
                    cursor.execute('''INSERT INTO ohlcv_data (symbol, timestamp, timeframe, open, high, low, close, volume)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                                   (symbol, int(row['timestamp']), timeframe, row['open'], row['high'], row['low'],
                                    row['close'], row['volume']))
                except sqlite3.IntegrityError:
                    pass

            conn.commit()
            all_ohlcv.extend(filtered_df.values.tolist())

            print(f"{symbol} {timeframe}: {len(filtered_df)} yeni veri noktası çekildi ve kaydedildi.")

            # Bir sonraki çekimin başlangıç noktasını güncelle
            if not filtered_df.empty:
                current_since = int(filtered_df['timestamp'].iloc[-1]) + 60 * 1000
            else:
                current_since = int(datetime.now().timestamp() * 1000)

            time.sleep(1)

        except ccxt.RateLimitExceeded:
            print(f"UYARI: Rate limit aşıldı. {symbol} {timeframe} için 60 saniye bekleniyor...")
            time.sleep(60)
            continue

        except Exception as e:
            print(f"Binance'ten veri çekme hatası: {e}")
            break

    conn.close()
    return pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])


# --- crypto_data.db'den 1m verilerini oku ---
def get_ohlcv_1m(limit=None):
    conn = sqlite3.connect(LOCAL_DB_PATH)
    if limit:
        df = pd.read_sql_query(
            "SELECT * FROM ohlcv_data WHERE symbol = ? AND timeframe = ? ORDER BY timestamp DESC LIMIT ?",
            conn, params=(SYMBOL, TIMEFRAME, limit)
        )
        # Sıralamayı düzelt (eski tarihten yeniye)
        df = df.sort_values('timestamp').reset_index(drop=True)
    else:
        df = pd.read_sql_query(
            "SELECT * FROM ohlcv_data WHERE symbol = ? AND timeframe = ? ORDER BY timestamp",
            conn, params=(SYMBOL, TIMEFRAME)
        )
    conn.close()
    print("DEBUG: get_ohlcv_1m - DataFrame info after reading from DB:")
    df.info()
    return df


# --- Strateji ve İşlem Kaydı (deneme fonksiyonu mantığıyla) ---
def run_strategy_and_save(df, user_email, symbol):
    """
    deneme fonksiyonundaki mantığı kullanarak gerçek zamanlı strateji çalıştırır
    """
    print(f"\nStrateji çalıştırılıyor - {symbol} {TIMEFRAME}")

    # Veri tiplerini kontrol et ve dönüştür
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')

    # NaN değerleri temizle
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'timestamp'])
    df = df.reset_index(drop=True)

    if len(df) < ATR_PERIOD + 10:
        print("Yeterli veri yok")
        return

    # Arrays oluştur
    close_array = df["close"].values.astype(float)
    high_array = df["high"].values.astype(float)
    low_array = df["low"].values.astype(float)
    open_array = df["open"].values.astype(float)

    # Supertrend hesapla
    supertrend = generateSupertrend(close_array, high_array, low_array, ATR_PERIOD, ATR_MULTIPLIER)

    # Veritabanı bağlantısı
    conn = sqlite3.connect(APP_DB_PATH)
    cursor = conn.cursor()

    # Mevcut açık işlemleri kontrol et
    cursor.execute("""
        SELECT id, trade_type, entry_price, entry_time, entry_balance
        FROM realtime_transactions
        WHERE user_email = ? AND symbol = ? AND trade_closed = 0
    """, (user_email, symbol))
    open_trades = cursor.fetchall()

    # Mevcut bakiyeyi hesapla (son işlemden)
    cursor.execute("""
        SELECT exit_balance FROM realtime_transactions
        WHERE user_email = ? AND symbol = ? AND trade_closed = 1
        ORDER BY exit_time DESC LIMIT 1
    """, (user_email, symbol))
    last_balance = cursor.fetchone()
    current_balance = last_balance[0] if last_balance else INITIAL_BALANCE

    # Açık pozisyon kontrolü
    position = None
    entry_price = 0
    entry_balance = current_balance
    trade_id = None

    if open_trades:
        trade_id, position, entry_price, entry_time_raw, entry_balance = open_trades[0]
        print(f"Açık pozisyon bulundu: {position} @ {entry_price}")

    # *** ANA DÜZELTME: Sadece son candle'ı işle ***
    # Son candle index'i (en son tamamlanan candle)
    last_index = len(df) - 1

    # NaN kontrolü
    if (last_index < ATR_PERIOD + 1 or
            math.isnan(supertrend[last_index]) or
            math.isnan(supertrend[last_index - 1])):
        print("Supertrend hesaplama için yeterli veri yok")
        conn.close()
        return

    current_timestamp = int(df['timestamp'].iloc[last_index])

    # *** DÜZELTME: Sadece birden fazla açık pozisyon kontrolü ***
    cursor.execute("""
        SELECT COUNT(*) FROM realtime_transactions
        WHERE user_email = ? AND symbol = ? AND entry_time = ? AND trade_closed = 0
    """, (user_email, symbol, current_timestamp))

    existing_open_count = cursor.fetchone()[0]
    if existing_open_count > 1:  # 1'den fazla açık pozisyon varsa
        print(f"Bu timestamp ({current_timestamp}) için zaten birden fazla açık pozisyon var, atlanıyor...")
        conn.close()
        return

    i = last_index  # Sadece son candle'ı kontrol et

    # Açık pozisyon varsa kontrol et
    if position is not None and trade_id is not None:
        # LONG pozisyonu için
        if position == 'LONG':
            # Stop loss kontrolü
            if STOP_LOSS_PCT > 0 and close_array[i] <= entry_price * (1 - STOP_LOSS_PCT / 100):
                exit_price = close_array[i]
                price_change_pct = ((exit_price - entry_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)
                new_balance = max(0, new_balance)

                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"LONG pozisyon stop loss ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")
                position = None

            # Take profit kontrolü
            elif TAKE_PROFIT_PCT > 0 and close_array[i] >= entry_price * (1 + TAKE_PROFIT_PCT / 100):
                exit_price = close_array[i]
                price_change_pct = ((exit_price - entry_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)

                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"LONG pozisyon take profit ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")
                position = None

            # Trend değişimi kontrolü
            elif close_array[i] < supertrend[i] and close_array[i - 1] >= supertrend[i - 1]:
                exit_price = close_array[i]
                price_change_pct = ((exit_price - entry_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)
                new_balance = max(0, new_balance)

                # Mevcut LONG pozisyonu kapat
                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"LONG pozisyon trend değişimi ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")

                # Aynı candle'da ters yönde SHORT pozisyon aç
                if new_balance > 0:
                    cursor.execute("""
                        INSERT INTO realtime_transactions 
                        (user_email, symbol, trade_type, entry_price, entry_time, entry_balance, trade_closed)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (user_email, symbol, 'SHORT', exit_price, current_timestamp, new_balance, 0))

                    print(f"Yeni SHORT pozisyon açıldı: {exit_price} @ Bakiye: {new_balance:.2f}")

                    # Local değişkenleri güncelle
                    position = 'SHORT'
                    entry_price = exit_price
                    entry_balance = new_balance
                    trade_id = cursor.lastrowid
                else:
                    position = None

        # SHORT pozisyonu için
        elif position == 'SHORT':
            # Stop loss kontrolü
            if STOP_LOSS_PCT > 0 and close_array[i] >= entry_price * (1 + STOP_LOSS_PCT / 100):
                exit_price = close_array[i]
                price_change_pct = ((entry_price - exit_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)
                new_balance = max(0, new_balance)

                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"SHORT pozisyon stop loss ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")
                position = None

            # Take profit kontrolü
            elif TAKE_PROFIT_PCT > 0 and close_array[i] <= entry_price * (1 - TAKE_PROFIT_PCT / 100):
                exit_price = close_array[i]
                price_change_pct = ((entry_price - exit_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)

                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"SHORT pozisyon take profit ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")
                position = None

            # Trend değişimi kontrolü
            elif close_array[i] > supertrend[i] and close_array[i - 1] <= supertrend[i - 1]:
                exit_price = close_array[i]
                price_change_pct = ((entry_price - exit_price) / entry_price) * 100
                profit_loss = price_change_pct * LEVERAGE
                new_balance = entry_balance * (1 + profit_loss / 100)
                new_balance = max(0, new_balance)

                # Mevcut SHORT pozisyonu kapat
                cursor.execute("""
                    UPDATE realtime_transactions
                    SET exit_price = ?, exit_time = ?, exit_balance = ?, profit_loss = ?, trade_closed = 1
                    WHERE id = ?
                """, (exit_price, current_timestamp, new_balance, profit_loss, trade_id))

                print(
                    f"SHORT pozisyon trend değişimi ile kapandı: Kar/Zarar: {profit_loss:.2f}%, Yeni Bakiye: {new_balance:.2f}")

                # Aynı candle'da ters yönde LONG pozisyon aç
                if new_balance > 0:
                    cursor.execute("""
                        INSERT INTO realtime_transactions 
                        (user_email, symbol, trade_type, entry_price, entry_time, entry_balance, trade_closed)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (user_email, symbol, 'LONG', exit_price, current_timestamp, new_balance, 0))

                    print(f"Yeni LONG pozisyon açıldı: {exit_price} @ Bakiye: {new_balance:.2f}")

                    # Local değişkenleri güncelle
                    position = 'LONG'
                    entry_price = exit_price
                    entry_balance = new_balance
                    trade_id = cursor.lastrowid
                else:
                    position = None

    # Pozisyon yoksa yeni pozisyon açma kontrolü
    elif position is None and current_balance > 0:
        # LONG sinyali - trend yukarı dönüyor
        if (close_array[i] > supertrend[i] and close_array[i - 1] <= supertrend[i - 1]):
            entry_price = close_array[i]

            cursor.execute("""
                INSERT INTO realtime_transactions 
                (user_email, symbol, trade_type, entry_price, entry_time, entry_balance, trade_closed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_email, symbol, 'LONG', entry_price, current_timestamp, current_balance, 0))

            print(f"Yeni LONG pozisyon açıldı: {entry_price} @ Bakiye: {current_balance:.2f}")

        # SHORT sinyali - trend aşağı dönüyor
        elif (close_array[i] < supertrend[i] and close_array[i - 1] >= supertrend[i - 1]):
            entry_price = close_array[i]

            cursor.execute("""
                INSERT INTO realtime_transactions 
                (user_email, symbol, trade_type, entry_price, entry_time, entry_balance, trade_closed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_email, symbol, 'SHORT', entry_price, current_timestamp, current_balance, 0))

            print(f"Yeni SHORT pozisyon açıldı: {entry_price} @ Bakiye: {current_balance:.2f}")

    conn.commit()
    conn.close()
    print("Strateji çalıştırma tamamlandı.")

def run_simulation(df_ohlcv):
    app = create_app()
    with app.app_context():
        # Aktif ayarları al
        settings = TradingSettings.query.first()
        if not settings:
            print("Aktif ayar bulunamadı!")
            return

        # Stratejiyi çalıştır
        run_strategy_and_save(df_ohlcv, USER_EMAIL, 'BTC/USDT')

def on_new_data(kline_data):
    print(f"Yeni veri geldi: {kline_data['symbol']} - {kline_data['close']} - {datetime.fromtimestamp(kline_data['timestamp'] / 1000)}")
    # Son 200 mumu çek
    df_current_ohlcv = get_ohlcv_1m(limit=200)
    if df_current_ohlcv.empty or len(df_current_ohlcv) < ATR_PERIOD + 1:
        print(f"Yeterli OHLCV verisi yok (şu an {len(df_current_ohlcv)} mum var), bekleniyor...")
        return
    run_strategy_and_save(df_current_ohlcv, USER_EMAIL, SYMBOL)


# --- Ana Akış ---
if __name__ == "__main__":
    create_appdb_table()
    print("Başlangıçta eksik veriler tamamlanıyor...")
    fetch_and_save_ohlcv(SYMBOL, TIMEFRAME)  # Sadece bir kere, eksik verileri tamamlamak için

    print("WebSocket ile anlık veri dinleniyor ve strateji tetiklenecek...")
    ws_manager = WebSocketManager()
    ws_manager.start('btcusdt', on_new_data)
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("Durduruluyor...")
        ws_manager.stop()