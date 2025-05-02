import time
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib as ta
import math
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from app.services.ohlcv_service import OHLCVService
from functools import partial
from app.services.backtest_service import BacktestService
symbol = "BTC/USDT"
symbolName = "BTC"

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
        lim = 2 * 143 * float(mum)
        bekleme = int(a[0]) * 60 * 60 * 24 * 7
    lim = lim * 1
    return lim, bekleme, mum, periyot


# Function to generate Supertrend indicator values
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


# Function to fetch historical data for all timeframes
def fetch_all_historical_data():
    print("Fetching historical data...")
    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]
    dataframes = {}
    
    # OHLCV servisini başlat
    ohlcv_service = OHLCVService(exchange)
    
    # Başlangıç tarihi (2 yıl önce)
    start_date = datetime.utcnow() - timedelta(days=730)
    end_date = datetime.utcnow()

    for tf in timeframes:
        print(f"Fetching {tf} timeframe data...")
        try:
            # Verileri DataFrame olarak al
            df = ohlcv_service.get_data_as_dataframe(symbol, tf, start_date, end_date)
            
            if not df.empty:
                dataframes[tf] = df
            else:
                print(f"No data available for {tf} timeframe")
                
        except Exception as e:
            print(f"Error fetching {tf} timeframe data: {e}")
            continue

    return dataframes

