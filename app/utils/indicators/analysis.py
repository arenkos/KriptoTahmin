import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import talib as ta
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import ccxt

class CryptoAnalyzer:
    def __init__(self, exchange, symbol, timeframe):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.model = None
        
    def fetch_historical_data(self, years=3):
        """Fetch historical data for the specified period"""
        end_time = datetime.now()
        start_time = end_time - timedelta(days=years*365)
        
        ohlcv = self.exchange.fetch_ohlcv(
            self.symbol,
            timeframe=self.timeframe,
            since=int(start_time.timestamp() * 1000),
            limit=1000
        )
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        # Supertrend
        df['supertrend'] = self._calculate_supertrend(df)
        
        # RSI
        df['rsi'] = ta.RSI(df['close'])
        
        # MACD
        macd, signal, hist = ta.MACD(df['close'])
        df['macd'] = macd
        df['macd_signal'] = signal
        df['macd_hist'] = hist
        
        # Bollinger Bands
        upper, middle, lower = ta.BBANDS(df['close'])
        df['bb_upper'] = upper
        df['bb_middle'] = middle
        df['bb_lower'] = lower
        
        # Volume indicators
        df['volume_sma'] = ta.SMA(df['volume'])
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        return df
    
    def _calculate_supertrend(self, df, period=10, multiplier=3):
        """Calculate Supertrend indicator"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        # Calculate ATR
        atr = ta.ATR(high, low, close, timeperiod=period)
        
        # Calculate basic upper and lower bands
        basic_upper = (high + low) / 2 + multiplier * atr
        basic_lower = (high + low) / 2 - multiplier * atr
        
        # Calculate final upper and lower bands
        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()
        
        for i in range(1, len(df)):
            if basic_upper[i] < final_upper[i-1] and close[i-1] <= final_upper[i-1]:
                final_upper[i] = final_upper[i-1]
            if basic_lower[i] > final_lower[i-1] and close[i-1] >= final_lower[i-1]:
                final_lower[i] = final_lower[i-1]
        
        # Calculate Supertrend
        supertrend = pd.Series(index=df.index, dtype=float)
        for i in range(1, len(df)):
            if close[i] <= final_upper[i]:
                supertrend[i] = final_upper[i]
            else:
                supertrend[i] = final_lower[i]
        
        return supertrend
    
    def prepare_features(self, df):
        """Prepare features for machine learning"""
        features = [
            'rsi', 'macd', 'macd_signal', 'macd_hist',
            'bb_upper', 'bb_middle', 'bb_lower',
            'volume_ratio'
        ]
        
        X = df[features].values
        y = np.where(df['close'].shift(-1) > df['close'], 1, 0)
        
        return X[:-1], y[:-1]  # Remove last row as we don't have future price
    
    def train_model(self, X, y):
        """Train machine learning model"""
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        
        self.model = model
        return accuracy
    
    def analyze(self):
        """Perform complete analysis"""
        # Fetch data
        df = self.fetch_historical_data()
        
        # Calculate indicators
        df = self.calculate_indicators(df)
        
        # Prepare features
        X, y = self.prepare_features(df)
        
        # Train model
        accuracy = self.train_model(X, y)
        
        # Calculate optimal parameters
        optimal_params = self._calculate_optimal_parameters(df)
        
        return {
            'accuracy': accuracy,
            'optimal_params': optimal_params,
            'last_analysis_date': datetime.now()
        }
    
    def _calculate_optimal_parameters(self, df):
        """Calculate optimal trading parameters"""
        # This is a simplified version - in reality, you'd want to do more sophisticated analysis
        volatility = df['close'].pct_change().std()
        
        # Calculate optimal leverage based on volatility
        optimal_leverage = min(20, int(1 / (volatility * 2)))
        
        # Calculate stop loss and take profit based on volatility
        stop_loss = volatility * 2 * 100  # 2x volatility
        take_profit = stop_loss * 2  # 2x stop loss
        
        return {
            'leverage': optimal_leverage,
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2)
        } 