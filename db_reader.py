import sqlite3
import pandas as pd

def get_db_connection():
    conn = sqlite3.connect('crypto_data.db')
    return conn

def get_db_connection2():
    conn = sqlite3.connect('app.db')
    return conn

def read_analiz():
    conn = get_db_connection()

    query = """
    SELECT DISTINCT *
    FROM analysis_results WHERE final_balance>=100;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(df)

def read_islemler():
    conn = get_db_connection()

    query = """
    SELECT COUNT(*)
    FROM backtest_transactions ;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(df)

def read_veriler():
    conn = get_db_connection()

    query = """
    SELECT *, datetime(timestamp / 1000, 'unixepoch') AS human_readable_time
    FROM ohlcv_data
    WHERE symbol LIKE '%BTC%' AND timeframe = '1m' ORDER BY timestamp DESC LIMIT 1;
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    print(df)

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        UPDATE ohlcv_data
        SET symbol = symbol || '/USDT'
        WHERE symbol NOT LIKE '%/USDT%';
    """

    cursor.execute(query)
    conn.commit()  # Değişiklikleri kaydet
    conn.close()

    print("Güncelleme tamamlandı.")

def read_islem_gercek():
    conn = get_db_connection2()
    cursor = conn.cursor()
    query = """
            SELECT *,datetime(entry_time / 1000, 'unixepoch') AS enter_time FROM realtime_transactions;
        """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(df)
def delete_veriler_gercek():
    conn = get_db_connection2()
    cursor = conn.cursor()
    query = """
        DELETE FROM realtime_transactions;
    """

    cursor.execute(query)  # Sorguyu çalıştır
    conn.commit()  # Silinen kayıtları kalıcı olarak uygula
    conn.close()  # Bağlantıyı kapat

def tablo_liste():
    # Veritabanına bağlan
    conn = sqlite3.connect('instance/app.db')
    cursor = conn.cursor()

    # Tabloları sorgula
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    # Tabloları yazdır
    print("Veritabanındaki tablolar:")
    for table in tables:
        print(table[0])

    # Bağlantıyı kapat
    conn.close()

def delete_analiz():
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    DELETE FROM analysis_results;
    """

    cursor.execute(query)
    conn.commit()
    conn.close()

def delete_islemler():
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    DELETE FROM backtest_transactions;
    """

    cursor.execute(query)
    conn.commit()
    conn.close()

    print("Tüm veriler silindi.")
def find_duplicates():
    conn = get_db_connection()

    # Tekrarlanan kayıtları bul
    query = """
        SELECT symbol, timeframe, timestamp, COUNT(*) as tekrar_sayisi
        FROM ohlcv_data
        GROUP BY symbol, timeframe, timestamp
        HAVING COUNT(*) > 1
        ORDER BY tekrar_sayisi DESC
        """
    
    duplicates = pd.read_sql_query(query, conn)
    
    if len(duplicates) > 0:
        print("\nTekrarlanan kayıtlar:")
        print(duplicates)
        
        # Her tekrarlanan kayıt için detaylı bilgi
        for _, row in duplicates.iterrows():
            detail_query = """
            SELECT *
FROM ohlcv_data
            WHERE symbol = ? AND timeframe = ? AND timestamp = ?
            ORDER BY id
            """
            details = pd.read_sql_query(detail_query, conn, params=(row['symbol'], row['timeframe'], row['timestamp']))
            print(f"\n{row['symbol']} - {row['timeframe']} - {row['timestamp']} için detaylar:")
            print(details)
    else:
        print("\nTekrarlanan kayıt bulunamadı.")
    
    conn.close()

def clean_duplicates():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tekrarlanan kayıtları temizle
    query = """
    DELETE FROM ohlcv_data
    WHERE id NOT IN (
        SELECT MIN(id)
        FROM ohlcv_data
        GROUP BY symbol, timeframe, timestamp
    )
    """
    
    cursor.execute(query)
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"\n{deleted_count} adet tekrarlanan kayıt temizlendi.")

if __name__ == "__main__":
    print("Veritabanındaki tekrarlanan kayıtları kontrol ediyorum...")
    #find_duplicates()
    #tablo_liste()
    response = input("\nAnaliz tablosu mu İşlemler tablosu mu (a/i): ")
    if response.lower() == 'a':
        read_analiz()
    elif response.lower() == 'i':
        read_islemler()
    elif response.lower() == 'v':
        read_veriler()
    elif response.lower() == 'r':
        read_islem_gercek()
    #delete()
    response = input("\nAnaliz tablosunu temizlemek istiyor musunuz? (e/h): ")
    if response.lower() == 'ea':
        delete_analiz()
    elif response.lower() == 'ei':
        delete_islemler()
    elif response.lower() == 'er':
        delete_veriler_gercek()
    #response = input("\nTekrarlanan kayıtları temizlemek istiyor musunuz? (e/h): ")
    response = "."
    if response.lower() == 'e':
        clean_duplicates()
        print("\nTemizlik sonrası kontrol:")
        find_duplicates()