# Function to backtest the strategy
def backtest_strategy(timeframe, df):
    print(f"Backtesting {timeframe} timeframe...")
    best_result = {
        'leverage': 1,
        'stop_percentage': 0.5,
        'atr_period': 10,
        'atr_multiplier': 3,
        'success_rate': 0,
        'profit_rate': 0,
        'successful_trades': 0,
        'unsuccessful_trades': 0,
        'final_balance': 100,
        'trades': []
    }

    # ATR parametreleri için aralıklar
    atr_periods = range(5, 31, 5)  # 5'ten 30'a 5'er artışla
    atr_multipliers = [x / 10 for x in range(10, 51, 10)]  # 1.0'dan 5.0'a 1.0 artışla

    # Zaman aralığına göre işlem sıklığı kontrolü - kısa zaman aralıkları için işlem sayısını sınırla
    min_bars_between_trades = 1
    if timeframe.endswith('m'):
        min_bars_between_trades = max(5, int(timeframe[:-1]) // 3)  # Dakikalık grafiklerde daha az işlem
    elif timeframe.endswith('h'):
        min_bars_between_trades = max(3, int(timeframe[:-1]))  # Saatlik grafiklerde daha az işlem
    else:
        min_bars_between_trades = 1  # Günlük/Haftalık için normal

    print(f"Min bars between trades for {timeframe}: {min_bars_between_trades}")

    for atr_period in atr_periods:
        for atr_multiplier in atr_multipliers:
            leverage = 1
            while leverage <= 20:  # Daha makul bir kaldıraç üst sınırı
                stop_percentage = 0.5
                while stop_percentage <= 5:  # Daha makul bir stop loss üst sınırı
                    bakiye = 100.0
                    basarili = 0
                    basarisiz = 0
                    trades = []
                    pozisyon_acik = False
                    son_islem_indeksi = -min_bars_between_trades * 2  # İşlemleri sınırlamak için son işlem indeksi
                    
                    # Debugging için değişkenler
                    toplam_kar_zarar = 0

                    # Supertrend hesaplama
                    close_array = np.asarray(df["close"]).astype(float)
                    high_array = np.asarray(df["high"]).astype(float)
                    low_array = np.asarray(df["low"]).astype(float)

                    supertrend = generateSupertrend(close_array, high_array, low_array,
                                                  atr_period=atr_period,
                                                  atr_multiplier=atr_multiplier)

                    # Trading simülasyonu
                    for i in range(3, len(df)):
                        try:
                            # Minimum işlem aralığı kontrolü
                            if i - son_islem_indeksi < min_bars_between_trades:
                                continue
                                
                            son_kapanis = close_array[i - 2]
                            onceki_kapanis = close_array[i - 3]
                            son_supertrend = supertrend[i - 2]
                            onceki_supertrend = supertrend[i - 3]

                            # Sadece bir pozisyon açık değilse yeni sinyal alalım
                            if not pozisyon_acik:
                                # Long pozisyon sinyali
                                if son_kapanis > son_supertrend and onceki_kapanis < onceki_supertrend:
                                    giris_fiyati = float(df["open"].iloc[i])
                                    pozisyon_tipi = "long"
                                    pozisyon_acik = True
                                    pozisyon_acilis_indeksi = i
                                    son_islem_indeksi = i  # Son işlem indeksini güncelle
                                
                                # Short pozisyon sinyali
                                elif son_kapanis < son_supertrend and onceki_kapanis > onceki_supertrend:
                                    giris_fiyati = float(df["open"].iloc[i])
                                    pozisyon_tipi = "short"
                                    pozisyon_acik = True
                                    pozisyon_acilis_indeksi = i
                                    son_islem_indeksi = i  # Son işlem indeksini güncelle
                            
                            # Açık pozisyon varsa kontrol edelim
                            if pozisyon_acik:
                                # LONG pozisyon için çıkış kontrolü
                                if pozisyon_tipi == "long":
                                    # Stop loss kontrolü
                                    if float(df["low"].iloc[i]) <= giris_fiyati * (1 - stop_percentage/100):
                                        kar_zarar = -stop_percentage  # Sabit stop loss değeri
                                        yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                                        
                                        if yeni_bakiye <= 0:  # Bakiye sıfırın altına inmesin
                                            yeni_bakiye = 0.01
                                            
                                        bakiye = yeni_bakiye
                                        basarisiz += 1
                                        trades.append(kar_zarar * leverage)
                                        toplam_kar_zarar += kar_zarar * leverage
                                        pozisyon_acik = False
                                        son_islem_indeksi = i  # Son işlem indeksini güncelle
                                    
                                    # Satış sinyali kontrolü
                                    elif son_kapanis < son_supertrend and onceki_kapanis > onceki_supertrend:
                                        cikis_fiyati = float(df["open"].iloc[i])
                                        kar_zarar = ((cikis_fiyati - giris_fiyati) / giris_fiyati) * 100  # Yüzde olarak kar/zarar
                                        yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                                        
                                        if yeni_bakiye <= 0:  # Bakiye sıfırın altına inmesin
                                            yeni_bakiye = 0.01
                                            
                                        bakiye = yeni_bakiye
                                        
                                        if kar_zarar > 0:
                                            basarili += 1
                                        else:
                                            basarisiz += 1
                                            
                                        trades.append(kar_zarar * leverage)
                                        toplam_kar_zarar += kar_zarar * leverage
                                        pozisyon_acik = False
                                        son_islem_indeksi = i  # Son işlem indeksini güncelle
                                
                                # SHORT pozisyon için çıkış kontrolü
                                elif pozisyon_tipi == "short":
                                    # Stop loss kontrolü
                                    if float(df["high"].iloc[i]) >= giris_fiyati * (1 + stop_percentage/100):
                                        kar_zarar = -stop_percentage  # Sabit stop loss değeri
                                        yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                                        
                                        if yeni_bakiye <= 0:  # Bakiye sıfırın altına inmesin
                                            yeni_bakiye = 0.01
                                            
                                        bakiye = yeni_bakiye
                                        basarisiz += 1
                                        trades.append(kar_zarar * leverage)
                                        toplam_kar_zarar += kar_zarar * leverage
                                        pozisyon_acik = False
                                        son_islem_indeksi = i  # Son işlem indeksini güncelle
                                    
                                    # Alış sinyali kontrolü
                                    elif son_kapanis > son_supertrend and onceki_kapanis < onceki_supertrend:
                                        cikis_fiyati = float(df["open"].iloc[i])
                                        kar_zarar = ((giris_fiyati - cikis_fiyati) / giris_fiyati) * 100  # Yüzde olarak kar/zarar
                                        yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                                        
                                        if yeni_bakiye <= 0:  # Bakiye sıfırın altına inmesin
                                            yeni_bakiye = 0.01
                                            
                                        bakiye = yeni_bakiye
                                        
                                        if kar_zarar > 0:
                                            basarili += 1
                                        else:
                                            basarisiz += 1
                                            
                                        trades.append(kar_zarar * leverage)
                                        toplam_kar_zarar += kar_zarar * leverage
                                        pozisyon_acik = False
                                        son_islem_indeksi = i  # Son işlem indeksini güncelle
                                
                                # Eğer pozisyon çok uzun süredir açıksa zorunlu kapatma (zaman diliminin 100 katı)
                                if i - pozisyon_acilis_indeksi > min(100, len(df) // 10):
                                    cikis_fiyati = float(df["open"].iloc[i])
                                    
                                    if pozisyon_tipi == "long":
                                        kar_zarar = ((cikis_fiyati - giris_fiyati) / giris_fiyati) * 100
                                    else:  # short
                                        kar_zarar = ((giris_fiyati - cikis_fiyati) / giris_fiyati) * 100
                                    
                                    yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                                    
                                    if yeni_bakiye <= 0:
                                        yeni_bakiye = 0.01
                                        
                                    bakiye = yeni_bakiye
                                    
                                    if kar_zarar > 0:
                                        basarili += 1
                                    else:
                                        basarisiz += 1
                                        
                                    trades.append(kar_zarar * leverage)
                                    toplam_kar_zarar += kar_zarar * leverage
                                    pozisyon_acik = False
                                    son_islem_indeksi = i  # Son işlem indeksini güncelle

                        except Exception as e:
                            print(f"Error in trading simulation: {e}")
                            continue

                    # Son açık pozisyonu kapat
                    if pozisyon_acik:
                        cikis_fiyati = float(df["close"].iloc[-1])
                        
                        if pozisyon_tipi == "long":
                            kar_zarar = ((cikis_fiyati - giris_fiyati) / giris_fiyati) * 100
                        else:  # short
                            kar_zarar = ((giris_fiyati - cikis_fiyati) / giris_fiyati) * 100
                        
                        yeni_bakiye = bakiye * (1 + (kar_zarar/100) * leverage)
                        
                        if yeni_bakiye <= 0:
                            yeni_bakiye = 0.01
                            
                        bakiye = yeni_bakiye
                        
                        if kar_zarar > 0:
                            basarili += 1
                        else:
                            basarisiz += 1
                            
                        trades.append(kar_zarar * leverage)
                        toplam_kar_zarar += kar_zarar * leverage
                        pozisyon_acik = False

                    # Sonuçları değerlendir
                    total_trades = basarili + basarisiz
                    if total_trades > 0:
                        success_rate = (basarili / total_trades) * 100
                        profit_rate = ((bakiye / 100.0) - 1) * 100  # Doğru kar yüzdesi hesaplama

                        # En iyi sonucu güncelle - sadece yeterli sayıda işlem yapıldıysa
                        if profit_rate > best_result['profit_rate'] and total_trades >= 5:
                            best_result.update({
                                'leverage': leverage,
                                'stop_percentage': stop_percentage,
                                'atr_period': atr_period,
                                'atr_multiplier': atr_multiplier,
                                'success_rate': success_rate,
                                'profit_rate': profit_rate,
                                'successful_trades': basarili,
                                'unsuccessful_trades': basarisiz,
                                'final_balance': bakiye,
                                'trades': trades
                            })
                            
                            # Debug bilgisi
                            print(f"Yeni en iyi sonuç: {timeframe}, Kaldıraç: {leverage}, Stop %: {stop_percentage}, "
                                 f"ATR Periyot: {atr_period}, ATR Çarpan: {atr_multiplier}, "
                                 f"Başarı Oranı: {success_rate:.2f}%, Kar: {profit_rate:.2f}%, "
                                 f"İşlem Sayısı: {total_trades}, Bakiye: {bakiye:.2f}")

                    stop_percentage += 0.5
                leverage += 1

    # Performans metriklerini hesapla
    metrics = calculate_performance_metrics(best_result['trades'])
    best_result.update(metrics)
    
    return best_result

def calculate_performance_metrics(trades):
    """İşlem performans metriklerini hesaplar."""
    if not trades:
        return {
            'total_trades': 0,
            'win_rate': 0,
            'average_win': 0,
            'average_loss': 0,
            'max_drawdown': 0,
            'risk_reward_ratio': 0,
            'sharpe_ratio': 0
        }

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t < 0]
    
    total_trades = len(trades)
    win_rate = len(wins) / total_trades if trades else 0
    average_win = np.mean(wins) if wins else 0
    average_loss = abs(np.mean(losses)) if losses else 0
    
    # Maximum Drawdown hesaplama
    cumulative = np.cumsum(trades)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = running_max - cumulative
    max_drawdown = np.max(drawdowns)
    
    # Risk/Reward Ratio
    risk_reward_ratio = average_win / average_loss if average_loss != 0 else 0
    
    # Sharpe Ratio (basitleştirilmiş)
    returns = np.array(trades)
    sharpe_ratio = np.mean(returns) / np.std(returns) if len(returns) > 1 else 0
    
    return {
        'total_trades': total_trades,
        'win_rate': win_rate * 100,
        'average_win': average_win,
        'average_loss': average_loss,
        'max_drawdown': max_drawdown,
        'risk_reward_ratio': risk_reward_ratio,
        'sharpe_ratio': sharpe_ratio
    }


# Function to fetch the most recent data for prediction
def fetch_recent_data(timeframe, limit=1000):
    print(f"Fetching recent data for {timeframe} timeframe...")
    
    # OHLCV servisini başlat
    ohlcv_service = OHLCVService(exchange)
    
    # Limit'e göre başlangıç tarihini hesapla
    minutes_map = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15, '30m': 30,
        '1h': 60, '2h': 120, '4h': 240, '1d': 1440, '1w': 10080
    }
    
    minutes = minutes_map.get(timeframe, 1) * limit
    start_date = datetime.utcnow() - timedelta(minutes=minutes)
    end_date = datetime.utcnow()
    
    try:
        df = ohlcv_service.get_data_as_dataframe(symbol, timeframe, start_date, end_date)
        df['datetime'] = df['timestamp']  # datetime sütununu ekle
        return df
    except Exception as e:
        print(f"Error fetching recent data: {e}")
        return pd.DataFrame()


