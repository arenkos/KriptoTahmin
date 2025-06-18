import mysql.connector
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from config import Config

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

class OHLCVService:
    def __init__(self, db_name='crypto_data.db'):
        self.db_name = db_name
    
    def get_connection(self):
        """Veritabanı bağlantısı oluştur"""
        return get_mysql_connection()
    
    def get_ohlcv_data(self, symbol, timeframe, limit=1000):
        """Belirli bir sembol ve timeframe için OHLCV verilerini getirir"""
        conn = self.get_connection()
        if not conn:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        cursor = conn.cursor()
        
        query = '''
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = %s AND timeframe = %s
        ORDER BY timestamp DESC
        LIMIT %s
        '''
        
        cursor.execute(query, (symbol, timeframe, limit))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Veriyi DataFrame'e dönüştür
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Zaman damgası dönüşümleri yap
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Verileri tarihe göre sırala (en yeni en üstte)
        df = df.sort_values('timestamp', ascending=False).reset_index(drop=True)
        
        return df
    
    def get_latest_candle(self, symbol, timeframe):
        """En son mum verisini getir"""
        conn = self.get_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        
        query = '''
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = %s AND timeframe = %s
        ORDER BY timestamp DESC
        LIMIT 1
        '''
        
        cursor.execute(query, (symbol, timeframe))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        candle = {
            'timestamp': row[0],
            'open': row[1],
            'high': row[2],
            'low': row[3],
            'close': row[4],
            'volume': row[5],
            'date': datetime.fromtimestamp(row[0] / 1000)
        }
        
        return candle
    
    def get_historical_data(self, symbol, timeframe, days=30):
        """Geçmiş verileri al"""
        conn = self.get_connection()
        if not conn:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        cursor = conn.cursor()
        
        # Belirli gün sayısı öncesinden şimdiye kadar olan verileri getir
        current_time = datetime.now().timestamp() * 1000
        past_time = (datetime.now() - timedelta(days=days)).timestamp() * 1000
        
        query = '''
        SELECT timestamp, open, high, low, close, volume
        FROM ohlcv_data
        WHERE symbol = %s AND timeframe = %s AND timestamp >= %s AND timestamp <= %s
        ORDER BY timestamp ASC
        '''
        
        cursor.execute(query, (symbol, timeframe, past_time, current_time))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Veriyi DataFrame'e dönüştür
        df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Zaman damgası dönüşümleri yap
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Verileri tarihe göre sırala (eski -> yeni)
        df = df.sort_values('timestamp', ascending=True).reset_index(drop=True)
        
        return df 