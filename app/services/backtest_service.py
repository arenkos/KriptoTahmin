import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib as ta
import math
from app.services.ohlcv_service import OHLCVService

class BacktestService:
    def __init__(self):
        self.ohlcv_service = OHLCVService()

    def backtest_strategy(self, symbol, timeframe, leverage=1, stop_percentage=2, days=30):
        """Belirli bir sembol, zaman dilimi ve parametreler için stratejiyi test eder."""
        # Verileri al
        df = self.ohlcv_service.get_historical_data(symbol, timeframe, days)
        
        if df.empty:
            return {
                'symbol': symbol,
                'timeframe': timeframe,
                'leverage': leverage,
                'stop_percentage': stop_percentage,
                'successful_trades': 0,
                'unsuccessful_trades': 0,
                'final_balance': 100.0,  # Başlangıç bakiyesi
                'roi_percentage': 0,
                'trades': []
            }
        
        # Teknik göstergeleri hesapla
        df = self.calculate_indicators(df)
        
        # Alım-satım sinyallerini oluştur
        signals = self.generate_signals(df)
        
        # Backtest işlemini yap
        result = self.run_backtest(signals, leverage, stop_percentage)
        
        # Sonuçları dön
        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'leverage': leverage,
            'stop_percentage': stop_percentage,
            'successful_trades': result['successful_trades'],
            'unsuccessful_trades': result['unsuccessful_trades'],
            'final_balance': result['final_balance'],
            'roi_percentage': result['roi_percentage'],
            'trades': result['trades']
        }
    
    def calculate_indicators(self, df):
        """Teknik göstergeleri hesapla"""
        # Numpy dizileri oluştur (talib için)
        close_array = np.asarray(df['close']).astype(float)
        high_array = np.asarray(df['high']).astype(float)
        low_array = np.asarray(df['low']).astype(float)
        
        # Supertrend indikatörü
        df['supertrend'] = self.generate_supertrend(close_array, high_array, low_array, atr_period=10, atr_multiplier=3)
        
        # RSI
        df['rsi'] = ta.RSI(close_array, timeperiod=14)
        
        # MACD
        macd, macdsignal, macdhist = ta.MACD(close_array, fastperiod=12, slowperiod=26, signalperiod=9)
        df['macd'] = macd
        df['macdsignal'] = macdsignal
        df['macdhist'] = macdhist
        
        # Bollinger Bands
        upperband, middleband, lowerband = ta.BBANDS(close_array, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        df['bb_upper'] = upperband
        df['bb_middle'] = middleband
        df['bb_lower'] = lowerband
        
        return df
    
    def generate_supertrend(self, close_array, high_array, low_array, atr_period=10, atr_multiplier=3):
        """Supertrend indikatörünü hesaplar"""
        try:
            atr = ta.ATR(high_array, low_array, close_array, atr_period)
        except Exception as e:
            print(f"ATR hesaplanırken hata: {e}")
            return np.zeros(len(close_array))

        previous_final_upperband = 0
        previous_final_lowerband = 0
        final_upperband = 0
        final_lowerband = 0
        previous_close = 0
        previous_supertrend = 0
        supertrend = np.zeros(len(close_array))
        
        for i in range(0, len(close_array)):
            if np.isnan(close_array[i]):
                continue
                
            highc = high_array[i]
            lowc = low_array[i]
            closec = close_array[i]
            
            if i < atr_period:
                supertrend[i] = 0
                continue
                
            atrc = atr[i]
            
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
                supertrend[i] = final_upperband
            elif previous_supertrend == previous_final_upperband and closec >= final_upperband:
                supertrend[i] = final_lowerband
            elif previous_supertrend == previous_final_lowerband and closec >= final_lowerband:
                supertrend[i] = final_lowerband
            elif previous_supertrend == previous_final_lowerband and closec <= final_lowerband:
                supertrend[i] = final_upperband
            else:
                supertrend[i] = 0  # Başlangıç değeri
            
            previous_close = closec
            previous_final_upperband = final_upperband
            previous_final_lowerband = final_lowerband
            previous_supertrend = supertrend[i]
        
        return supertrend
    
    def generate_signals(self, df):
        """Alım-satım sinyallerini oluştur"""
        # Supertrend temelli sinyaller
        signals = pd.DataFrame(index=df.index)
        signals['timestamp'] = df['timestamp']
        signals['date'] = df['date']
        signals['close'] = df['close']
        signals['supertrend'] = df['supertrend']
        signals['signal'] = 0  # 0: no signal, 1: buy, -1: sell
        
        # Alım-satım sinyalleri
        for i in range(2, len(df)):
            if df['close'].iloc[i-1] > df['supertrend'].iloc[i-1] and df['close'].iloc[i-2] < df['supertrend'].iloc[i-2]:
                signals['signal'].iloc[i] = 1  # Alım sinyali
            elif df['close'].iloc[i-1] < df['supertrend'].iloc[i-1] and df['close'].iloc[i-2] > df['supertrend'].iloc[i-2]:
                signals['signal'].iloc[i] = -1  # Satım sinyali
        
        return signals
    
    def run_backtest(self, signals, leverage=1, stop_percentage=2):
        """Backtest işlemi yap"""
        initial_balance = 100.0
        balance = initial_balance
        position = 0  # 0: no position, 1: long, -1: short
        entry_price = 0
        trades = []
        successful_trades = 0
        unsuccessful_trades = 0
        
        for i in range(len(signals)):
            if position == 0:  # Pozisyon yok
                if signals['signal'].iloc[i] == 1:  # Alım sinyali
                    position = 1
                    entry_price = signals['close'].iloc[i]
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'buy',
                        'price': entry_price,
                        'balance': balance
                    }
                    trades.append(trade)
                elif signals['signal'].iloc[i] == -1:  # Satım sinyali
                    position = -1
                    entry_price = signals['close'].iloc[i]
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'sell',
                        'price': entry_price,
                        'balance': balance
                    }
                    trades.append(trade)
            
            elif position == 1:  # Long pozisyon
                # Stop loss kontrolü
                if signals['close'].iloc[i] <= entry_price * (1 - stop_percentage / 100):
                    position = 0
                    exit_price = signals['close'].iloc[i]
                    profit_percentage = (exit_price - entry_price) / entry_price * 100 * leverage
                    balance = balance * (1 + profit_percentage / 100)
                    
                    if profit_percentage > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'exit_long',
                        'price': exit_price,
                        'profit_percentage': profit_percentage,
                        'balance': balance,
                        'reason': 'stop_loss'
                    }
                    trades.append(trade)
                
                # Satım sinyali kontrolü
                elif signals['signal'].iloc[i] == -1:
                    position = 0
                    exit_price = signals['close'].iloc[i]
                    profit_percentage = (exit_price - entry_price) / entry_price * 100 * leverage
                    balance = balance * (1 + profit_percentage / 100)
                    
                    if profit_percentage > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'exit_long',
                        'price': exit_price,
                        'profit_percentage': profit_percentage,
                        'balance': balance,
                        'reason': 'signal'
                    }
                    trades.append(trade)
            
            elif position == -1:  # Short pozisyon
                # Stop loss kontrolü
                if signals['close'].iloc[i] >= entry_price * (1 + stop_percentage / 100):
                    position = 0
                    exit_price = signals['close'].iloc[i]
                    profit_percentage = (entry_price - exit_price) / entry_price * 100 * leverage
                    balance = balance * (1 + profit_percentage / 100)
                    
                    if profit_percentage > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'exit_short',
                        'price': exit_price,
                        'profit_percentage': profit_percentage,
                        'balance': balance,
                        'reason': 'stop_loss'
                    }
                    trades.append(trade)
                
                # Alım sinyali kontrolü
                elif signals['signal'].iloc[i] == 1:
                    position = 0
                    exit_price = signals['close'].iloc[i]
                    profit_percentage = (entry_price - exit_price) / entry_price * 100 * leverage
                    balance = balance * (1 + profit_percentage / 100)
                    
                    if profit_percentage > 0:
                        successful_trades += 1
                    else:
                        unsuccessful_trades += 1
                    
                    trade = {
                        'timestamp': signals['timestamp'].iloc[i],
                        'date': signals['date'].iloc[i],
                        'type': 'exit_short',
                        'price': exit_price,
                        'profit_percentage': profit_percentage,
                        'balance': balance,
                        'reason': 'signal'
                    }
                    trades.append(trade)
        
        # Son işlemden çık (açık pozisyon kaldıysa)
        if position != 0 and len(signals) > 0:
            exit_price = signals['close'].iloc[-1]
            
            if position == 1:  # Long pozisyon
                profit_percentage = (exit_price - entry_price) / entry_price * 100 * leverage
                balance = balance * (1 + profit_percentage / 100)
                
                if profit_percentage > 0:
                    successful_trades += 1
                else:
                    unsuccessful_trades += 1
                
                trade = {
                    'timestamp': signals['timestamp'].iloc[-1],
                    'date': signals['date'].iloc[-1],
                    'type': 'exit_long',
                    'price': exit_price,
                    'profit_percentage': profit_percentage,
                    'balance': balance,
                    'reason': 'final'
                }
                trades.append(trade)
            
            elif position == -1:  # Short pozisyon
                profit_percentage = (entry_price - exit_price) / entry_price * 100 * leverage
                balance = balance * (1 + profit_percentage / 100)
                
                if profit_percentage > 0:
                    successful_trades += 1
                else:
                    unsuccessful_trades += 1
                
                trade = {
                    'timestamp': signals['timestamp'].iloc[-1],
                    'date': signals['date'].iloc[-1],
                    'type': 'exit_short',
                    'price': exit_price,
                    'profit_percentage': profit_percentage,
                    'balance': balance,
                    'reason': 'final'
                }
                trades.append(trade)
        
        # ROI (Return on Investment) yüzdesi hesapla
        roi_percentage = (balance - initial_balance) / initial_balance * 100
        
        return {
            'successful_trades': successful_trades,
            'unsuccessful_trades': unsuccessful_trades,
            'final_balance': balance,
            'roi_percentage': roi_percentage,
            'trades': trades
        } 