# Function to predict future prices based on Supertrend signals
def predict_prices(df, leverage, stop_percent, timeframe, atr_period, atr_multiplier):
    print(f"Predicting future prices for {timeframe} timeframe...")
    
    # Calculate Supertrend
    close_array = np.asarray(df["close"]).astype(float)
    high_array = np.asarray(df["high"]).astype(float)
    low_array = np.asarray(df["low"]).astype(float)

    supertrend = generateSupertrend(close_array, high_array, low_array, 
                                  atr_period=atr_period, 
                                  atr_multiplier=atr_multiplier)

    # Create signals DataFrame
    signals = pd.DataFrame(index=df.index)
    signals['price'] = df['close']
    signals['supertrend'] = supertrend
    signals['datetime'] = df['datetime']

    # Generate trading signals
    signals['signal'] = 0
    for i in range(3, len(signals)):
        curr_close = close_array[i - 2]
        prev_close = close_array[i - 3]
        curr_supertrend = supertrend[i - 2]
        prev_supertrend = supertrend[i - 3]

        # Long signal
        if curr_close > curr_supertrend and prev_close < prev_supertrend:
            signals.loc[i, 'signal'] = 1
        # Short signal
        elif curr_close < curr_supertrend and prev_close > prev_supertrend:
            signals.loc[i, 'signal'] = -1

    # Calculate prediction for 1 month ahead
    last_price = df['close'].iloc[-1]
    last_date = df['datetime'].iloc[-1]

    # Find the timeframe duration in minutes
    if timeframe.endswith('m'):
        minutes = int(timeframe[:-1])
    elif timeframe.endswith('h'):
        minutes = int(timeframe[:-1]) * 60
    elif timeframe.endswith('d'):
        minutes = int(timeframe[:-1]) * 60 * 24
    elif timeframe.endswith('w'):
        minutes = int(timeframe[:-1]) * 60 * 24 * 7
    else:
        minutes = 1  # Default

    # Calculate number of periods in 1 month
    periods_in_month = (30 * 24 * 60) // minutes

    # Create future dates
    future_dates = [last_date + timedelta(minutes=minutes * i) for i in range(1, periods_in_month + 1)]

    # Get the last signal
    last_signals = signals['signal'].iloc[-10:]
    last_signal = 0
    for sig in reversed(last_signals):
        if sig != 0:
            last_signal = sig
            break

    # Simple future prediction based on last signal and stop_percent
    future_prices = []
    future_price = last_price

    if last_signal == 1:  # Long position
        trend_direction = 1
        max_move = stop_percent / 100  # Maximum price move based on stop percentage
    elif last_signal == -1:  # Short position
        trend_direction = -1
        max_move = -stop_percent / 100
    else:
        trend_direction = 0
        max_move = 0

    # Generate future prices with some random noise
    for _ in range(len(future_dates)):
        random_factor = np.random.normal(0, 0.01)
        if trend_direction != 0:
            move_pct = max_move * (0.1 + 0.9 * np.random.random())
            future_price = future_price * (1 + trend_direction * move_pct * random_factor)
        else:
            future_price = future_price * (1 + random_factor)
        future_prices.append(future_price)

    # Create prediction DataFrame
    prediction_df = pd.DataFrame({
        'datetime': future_dates,
        'predicted_price': future_prices
    })

    return signals, prediction_df


