"""
MySQL bağlantısı.
Ayarlar proje kökündeki .env dosyasından okunur; değişken adları
mqtt/subscriber.py ile aynı, böylece tek bir .env iki tarafa da yetiyor.
"""
import os
from contextlib import contextmanager

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "akilli_fabrika"),
    "connection_timeout": 5,
}


@contextmanager
def get_cursor():
    """
    Her istek için kısa ömürlü bir bağlantı açar, iş bitince kapatır.
    dictionary=True sayesinde satırlar {"sütun": değer} şeklinde gelir,
    bu da Pydantic modellerine doğrudan verilebiliyor.
    """
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        cursor = conn.cursor(dictionary=True)
        try:
            yield cursor
            conn.commit()
        finally:
            cursor.close()
    finally:
        conn.close()
