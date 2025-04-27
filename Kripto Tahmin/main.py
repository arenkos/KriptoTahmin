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
        lim = 365 * (float(mum) * 60 * 24)
        bekleme = int(a[0]) * 60
        periyot = "%M"
    elif lst[len(lst) - 1] == 'h':
        list = convert(lst)
        a = list.split("h")
        mum = a[0]
        lim = 365 * (float(mum) * 24)
        bekleme = int(a[0]) * 60 * 60
        periyot = "%H"
    elif lst[len(lst) - 1] == 'd':
        list = convert(lst)
        a = list.split("d")
        mum = a[0]
        lim = 365 * float(mum)
        bekleme = int(a[0]) * 60 * 60 * 24
        periyot = "%d"
    elif lst[len(lst) - 1] == 'w':
        list = convert(lst)
        a = list.split("w")
        mum = a[0]
        lim = 143 * float(mum)
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

    for tf in timeframes:
        lim, _, _, _ = lim_olustur(tf)
        if tf == "1w":
            # For weekly data, we can just get it directly
            bars = exchange.fetch_ohlcv(symbol, timeframe=tf, since=None, limit=int(lim_olustur(tf)[0]))
            dataframes[tf] = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        else:
            # For other timeframes, we need to fetch in chunks due to exchange limits
            df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

            # Start date approximately 1 year ago
            start_date = int(datetime(2022, 7, 15, 3, 0, 0).timestamp() * 1000)

            # Define chunk sizes based on timeframe to avoid rate limits
            if tf == "1m":
                chunk_size = 1440
            elif tf == "3m":
                chunk_size = 480
            elif tf == "5m":
                chunk_size = 288
            elif tf == "15m":
                chunk_size = 96
            elif tf == "30m":
                chunk_size = 48
            elif tf == "1h":
                chunk_size = 24
            elif tf == "2h":
                chunk_size = 12
            elif tf == "4h":
                chunk_size = 6
            elif tf == "1d":
                chunk_size = 1

            # Fetch data for 365 days
            for a in range(365):
                bars = exchange.fetch_ohlcv(symbol, timeframe=tf, since=start_date, limit=chunk_size)
                chunk_df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df = pd.concat([df, chunk_df], ignore_index=True)
                start_date = start_date + 86400000  # Add one day in milliseconds
                print(f"Fetched day {a + 1}/365 for {tf} timeframe")

            dataframes[tf] = df

    return dataframes


# Function to backtest the strategy
def backtest_strategy(timeframe, df):
    print(f"Backtesting {timeframe} timeframe...")
    alinacak_miktar = 0
    bekleme = 0
    bakiye = 100.0
    leverage_ust = 50
    lev_ust = 50
    yuzde_ust = 50
    yuz_ust = 50
    islemsonu = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    son = 0
    islem = 0
    basarili = 0
    basarili_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    basarisiz = 0
    basarisiz_islem = [[0 for x in range(yuz_ust * 2 + 1)] for y in range(lev_ust + 1)]
    yuzde = 0.5
    sonuclar = []
    tahmin = []

    lim = int(len(df["open"]))

    kesisim = False
    longPozisyonda = False
    shortPozisyonda = False
    pozisyondami = False
    likit = 0
    yuzde = 0.5
    a = 0

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
    supertrend = generateSupertrend(close_array, high_array, low_array, atr_period=10, atr_multiplier=3)

    # Yüzde döngüsü
    while yuzde <= yuzde_ust:
        stop = 0
        likit = 0
        leverage = 1

        # Kaldıraç döngüsü
        while leverage <= leverage_ust:
            bakiye = 100.0
            x = 3
            stop = 0
            likit = 0
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
                    giris = float(df["open"][x])
                    y = 0
                    while True:
                        if x + y >= lim:
                            break

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

                        # Stop olma durumu
                        if ((float(df["high"][x + y]) - giris) / giris * 100 >= yuzde):
                            basarili = basarili + 1
                            bakiye = bakiye + bakiye * yuzde / 100 * leverage
                            stop = 1
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
                    giris = float(df["open"][x])
                    y = 0
                    while True:
                        if x + y >= lim:
                            break

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

                        # Stop olma durumu
                        if ((float(df["low"][x + y]) - giris) / giris * 100 <= yuzde * (-1)):
                            basarili = basarili + 1
                            bakiye = bakiye + bakiye * yuzde / 100 * leverage
                            stop = 1
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

    leverage = 0
    while leverage < lev_ust:
        tahmin.append(max(islemsonu[leverage]))
        leverage = leverage + 1
    leverage = 0
    while leverage < lev_ust:
        k = 1
        while k <= len(islemsonu[leverage]):
            if islemsonu[int(leverage)][int(k - 1)] == max(tahmin):
                return str(leverage + 1), str(k / 2), basarili_islem[leverage][k - 1], basarisiz_islem[leverage][
                    k - 1], str(islemsonu[int(leverage)][int(k - 1)])
            k = k + 1
        leverage = leverage + 1

    # If no result found, return defaults
    return "1", "0.5", 0, 0, "0"