# Function to visualize historical data and predictions
def visualize_data(historical_df, signals_df, prediction_df, timeframe, leverage, stop_percent, atr_period, atr_multiplier):
    print(f"Visualizing data for {timeframe} timeframe...")
    plt.figure(figsize=(12, 6))

    # Plot historical prices
    plt.plot(historical_df['datetime'], historical_df['close'], label='Historical Price', color='blue')

    # Plot supertrend line
    plt.plot(signals_df['datetime'], signals_df['supertrend'], label='Supertrend', color='purple', alpha=0.5)

    # Plot buy signals
    buy_signals = signals_df[signals_df['signal'] == 1]
    plt.scatter(buy_signals['datetime'], buy_signals['price'], color='green', label='Buy Signal', marker='^', s=100)

    # Plot sell signals
    sell_signals = signals_df[signals_df['signal'] == -1]
    plt.scatter(sell_signals['datetime'], sell_signals['price'], color='red', label='Sell Signal', marker='v', s=100)

    # Plot predicted prices
    plt.plot(prediction_df['datetime'], prediction_df['predicted_price'], label='Predicted Price', color='orange',
             linestyle='--')

    # Formatting
    plt.title(
        f'BTC/USDT {timeframe} - Supertrend Strategy with Predictions\n'
        f'Leverage: {leverage}, Stop %: {stop_percent}, ATR Period: {atr_period}, ATR Multiplier: {atr_multiplier}'
    )
    plt.xlabel('Date')
    plt.ylabel('Price (USDT)')
    plt.legend()
    plt.grid(True, alpha=0.3)

    # Format x-axis date
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gca().xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.gcf().autofmt_xdate()

    # Save figure
    output_dir = 'predictions'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    plt.savefig(f'{output_dir}/{symbolName}_{timeframe}_prediction.png', dpi=300, bbox_inches='tight')

    plt.close()


