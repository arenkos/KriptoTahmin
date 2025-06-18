import mysql.connector
# ... diğer importlar ...

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

# ... create_db_connection ve diğer sqlite3 bağlantılarını MySQL ile değiştir ... 