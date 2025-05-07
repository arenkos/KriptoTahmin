import sqlite3
import pandas as pd

# Veritabanına bağlan
conn = sqlite3.connect('crypto_data.db')

# SQL sorgusu: her 'timestamp'te kaç farklı timeframe olduğunu ve hangi symbol'e ait olduğunu gösterir
query = """
SELECT *, COUNT(*) as tekrar_sayisi
FROM ohlcv_data
GROUP BY symbol, timestamp, open, high, low, close, volume
HAVING COUNT(*) > 1"""

# Sorguyu çalıştır ve DataFrame'e yükle
df = pd.read_sql_query(query, conn)

# İlk birkaç satırı yazdır
print(df.head())

# Bağlantıyı kapat
conn.close()