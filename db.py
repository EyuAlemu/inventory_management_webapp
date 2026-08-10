import sqlite3


DB_PATH = "inventory.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def reconcile_base_quantity_overages(cursor):
    """Remove legacy physical overages from unowned company stock without touching Admin ownership."""
    cursor.execute("SELECT item_code,COALESCE(quantity,0) FROM inventory")
    for item_code, base_quantity in cursor.fetchall():
        cursor.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM location_inventory WHERE LOWER(item_code)=LOWER(?)",
            (item_code,)
        )
        excess = max(int(cursor.fetchone()[0] or 0) - int(base_quantity or 0), 0)
        if excess <= 0:
            continue
        cursor.execute(
            '''SELECT li.location_id,li.quantity,
                      COALESCE((SELECT SUM(als.quantity) FROM admin_location_stock als
                                WHERE als.location_id=li.location_id
                                  AND LOWER(als.item_code)=LOWER(li.item_code)),0) AS owned
               FROM location_inventory li
               WHERE LOWER(li.item_code)=LOWER(?)
               ORDER BY (li.quantity-owned) DESC,li.location_id''',
            (item_code,)
        )
        for location_id, location_quantity, owned_quantity in cursor.fetchall():
            unowned_quantity = max(int(location_quantity or 0) - int(owned_quantity or 0), 0)
            reduction = min(excess, unowned_quantity)
            if reduction <= 0:
                continue
            quantity_after = int(location_quantity or 0) - reduction
            cursor.execute(
                '''UPDATE location_inventory SET quantity=?
                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                (quantity_after, location_id, item_code)
            )
            cursor.execute(
                '''INSERT INTO location_stock_history
                   (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                   VALUES (?,?,?,?,?,'Reconcile Base Overage','System',CURRENT_TIMESTAMP)''',
                (location_id, item_code, int(location_quantity or 0), -reduction, quantity_after)
            )
            if quantity_after == 0:
                cursor.execute(
                    "DELETE FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                    (location_id, item_code)
                )
                cursor.execute(
                    "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                    (location_id, item_code)
                )
            excess -= reduction
            if excess <= 0:
                break


def reconcile_invoice_overpayments(cursor):
    """Clamp legacy payment totals to invoice totals, reducing newest payments first."""
    cursor.execute(
        '''SELECT inv.id,ROUND(COALESCE(SUM(p.amount),0)-inv.total,2) AS excess
           FROM invoices inv JOIN payments p ON p.invoice_id=inv.id
           GROUP BY inv.id HAVING ROUND(COALESCE(SUM(p.amount),0)-inv.total,2)>0'''
    )
    for invoice_id, excess_amount in cursor.fetchall():
        remaining_excess = float(excess_amount or 0)
        cursor.execute(
            "SELECT id,amount FROM payments WHERE invoice_id=? ORDER BY id DESC",
            (invoice_id,)
        )
        for payment_id, amount in cursor.fetchall():
            reduction = min(float(amount or 0), remaining_excess)
            corrected_amount = round(float(amount or 0) - reduction, 2)
            if corrected_amount <= 0:
                cursor.execute("DELETE FROM payments WHERE id=?", (payment_id,))
            else:
                cursor.execute("UPDATE payments SET amount=? WHERE id=?", (corrected_amount, payment_id))
            remaining_excess = round(remaining_excess - reduction, 2)
            if remaining_excess <= 0:
                break
        cursor.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))


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
        quantity INTEGER,
        cost REAL DEFAULT 0
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
        source_type TEXT,
        location_id INTEGER,
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
    CREATE TABLE IF NOT EXISTS location_stock_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        location_id INTEGER NOT NULL,
        item_code TEXT NOT NULL,
        quantity_before INTEGER DEFAULT 0,
        quantity_set INTEGER DEFAULT 0,
        quantity_after INTEGER DEFAULT 0,
        action_type TEXT,
        updated_by TEXT,
        updated_at TEXT
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
    c.execute("PRAGMA table_info(invoice_items)")
    invoice_item_columns = {column[1] for column in c.fetchall()}
    if "owner_username" not in invoice_item_columns:
        c.execute("ALTER TABLE invoice_items ADD COLUMN owner_username TEXT")
    if "generic_quantity" not in invoice_item_columns:
        c.execute("ALTER TABLE invoice_items ADD COLUMN generic_quantity INTEGER DEFAULT 0")
    if "owner_quantity" not in invoice_item_columns:
        c.execute("ALTER TABLE invoice_items ADD COLUMN owner_quantity INTEGER DEFAULT 0")

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
    CREATE TABLE IF NOT EXISTS invoice_credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        return_id INTEGER,
        amount REAL DEFAULT 0,
        credit_type TEXT DEFAULT 'customer_return',
        created_by TEXT,
        created_at TEXT,
        UNIQUE(return_id)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS refunds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        credit_id INTEGER,
        amount REAL DEFAULT 0,
        refund_method TEXT,
        reference_number TEXT,
        status TEXT DEFAULT 'completed',
        processed_by TEXT,
        processed_at TEXT
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
    c.execute("PRAGMA table_info(returns)")
    return_columns = {column[1] for column in c.fetchall()}
    if "quantity_before" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN quantity_before INTEGER")
    if "quantity_after" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN quantity_after INTEGER")
    if "inventory_action" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN inventory_action TEXT")
    if "invoice_id" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN invoice_id INTEGER")
    if "affected_owner_username" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN affected_owner_username TEXT")
    if "owner_quantity" not in return_columns:
        c.execute("ALTER TABLE returns ADD COLUMN owner_quantity INTEGER DEFAULT 0")

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
    c.execute("PRAGMA table_info(inventory_transfers)")
    transfer_columns = {column[1] for column in c.fetchall()}
    if "affected_owner_username" not in transfer_columns:
        c.execute("ALTER TABLE inventory_transfers ADD COLUMN affected_owner_username TEXT")

    c.execute('''
    CREATE TABLE IF NOT EXISTS product_suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        item_code TEXT NOT NULL,
        UNIQUE(username, item_code)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS admin_product_allocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        item_code TEXT NOT NULL,
        quantity INTEGER DEFAULT 0,
        UNIQUE(username, item_code)
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS admin_location_stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        location_id INTEGER NOT NULL,
        item_code TEXT NOT NULL,
        quantity INTEGER DEFAULT 0,
        UNIQUE(username, location_id, item_code)
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

    if "source_type" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN source_type TEXT")

    if "location_id" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN location_id INTEGER")
    if "affected_owner_username" not in transaction_columns:
        c.execute("ALTER TABLE transactions ADD COLUMN affected_owner_username TEXT")

    c.execute("PRAGMA table_info(inventory)")
    inventory_columns = {column[1] for column in c.fetchall()}

    if "cost" not in inventory_columns:
        c.execute("ALTER TABLE inventory ADD COLUMN cost REAL DEFAULT 0")

    c.execute(
        '''
        UPDATE admin_product_allocations
        SET quantity = (
            SELECT COALESCE(SUM(apa2.quantity), 0)
            FROM admin_product_allocations apa2
            WHERE apa2.username = admin_product_allocations.username
              AND apa2.item_code = admin_product_allocations.item_code
        )
        WHERE id IN (
            SELECT MIN(id)
            FROM admin_product_allocations
            GROUP BY username, item_code
        )
        '''
    )
    c.execute(
        '''
        DELETE FROM admin_product_allocations
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM admin_product_allocations
            GROUP BY username, item_code
        )
        '''
    )
    c.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_product_allocations_user_item
        ON admin_product_allocations(username, item_code)
        '''
    )
    c.execute(
        '''
        UPDATE admin_product_allocations
        SET quantity = (
            SELECT COALESCE(SUM(apa2.quantity), 0)
            FROM admin_product_allocations apa2
            WHERE LOWER(apa2.username) = LOWER(admin_product_allocations.username)
              AND LOWER(apa2.item_code) = LOWER(admin_product_allocations.item_code)
        )
        WHERE id IN (
            SELECT MIN(id)
            FROM admin_product_allocations
            GROUP BY LOWER(username), LOWER(item_code)
        )
        '''
    )
    c.execute(
        '''
        DELETE FROM admin_product_allocations
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM admin_product_allocations
            GROUP BY LOWER(username), LOWER(item_code)
        )
        '''
    )
    c.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_product_allocations_user_item_ci
        ON admin_product_allocations(LOWER(username), LOWER(item_code))
        '''
    )

    c.execute(
        '''
        DELETE FROM product_suppliers
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM product_suppliers
            GROUP BY LOWER(username), LOWER(item_code)
        )
        '''
    )
    c.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_product_suppliers_user_item_ci
        ON product_suppliers(LOWER(username), LOWER(item_code))
        '''
    )

    # A Standard User's positive personal stock must never be stranded by a
    # missing product-access row.  New removals are blocked in the Super Admin
    # workflow; this repairs legacy databases created before that validation.
    c.execute(
        '''
        INSERT INTO product_suppliers (username, item_code)
        SELECT ui.username, ui.item_code
        FROM user_inventory ui
        INNER JOIN users u
            ON LOWER(u.username)=LOWER(ui.username)
           AND LOWER(COALESCE(u.role,''))='user'
        INNER JOIN inventory i
            ON LOWER(i.item_code)=LOWER(ui.item_code)
        LEFT JOIN product_suppliers ps
            ON LOWER(ps.username)=LOWER(ui.username)
           AND LOWER(ps.item_code)=LOWER(ui.item_code)
        WHERE COALESCE(ui.quantity,0)>0
          AND ps.id IS NULL
        '''
    )

    c.execute(
        '''
        INSERT INTO admin_product_allocations (username, item_code, quantity)
        SELECT ps.username, ps.item_code, COALESCE(SUM(li.quantity), 0)
        FROM product_suppliers ps
        INNER JOIN users u ON u.username = ps.username
        LEFT JOIN user_locations ul ON ul.username = ps.username
        LEFT JOIN location_inventory li
            ON li.location_id = ul.location_id
            AND li.item_code = ps.item_code
        WHERE u.role = 'admin'
        GROUP BY ps.username, ps.item_code
        ON CONFLICT(username, item_code) DO NOTHING
        '''
    )

    c.execute(
        '''
        UPDATE location_inventory
        SET quantity = (
            SELECT COALESCE(SUM(li2.quantity), 0)
            FROM location_inventory li2
            WHERE li2.location_id = location_inventory.location_id
              AND li2.item_code = location_inventory.item_code
        )
        WHERE id IN (
            SELECT MIN(id)
            FROM location_inventory
            GROUP BY location_id, item_code
        )
        '''
    )
    c.execute(
        '''
        DELETE FROM location_inventory
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM location_inventory
            GROUP BY location_id, item_code
        )
        '''
    )
    c.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_location_inventory_location_item
        ON location_inventory(location_id, item_code)
        '''
    )

    c.execute(
        '''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_location_stock_user_location_item_ci
        ON admin_location_stock(LOWER(username), location_id, LOWER(item_code))
        '''
    )
    c.execute(
        '''
        INSERT INTO admin_location_stock (username, location_id, item_code, quantity)
        SELECT h.updated_by, h.location_id, h.item_code,
               MIN(MAX(SUM(h.quantity_set), 0), COALESCE(li.quantity, 0))
        FROM location_stock_history h
        INNER JOIN users u ON LOWER(u.username)=LOWER(h.updated_by) AND u.role='admin'
        INNER JOIN location_inventory li
            ON li.location_id=h.location_id AND LOWER(li.item_code)=LOWER(h.item_code)
        GROUP BY LOWER(h.updated_by), h.location_id, LOWER(h.item_code)
        HAVING SUM(h.quantity_set) > 0
        ON CONFLICT DO NOTHING
        '''
    )

    reconcile_invoice_overpayments(c)

    conn.commit()
    conn.close()