# Function to fetch the most recent data for prediction
def fetch_recent_data(timeframe, limit=1000):
    print(f"Fetching recent data for {timeframe} timeframe...")
    bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=None, limit=limit)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


# Function to predict future prices based on Supertrend signals
def predict_prices(df, leverage, stop_percent, timeframe):
    print(f"Predicting future prices for {timeframe} timeframe...")
    # Convert parameters to numeric
    leverage = float(leverage)
    stop_percent = float(stop_percent)

    # Calculate Supertrend
    close_array = np.asarray(df["close"]).astype(float)
    high_array = np.asarray(df["high"]).astype(float)
    low_array = np.asarray(df["low"]).astype(float)

    supertrend = generateSupertrend(close_array, high_array, low_array, atr_period=10, atr_multiplier=3)

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
        # Add some randomness but overall follow the trend
        random_factor = np.random.normal(0, 0.01)  # Normal distribution with mean 0 and std 0.01

        # Price moves in trend direction with some noise, constrained by max_move
        if trend_direction != 0:
            # Calculate move percentage (with diminishing returns)
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
def visualize_data(historical_df, signals_df, prediction_df, timeframe, leverage, stop_percent):
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
        f'BTC/USDT {timeframe} - Supertrend Strategy with Predictions\nLeverage: {leverage}, Stop %: {stop_percent}')
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


# Main function
def main():
    print("Starting cryptocurrency analysis and prediction...")

    # First, let's run the backtest to find the best parameters
    timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d", "1w"]

    # Fetch historical data for backtesting
    historical_data = fetch_all_historical_data()

    # Store results
    best_params = {}

    # Run backtests
    for tf in timeframes:
        leverage, stop_percent, successful, unsuccessful, final_balance = backtest_strategy(tf, historical_data[tf])
        best_params[tf] = {
            'leverage': leverage,
            'stop_percent': stop_percent,
            'successful_trades': successful,
            'unsuccessful_trades': unsuccessful,
            'final_balance': final_balance
        }
        print(
            f"{tf} - Leverage: {leverage}, Stop %: {stop_percent}, Successful: {successful}, Unsuccessful: {unsuccessful}, Balance: {final_balance}")

    # Save results to file
    with open(f"{symbolName}_results.txt", "w") as f:
        for tf in timeframes:
            params = best_params[tf]
            f.write(f"{tf} Kaldıraç = {params['leverage']} Yüzde = {params['stop_percent']} " +
                    f"Başarılı İşlem = {params['successful_trades']} Başarısız İşlem = {params['unsuccessful_trades']} " +
                    f"İşlem Sonu Bakiye = {params['final_balance']}\n")

    # Now fetch recent data and create predictions for 1 month ahead
    for tf in timeframes:
        # Adjust limit based on timeframe to get enough data
        if tf == "1m":
            limit = 1440 * 2  # 2 days worth of 1-minute data
        elif tf == "3m":
            limit = 480 * 2  # 2 days worth of 3-minute data
        elif tf == "5m":
            limit = 288 * 2  # 2 days worth of 5-minute data
        elif tf == "15m":
            limit = 96 * 7  # 1 week worth of 15-minute data
        elif tf == "30m":
            limit = 48 * 14  # 2 weeks worth of 30-minute data
        elif tf == "1h":
            limit = 24 * 30  # 1 month worth of 1-hour data
        elif tf == "2h":
            limit = 12 * 30  # 1 month worth of 2-hour data
        elif tf == "4h":
            limit = 6 * 60  # 2 months worth of 4-hour data
        elif tf == "1d":
            limit = 365  # 1 year worth of daily data
        elif tf == "1w":
            limit = 52  # 1 year worth of weekly data

        recent_data = fetch_recent_data(tf, limit)

        # Get the best parameters for this timeframe
        leverage = best_params[tf]['leverage']
        stop_percent = best_params[tf]['stop_percent']

        # Generate signals and predictions
        signals, predictions = predict_prices(recent_data, leverage, stop_percent, tf)

        # Visualize the data and predictions
        visualize_data(recent_data, signals, predictions, tf, leverage, stop_percent)

    print("Analysis and prediction completed. Results and charts have been saved.")


if __name__ == "__main__":
    main()