import mysql.connector
import pandas as pd
from app.services.backtest_service import BacktestService
from app.services.ohlcv_service import OHLCVService

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

class AnalysisService:
    @staticmethod
    def get_results_by_timeframe(timeframe):
        """Belirli bir zaman dilimi için tüm kripto para birimlerinin analiz sonuçlarını getirir"""
        conn = get_mysql_connection()
        if not conn:
            return []
        cursor = conn.cursor()
        
        query = '''
        SELECT symbol, leverage, stop_percentage, kar_al_percentage, successful_trades, unsuccessful_trades, final_balance
        FROM analysis_results
        WHERE timeframe = %s
        ORDER BY final_balance DESC
        '''
        
        cursor.execute(query, (timeframe,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        results = []
        for row in rows:
            result = {
                'symbol': row[0],
                'leverage': row[1],
                'stop_percentage': row[2],
                'kar_al_percentage': row[3],
                'successful_trades': row[4],
                'unsuccessful_trades': row[5],
                'final_balance': row[6],
                'success_rate': row[4] / (row[4] + row[5]) * 100 if (row[4] + row[5]) > 0 else 0,
                'profit_rate': (row[6] - 100) / 100 * 100 if row[6] > 0 else -100
            }
            results.append(result)
        
        return results
    
    @staticmethod
    def get_best_results():
        """Tüm zaman dilimleri için en iyi sonuçları getirir"""
        conn = get_mysql_connection()
        if not conn:
            return []
        cursor = conn.cursor()
        
        query = '''
        SELECT symbol, timeframe, leverage, stop_percentage, kar_al_percentage, successful_trades, unsuccessful_trades, final_balance
        FROM analysis_results
        ORDER BY final_balance DESC
        LIMIT 10
        '''
        
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return []
        
        results = []
        for row in rows:
            result = {
                'symbol': row[0],
                'timeframe': row[1],
                'leverage': row[2],
                'stop_percentage': row[3],
                'kar_al_percentage': row[4],
                'successful_trades': row[5],
                'unsuccessful_trades': row[6],
                'final_balance': row[7],
                'success_rate': row[5] / (row[5] + row[6]) * 100 if (row[5] + row[6]) > 0 else 0,
                'profit_rate': (row[7] - 100) / 100 * 100 if row[7] > 0 else -100
            }
            results.append(result)
        
        return results
    
    @staticmethod
    def analyze_symbol(symbol, timeframe, leverage=1, stop_percentage=2, days=30):
        """Belirli bir sembol ve zaman dilimi için analiz yapar"""
        backtest_service = BacktestService()
        result = backtest_service.backtest_strategy(symbol, timeframe, leverage, stop_percentage, days)
        
        return result
    
    @staticmethod
    def get_symbol_data(symbol, timeframe, days=30):
        """Belirli bir sembol ve zaman dilimi için OHLCV verilerini getirir"""
        ohlcv_service = OHLCVService()
        df = ohlcv_service.get_historical_data(symbol, timeframe, days)
        
        if df.empty:
            return None
        
        # Veriyi JSON formatına dönüştür
        data = {
            'timestamps': df['timestamp'].tolist(),
            'dates': df['date'].astype(str).tolist(),
            'open': df['open'].tolist(),
            'high': df['high'].tolist(),
            'low': df['low'].tolist(),
            'close': df['close'].tolist(),
            'volume': df['volume'].tolist()
        }
        
        return data 