def analyze_symbol(symbol, timeframe, exchange):
    """Tek bir sembol ve zaman dilimi için analiz yapar"""
    try:
        ohlcv_service = OHLCVService(exchange)
        start_date = datetime.utcnow() - timedelta(days=730)  # 2 yıllık veri
        end_date = datetime.utcnow()
        
        df = ohlcv_service.get_data_as_dataframe(symbol, timeframe, start_date, end_date)

        print(f"DEBUG: DataFrame created for {symbol} {timeframe}. Info:")  # ADD THIS
        print(df.info())  # ADD THIS
        print(df.head())  # ADD THIS
        if df.empty:
            print(f"DEBUG: DataFrame is empty for {symbol} {timeframe}.")  # ADD THIS

            return None
            
        result = backtest_strategy(timeframe, df)
        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'result': result
        }
    except Exception as e:
        print(f"Error analyzing {symbol} {timeframe}: {str(e)}")
        return None


# Main function
def main():
    """
    Main function to run cryptocurrency analysis sequentially for multiple symbols and timeframes.
    """
    from app.services.backtest_service import BacktestService
    
    print("Starting cryptocurrency analysis and prediction (Sequential Execution)...")

    symbols = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "XRP/USDT", "ADA/USDT"]
    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]

    results = {} # Dictionary to store results for each symbol/timeframe

    # --- Sequential Execution Loop ---
    for sym in symbols:
        print(f"\n--- Processing Symbol: {sym} ---")
        for tf in timeframes:
            # Önce veritabanında kayıtlı sonuçları kontrol et
            symbol_short = sym.split('/')[0]
            existing_result = BacktestService.get_result(symbol_short, tf)
            
            if existing_result:
                print(f"Using cached results for {sym} - {tf}.")
                results[f"{sym}_{tf}"] = existing_result
                continue
            
            print(f"Analyzing {sym} - {tf}...")
            try:
                # Call analyze_symbol directly
                analysis_result = analyze_symbol(sym, tf, exchange)

                # Store the result if analysis was successful
                if analysis_result:
                    # Create a unique key for the dictionary
                    symbol_key = f"{analysis_result['symbol']}_{analysis_result['timeframe']}"
                    results[symbol_key] = analysis_result['result']
                    
                    # Sonucu veritabanına kaydet
                    symbol_short = analysis_result['symbol'].split('/')[0]
                    BacktestService.save_result(
                        symbol_short, 
                        analysis_result['timeframe'], 
                        analysis_result['result']
                    )
                    
                    print(f"Analysis complete for {sym} - {tf}.")
                else:
                    print(f"Analysis skipped or failed for {sym} - {tf}.")

            except Exception as e:
                # Catch potential errors during the analysis of a single symbol/timeframe
                print(f"!!! Critical Error analyzing {sym} - {tf}: {e}")
                # Optionally add more detailed error logging here
                continue # Continue to the next timeframe/symbol

    # --- Save Results ---
    print("\n--- Saving Results ---")
    output_dir = 'results' # Define an output directory for results
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created results directory: {output_dir}")

    for sym in symbols:
        symbol_name = sym.split('/')[0]
        file_path = os.path.join(output_dir, f"{symbol_name}_results.txt")
        print(f"Saving results for {symbol_name} to {file_path}...")
        try:
            with open(file_path, "w", encoding='utf-8') as f: # Specify encoding
                f.write(f"Analysis Results for {sym}\n")
                f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("="*30 + "\n\n")

                has_results = False
                for tf in timeframes:
                    symbol_key = f"{sym}_{tf}"
                    if symbol_key in results:
                        has_results = True
                        params = results[symbol_key]
                        f.write(
                            f"Timeframe: {tf}\n"
                            f"  Best Parameters Found:\n"
                            f"    Leverage: {params.get('leverage', 'N/A')}\n"
                            f"    Stop Percentage: {params.get('stop_percentage', 'N/A')}%\n"
                            f"    ATR Period: {params.get('atr_period', 'N/A')}\n"
                            f"    ATR Multiplier: {params.get('atr_multiplier', 'N/A')}\n"
                            f"  Performance Metrics:\n"
                            f"    Success Rate: {params.get('success_rate', 0):.2f}%\n"
                            f"    Profit Rate (Final Balance vs Initial): {params.get('profit_rate', 0):.2f}%\n"
                            f"    Successful Trades: {params.get('successful_trades', 'N/A')}\n"
                            f"    Unsuccessful Trades: {params.get('unsuccessful_trades', 'N/A')}\n"
                            f"    Total Trades: {params.get('total_trades', 'N/A')}\n"
                            f"    Win Rate: {params.get('win_rate', 0):.2f}%\n"
                            f"    Average Win: {params.get('average_win', 0):.2f}\n"
                            f"    Average Loss: {params.get('average_loss', 0):.2f}\n"
                            f"    Max Drawdown: {params.get('max_drawdown', 0):.2f}%\n"
                            f"    Risk/Reward Ratio: {params.get('risk_reward_ratio', 0):.2f}\n"
                            f"    Sharpe Ratio: {params.get('sharpe_ratio', 0):.2f}\n"
                            f"    Final Balance: {params.get('final_balance', 0):.2f} USDT\n"
                            f"  -----------------------------\n\n"
                        )
                if not has_results:
                     f.write("No successful analysis results found for this symbol.\n")

        except IOError as e:
            print(f"!!! Error writing results file {file_path}: {e}")
        except Exception as e:
            print(f"!!! Unexpected error saving results for {symbol_name}: {e}")


    print("Analysis and prediction completed. Results have been saved.")


if __name__ == "__main__":
    main()