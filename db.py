import sqlite3


DB_PATH = "inventory.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_code TEXT UNIQUE,
        item_name TEXT,
        description TEXT,
        quantity INTEGER
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        item_code TEXT,
        quantity_used INTEGER,
        quantity_before INTEGER,
        quantity_after INTEGER,
        transaction_type TEXT,
        transaction_time TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS user_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        item_code TEXT,
        quantity INTEGER DEFAULT 0,
        UNIQUE(username, item_code)
    )
    ''')

    c.execute("PRAGMA table_info(transactions)")
    transaction_columns = {column[1] for column in c.fetchall()}

    if "quantity_before" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN quantity_before INTEGER")

    if "quantity_after" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN quantity_after INTEGER")

    if "transaction_type" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN transaction_type TEXT")

    conn.commit()
    conn.close()
