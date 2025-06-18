import sqlite3
import mysql.connector

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

def map_sqlite_type_to_mysql(sqlite_type):
    t = sqlite_type.lower()
    if "int" in t:
        return "BIGINT"
    elif "float" in t or "real" in t or "double" in t:
        return "DOUBLE"
    elif "char" in t or "text" in t or "clob" in t:
        return "TEXT"
    elif "date" in t or "time" in t:
        return "DATETIME"
    else:
        return "TEXT"

# SQLite bağlantısı
sqlite_conn = sqlite3.connect("crypto_data.db")
sqlite_cursor = sqlite_conn.cursor()

# Tabloları al
sqlite_cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in sqlite_cursor.fetchall()]

# MySQL bağlantısı
mysql_conn = get_mysql_connection()
mysql_cursor = mysql_conn.cursor()

batch_size = 100_000

# Aktarılacak analysis_id listesi
sqlite_cursor.execute("SELECT id FROM analysis_results WHERE final_balance > 100")
valid_ids = set(row[0] for row in sqlite_cursor.fetchall())

for table in tables:
    print(f"\n📄 Aktarılıyor: {table}")

    # Kolon bilgilerini al
    sqlite_cursor.execute(f"PRAGMA table_info({table})")
    columns_info = sqlite_cursor.fetchall()
    column_names = [col[1] for col in columns_info]
    columns_sql = ', '.join(column_names)
    placeholders = ', '.join(['%s'] * len(column_names))

    # MySQL'de tablo oluştur
    mysql_cursor.execute(f"DROP TABLE IF EXISTS {table}")
    create_sql = f"CREATE TABLE IF NOT EXISTS {table} ("
    for col in columns_info:
        col_name = col[1]
        col_type = map_sqlite_type_to_mysql(col[2])
        create_sql += f"{col_name} {col_type}, "
    create_sql = create_sql.rstrip(", ") + ")"
    mysql_cursor.execute(create_sql)

    # Veri sorgusunu oluştur
    if table == "analysis_results":
        query = "SELECT * FROM analysis_results WHERE final_balance > 100"
    elif table == "backtest_transactions":
        if not valid_ids:
            print("⚠️ Aktarılacak analysis_id bulunamadı, tablo atlandı.")
            continue
        id_list_str = ','.join(map(str, valid_ids))
        query = f"SELECT * FROM backtest_transactions WHERE analysis_id IN ({id_list_str})"
    elif table == "ohlcv_data":
        query = f"SELECT * FROM ohlcv_data WHERE symbol LIKE '%BTC%' AND timeframe LIKE '%1m%'"
    else:
        query = f"SELECT * FROM {table}"

    # Satır sayısını al
    sqlite_cursor.execute(f"SELECT COUNT(*) FROM ({query})")
    total_rows = sqlite_cursor.fetchone()[0]
    print(f"🔢 {total_rows} satır aktarılacak...")

    # Batch aktar
    for offset in range(0, total_rows, batch_size):
        paginated_query = f"{query} LIMIT {batch_size} OFFSET {offset}"
        sqlite_cursor.execute(paginated_query)
        rows = sqlite_cursor.fetchall()
        if not rows:
            break
        insert_sql = f"INSERT INTO {table} ({columns_sql}) VALUES ({placeholders})"
        mysql_cursor.executemany(insert_sql, rows)
        mysql_conn.commit()
        print(f"✅ {offset} → {offset + len(rows)} satır aktarıldı.")

# Temizlik
sqlite_conn.close()
mysql_cursor.close()
mysql_conn.close()

print("\n🎉 Tüm tablolar başarıyla aktarıldı.")