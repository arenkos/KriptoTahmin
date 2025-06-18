import mysql.connector
import pandas as pd
from sqlalchemy import create_engine

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

def get_sqlalchemy_engine():
    """Pandas için SQLAlchemy engine oluştur"""
    try:
        return create_engine('mysql+mysqlconnector://u162605596_kripto2:Arenkos1.@193.203.168.175/u162605596_kripto2')
    except Exception as err:
        print(f"SQLAlchemy engine hatası: {err}")
        return None

def get_db_connection():
    return get_mysql_connection()

def get_db_connection2():
    return get_mysql_connection()

def read_analiz():
    engine = get_sqlalchemy_engine()
    if not engine:
        print("SQLAlchemy engine oluşturulamadı!")
        return

    query = """
    SELECT DISTINCT *
    FROM analysis_results WHERE final_balance>=100;
    """

    try:
        df = pd.read_sql_query(query, engine)
        print(df)
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
    finally:
        engine.dispose()

def read_islemler():
    engine = get_sqlalchemy_engine()
    if not engine:
        print("SQLAlchemy engine oluşturulamadı!")
        return

    query = """
    SELECT COUNT(*)
    FROM backtest_transactions ;
    """

    try:
        df = pd.read_sql_query(query, engine)
        print(df)
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
    finally:
        engine.dispose()

def read_veriler():
    engine = get_sqlalchemy_engine()
    if not engine:
        print("SQLAlchemy engine oluşturulamadı!")
        return

    query = """
    SELECT *, FROM_UNIXTIME(timestamp / 1000) AS human_readable_time
    FROM ohlcv_data
    WHERE symbol LIKE '%BTC%' AND timeframe = '1m' ORDER BY timestamp DESC LIMIT 15;
    """
    
    try:
        df = pd.read_sql_query(query, engine)
        print(df)
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
    finally:
        engine.dispose()

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        DELETE FROM ohlcv_data WHERE id = 26267212
    """

    cursor.execute(query)
    conn.commit()  # Değişiklikleri kaydet
    conn.close()

    print("Güncelleme tamamlandı.")

def read_islem_gercek():
    engine = get_sqlalchemy_engine()
    if not engine:
        print("SQLAlchemy engine oluşturulamadı!")
        return

    query = """
            SELECT *, FROM_UNIXTIME(entry_time / 1000) AS enter_time FROM realtime_transactions;
        """

    try:
        df = pd.read_sql_query(query, engine)
        print(df)
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
    finally:
        engine.dispose()

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
    conn = get_mysql_connection()
    if not conn:
        print("MySQL bağlantısı kurulamadı!")
        return []
    cursor = conn.cursor()

    # Tabloları listele
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    
    table_list = []
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        table_list.append({
            'name': table_name,
            'count': count
        })
    
    conn.close()
    return table_list

def delete_analiz():
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    DELETE FROM analysis_results;
    """

    cursor.execute(query)
    conn.commit()
    conn.close()

    print("Tüm veriler silindi.")

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
    engine = get_sqlalchemy_engine()
    if not engine:
        print("SQLAlchemy engine oluşturulamadı!")
        return

    # Tekrarlanan kayıtları bul
    query = """
        SELECT symbol, timeframe, timestamp, COUNT(*) as tekrar_sayisi
        FROM ohlcv_data
        GROUP BY symbol, timeframe, timestamp
        HAVING COUNT(*) > 1
        ORDER BY tekrar_sayisi DESC
        """
    
    try:
        duplicates = pd.read_sql_query(query, engine)
        
        if len(duplicates) > 0:
            print("\nTekrarlanan kayıtlar:")
            print(duplicates)
            
            # Her tekrarlanan kayıt için detaylı bilgi
            for _, row in duplicates.iterrows():
                detail_query = """
                SELECT *
                FROM ohlcv_data
                WHERE symbol = %s AND timeframe = %s AND timestamp = %s
                ORDER BY id
                """
                details = pd.read_sql_query(detail_query, engine, params=(row['symbol'], row['timeframe'], row['timestamp']))
                print(f"\n{row['symbol']} - {row['timeframe']} - {row['timestamp']} için detaylar:")
                print(details)
        else:
            print("\nTekrarlanan kayıt bulunamadı.")
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
    finally:
        engine.dispose()

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

def ohlcv_veri_cek(symbol, timeframe, limit=100):
    """OHLCV verilerini çek"""
    engine = get_sqlalchemy_engine()
    if not engine:
        return pd.DataFrame()
    
    query = """
    SELECT timestamp, open, high, low, close, volume
    FROM ohlcv_data
    WHERE symbol = %s AND timeframe = %s
    ORDER BY timestamp DESC
    LIMIT %s
    """
    
    try:
        df = pd.read_sql_query(query, engine, params=(symbol, timeframe, limit))
        return df
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
        return pd.DataFrame()
    finally:
        engine.dispose()

def analysis_sonuclari_cek():
    """Analiz sonuçlarını çek"""
    engine = get_sqlalchemy_engine()
    if not engine:
        return pd.DataFrame()
    
    query = """
    SELECT symbol, timeframe, leverage, stop_percentage, kar_al_percentage,
           successful_trades, unsuccessful_trades, final_balance, success_rate
    FROM analysis_results
    ORDER BY final_balance DESC
    """
    
    try:
        df = pd.read_sql_query(query, engine)
        return df
    except Exception as e:
        print(f"Veri okuma hatası: {e}")
        return pd.DataFrame()
    finally:
        engine.dispose()

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