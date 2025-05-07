import sqlite3

def fix_blob_timestamps(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # BLOB timestamp'leri seç
    cursor.execute("SELECT rowid, timestamp FROM ohlcv_data WHERE typeof(timestamp) = 'blob'")
    rows = cursor.fetchall()

    updated = 0
    for rowid, blob in rows:
        if isinstance(blob, bytes):
            try:
                # Little endian olarak int'e çevir
                timestamp_int = int.from_bytes(blob, byteorder='little')
                # Güncelle
                cursor.execute("UPDATE ohlcv_data SET timestamp = ? WHERE rowid = ?", (timestamp_int, rowid))
                updated += 1
            except Exception as e:
                print(f"Satır {rowid} dönüştürülemedi: {e}")

    conn.commit()
    conn.close()
    print(f"{updated} kayıt başarıyla dönüştürüldü.")

# Kullanım
fix_blob_timestamps("crypto_data.db")