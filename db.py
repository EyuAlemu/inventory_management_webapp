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

    c.execute('''
    CREATE TABLE IF NOT EXISTS locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        address TEXT,
        owner_username TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS user_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        location_id INTEGER NOT NULL,
        UNIQUE(username, location_id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS location_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id INTEGER NOT NULL,
        item_code TEXT NOT NULL,
        quantity INTEGER DEFAULT 0,
        UNIQUE(location_id, item_code)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS location_prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id INTEGER NOT NULL,
        item_code TEXT NOT NULL,
        price REAL DEFAULT 0,
        UNIQUE(location_id, item_code)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT UNIQUE,
        location_id INTEGER,
        customer_name TEXT,
        created_by TEXT,
        subtotal REAL DEFAULT 0,
        total REAL DEFAULT 0,
        status TEXT DEFAULT 'open',
        created_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        item_code TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL DEFAULT 0,
        line_total REAL DEFAULT 0
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER,
        amount REAL DEFAULT 0,
        payment_method TEXT,
        reference_number TEXT,
        received_by TEXT,
        paid_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS returns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id INTEGER,
        item_code TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        reason TEXT,
        condition_status TEXT DEFAULT 'bad',
        recorded_by TEXT,
        status TEXT DEFAULT 'open',
        created_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS inventory_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_code TEXT NOT NULL,
        source_location_id INTEGER,
        destination_location_id INTEGER,
        quantity INTEGER NOT NULL,
        requested_by TEXT,
        approved_by TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        completed_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS product_suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        item_code TEXT NOT NULL,
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
