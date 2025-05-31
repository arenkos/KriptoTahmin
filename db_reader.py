import sqlite3
import pandas as pd

def get_db_connection():
    conn = sqlite3.connect('crypto_data.db')
    return conn


def read():
    conn = get_db_connection()

    query = """
    SELECT *
    FROM analysis_results;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(df.head())

def delete():
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    DELETE FROM analysis_results;
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
    #read()
    delete()
    response = input("\nTekrarlanan kayıtları temizlemek istiyor musunuz? (e/h): ")
    if response.lower() == 'e':
        clean_duplicates()
        print("\nTemizlik sonrası kontrol:")
        find_duplicates()