#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import mysql.connector
from datetime import datetime

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

def test_connection():
    """MySQL bağlantısını test et"""
    print("MySQL bağlantısı test ediliyor...")
    
    conn = get_mysql_connection()
    if not conn:
        print("❌ MySQL bağlantısı kurulamadı!")
        return False
    
    try:
        cursor = conn.cursor()
        
        # Bağlantıyı test et
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            print("✅ MySQL bağlantısı başarılı!")
            
            # Mevcut tabloları listele
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            
            print(f"📋 Mevcut tablolar ({len(tables)} adet):")
            for table in tables:
                print(f"  - {table[0]}")
            
            # ohlcv_data tablosunu kontrol et
            cursor.execute("SHOW TABLES LIKE 'ohlcv_data'")
            ohlcv_exists = cursor.fetchone()
            
            if ohlcv_exists:
                print("✅ ohlcv_data tablosu mevcut")
                
                # Tablo yapısını göster
                cursor.execute("DESCRIBE ohlcv_data")
                columns = cursor.fetchall()
                print("📊 ohlcv_data tablosu yapısı:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]}")
                
                # Veri sayısını kontrol et
                cursor.execute("SELECT COUNT(*) FROM ohlcv_data")
                count = cursor.fetchone()[0]
                print(f"📈 ohlcv_data tablosunda {count} kayıt var")
                
            else:
                print("⚠️  ohlcv_data tablosu mevcut değil")
            
            # realtime_transactions tablosunu kontrol et
            cursor.execute("SHOW TABLES LIKE 'realtime_transactions'")
            transactions_exists = cursor.fetchone()
            
            if transactions_exists:
                print("✅ realtime_transactions tablosu mevcut")
                
                # Tablo yapısını göster
                cursor.execute("DESCRIBE realtime_transactions")
                columns = cursor.fetchall()
                print("📊 realtime_transactions tablosu yapısı:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]}")
                
                # Veri sayısını kontrol et
                cursor.execute("SELECT COUNT(*) FROM realtime_transactions")
                count = cursor.fetchone()[0]
                print(f"📈 realtime_transactions tablosunda {count} kayıt var")
                
            else:
                print("⚠️  realtime_transactions tablosu mevcut değil")
            
            return True
            
        else:
            print("❌ MySQL bağlantı testi başarısız!")
            return False
            
    except mysql.connector.Error as err:
        print(f"❌ MySQL hatası: {err}")
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    test_connection() 