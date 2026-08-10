from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import sqlite3


def configure(context):
    globals().update(
        {
            key: value
            for key, value in context.items()
            if not key.startswith("__")
        }
    )


def ensure_financial_schema(conn):
    """Apply additive finance migrations before any Financials query runs."""
    cursor = conn.cursor()
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS invoice_credits (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               invoice_id INTEGER NOT NULL,
               return_id INTEGER,
               amount REAL DEFAULT 0,
               credit_type TEXT DEFAULT 'customer_return',
               created_by TEXT,
               created_at TEXT,
               UNIQUE(return_id)
           )'''
    )
    cursor.execute(
        '''CREATE TABLE IF NOT EXISTS refunds (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               invoice_id INTEGER NOT NULL,
               credit_id INTEGER,
               amount REAL DEFAULT 0,
               refund_method TEXT,
               reference_number TEXT,
               status TEXT DEFAULT 'completed',
               processed_by TEXT,
               processed_at TEXT
           )'''
    )
    cursor.execute("PRAGMA table_info(refunds)")
    refund_columns = {row[1] for row in cursor.fetchall()}
    refund_migrations = {
        "invoice_id": "INTEGER",
        "credit_id": "INTEGER",
        "amount": "REAL DEFAULT 0",
        "refund_method": "TEXT",
        "reference_number": "TEXT",
        "status": "TEXT DEFAULT 'completed'",
        "processed_by": "TEXT",
        "processed_at": "TEXT",
    }
    for column_name, column_definition in refund_migrations.items():
        if column_name not in refund_columns:
            cursor.execute(
                f"ALTER TABLE refunds ADD COLUMN {column_name} {column_definition}"
            )
    cursor.execute("PRAGMA table_info(invoice_items)")
    invoice_item_columns = {row[1] for row in cursor.fetchall()}
    if invoice_item_columns and "owner_username" not in invoice_item_columns:
        cursor.execute("ALTER TABLE invoice_items ADD COLUMN owner_username TEXT")
    if invoice_item_columns and "generic_quantity" not in invoice_item_columns:
        cursor.execute("ALTER TABLE invoice_items ADD COLUMN generic_quantity INTEGER DEFAULT 0")
    if invoice_item_columns and "owner_quantity" not in invoice_item_columns:
        cursor.execute("ALTER TABLE invoice_items ADD COLUMN owner_quantity INTEGER DEFAULT 0")
    cursor.execute("PRAGMA table_info(returns)")
    return_columns = {row[1] for row in cursor.fetchall()}
    if return_columns and "owner_quantity" not in return_columns:
        cursor.execute("ALTER TABLE returns ADD COLUMN owner_quantity INTEGER DEFAULT 0")
    cursor.execute("PRAGMA table_info(transactions)")
    transaction_columns = {row[1] for row in cursor.fetchall()}
    if transaction_columns and "affected_owner_username" not in transaction_columns:
        cursor.execute("ALTER TABLE transactions ADD COLUMN affected_owner_username TEXT")
    conn.commit()


def calculate_company_physical_quantity(location_quantity, user_quantity):
    """Return physical units held in company locations and Standard User accounts."""
    return max(int(location_quantity or 0), 0) + max(int(user_quantity or 0), 0)


def get_location_physical_stock_metrics(cursor, item_code, selected_location_id):
    """Return authoritative physical stock totals for an item and one location."""
    cursor.execute(
        '''SELECT COALESCE(SUM(quantity),0) AS all_locations_quantity,
                  COALESCE(SUM(CASE WHEN location_id=? THEN quantity ELSE 0 END),0)
                      AS selected_location_quantity
           FROM location_inventory
           WHERE LOWER(item_code)=LOWER(?)''',
        (selected_location_id, item_code),
    )
    row = cursor.fetchone()
    if not row:
        return {"all_locations": 0, "selected_location": 0}
    return {
        "all_locations": max(int(row[0] or 0), 0),
        "selected_location": max(int(row[1] or 0), 0),
    }


def is_dashboard_usage_transaction(transaction_type):
    """Dashboard usage analytics include sales and their explicit void reversals."""
    return str(transaction_type or "").strip().lower() in {"sale", "invoice_void"}


def dashboard_usage_quantity(transaction_type, quantity):
    """Return a signed usage quantity so invoice voids reverse prior sales."""
    quantity = int(quantity or 0)
    return -quantity if str(transaction_type or "").strip().lower() == "invoice_void" else quantity


def calculate_remaining_assignment(
    assigned_quantity, placed_quantity, written_off_quantity=0, sold_quantity=0
):
    """Return reservation still usable after placed and permanently written-off units."""
    return max(
        int(assigned_quantity or 0)
        - int(placed_quantity or 0)
        - int(written_off_quantity or 0)
        - int(sold_quantity or 0),
        0,
    )


def get_total_reserved_assignment(cursor, item_code):
    """Sum each user's remaining reservation without one user's overuse offsetting another."""
    cursor.execute(
        '''SELECT username,COALESCE(quantity,0) FROM admin_product_allocations
           WHERE LOWER(item_code)=LOWER(?)''',
        (item_code,),
    )
    allocations = cursor.fetchall()
    total_remaining = 0
    for username, assigned_quantity in allocations:
        cursor.execute(
            '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
               WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
            (username, item_code),
        )
        placed = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            '''SELECT COALESCE(SUM(quantity),0) FROM returns
               WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                 AND condition_status<>'customer_return'
                 AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))=LOWER(?)''',
            (item_code, username),
        )
        written_off = int(cursor.fetchone()[0] or 0)
        total_remaining += calculate_remaining_assignment(
            assigned_quantity, placed, written_off,
            get_net_sold_quantity(cursor, item_code, username),
        )
    return total_remaining


def validate_location_selling_price(value, purchase_cost):
    """Return a finite selling price strictly above the current purchase cost."""
    try:
        price = float(value)
        cost = float(purchase_cost)
    except (TypeError, ValueError):
        raise ValueError("Selling Price must be a valid number.")
    if not math.isfinite(price):
        raise ValueError("Selling Price must be a finite number.")
    if price <= 0:
        raise ValueError("Selling Price must be greater than 0.")
    if price <= cost:
        raise ValueError(f"Selling Price must be greater than the purchase cost (${cost:,.2f}).")
    return round(price, 2)


def get_net_sold_quantity(cursor, item_code, owner_username=None):
    """Return sold units not reversed by customer returns, optionally for one stock owner."""
    cursor.execute("PRAGMA table_info(transactions)")
    transaction_columns = {str(row[1]).lower() for row in cursor.fetchall()}
    has_transaction_owner = "affected_owner_username" in transaction_columns
    cursor.execute("PRAGMA table_info(returns)")
    return_columns = {str(row[1]).lower() for row in cursor.fetchall()}
    has_owner_quantity = "owner_quantity" in return_columns
    has_affected_owner = "affected_owner_username" in return_columns
    owner_filter = ""
    params = [item_code]
    if owner_username is not None:
        owner_filter = (
            " AND LOWER(COALESCE(NULLIF(affected_owner_username,''),username))=LOWER(?)"
            if has_transaction_owner else " AND LOWER(username)=LOWER(?)"
        )
        params.append(owner_username)
    cursor.execute(
        f'''SELECT COALESCE(SUM(quantity_used),0) FROM transactions
            WHERE LOWER(item_code)=LOWER(?) AND transaction_type='sale'{owner_filter}''',
        tuple(params)
    )
    sold = int(cursor.fetchone()[0] or 0)
    void_params = [item_code]
    void_filter = ""
    if owner_username is not None:
        void_filter = (
            " AND LOWER(COALESCE(NULLIF(affected_owner_username,''),username))=LOWER(?)"
            if has_transaction_owner else " AND LOWER(username)=LOWER(?)"
        )
        void_params.append(owner_username)
    cursor.execute(
        f'''SELECT COALESCE(SUM(quantity_used),0) FROM transactions
            WHERE LOWER(item_code)=LOWER(?) AND transaction_type='invoice_void'{void_filter}''',
        tuple(void_params),
    )
    voided = int(cursor.fetchone()[0] or 0)
    return_params = [item_code]
    return_filter = ""
    if owner_username is not None:
        return_filter = (
            " AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))=LOWER(?)"
            if has_affected_owner else " AND LOWER(recorded_by)=LOWER(?)"
        )
        return_params.append(owner_username)
    return_quantity_expression = "quantity"
    if owner_username is not None:
        return_quantity_expression = (
            "CASE WHEN COALESCE(owner_quantity,0)>0 THEN owner_quantity "
            "WHEN COALESCE(NULLIF(affected_owner_username,''),'')<>'' THEN quantity ELSE 0 END"
            if has_owner_quantity and has_affected_owner
            else "quantity"
        )
    cursor.execute(
        f'''SELECT COALESCE(SUM({return_quantity_expression}),0) FROM returns
            WHERE LOWER(item_code)=LOWER(?) AND status='completed'
              AND condition_status IN ('customer_return','customer_return_damaged')
              {return_filter}''',
        tuple(return_params)
    )
    returned = int(cursor.fetchone()[0] or 0)
    return max(sold - voided - returned, 0)


def calculate_admin_location_capacity(
    base_quantity, total_location_quantity, selected_location_quantity,
    selected_location_admin_owned, selected_admin_remaining, unowned_elsewhere=0,
    personal_user_quantity=0, written_off_quantity=0, sold_quantity=0,
):
    """Return assignable ownership, existing stock used, and physical stock that may be added."""
    unowned_at_location = max(int(selected_location_quantity) - int(selected_location_admin_owned), 0)
    unlocated_company_stock = max(
        int(base_quantity) - int(total_location_quantity) - int(personal_user_quantity)
        - int(written_off_quantity)
        - int(sold_quantity),
        0,
    )
    available = min(
        max(int(selected_admin_remaining), 0),
        unowned_at_location + max(int(unowned_elsewhere), 0) + unlocated_company_stock,
    )
    return {
        "available": available,
        "unowned_at_location": unowned_at_location,
        "unlocated_company_stock": unlocated_company_stock,
        "unowned_elsewhere": max(int(unowned_elsewhere), 0),
    }


def calculate_invoice_available_quantity(role, physical_quantity, owned_quantity=0):
    """Return sellable invoice stock for the current role."""
    physical_quantity = max(int(physical_quantity or 0), 0)
    if role == "super_admin":
        return physical_quantity
    return min(physical_quantity, max(int(owned_quantity or 0), 0))


def money(value):
    """Normalize application money to two decimal places."""
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def financial_status(total, paid=0, credits=0, refunded=0):
    total, paid, credits, refunded = map(money, (total, paid, credits, refunded))
    net_total = max(total - credits, Decimal("0.00"))
    refund_due = max(paid - net_total - refunded, Decimal("0.00"))
    outstanding = max(net_total - paid, Decimal("0.00"))
    if refund_due > 0:
        label = "Refund Due"
    elif credits >= total and paid <= refunded:
        label = "Fully Credited"
    elif refunded > 0 and refund_due > 0:
        label = "Partially Refunded"
    elif refunded > 0:
        label = "Paid and Refunded"
    elif outstanding <= 0 and paid > 0:
        label = "Paid"
    elif paid > 0:
        label = "Partially Paid"
    else:
        label = "Unpaid"
    return {"label": label, "outstanding": float(outstanding), "refund_due": float(refund_due)}


def void_invoice(conn, invoice_id, voided_by):
    """Void an untouched invoice and atomically restore physical and owned stock."""
    c = conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            '''SELECT inv.location_id,inv.status,inv.created_by,COALESCE(u.role,'')
               FROM invoices inv LEFT JOIN users u ON LOWER(u.username)=LOWER(inv.created_by)
               WHERE inv.id=?''',
            (invoice_id,),
        )
        invoice_row = c.fetchone()
        if not invoice_row:
            raise ValueError("Invoice not found.")
        location_id, status, invoice_creator, creator_role = invoice_row
        if str(status or "").lower() in {"void", "cancelled", "canceled"}:
            raise ValueError("This invoice is already void or cancelled.")
        for table in ("payments", "invoice_credits", "refunds", "returns"):
            c.execute(f"SELECT COUNT(*) FROM {table} WHERE invoice_id=?", (invoice_id,))
            if int(c.fetchone()[0] or 0) > 0:
                raise ValueError(
                    "Invoice cannot be voided after a payment, return credit, refund, or return exists."
                )
        c.execute(
            '''SELECT item_code,quantity,owner_username,COALESCE(owner_quantity,0),
                      COALESCE(generic_quantity,0)
               FROM invoice_items WHERE invoice_id=?''',
            (invoice_id,),
        )
        lines = c.fetchall()
        if not lines:
            raise ValueError("Invoice has no item lines to restore.")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item_code, quantity, owner_username, owner_quantity, generic_quantity in lines:
            quantity = int(quantity or 0)
            owner_quantity = int(owner_quantity or 0)
            generic_quantity = int(generic_quantity or 0)
            # Older invoice rows predate ownership split columns. Infer their source
            # only when the stored owner or invoice creator makes it unambiguous.
            if owner_username and owner_quantity <= 0 and generic_quantity <= 0:
                owner_quantity = quantity
            elif not owner_username and owner_quantity <= 0 and generic_quantity <= 0 and creator_role in {"admin", "sales"}:
                owner_username = invoice_creator
                owner_quantity = quantity
            c.execute(
                '''SELECT COALESCE(quantity,0) FROM location_inventory
                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                (location_id, item_code),
            )
            stock_row = c.fetchone()
            quantity_before = int(stock_row[0] or 0) if stock_row else 0
            quantity_after = quantity_before + quantity
            c.execute(
                '''INSERT INTO location_inventory(location_id,item_code,quantity) VALUES (?,?,?)
                   ON CONFLICT(location_id,item_code) DO UPDATE SET quantity=excluded.quantity''',
                (location_id, item_code, quantity_after),
            )
            if owner_username and int(owner_quantity or 0) > 0:
                c.execute(
                    '''INSERT INTO admin_location_stock(username,location_id,item_code,quantity)
                       VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                       DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                    (owner_username, location_id, item_code, int(owner_quantity)),
                )
            c.execute(
                '''INSERT INTO location_stock_history
                   (location_id,item_code,quantity_before,quantity_set,quantity_after,
                    action_type,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)''',
                (location_id, item_code, quantity_before, quantity, quantity_after,
                 "Void Invoice", voided_by, now),
            )
            c.execute(
                '''INSERT INTO transactions
                   (username,item_code,quantity_used,quantity_before,quantity_after,
                    transaction_type,source_type,location_id,transaction_time,
                    affected_owner_username) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (voided_by, item_code, quantity, quantity_before, quantity_after,
                 "invoice_void", "location_stock", location_id, now, owner_username),
            )
        c.execute("UPDATE invoices SET status='void' WHERE id=?", (invoice_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def calculate_invoice_ownership_split(quantity, generic_available, owner_available=0):
    """Split an invoice line between generic company stock and one selected owner."""
    quantity = max(int(quantity or 0), 0)
    generic_quantity = min(quantity, max(int(generic_available or 0), 0))
    owner_quantity = quantity - generic_quantity
    if owner_quantity > max(int(owner_available or 0), 0):
        raise ValueError("The selected stock sources do not have enough quantity for this invoice.")
    return generic_quantity, owner_quantity


def calculate_return_owner_quantity(
    generic_sold_quantity, owner_sold_quantity, previously_returned_quantity, return_quantity
):
    """Return the owner-backed overlap for a cumulative partial customer return."""
    generic_sold_quantity = max(int(generic_sold_quantity or 0), 0)
    owner_sold_quantity = max(int(owner_sold_quantity or 0), 0)
    start = max(int(previously_returned_quantity or 0), 0)
    end = start + max(int(return_quantity or 0), 0)
    owner_start = generic_sold_quantity
    owner_end = generic_sold_quantity + owner_sold_quantity
    return max(min(end, owner_end) - max(start, owner_start), 0)


def consume_invoice_location_ownership(
    cursor, role, username, location_id, item_code, quantity, affected_owner_username=None
):
    """Reduce ownership ledgers for an invoice without allowing an Admin to sell another owner's stock."""
    quantity = int(quantity)
    if role == "admin":
        cursor.execute(
            '''SELECT COALESCE(quantity,0) FROM admin_location_stock
               WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
            (username, location_id, item_code)
        )
        owned_row = cursor.fetchone()
        owned_quantity = int(owned_row[0] or 0) if owned_row else 0
        if quantity > owned_quantity:
            raise ValueError(
                f"You own only {owned_quantity} unit(s) of this item at the selected location."
            )
        cursor.execute(
            '''UPDATE admin_location_stock SET quantity=quantity-?
               WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
            (quantity, username, location_id, item_code)
        )
        return username

    if role == "super_admin":
        cursor.execute(
            '''SELECT COALESCE(quantity,0) FROM location_inventory
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (location_id, item_code)
        )
        physical_row = cursor.fetchone()
        physical_quantity = int(physical_row[0] or 0) if physical_row else 0
        cursor.execute(
            '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
               WHERE location_id=? AND LOWER(item_code)=LOWER(?) AND quantity>0''',
            (location_id, item_code)
        )
        total_owned_quantity = int(cursor.fetchone()[0] or 0)
        generic_quantity = max(physical_quantity - total_owned_quantity, 0)
        remaining = max(quantity - generic_quantity, 0)
        if remaining <= 0:
            return None
        if not str(affected_owner_username or "").strip():
            raise ValueError("Select the Admin or Sales owner whose stock will be sold.")
        cursor.execute(
            '''SELECT COALESCE(quantity,0) FROM admin_location_stock
               WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
            (affected_owner_username, location_id, item_code)
        )
        owner_row = cursor.fetchone()
        owner_quantity = int(owner_row[0] or 0) if owner_row else 0
        if remaining > owner_quantity:
            raise ValueError(
                f"Only {generic_quantity} unowned and {owner_quantity} owned by "
                f"{affected_owner_username} are available for this invoice."
            )
        cursor.execute(
            '''UPDATE admin_location_stock SET quantity=quantity-?
               WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
            (remaining, affected_owner_username, location_id, item_code)
        )
        return affected_owner_username
    return None


def record_return_stock(
    conn, username, role, location_id, item_code, quantity, reason, condition_status,
    invoice_id=None, affected_owner_username=None,
):
    """Apply a completed return/damage transaction and return its stock impact."""
    allowed_conditions = {
        "customer_return", "customer_return_damaged",
        "damaged", "defective", "expired", "bad",
    }
    condition_status = str(condition_status or "").strip().lower()
    if condition_status not in allowed_conditions:
        raise ValueError("Select a valid return or damage condition.")
    if isinstance(quantity, bool):
        raise ValueError("Quantity must be a positive whole number.")
    try:
        numeric_quantity = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a positive whole number.")
    if not math.isfinite(numeric_quantity) or not numeric_quantity.is_integer():
        raise ValueError("Quantity must be a positive whole number.")
    quantity = int(numeric_quantity)
    reason = str(reason or "").strip()
    is_customer_return = str(condition_status or "").startswith("customer_return")
    is_sellable_customer_return = condition_status == "customer_return"
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if not reason:
        raise ValueError("Reason is required.")

    c = conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            '''SELECT COALESCE(quantity,0) FROM location_inventory
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (location_id, item_code)
        )
        stock_row = c.fetchone()
        quantity_before = int(stock_row[0] or 0) if stock_row else 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if is_customer_return:
            if invoice_id is None:
                raise ValueError("Select the customer invoice associated with this return.")
            c.execute(
                '''SELECT COALESCE(SUM(ii.quantity),0), inv.created_by,
                          COALESCE(SUM(ii.line_total),0),
                          GROUP_CONCAT(DISTINCT ii.owner_username),
                          COALESCE(SUM(ii.generic_quantity),0),
                          COALESCE(SUM(ii.owner_quantity),0)
                   FROM invoice_items ii JOIN invoices inv ON inv.id=ii.invoice_id
                   WHERE inv.id=? AND inv.location_id=? AND LOWER(ii.item_code)=LOWER(?)
                     AND LOWER(COALESCE(inv.status,'')) NOT IN ('cancelled','canceled','void')
                   GROUP BY inv.id''',
                (invoice_id, location_id, item_code)
            )
            invoice_row = c.fetchone()
            if not invoice_row:
                raise ValueError("Only 0 can be returned for the selected invoice and item.")
            sold_quantity = int(invoice_row[0] or 0) if invoice_row else 0
            invoice_creator = str(invoice_row[1] or "") if invoice_row else ""
            sold_line_total = float(invoice_row[2] or 0) if invoice_row else 0.0
            original_owner_username = str(invoice_row[3] or "").strip() if invoice_row else ""
            if not original_owner_username and role in {"admin", "sales"}:
                original_owner_username = invoice_creator
            generic_sold_quantity = int(invoice_row[4] or 0) if invoice_row else 0
            owner_sold_quantity = int(invoice_row[5] or 0) if invoice_row else 0
            if generic_sold_quantity + owner_sold_quantity == 0:
                if original_owner_username:
                    owner_sold_quantity = sold_quantity
                else:
                    generic_sold_quantity = sold_quantity
            if role in {"admin", "sales"} and invoice_creator.lower() != str(username).lower():
                raise ValueError("You can only receive returns for invoices you created.")
            c.execute(
                '''SELECT COALESCE(SUM(quantity),0) FROM returns
                   WHERE invoice_id=? AND location_id=? AND LOWER(item_code)=LOWER(?)
                     AND condition_status IN ('customer_return','customer_return_damaged')
                     AND status='completed' ''',
                (invoice_id, location_id, item_code)
            )
            returned_quantity = int(c.fetchone()[0] or 0)
            returnable_quantity = max(sold_quantity - returned_quantity, 0)
            if quantity > returnable_quantity:
                raise ValueError(
                    f"Only {returnable_quantity} can be returned: {sold_quantity} sold minus "
                    f"{returned_quantity} already returned."
                )
            returned_owner_quantity = calculate_return_owner_quantity(
                generic_sold_quantity, owner_sold_quantity, returned_quantity, quantity
            )
            if returned_owner_quantity <= 0:
                affected_owner_username = None
            quantity_after = quantity_before + quantity if is_sellable_customer_return else quantity_before
            quantity_change = quantity if is_sellable_customer_return else 0
            inventory_action = "add" if is_sellable_customer_return else "write_off_return"
            action_type = "Customer Return" if is_sellable_customer_return else "Damaged Customer Return"
            if role in {"admin", "sales"}:
                affected_owner_username = username
                c.execute(
                    '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                    (username, item_code)
                )
                assignment_row = c.fetchone()
                assigned_quantity = int(assignment_row[0] or 0) if assignment_row else 0
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                    (username, item_code)
                )
                owned_total = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM returns
                       WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                         AND condition_status<>'customer_return'
                         AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                             =LOWER(?)''',
                    (item_code, username)
                )
                written_off_total = int(c.fetchone()[0] or 0)
                if quantity > calculate_remaining_assignment(
                    assigned_quantity, owned_total, written_off_total
                ):
                    raise ValueError("This return exceeds your available item assignment.")
            if is_sellable_customer_return:
                c.execute(
                    '''INSERT INTO location_inventory (location_id,item_code,quantity)
                       VALUES (?,?,?) ON CONFLICT(location_id,item_code)
                       DO UPDATE SET quantity=excluded.quantity''',
                    (location_id, item_code, quantity_after)
                )
                if role in {"admin", "sales"} and returned_owner_quantity > 0:
                    c.execute(
                        '''INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                           VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                           DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                        (username, location_id, item_code, returned_owner_quantity)
                    )
                elif original_owner_username and returned_owner_quantity > 0:
                    affected_owner_username = original_owner_username
                    c.execute(
                        '''INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                           VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                           DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                        (original_owner_username, location_id, item_code, returned_owner_quantity)
                    )
            elif role in {"admin", "sales"} and returned_owner_quantity > 0:
                affected_owner_username = username
            elif original_owner_username and returned_owner_quantity > 0:
                affected_owner_username = original_owner_username
        else:
            returned_owner_quantity = 0
            if role == "sales":
                raise ValueError("Sales users cannot record damaged or unsellable stock.")
            removable_quantity = quantity_before
            if role == "admin":
                c.execute(
                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                       WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                    (username, location_id, item_code)
                )
                owned_row = c.fetchone()
                removable_quantity = min(quantity_before, int(owned_row[0] or 0) if owned_row else 0)
            if quantity > removable_quantity:
                raise ValueError(f"Only {removable_quantity} is available for you to remove at this location.")
            quantity_after = quantity_before - quantity
            quantity_change = -quantity
            inventory_action = "remove"
            action_type = str(condition_status).title()
            c.execute(
                '''UPDATE location_inventory SET quantity=?
                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                (quantity_after, location_id, item_code)
            )
            if role == "admin":
                c.execute(
                    '''UPDATE admin_location_stock SET quantity=MAX(quantity-?,0)
                       WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                    (quantity, username, location_id, item_code)
                )
                affected_owner_username = username
            else:
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                       WHERE location_id=? AND LOWER(item_code)=LOWER(?) AND quantity>0''',
                    (location_id, item_code)
                )
                total_owned = int(c.fetchone()[0] or 0)
                generic_quantity = max(quantity_before - total_owned, 0)
                remaining = max(quantity - generic_quantity, 0)
                if remaining > 0:
                    if not str(affected_owner_username or "").strip():
                        raise ValueError(
                            "Select the Admin or Sales owner whose assigned stock was damaged."
                        )
                    c.execute(
                        '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                           WHERE LOWER(username)=LOWER(?) AND location_id=?
                             AND LOWER(item_code)=LOWER(?)''',
                        (affected_owner_username, location_id, item_code)
                    )
                    owner_row = c.fetchone()
                    owner_quantity = int(owner_row[0] or 0) if owner_row else 0
                    if remaining > owner_quantity:
                        raise ValueError(
                            f"Only {generic_quantity} unowned and {owner_quantity} owned by "
                            f"{affected_owner_username} are available for this damage record."
                        )
                    c.execute(
                        '''UPDATE admin_location_stock SET quantity=quantity-?
                           WHERE LOWER(username)=LOWER(?) AND location_id=?
                             AND LOWER(item_code)=LOWER(?)''',
                        (remaining, affected_owner_username, location_id, item_code)
                    )
                else:
                    affected_owner_username = None

        c.execute(
            '''INSERT INTO returns
               (location_id,item_code,quantity,reason,condition_status,recorded_by,status,created_at,
                quantity_before,quantity_after,inventory_action,invoice_id,affected_owner_username,
                owner_quantity)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (location_id, item_code, quantity, reason, condition_status, username, "completed", now,
             quantity_before, quantity_after, inventory_action, invoice_id, affected_owner_username,
             returned_owner_quantity)
        )
        return_id = c.lastrowid
        if is_customer_return:
            c.execute(
                '''SELECT COALESCE(SUM(ic.amount),0)
                   FROM invoice_credits ic
                   JOIN returns previous_return ON previous_return.id=ic.return_id
                   WHERE ic.invoice_id=? AND previous_return.location_id=?
                     AND LOWER(previous_return.item_code)=LOWER(?)
                     AND previous_return.status='completed'
                     AND previous_return.condition_status IN
                         ('customer_return','customer_return_damaged')''',
                (invoice_id, location_id, item_code),
            )
            previous_item_credits = money(c.fetchone()[0] or 0)
            remaining_item_credit = max(
                money(sold_line_total) - previous_item_credits, Decimal("0.00")
            )
            proportional_credit = money(
                (Decimal(str(sold_line_total)) * Decimal(quantity) / Decimal(sold_quantity))
                if sold_quantity > 0 else 0
            )
            credit_amount = float(
                remaining_item_credit
                if quantity == returnable_quantity
                else min(proportional_credit, remaining_item_credit)
            )
            c.execute(
                '''INSERT INTO invoice_credits
                   (invoice_id,return_id,amount,credit_type,created_by,created_at)
                   VALUES (?,?,?,?,?,?)''',
                (invoice_id, return_id, credit_amount, "customer_return", username, now)
            )
            c.execute(
                '''SELECT MAX(inv.total
                              - COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id),0)
                              - COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id),0),0)
                   FROM invoices inv WHERE inv.id=?''',
                (invoice_id,)
            )
            return_balance = float(c.fetchone()[0] or 0)
            c.execute(
                "UPDATE invoices SET status=? WHERE id=?",
                ("paid" if return_balance <= 0.005 else "open", invoice_id)
            )
        c.execute(
            '''INSERT INTO location_stock_history
               (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (location_id, item_code, quantity_before, quantity_change, quantity_after, action_type, username, now)
        )
        c.execute(
            '''INSERT INTO transactions
               (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,
                source_type,location_id,transaction_time,affected_owner_username)
               VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (username, item_code, quantity, quantity_before, quantity_after,
             "customer_return_damaged" if condition_status == "customer_return_damaged"
             else "customer_return" if is_customer_return else "damage",
             "location_stock", location_id, now, affected_owner_username)
        )
        conn.commit()
        return {"quantity_before": quantity_before, "quantity_after": quantity_after,
                "inventory_action": inventory_action}
    except Exception:
        conn.rollback()
        raise


def render_returns_damage_records(returns_df):
    """Render the returns/damage audit table independently from the create form."""
    st.markdown('<div class="dashboard-section-title">Returns / Damage Records</div>', unsafe_allow_html=True)
    if returns_df.empty:
        st.info("No returned or damaged items have been recorded for the records you can access yet.")
        return
    if "affected_owner_username" not in returns_df.columns:
        returns_df = returns_df.copy()
        returns_df["affected_owner_username"] = ""

    return_filter_columns = st.columns(3 if is_super_admin() else 2)
    return_filter_col1, return_filter_col2 = return_filter_columns[:2]
    with return_filter_col1:
        return_location_filter = st.selectbox(
            "Filter Location",
            ["All"] + sorted(returns_df["location"].dropna().unique().tolist()),
            key="return_location_filter"
        )
    with return_filter_col2:
        return_condition_filter = st.selectbox(
            "Condition",
            ["All"] + sorted(returns_df["condition_status"].dropna().unique().tolist()),
            key="return_condition_filter"
        )
    return_user_filter = "All"
    if is_super_admin():
        with return_filter_columns[2]:
            visible_return_users = set(
                returns_df["recorded_by"].dropna().astype(str).tolist()
            )
            if "invoice_created_by" in returns_df.columns:
                visible_return_users.update(
                    returns_df["invoice_created_by"].dropna().astype(str).tolist()
                )
            return_user_filter = st.selectbox(
                "Admin or Sales User",
                ["All"] + sorted(user for user in visible_return_users if user),
                key="return_user_filter"
            )

    return_display_df = returns_df.copy()
    if return_location_filter != "All":
        return_display_df = return_display_df[
            return_display_df["location"] == return_location_filter
        ].copy()
    if return_condition_filter != "All":
        return_display_df = return_display_df[
            return_display_df["condition_status"] == return_condition_filter
        ].copy()
    if is_super_admin() and return_user_filter != "All":
        return_display_df = return_display_df[
            (
                return_display_df["recorded_by"].fillna("").astype(str).str.lower()
                == return_user_filter.lower()
            )
            | (
                return_display_df["invoice_created_by"].fillna("").astype(str).str.lower()
                == return_user_filter.lower()
            )
        ].copy()
    if return_display_df.empty:
        st.info("No return or damage records match the selected filters.")
        return

    if get_current_role() == "sales":
        return_display_df = return_display_df[
            [
                "invoice_number", "location", "item_code", "item_name", "quantity",
                "reason", "status", "created_at",
            ]
        ]
    elif is_super_admin():
        return_display_df = return_display_df[
            [
                "invoice_id", "invoice_number", "invoice_created_by", "location", "item_code", "item_name",
                "quantity_before", "quantity", "quantity_after", "inventory_action",
                "condition_status", "affected_owner_username", "status", "recorded_by",
                "created_at", "reason",
            ]
        ]
    else:
        return_display_df = return_display_df[
            [
                "invoice_number", "location", "item_code", "item_name", "quantity",
                "condition_status", "reason", "status", "created_at",
            ]
        ]
    st.dataframe(
        return_display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "invoice_id": "Invoice ID",
            "invoice_number": "Invoice",
            "invoice_created_by": "Invoice Created By",
            "location": "Location",
            "item_code": "Item Code",
            "item_name": "Item Name",
            "quantity": "Quantity",
            "reason": "Reason",
            "condition_status": "Condition",
            "affected_owner_username": "Affected Stock Owner",
            "recorded_by": "Recorded By",
            "status": "Status",
            "created_at": "Created",
        }
    )


def complete_pending_inventory_transfer(conn, transfer_id, approved_by, owner_override=None):
    """Atomically complete one pending transfer and preserve physical and owner ledgers."""
    c = conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            '''SELECT item_code,source_location_id,destination_location_id,quantity,
                      requested_by,COALESCE(affected_owner_username,'')
               FROM inventory_transfers WHERE id=? AND LOWER(status)='pending' ''',
            (transfer_id,),
        )
        row = c.fetchone()
        if not row:
            raise ValueError("This pending transfer no longer exists or was already processed.")
        item_code, source_id, destination_id, quantity, requested_by, owner_username = row
        if owner_override is not None:
            owner_username = str(owner_override or "").strip()
            c.execute(
                "UPDATE inventory_transfers SET affected_owner_username=? WHERE id=?",
                (owner_username or None, transfer_id),
            )
        quantity = int(quantity or 0)
        c.execute("SELECT COALESCE(role,'') FROM users WHERE LOWER(username)=LOWER(?)", (requested_by,))
        requester_role_row = c.fetchone()
        requester_role = str(requester_role_row[0] or "") if requester_role_row else ""
        if source_id == destination_id or quantity <= 0:
            raise ValueError("The pending transfer has invalid locations or quantity.")
        c.execute(
            "SELECT id,active FROM locations WHERE id IN (?,?)",
            (source_id, destination_id),
        )
        active_locations = {int(location_id): int(active or 0) for location_id, active in c.fetchall()}
        if active_locations.get(int(source_id)) != 1 or active_locations.get(int(destination_id)) != 1:
            raise ValueError("Source and destination locations must both still be active.")
        c.execute(
            '''SELECT COALESCE(quantity,0) FROM location_inventory
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (source_id, item_code),
        )
        source_row = c.fetchone()
        source_before = int(source_row[0] or 0) if source_row else 0
        c.execute(
            '''SELECT COALESCE(SUM(quantity),0) FROM inventory_transfers
               WHERE id<>? AND source_location_id=? AND LOWER(item_code)=LOWER(?)
                 AND LOWER(status)='pending' ''',
            (transfer_id, source_id, item_code),
        )
        other_pending = int(c.fetchone()[0] or 0)
        if quantity > max(source_before - other_pending, 0):
            raise ValueError("Source stock is no longer sufficient after other pending reservations.")
        c.execute(
            '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (source_id, item_code),
        )
        total_owned = int(c.fetchone()[0] or 0)
        generic_available = max(source_before - total_owned, 0)
        if requester_role == "admin":
            owner_username = requested_by
            owner_move = quantity
            c.execute(
                '''SELECT COALESCE(SUM(quantity),0) FROM inventory_transfers
                   WHERE id<>? AND source_location_id=? AND LOWER(item_code)=LOWER(?)
                     AND LOWER(requested_by)=LOWER(?) AND LOWER(status)='pending' ''',
                (transfer_id, source_id, item_code, requested_by),
            )
            other_owner_pending = int(c.fetchone()[0] or 0)
        else:
            owner_move = max(quantity - generic_available, 0)
            other_owner_pending = 0
        if owner_move > 0:
            if not owner_username:
                raise ValueError("Select and store the affected stock owner before completing this transfer.")
            c.execute(
                '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                   WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                (owner_username, source_id, item_code),
            )
            owner_available = int(c.fetchone()[0] or 0)
            if owner_move > max(owner_available - other_owner_pending, 0):
                raise ValueError(f"{owner_username} no longer has enough stock at the source location.")
            c.execute(
                '''UPDATE admin_location_stock SET quantity=quantity-?
                   WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                (owner_move, owner_username, source_id, item_code),
            )
            c.execute(
                '''INSERT INTO admin_location_stock(username,location_id,item_code,quantity)
                   VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                   DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                (owner_username, destination_id, item_code, owner_move),
            )
        c.execute(
            '''SELECT COALESCE(quantity,0) FROM location_inventory
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (destination_id, item_code),
        )
        destination_row = c.fetchone()
        destination_before = int(destination_row[0] or 0) if destination_row else 0
        source_after, destination_after = source_before - quantity, destination_before + quantity
        c.execute(
            '''UPDATE location_inventory SET quantity=?
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
            (source_after, source_id, item_code),
        )
        if source_after == 0:
            c.execute(
                "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                (source_id, item_code),
            )
        c.execute(
            '''INSERT INTO location_inventory(location_id,item_code,quantity) VALUES (?,?,?)
               ON CONFLICT(location_id,item_code) DO UPDATE SET quantity=location_inventory.quantity+excluded.quantity''',
            (destination_id, item_code, quantity),
        )
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for location_id, before, change, after, action, transaction_type in (
            (source_id, source_before, -quantity, source_after, "Transfer Out", "transfer_out"),
            (destination_id, destination_before, quantity, destination_after, "Transfer In", "transfer_in"),
        ):
            c.execute(
                '''INSERT INTO location_stock_history
                   (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                (location_id, item_code, before, change, after, action, approved_by, now),
            )
            c.execute(
                '''INSERT INTO transactions
                   (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,
                    source_type,location_id,transaction_time,affected_owner_username)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (approved_by, item_code, quantity, before, after, transaction_type,
                 "location_stock", location_id, now, owner_username or None),
            )
        c.execute(
            '''INSERT INTO location_prices(location_id,item_code,price)
               SELECT ?,item_code,price FROM location_prices
               WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                 AND NOT EXISTS (SELECT 1 FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?))''',
            (destination_id, source_id, item_code, destination_id, item_code),
        )
        c.execute(
            '''UPDATE inventory_transfers SET status='completed',approved_by=?,completed_at=?
               WHERE id=? AND LOWER(status)='pending' ''',
            (approved_by, now, transfer_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def render_transfer_records(transfers_df):
    """Render pending-transfer management and transfer history."""
    st.markdown('<div class="dashboard-section-title">Transfer Records</div>', unsafe_allow_html=True)
    if transfers_df.empty:
        st.info("No inventory transfers have been recorded for the locations you can access yet.")
        return

    pending_df = transfers_df[transfers_df["status"].astype(str).str.lower() == "pending"].copy()
    if not is_super_admin():
        pending_df = pending_df[
            pending_df["requested_by"].astype(str).str.lower() == str(st.session_state.username).lower()
        ].copy()
    if not pending_df.empty:
        pending_options = {
            f"#{int(row['id'])} | {row['item_code']} | {row['source_location']} -> "
            f"{row['destination_location']} | {int(row['quantity'])}": int(row["id"])
            for _, row in pending_df.iterrows()
        }
        selected_pending = st.selectbox(
            "Pending Transfer", list(pending_options), key="pending_transfer_manager"
        )
        pending_owner_override = None
        if is_super_admin():
            selected_pending_id = pending_options[selected_pending]
            selected_pending_row = pending_df[pending_df["id"] == selected_pending_id].iloc[0]
            owner_conn = get_connection()
            try:
                pending_owners_df = pd.read_sql_query(
                    '''SELECT als.username,COALESCE(u.role,'unknown') AS role,als.quantity
                       FROM admin_location_stock als
                       LEFT JOIN users u ON LOWER(u.username)=LOWER(als.username)
                       WHERE als.location_id=? AND LOWER(als.item_code)=LOWER(?)
                         AND als.quantity>0 ORDER BY u.role,als.username''',
                    owner_conn,
                    params=(int(selected_pending_row["source_location_id"]), selected_pending_row["item_code"]),
                )
            finally:
                owner_conn.close()
            pending_owner_options = {"Unowned company stock only": ""}
            pending_owner_options.update({
                f"{row['username']} ({str(row['role']).title()}) — {int(row['quantity'])} owned":
                str(row["username"])
                for _, row in pending_owners_df.iterrows()
            })
            stored_pending_owner = str(selected_pending_row.get("affected_owner_username") or "")
            default_pending_owner_index = 0
            for option_index, option_owner in enumerate(pending_owner_options.values()):
                if option_owner.lower() == stored_pending_owner.lower():
                    default_pending_owner_index = option_index
                    break
            pending_owner_label = st.selectbox(
                "Affected Stock Owner",
                list(pending_owner_options.keys()),
                index=default_pending_owner_index,
                key=f"pending_transfer_owner_{selected_pending_id}",
            )
            pending_owner_override = pending_owner_options[pending_owner_label]
        pending_action_cols = st.columns(2)
        with pending_action_cols[0]:
            complete_pending = st.button(
                "Complete Pending Transfer", type="primary", width="stretch",
                disabled=not is_super_admin(),
            )
        with pending_action_cols[1]:
            cancel_pending = st.button("Cancel Pending Transfer", width="stretch")
        if complete_pending:
            conn = get_connection()
            try:
                complete_pending_inventory_transfer(
                    conn, pending_options[selected_pending], st.session_state.username,
                    pending_owner_override,
                )
                st.success("Pending transfer completed and both locations were updated.")
                st.rerun()
            except (ValueError, sqlite3.Error) as exc:
                st.error(str(exc))
            finally:
                conn.close()
        if cancel_pending:
            conn = get_connection()
            try:
                c = conn.cursor()
                c.execute("BEGIN IMMEDIATE")
                if is_super_admin():
                    c.execute(
                        "UPDATE inventory_transfers SET status='cancelled' WHERE id=? AND LOWER(status)='pending'",
                        (pending_options[selected_pending],)
                    )
                else:
                    c.execute(
                        '''UPDATE inventory_transfers SET status='cancelled'
                           WHERE id=? AND LOWER(status)='pending' AND LOWER(requested_by)=LOWER(?)''',
                        (pending_options[selected_pending], st.session_state.username)
                    )
                conn.commit()
            finally:
                conn.close()
            st.success("Pending transfer cancelled and its reserved quantity released.")
            st.rerun()

    filter_location_col, filter_status_col = st.columns(2)
    location_values = sorted(
        set(transfers_df["source_location"].dropna()) | set(transfers_df["destination_location"].dropna())
    )
    with filter_location_col:
        location_filter = st.selectbox(
            "Filter Location", ["All"] + location_values, key="transfer_location_filter"
        )
    with filter_status_col:
        status_filter = st.selectbox(
            "Transfer Status", ["All"] + sorted(transfers_df["status"].dropna().unique().tolist()),
            key="transfer_status_filter"
        )

    display_df = transfers_df.copy()
    if location_filter != "All":
        display_df = display_df[
            (display_df["source_location"] == location_filter)
            | (display_df["destination_location"] == location_filter)
        ].copy()
    if status_filter != "All":
        display_df = display_df[display_df["status"] == status_filter].copy()
    if display_df.empty:
        st.info("No transfer records match the selected filters.")
        return

    display_df["route"] = (
        display_df["source_location"].fillna("Unknown") + " -> "
        + display_df["destination_location"].fillna("Unknown")
    )
    if is_super_admin():
        display_df = display_df[
            ["item_code", "item_name", "route", "quantity", "source_current_quantity",
             "destination_current_quantity", "affected_owner_username", "status", "requested_by", "approved_by",
             "created_at", "completed_at"]
        ]
    else:
        display_df = display_df[
            ["item_code", "item_name", "route", "quantity", "status", "created_at", "completed_at"]
        ]
    st.dataframe(
        display_df, width="stretch", hide_index=True,
        column_config={
            "item_code": "Item Code", "item_name": "Item Name", "route": "Route",
            "quantity": "Quantity", "source_current_quantity": "Source Current Qty",
            "destination_current_quantity": "Destination Current Qty", "requested_by": "Requested By",
            "approved_by": "Approved By", "status": "Status", "created_at": "Created",
            "completed_at": "Completed",
        }
    )


def render_location_stock_table(location_stock_df, inventory_df, table_key_suffix=""):
    stock_table_title = "All Location Stock" if is_super_admin() else "My Assigned Location Stock"
    st.markdown(
        f'<div class="dashboard-section-title">{stock_table_title}</div>',
        unsafe_allow_html=True
    )
    if is_super_admin():
        st.caption("Shows the saved quantity and selling price for each item at each location.")
    else:
        st.caption(
            "Shows only your assigned locations, supplied products, owned quantity, selling price, "
            "and remaining assignment. Shared company quantities stay in the validation logic."
        )

    if location_stock_df.empty:
        if not is_super_admin() and not inventory_df.empty:
            empty_assignment_rows = []
            for _, inventory_row in inventory_df.iterrows():
                assigned_quantity = get_assigned_product_quantity(
                    st.session_state.username,
                    inventory_row["item_code"]
                )
                conn = get_connection()
                placed_quantity = int(
                    conn.execute(
                        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                           WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                        (st.session_state.username, inventory_row["item_code"])
                    ).fetchone()[0] or 0
                )
                conn.close()
                empty_assignment_rows.append(
                    {
                        "Item Code": inventory_row["item_code"],
                        "Item Name": inventory_row["item_name"],
                        "Assigned To You": assigned_quantity,
                        "Added By You": placed_quantity,
                        "Remaining Assignment": max(assigned_quantity - placed_quantity, 0),
                    }
                )
            st.markdown('<div class="dashboard-section-title">My Assignment Summary</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(empty_assignment_rows), width="stretch", hide_index=True)
        show_next_step(
            "No location inventory records exist yet.",
            "Select a location and item, then save quantity and price."
        )
        return

    stock_filter_col1, stock_filter_col2 = st.columns(2)
    with stock_filter_col1:
        stock_location_filter = st.selectbox(
            "Filter Location",
            ["All"] + sorted(location_stock_df["location"].dropna().unique().tolist()),
            key=f"location_stock_filter{table_key_suffix}"
        )
    with stock_filter_col2:
        stock_status_filter = st.selectbox(
            "Stock Status",
            ["All", "In stock", "Low stock", "Out of stock"],
            key=f"location_stock_status_filter{table_key_suffix}"
        )

    stock_display_df = location_stock_df.copy()
    if is_super_admin():
        stock_display_df["stock_status"] = stock_display_df["quantity"].apply(stock_status)

    if stock_location_filter != "All":
        stock_display_df = stock_display_df[
            stock_display_df["location"] == stock_location_filter
        ].copy()

    if is_super_admin() and stock_status_filter != "All":
        stock_display_df = stock_display_df[
            stock_display_df["stock_status"] == stock_status_filter
        ].copy()

    if stock_display_df.empty:
        st.info("No location stock records match the selected filters.")
        return

    conn = get_connection()
    stock_history_df = pd.read_sql_query(
        '''
        SELECT h.location_id, h.item_code, h.quantity_before, h.quantity_set,
               h.quantity_after, h.action_type, h.updated_by, h.updated_at
        FROM location_stock_history h
        INNER JOIN (
            SELECT location_id, item_code, MAX(id) AS latest_id
            FROM location_stock_history
            GROUP BY location_id, item_code
        ) latest ON latest.latest_id = h.id
        ''',
        conn
    )
    conn.close()
    if not stock_history_df.empty:
        stock_display_df = stock_display_df.merge(
            stock_history_df,
            on=["location_id", "item_code"],
            how="left"
        )
    else:
        stock_display_df["quantity_before"] = 0
        stock_display_df["quantity_set"] = 0
        stock_display_df["quantity_after"] = stock_display_df["quantity"]
        stock_display_df["action_type"] = ""
        stock_display_df["updated_by"] = ""
        stock_display_df["updated_at"] = ""

    for history_column in ["quantity_before", "quantity_set", "quantity_after"]:
        stock_display_df[history_column] = (
            stock_display_df[history_column].fillna(0).astype(int)
        )
    stock_display_df["quantity_after"] = stock_display_df["quantity"].fillna(0).astype(int)
    stock_display_df["action_type"] = stock_display_df["action_type"].fillna("")
    stock_display_df["updated_by"] = stock_display_df["updated_by"].fillna("")
    stock_display_df["updated_at"] = stock_display_df["updated_at"].fillna("")

    if not is_super_admin():
        conn = get_connection()
        admin_stock_history_df = pd.read_sql_query(
            '''
            SELECT location_id, item_code, quantity AS quantity_set, username AS updated_by
            FROM admin_location_stock
            WHERE LOWER(username)=LOWER(?) AND quantity > 0
            ''',
            conn,
            params=(st.session_state.get("username", ""),)
        )
        admin_written_off_df = pd.read_sql_query(
            '''SELECT item_code, SUM(quantity) AS written_off
               FROM returns
               WHERE status='completed' AND condition_status<>'customer_return'
                 AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))=LOWER(?)
               GROUP BY LOWER(item_code)''',
            conn,
            params=(st.session_state.get("username", ""),)
        )
        admin_sold_df = pd.read_sql_query(
            '''SELECT item_code,
                      MAX(COALESCE(SUM(CASE
                              WHEN transaction_type='sale' THEN quantity_used
                              WHEN transaction_type='invoice_void' THEN -quantity_used
                              ELSE 0 END),0)
                          - COALESCE((SELECT SUM(r.quantity) FROM returns r
                              WHERE r.status='completed'
                                AND r.condition_status IN ('customer_return','customer_return_damaged')
                                AND LOWER(COALESCE(NULLIF(r.affected_owner_username,''),r.recorded_by))=LOWER(?)
                                AND LOWER(r.item_code)=LOWER(t.item_code)),0),0) AS sold
               FROM transactions t
               WHERE transaction_type IN ('sale','invoice_void')
                 AND LOWER(COALESCE(NULLIF(affected_owner_username,''),username))=LOWER(?)
               GROUP BY LOWER(item_code)''',
            conn,
            params=(st.session_state.get("username", ""), st.session_state.get("username", ""))
        )
        conn.close()
        if not admin_stock_history_df.empty:
            allowed_history_df = admin_stock_history_df.copy()
        else:
            allowed_history_df = pd.DataFrame(
                columns=["location_id", "item_code", "quantity_set", "updated_by"]
            )
        current_admin_username = st.session_state.get("username", "")
        admin_added_by_item = (
            allowed_history_df[
                allowed_history_df["updated_by"].astype(str).str.lower() == current_admin_username.lower()
            ].groupby("item_code")["quantity_set"].sum().astype(int).to_dict()
            if not allowed_history_df.empty
            else {}
        )
        admin_added_by_location_item = (
            allowed_history_df.groupby(["location_id", "item_code"])["quantity_set"]
            .sum().clip(lower=0).astype(int).to_dict()
            if not allowed_history_df.empty
            else {}
        )
        assigned_by_ruth_by_item = {
            row["item_code"]: get_assigned_product_quantity(
                st.session_state.username,
                row["item_code"]
            )
            for _, row in inventory_df.iterrows()
        }
        admin_written_off_by_item = (
            admin_written_off_df.set_index("item_code")["written_off"]
            .fillna(0).astype(int).to_dict()
            if not admin_written_off_df.empty else {}
        )
        admin_sold_by_item = (
            admin_sold_df.set_index("item_code")["sold"].fillna(0).astype(int).to_dict()
            if not admin_sold_df.empty else {}
        )
        stock_display_df["assigned_by_ruth"] = (
            stock_display_df["item_code"].map(assigned_by_ruth_by_item).fillna(0).astype(int)
        )
        stock_display_df["quantity_added_by_admin"] = (
            stock_display_df["item_code"].map(admin_added_by_item).fillna(0).astype(int)
        ).clip(lower=0).astype(int)
        stock_display_df["written_off_by_admin"] = (
            stock_display_df["item_code"].map(admin_written_off_by_item).fillna(0).astype(int)
        )
        stock_display_df["sold_by_admin"] = (
            stock_display_df["item_code"].map(admin_sold_by_item).fillna(0).astype(int)
        )
        stock_display_df["my_quantity_here"] = stock_display_df.apply(
            lambda row: int(
                admin_added_by_location_item.get(
                    (int(row["location_id"]), row["item_code"]),
                    0
                )
            ),
            axis=1
        )
        stock_display_df["stock_status"] = stock_display_df["my_quantity_here"].apply(stock_status)
        stock_display_df["available_to_add"] = (
            stock_display_df["assigned_by_ruth"]
            - stock_display_df["quantity_added_by_admin"]
            - stock_display_df["written_off_by_admin"]
            - stock_display_df["sold_by_admin"]
        ).clip(lower=0).astype(int)
        stock_display_df["assignment_status"] = stock_display_df.apply(
            lambda row: (
                "Needs Super Admin Increase"
                if int(row["quantity_added_by_admin"]) + int(row["written_off_by_admin"]) + int(row["sold_by_admin"])
                > int(row["assigned_by_ruth"])
                else "Available"
                if int(row["available_to_add"]) > 0
                else "Fully Assigned"
            ),
            axis=1
        )
        assignment_summary_df = inventory_df[["item_code", "item_name"]].drop_duplicates().copy()
        assignment_summary_df["assigned_by_ruth"] = (
            assignment_summary_df["item_code"].map(assigned_by_ruth_by_item).fillna(0).astype(int)
        )
        assignment_summary_df["quantity_added_by_admin"] = (
            assignment_summary_df["item_code"].map(admin_added_by_item).fillna(0).astype(int)
        )
        assignment_summary_df["written_off_by_admin"] = (
            assignment_summary_df["item_code"].map(admin_written_off_by_item).fillna(0).astype(int)
        )
        assignment_summary_df["sold_by_admin"] = (
            assignment_summary_df["item_code"].map(admin_sold_by_item).fillna(0).astype(int)
        )
        assignment_summary_df["available_to_add"] = (
            assignment_summary_df["assigned_by_ruth"]
            - assignment_summary_df["quantity_added_by_admin"]
            - assignment_summary_df["written_off_by_admin"]
            - assignment_summary_df["sold_by_admin"]
        ).clip(lower=0).astype(int)
        assignment_summary_df["assignment_status"] = assignment_summary_df.apply(
            lambda row: (
                "Over assignment"
                if int(row["quantity_added_by_admin"]) + int(row["written_off_by_admin"]) + int(row["sold_by_admin"])
                > int(row["assigned_by_ruth"])
                else "Available"
                if int(row["available_to_add"]) > 0
                else "Fully used"
            ),
            axis=1
        )
        st.markdown('<div class="dashboard-section-title">My Assignment Summary</div>', unsafe_allow_html=True)
        st.dataframe(
            assignment_summary_df,
            width="stretch",
            hide_index=True,
            column_config={
                "item_code": "Item Code",
                "item_name": "Item Name",
                "assigned_by_ruth": "Assigned To You",
                "quantity_added_by_admin": "Added By You",
                "written_off_by_admin": "Written Off / Damaged",
                "sold_by_admin": "Net Sold",
                "available_to_add": "Remaining Assignment",
                "assignment_status": "Assignment Status",
            }
        )
        if stock_status_filter != "All":
            stock_display_df = stock_display_df[
                stock_display_df["stock_status"] == stock_status_filter
            ].copy()
        if stock_display_df.empty:
            st.info("No owned stock records match the selected status filter.")
            return
        stock_display_df = stock_display_df[
            [
                "location",
                "item_code",
                "item_name",
                "my_quantity_here",
                "stock_status",
                "price",
            ]
        ]
    else:
        base_quantity_by_item = (
            inventory_df.set_index("item_code")["quantity"].fillna(0).astype(int).to_dict()
            if not inventory_df.empty and "quantity" in inventory_df
            else {}
        )
        purchase_cost_by_item = (
            inventory_df.set_index("item_code")["cost"].fillna(0).astype(float).to_dict()
            if not inventory_df.empty and "cost" in inventory_df
            else {}
        )
        assigned_quantity_by_item = (
            location_stock_df.groupby("item_code")["quantity"].sum().astype(int).to_dict()
            if not location_stock_df.empty
            else {}
        )
        conn = get_connection()
        admin_allocation_df = pd.read_sql_query(
            '''
            SELECT item_code, SUM(quantity) AS allocated_to_admins
            FROM admin_product_allocations
            GROUP BY LOWER(item_code)
            ''',
            conn
        )
        admin_placed_df = pd.read_sql_query(
            '''
            SELECT item_code, SUM(quantity) AS placed_by_admins
            FROM admin_location_stock
            GROUP BY LOWER(item_code)
            ''',
            conn
        )
        user_stock_df = pd.read_sql_query(
            '''SELECT item_code, SUM(quantity) AS user_stock
               FROM user_inventory GROUP BY LOWER(item_code)''',
            conn
        )
        written_off_df = pd.read_sql_query(
            '''SELECT item_code, SUM(quantity) AS written_off,
                      SUM(CASE WHEN COALESCE(affected_owner_username,'')<>''
                               THEN quantity ELSE 0 END) AS owner_written_off
               FROM returns
               WHERE status='completed' AND condition_status<>'customer_return'
               GROUP BY LOWER(item_code)''',
            conn
        )
        scoped_item_codes = stock_display_df["item_code"].dropna().astype(str).unique()
        reserved_by_item = {
            code.lower(): get_total_reserved_assignment(conn.cursor(), code)
            for code in scoped_item_codes
        }
        net_sold_by_item = {
            code.lower(): get_net_sold_quantity(conn.cursor(), code)
            for code in scoped_item_codes
        }
        conn.close()
        admin_allocated_by_item = (
            admin_allocation_df.assign(
                item_code_key=admin_allocation_df["item_code"].astype(str).str.lower()
            ).set_index("item_code_key")["allocated_to_admins"].fillna(0).astype(int).to_dict()
            if not admin_allocation_df.empty
            else {}
        )
        admin_placed_by_item = (
            admin_placed_df.assign(
                item_code_key=admin_placed_df["item_code"].astype(str).str.lower()
            ).set_index("item_code_key")["placed_by_admins"].fillna(0).astype(int).to_dict()
            if not admin_placed_df.empty
            else {}
        )
        user_stock_by_item = (
            user_stock_df.assign(
                item_code_key=user_stock_df["item_code"].astype(str).str.lower()
            ).set_index("item_code_key")["user_stock"].fillna(0).astype(int).to_dict()
            if not user_stock_df.empty else {}
        )
        written_off_by_item = (
            written_off_df.assign(
                item_code_key=written_off_df["item_code"].astype(str).str.lower()
            ).set_index("item_code_key")["written_off"].fillna(0).astype(int).to_dict()
            if not written_off_df.empty else {}
        )
        owner_written_off_by_item = (
            written_off_df.assign(
                item_code_key=written_off_df["item_code"].astype(str).str.lower()
            ).set_index("item_code_key")["owner_written_off"].fillna(0).astype(int).to_dict()
            if not written_off_df.empty else {}
        )
        stock_display_df["item_code_key"] = stock_display_df["item_code"].astype(str).str.lower()
        stock_display_df["base_quantity"] = (
            stock_display_df["item_code"].map(base_quantity_by_item).fillna(0).astype(int)
        )
        stock_display_df["assigned_quantity"] = (
            stock_display_df["item_code"].map(assigned_quantity_by_item).fillna(0).astype(int)
        )
        stock_display_df["assigned_to_admins"] = (
            stock_display_df["item_code_key"].map(admin_allocated_by_item).fillna(0).astype(int)
        )
        stock_display_df["placed_by_admins"] = (
            stock_display_df["item_code_key"].map(admin_placed_by_item).fillna(0).astype(int)
        )
        stock_display_df["user_stock"] = (
            stock_display_df["item_code_key"].map(user_stock_by_item).fillna(0).astype(int)
        )
        stock_display_df["written_off"] = (
            stock_display_df["item_code_key"].map(written_off_by_item).fillna(0).astype(int)
        )
        stock_display_df["owner_written_off"] = (
            stock_display_df["item_code_key"].map(owner_written_off_by_item).fillna(0).astype(int)
        )
        stock_display_df["admin_reserved_remaining"] = (
            stock_display_df["item_code_key"].map(reserved_by_item).fillna(0).astype(int)
        )
        stock_display_df["net_sold"] = (
            stock_display_df["item_code_key"].map(net_sold_by_item).fillna(0).astype(int)
        )
        stock_display_df["available_quantity"] = (
            stock_display_df["base_quantity"]
            - stock_display_df["assigned_quantity"]
            - stock_display_df["user_stock"]
            - stock_display_df["admin_reserved_remaining"]
            - stock_display_df["written_off"]
            - stock_display_df["net_sold"]
        ).astype(int)
        stock_display_df["quantity_integrity"] = stock_display_df["available_quantity"].apply(
            lambda available: "Over-allocated" if int(available) < 0 else "Valid"
        )
        stock_display_df["purchase_cost"] = (
            stock_display_df["item_code"].map(purchase_cost_by_item).fillna(0).astype(float)
        )
        stock_display_df["location_purchase_total"] = (
            stock_display_df["quantity"].astype(int) * stock_display_df["purchase_cost"].astype(float)
        )
        stock_display_df["location_sales_value"] = (
            stock_display_df["quantity"].astype(int) * stock_display_df["price"].astype(float)
        )
        stock_display_df = stock_display_df[
            [
                "location",
                "item_code",
                "item_name",
                "base_quantity",
                "assigned_quantity",
                "assigned_to_admins",
                "placed_by_admins",
                "user_stock",
                "written_off",
                "net_sold",
                "admin_reserved_remaining",
                "available_quantity",
                "quantity_integrity",
                "quantity_before",
                "quantity_set",
                "quantity_after",
                "purchase_cost",
                "location_purchase_total",
                "price",
                "location_sales_value",
                "action_type",
                "updated_by",
                "updated_at",
                "quantity",
                "stock_status",
            ]
        ]

    st.dataframe(
        stock_display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "location": "Location",
            "item_code": "Item Code",
            "item_name": "Item Name",
            "base_quantity": "Base Quantity",
            "assigned_quantity": "Total In Locations",
            "assigned_to_admins": "Assigned To Admins",
            "placed_by_admins": "Placed By Admins",
            "user_stock": "Standard User Stock",
            "written_off": "Written Off / Damaged",
            "net_sold": "Net Sold",
            "admin_reserved_remaining": "Admin Reserved Remaining",
            "available_quantity": "Available To Super Admin",
            "quantity_integrity": "Quantity Integrity",
            "quantity_before": "Latest Before Quantity",
            "quantity_set": "Latest Change Quantity",
            "quantity_after": "Latest After Quantity",
            "quantity": "Current Location Quantity",
            "my_quantity_here": "My Quantity Here",
            "purchase_cost": st.column_config.NumberColumn("Purchase Cost", format="$%.2f"),
            "location_purchase_total": st.column_config.NumberColumn("Location Cost Total", format="$%.2f"),
            "assigned_by_ruth": "Assigned By Super Admin",
            "quantity_added_by_admin": "Added By You",
            "available_to_add": "Available To Add",
            "assignment_status": "Quantity Assignment Status",
            "action_type": "Latest Update Type",
            "updated_by": "Latest Updated By",
            "updated_at": "Latest Updated At",
            "stock_status": "Stock Status",
            "price": st.column_config.NumberColumn("Selling Price", format="$%.2f"),
            "location_sales_value": st.column_config.NumberColumn("Location Sales Value", format="$%.2f"),
        }
    )

    if not is_super_admin():
        return

    with st.expander("Stock Update History", expanded=False):
        conn = get_connection()
        history_df = pd.read_sql_query(
            '''
            SELECT h.id, l.name AS location, h.location_id, h.item_code, i.item_name,
                   h.quantity_before, h.quantity_set, h.quantity_after,
                   h.action_type, h.updated_by, h.updated_at
            FROM location_stock_history h
            LEFT JOIN locations l ON l.id = h.location_id
            LEFT JOIN inventory i ON i.item_code = h.item_code
            ORDER BY h.id DESC
            ''',
            conn
        )
        conn.close()

        if history_df.empty:
            st.info("No stock update history has been recorded yet.")
        else:
            allowed_pairs_df = location_stock_df[["location_id", "item_code"]].drop_duplicates()
            history_df = history_df.merge(
                allowed_pairs_df,
                on=["location_id", "item_code"],
                how="inner"
            )

            if history_df.empty:
                st.info("No stock update history is available for this view.")
            else:
                history_df = history_df[
                    [
                        "updated_at",
                        "location",
                        "item_code",
                        "item_name",
                        "quantity_before",
                        "quantity_set",
                        "quantity_after",
                        "action_type",
                        "updated_by",
                    ]
                ]
                st.dataframe(
                    history_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "updated_at": "Updated At",
                        "location": "Location",
                        "item_code": "Item Code",
                        "item_name": "Item Name",
                        "quantity_before": "Before Quantity",
                        "quantity_set": "Changed Quantity",
                        "quantity_after": "After Quantity",
                        "action_type": "Update Type",
                        "updated_by": "Updated By",
                    }
                )


def render(menu):
    if menu == "Dashboard" and has_admin_access():

        conn = get_connection()

        inventory_df = pd.read_sql_query(
            "SELECT * FROM inventory",
            conn
        )

        trans_df = pd.read_sql_query(
            "SELECT * FROM transactions",
            conn
        )

        users_df = pd.read_sql_query(
            "SELECT id, username, role FROM users",
            conn
        )

        location_inventory_df = pd.read_sql_query(
            '''
            SELECT li.location_id, li.item_code, i.item_name, li.quantity
            FROM location_inventory li
            LEFT JOIN inventory i ON li.item_code = i.item_code
            ''',
            conn
        )

        invoice_activity_df = pd.read_sql_query(
            '''
            SELECT inv.id, inv.location_id, inv.created_by AS username, ii.item_code,
                   ii.quantity AS quantity_used, inv.created_at AS transaction_time
            FROM invoices inv
            LEFT JOIN invoice_items ii ON ii.invoice_id = inv.id
            WHERE LOWER(COALESCE(inv.status,'')) NOT IN ('void','cancelled','canceled')
            ORDER BY inv.id DESC
            ''',
            conn
        )

        admin_owned_stock_df = pd.DataFrame()
        if not is_super_admin():
            admin_owned_stock_df = pd.read_sql_query(
                '''
                SELECT als.location_id, als.item_code, i.item_name,
                       COALESCE(als.quantity, 0) AS quantity
                FROM admin_location_stock als
                LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(als.item_code)
                WHERE LOWER(als.username)=LOWER(?)
                ''',
                conn,
                params=(st.session_state.username,)
            )
        else:
            inventory_df = pd.read_sql_query(
                '''
                SELECT i.item_code, i.item_name,
                       COALESCE(location_totals.quantity, 0)
                       + COALESCE(user_totals.quantity, 0) AS quantity
                FROM inventory i
                LEFT JOIN (
                    SELECT LOWER(item_code) AS item_code_key, SUM(MAX(quantity, 0)) AS quantity
                    FROM location_inventory
                    GROUP BY LOWER(item_code)
                ) location_totals ON location_totals.item_code_key=LOWER(i.item_code)
                LEFT JOIN (
                    SELECT LOWER(item_code) AS item_code_key, SUM(MAX(quantity, 0)) AS quantity
                    FROM user_inventory
                    GROUP BY LOWER(item_code)
                ) user_totals ON user_totals.item_code_key=LOWER(i.item_code)
                ORDER BY i.item_name, i.item_code
                ''',
                conn
            )

        conn.close()

        if not is_super_admin():
            assigned_location_ids = get_assigned_location_ids()
            supplied_item_codes = set(get_supplied_item_codes())

            invoice_activity_df = invoice_activity_df[
                invoice_activity_df["location_id"].isin(assigned_location_ids)
            ].copy()
            invoice_activity_df = invoice_activity_df.loc[
                invoice_activity_df["username"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()

            if supplied_item_codes:
                admin_owned_stock_df = admin_owned_stock_df[
                    admin_owned_stock_df["location_id"].isin(assigned_location_ids)
                    & admin_owned_stock_df["item_code"].isin(supplied_item_codes)
                ].copy()
                invoice_activity_df = invoice_activity_df[
                    invoice_activity_df["item_code"].isin(supplied_item_codes)
                ].copy()

                visible_products_df = inventory_df[
                    inventory_df["item_code"].isin(supplied_item_codes)
                ][["item_code", "item_name"]].drop_duplicates().copy()
                owned_totals_df = (
                    admin_owned_stock_df.groupby("item_code", as_index=False)["quantity"].sum()
                    if not admin_owned_stock_df.empty
                    else pd.DataFrame(columns=["item_code", "quantity"])
                )
                inventory_df = visible_products_df.merge(
                    owned_totals_df,
                    on="item_code",
                    how="left"
                )
                inventory_df["quantity"] = (
                    pd.to_numeric(inventory_df["quantity"], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )
            else:
                invoice_activity_df = invoice_activity_df.iloc[0:0].copy()
                inventory_df = inventory_df.iloc[0:0].copy()

            trans_df = invoice_activity_df.rename(columns={"id": "invoice_id"}).copy()
            if not trans_df.empty:
                trans_df["id"] = trans_df["invoice_id"]
                trans_df["transaction_type"] = "sale"
                trans_df["quantity_before"] = None
                trans_df["quantity_after"] = None
            total_users = 1
        else:
            total_users = len(users_df)

        total_items = len(inventory_df)
        total_stock = int(inventory_df["quantity"].sum()) if not inventory_df.empty else 0
        low_stock = int((inventory_df["quantity"] <= 5).sum()) if not inventory_df.empty else 0
        total_transactions = len(trans_df)
        usage_trans_df = trans_df[
            trans_df["transaction_type"].apply(is_dashboard_usage_transaction)
        ].copy() if not trans_df.empty else trans_df.copy()
        if not usage_trans_df.empty:
            usage_trans_df["quantity_used"] = usage_trans_df.apply(
                lambda row: dashboard_usage_quantity(
                    row.get("transaction_type"), row.get("quantity_used", 0)
                ),
                axis=1,
            )
        total_used = int(usage_trans_df["quantity_used"].sum()) if not usage_trans_df.empty else 0
        username_safe = safe_html(st.session_state.username)
        role_label = "Super Admin" if is_super_admin() else "Admin"
        dashboard_scope = "company-wide" if is_super_admin() else "assigned-location and supplied-product"
        products_note = "Master inventory items" if is_super_admin() else "Visible supplied products"
        stock_note = "Physical units company-wide" if is_super_admin() else "Your stock in assigned locations"
        activity_note = "Usage records saved" if is_super_admin() else "Visible invoice activity"
        users_label = "Users" if is_super_admin() else "Scope"
        users_note = "System accounts" if is_super_admin() else "Your scoped access"

        st.markdown(
            f"""
            <div class="admin-dashboard-header">
                <div>
                    <div class="admin-dashboard-title">Dashboard</div>
                    <div class="admin-dashboard-subtitle">Welcome back, {username_safe}. This dashboard shows {dashboard_scope} activity.</div>
                </div>
                <div class="admin-profile-pill">
                    <div class="admin-profile-avatar">A</div>
                    <div>
                        <div class="admin-profile-name">{username_safe}</div>
                        <div class="admin-profile-role">{role_label}</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        card1, card2, card3, card4, card5 = st.columns(5)

        with card1:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-blue">
                    <div class="admin-stat-icon">📦</div>
                    <div class="admin-stat-label">Products</div>
                    <div class="admin-stat-value">{total_items}</div>
                    <div class="admin-stat-note">{products_note}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card2:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-cyan">
                    <div class="admin-stat-icon">🏷</div>
                    <div class="admin-stat-label">Stock Units</div>
                    <div class="admin-stat-value">{total_stock}</div>
                    <div class="admin-stat-note">{stock_note}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card3:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-amber">
                    <div class="admin-stat-icon">⚠</div>
                    <div class="admin-stat-label">Low Stock Items</div>
                    <div class="admin-stat-value">{low_stock}</div>
                    <div class="admin-stat-note">Need attention</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card4:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-violet">
                    <div class="admin-stat-icon">🧾</div>
                    <div class="admin-stat-label">Activity</div>
                    <div class="admin-stat-value">{total_transactions}</div>
                    <div class="admin-stat-note">{activity_note}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card5:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-emerald">
                    <div class="admin-stat-icon">👥</div>
                    <div class="admin-stat-label">{users_label}</div>
                    <div class="admin-stat-value">{total_users}</div>
                    <div class="admin-stat-note">{users_note}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown(
            f"""
            <div class="dashboard-section-title">Reports & Analytics</div>
            <div class="content-panel" style="margin-bottom: 0.9rem;">
                <div class="dashboard-card-label">Operational insight</div>
                <div class="dashboard-card-note">Monitor {dashboard_scope} trends, item movement, recent activity, and low-stock risk from one dashboard.</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        report_col1, report_col2 = st.columns([1.35, 0.85])

        with report_col1:
            usage_overview_html = '<div class="analytics-empty">No transaction data available yet.</div>'

            if not usage_trans_df.empty:
                usage_chart_df = usage_trans_df.copy()
                usage_chart_df["transaction_date"] = pd.to_datetime(
                    usage_chart_df["transaction_time"],
                    errors="coerce"
                ).dt.normalize()
                usage_chart_df = usage_chart_df.dropna(subset=["transaction_date"])

                if not usage_chart_df.empty:
                    usage_by_date = usage_chart_df.groupby("transaction_date")[
                        "quantity_used"
                    ].sum().clip(lower=0).sort_index().tail(7)
                    max_usage = max(int(usage_by_date.max()), 1)
                    y_axis_values = [max_usage, round(max_usage * 0.67), round(max_usage * 0.33), 0]
                    y_axis_html = "".join(
                        f'<div>{value}</div>'
                        for value in y_axis_values
                    )
                    usage_rows = []

                    for transaction_date, quantity_used in usage_by_date.items():
                        date_label = transaction_date.strftime("%b %d")
                        percent = min(int((int(quantity_used) / max_usage) * 100), 100)
                        usage_rows.append(
                            f'<div class="analytics-bar-item">'
                            f'<div class="analytics-bar-value">{int(quantity_used)}</div>'
                            f'<div class="analytics-bar-track">'
                            f'<div class="analytics-bar-fill" style="height: {percent}%"></div>'
                            f'</div>'
                            f'<div class="analytics-bar-label">{date_label}</div>'
                            f'</div>'
                        )

                    usage_overview_html = (
                        f'<div class="analytics-bar-chart">'
                        f'<div class="analytics-y-axis">{y_axis_html}</div>'
                        f'<div class="analytics-plot">{"".join(usage_rows)}</div>'
                        f'</div>'
                    )

            st.html(
                f'<div class="analytics-card">'
                f'<div class="analytics-card-header">'
                f'<div class="admin-panel-title">Usage Overview</div>'
                f'<div class="analytics-badge">Last activity</div>'
                f'</div>'
                f'{usage_overview_html}'
                f'</div>'
            )

        with report_col2:
            usage_by_item_html = '<div class="analytics-empty">No item usage yet.</div>'

            if not usage_trans_df.empty:
                usage_by_item_df = usage_trans_df.groupby("item_code")[
                    "quantity_used"
                ].sum().clip(lower=0)
                usage_by_item_df = usage_by_item_df[
                    usage_by_item_df > 0
                ].sort_values(ascending=False).head(6)

                if not usage_by_item_df.empty:
                    donut_colors = ["#2563eb", "#06b6d4", "#7c3aed", "#f59e0b", "#059669", "#ef4444"]
                    total_item_usage = max(int(usage_by_item_df.sum()), 1)
                    current_percent = 0
                    donut_segments = []
                    legend_rows = []

                    for index, (item_code, quantity_used) in enumerate(usage_by_item_df.items()):
                        item_percent = round((int(quantity_used) / total_item_usage) * 100, 1)
                        next_percent = current_percent + item_percent
                        color = donut_colors[index % len(donut_colors)]
                        item_code_safe = safe_html(item_code)
                        donut_segments.append(f"{color} {current_percent}% {next_percent}%")
                        legend_rows.append(
                            f'<div class="donut-legend-row">'
                            f'<span class="donut-dot" style="background: {color};"></span>'
                            f'<span>{item_code_safe}</span>'
                            f'<span class="donut-percent">{item_percent}%</span>'
                            f'</div>'
                        )
                        current_percent = next_percent

                    usage_by_item_html = (
                        f'<div class="donut-layout">'
                        f'<div class="donut-chart" style="background: conic-gradient({", ".join(donut_segments)});"></div>'
                        f'<div class="donut-legend">{"".join(legend_rows)}</div>'
                        f'</div>'
                    )

            st.html(
                f'<div class="analytics-card">'
                f'<div class="analytics-card-header">'
                f'<div class="admin-panel-title">Usage by Item</div>'
                f'<div class="analytics-badge">Top items</div>'
                f'</div>'
                f'{usage_by_item_html}'
                f'</div>'
            )

        detail_col1, detail_col2, detail_col3 = st.columns([1.05, 1.05, 1.1])

        with detail_col1:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Low Stock Items</div>', unsafe_allow_html=True)

                if inventory_df.empty:
                    st.info("No inventory records are available for this view yet.")
                else:
                    low_stock_df = inventory_df[inventory_df["quantity"] <= 5][
                        ["item_code", "item_name", "quantity"]
                    ].sort_values("quantity")

                    if low_stock_df.empty:
                        st.success("All visible items are above the low-stock threshold.")
                    else:
                        st.dataframe(low_stock_df, width="stretch", hide_index=True)

        with detail_col2:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Recent Transactions</div>', unsafe_allow_html=True)

                if trans_df.empty:
                    st.info("No operational activity has been recorded for this view yet.")
                else:
                    recent_transaction_columns = ["item_code", "quantity_used", "transaction_time"]
                    if is_super_admin():
                        recent_transaction_columns.insert(0, "username")
                    recent_trans_df = trans_df.copy()
                    recent_trans_df["_sort_time"] = pd.to_datetime(
                        recent_trans_df["transaction_time"], errors="coerce"
                    )
                    recent_trans_df = recent_trans_df.sort_values(
                        ["_sort_time", "id"], ascending=[False, False], na_position="last"
                    ).head(5)[recent_transaction_columns]
                    st.dataframe(recent_trans_df, width="stretch", hide_index=True)

        with detail_col3:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Inventory Status</div>', unsafe_allow_html=True)

                if inventory_df.empty:
                    st.info("No inventory records are available for this view yet.")
                else:
                    max_quantity = max(int(inventory_df["quantity"].max()), 1)
                    status_rows = []

                    for _, row in inventory_df.sort_values("quantity").head(5).iterrows():
                        quantity = int(row["quantity"])
                        percent = min(int((quantity / max_quantity) * 100), 100)
                        progress_class = "empty" if quantity == 0 else "low" if quantity <= 5 else ""
                        status = "Out of Stock" if quantity == 0 else "Low Stock" if quantity <= 5 else "In Stock"
                        item_name_safe = safe_html(row["item_name"])
                        item_code_safe = safe_html(row["item_code"])

                        status_rows.append(
                            f"""
                            <div class="admin-status-row">
                                <div>
                                    <div class="admin-status-name">{item_name_safe}</div>
                                    <div class="admin-status-meta">{item_code_safe} · {status}</div>
                                    <div class="admin-progress">
                                        <div class="admin-progress-fill {progress_class}" style="width: {percent}%"></div>
                                    </div>
                                </div>
                                <div class="admin-status-qty">{quantity}</div>
                            </div>
                            """
                        )

                    st.markdown("".join(status_rows), unsafe_allow_html=True)

        most_used_item = (
            usage_trans_df.groupby("item_code")["quantity_used"].sum().idxmax()
            if not usage_trans_df.empty else "No sales yet"
        )
        most_used_item_safe = safe_html(most_used_item)

        st.markdown(
            f"""
            <div class="admin-panel" style="margin-top: 1rem;">
                <div class="admin-panel-title">Analytics Summary</div>
                <div class="preview-list">
                    <div class="preview-row">
                        <div class="preview-label">Total Quantity Used</div>
                        <div class="preview-value">{total_used}</div>
                    </div>
                    <div class="preview-row">
                        <div class="preview-label">Most Used Item</div>
                        <div class="preview-value">{most_used_item_safe}</div>
                    </div>
                    <div class="preview-row">
                        <div class="preview-label">Inventory Health</div>
                        <div class="preview-value">{
                            "Needs attention" if low_stock else "Healthy"
                        }</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )


    if menu == "Location Inventory" and has_admin_access():
        conn = get_connection()
        locations_df = pd.read_sql_query("SELECT id, name FROM locations WHERE active=1 ORDER BY name", conn)
        admin_users_df = pd.read_sql_query(
            "SELECT username FROM users WHERE role='admin' ORDER BY username",
            conn
        )
        inventory_df = pd.read_sql_query(
            "SELECT item_code, item_name, description, quantity, cost FROM inventory ORDER BY item_name",
            conn
        )
        location_stock_df = pd.read_sql_query(
            '''
            SELECT MIN(li.id) AS id, li.location_id, l.name AS location, li.item_code,
                   i.item_name, COALESCE(SUM(li.quantity), 0) AS quantity,
                   COALESCE(lp.price, 0) AS price
            FROM location_inventory li
            LEFT JOIN locations l ON li.location_id = l.id
            LEFT JOIN inventory i ON LOWER(li.item_code)=LOWER(i.item_code)
            LEFT JOIN location_prices lp
                ON lp.location_id=li.location_id AND LOWER(lp.item_code)=LOWER(li.item_code)
            GROUP BY li.location_id, l.name, li.item_code, i.item_name, lp.price
            UNION ALL
            SELECT -lp.id AS id,lp.location_id,l.name AS location,lp.item_code,
                   i.item_name,0 AS quantity,lp.price
            FROM location_prices lp
            LEFT JOIN locations l ON l.id=lp.location_id
            LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(lp.item_code)
            WHERE NOT EXISTS (
                SELECT 1 FROM location_inventory li
                WHERE li.location_id=lp.location_id
                  AND LOWER(li.item_code)=LOWER(lp.item_code)
            )
            ORDER BY location,item_name
            ''',
            conn
        )
        conn.close()

        all_location_stock_df = location_stock_df.copy()
        assigned_location_ids = get_assigned_location_ids()
        if not is_super_admin():
            supplied_item_codes = set(get_supplied_item_codes())
            locations_df = locations_df[locations_df["id"].isin(assigned_location_ids)].copy()
            inventory_df = inventory_df[inventory_df["item_code"].isin(supplied_item_codes)].copy()
            location_stock_df = location_stock_df[
                location_stock_df["location_id"].isin(assigned_location_ids)
            ].copy()
            location_stock_df = location_stock_df[
                location_stock_df["item_code"].isin(supplied_item_codes)
            ].copy()

        st.markdown(
            f"""
            <div class="page-header">
                <div class="page-eyebrow">Owner Inventory</div>
                <div class="page-title">Location Inventory</div>
                <p class="page-subtitle">Manage item quantities and pricing for each storage location.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        stock_page_mode = "Set Stock / Price"
        stock_form_title = "Set Location Stock / Price"
        if "location_stock_form_reset_counter" not in st.session_state:
            st.session_state.location_stock_form_reset_counter = 0
        if is_super_admin():
            if "ruth_stock_page_mode" not in st.session_state:
                st.session_state.ruth_stock_page_mode = "Set Stock / Price"

            stock_nav_cols = st.columns(3)
            stock_nav_options = [
                ("Set Stock / Price", "Set Stock / Price"),
                ("View Stock", "View Stock"),
                ("Edit / Update Stock", "Edit / Update Stock"),
            ]
            for stock_nav_col, (button_label, mode_value) in zip(stock_nav_cols, stock_nav_options):
                with stock_nav_col:
                    if st.button(
                        button_label,
                        type="primary" if st.session_state.ruth_stock_page_mode == mode_value else "secondary",
                        width="stretch",
                        key=f"ruth_stock_nav_{mode_value}"
                    ):
                        st.session_state.ruth_stock_page_mode = mode_value
                        st.rerun()

            stock_page_mode = st.session_state.ruth_stock_page_mode
            stock_form_title = (
                "Edit / Update Location Stock"
                if stock_page_mode == "Edit / Update Stock"
                else "Set Location Stock / Price"
            )

            if stock_page_mode == "View Stock":
                render_location_stock_table(location_stock_df, inventory_df, "_ruth_view")
                st.stop()

        if not is_super_admin():
            if "admin_stock_page_mode" not in st.session_state:
                st.session_state.admin_stock_page_mode = "Set Stock / Price"
            admin_stock_nav_cols = st.columns(2)
            for nav_col, (button_label, mode_value) in zip(
                admin_stock_nav_cols,
                [
                    ("Set Stock / Price", "Set Stock / Price"),
                    ("View Stock", "View Stock"),
                ]
            ):
                with nav_col:
                    if st.button(
                        button_label,
                        type=(
                            "primary"
                            if st.session_state.admin_stock_page_mode == mode_value
                            else "secondary"
                        ),
                        width="stretch",
                        key=f"admin_stock_nav_{mode_value}"
                    ):
                        st.session_state.admin_stock_page_mode = mode_value
                        st.rerun()
            stock_page_mode = st.session_state.admin_stock_page_mode
            if stock_page_mode == "View Stock":
                render_location_stock_table(location_stock_df, inventory_df, "_admin_view")
                st.stop()

        if is_super_admin():
            stock_form_col = st.container()
            stock_table_col = None
        else:
            stock_form_col = st.container()
            stock_table_col = None

        with stock_form_col:
            st.markdown(f'<div class="dashboard-section-title">{stock_form_title}</div>', unsafe_allow_html=True)

            if locations_df.empty or inventory_df.empty:
                if not is_super_admin() and locations_df.empty:
                    show_next_step(
                        "No active locations are available for your account.",
                        "Ruth should open Locations and assign your account to an active location."
                    )
                elif not is_super_admin() and inventory_df.empty:
                    show_next_step(
                        "No supplied products are assigned to your account.",
                        "Ruth should open Users & Access and assign supplied products to your admin account."
                    )
                elif locations_df.empty:
                    show_next_step(
                        "No active locations exist yet.",
                        "Create an active location before setting stock and selling price."
                    )
                else:
                    show_next_step(
                        "No inventory items exist yet.",
                        "Create inventory items before setting location stock and selling price."
                    )
            else:
                stock_locations_for_options = locations_df.copy()
                stock_inventory_for_options = inventory_df.copy()

                if is_super_admin() and stock_page_mode == "Edit / Update Stock":
                    stock_edit_search = st.text_input(
                        "Search Item or Location",
                        placeholder="Search by item name, item code, description, or location",
                        key="ruth_stock_edit_search"
                    ).strip().lower()

                    if stock_edit_search:
                        item_search_mask = (
                            stock_inventory_for_options["item_code"].astype(str).str.lower().str.contains(stock_edit_search, na=False)
                            | stock_inventory_for_options["item_name"].astype(str).str.lower().str.contains(stock_edit_search, na=False)
                            | stock_inventory_for_options["description"].astype(str).str.lower().str.contains(stock_edit_search, na=False)
                        )
                        location_search_mask = (
                            stock_locations_for_options["name"].astype(str).str.lower().str.contains(stock_edit_search, na=False)
                        )

                        if item_search_mask.any():
                            stock_inventory_for_options = stock_inventory_for_options[item_search_mask].copy()
                        if location_search_mask.any():
                            stock_locations_for_options = stock_locations_for_options[location_search_mask].copy()
                        if not item_search_mask.any() and not location_search_mask.any():
                            st.info("No matching item or location found for that search.")

                location_options = {
                    f"{row['name']} (ID {row['id']})": int(row["id"])
                    for _, row in stock_locations_for_options.iterrows()
                }
                item_options = {
                    f"{row['item_name']} ({row['item_code']})": row["item_code"]
                    for _, row in stock_inventory_for_options.iterrows()
                }

                if not location_options or not item_options:
                    show_next_step(
                        "No stock setup options match the current search.",
                        "Clear or change the search text to select a location and item."
                    )
                    st.stop()

                selected_location = st.selectbox(
                    "Location",
                    list(location_options.keys()),
                    key="location_inventory_location_selector"
                )
                selected_item = st.selectbox(
                    "Inventory Item",
                    list(item_options.keys()),
                    key="location_inventory_item_selector"
                )
                location_id = location_options[selected_location]
                item_code = item_options[selected_item]
                selected_inventory_rows = inventory_df[inventory_df["item_code"] == item_code]
                selected_purchase_cost = (
                    float(selected_inventory_rows.iloc[0]["cost"])
                    if not selected_inventory_rows.empty
                    and pd.notna(selected_inventory_rows.iloc[0]["cost"])
                    else 0.0
                )
                selected_base_quantity = (
                    int(selected_inventory_rows.iloc[0]["quantity"])
                    if not selected_inventory_rows.empty
                    and pd.notna(selected_inventory_rows.iloc[0]["quantity"])
                    else 0
                )
                visible_item_stock_rows = location_stock_df[
                    location_stock_df["item_code"] == item_code
                ]
                all_item_stock_rows = all_location_stock_df[
                    all_location_stock_df["item_code"] == item_code
                ]
                current_stock_rows = location_stock_df[
                    (location_stock_df["location_id"] == location_id)
                    & (location_stock_df["item_code"] == item_code)
                ]
                current_location_quantity = (
                    int(current_stock_rows.iloc[0]["quantity"])
                    if not current_stock_rows.empty and pd.notna(current_stock_rows.iloc[0]["quantity"])
                    else 0
                )
                conn = get_connection()
                c = conn.cursor()
                physical_stock_metrics = get_location_physical_stock_metrics(
                    c, item_code, location_id
                )
                all_assigned_quantity = physical_stock_metrics["all_locations"]
                current_location_quantity = physical_stock_metrics["selected_location"]
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_product_allocations
                       WHERE LOWER(item_code)=LOWER(?)''',
                    (item_code,)
                )
                total_admin_assigned_quantity = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                       WHERE LOWER(item_code)=LOWER(?)''',
                    (item_code,)
                )
                total_admin_placed_quantity = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                       WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                    (location_id, item_code)
                )
                selected_location_admin_quantity = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM user_inventory
                       WHERE LOWER(item_code)=LOWER(?)''',
                    (item_code,)
                )
                total_personal_user_quantity = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM returns
                       WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                         AND condition_status<>'customer_return' ''',
                    (item_code,)
                )
                total_written_off_quantity = int(c.fetchone()[0] or 0)
                c.execute(
                    '''SELECT COALESCE(SUM(quantity),0) FROM returns
                       WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                         AND condition_status<>'customer_return'
                         AND COALESCE(affected_owner_username,'')<>'' ''',
                    (item_code,)
                )
                total_owner_written_off_quantity = int(c.fetchone()[0] or 0)
                total_net_sold_quantity = get_net_sold_quantity(c, item_code)
                c.execute(
                    '''SELECT DISTINCT username FROM admin_product_allocations
                       WHERE LOWER(item_code)=LOWER(?)''',
                    (item_code,)
                )
                allocation_owners = [row[0] for row in c.fetchall()]
                total_owner_net_sold_quantity = sum(
                    get_net_sold_quantity(c, item_code, owner) for owner in allocation_owners
                )
                c.execute(
                    '''
                    SELECT DISTINCT u.username, u.role
                    FROM users u
                    INNER JOIN user_locations ul
                        ON LOWER(ul.username)=LOWER(u.username) AND ul.location_id=?
                    WHERE u.role IN ('admin','sales')
                      AND EXISTS (
                          SELECT 1 FROM product_suppliers ps
                          WHERE LOWER(ps.username)=LOWER(u.username)
                            AND LOWER(ps.item_code)=LOWER(?)
                      )
                    ORDER BY u.role, u.username
                    ''',
                    (location_id, item_code)
                )
                assigned_user_rows = c.fetchall()
                conn.close()
                price_conn = get_connection()
                current_price_row = price_conn.execute(
                    '''SELECT COALESCE(price,0) FROM location_prices
                       WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                    (location_id, item_code),
                ).fetchone()
                price_conn.close()
                current_location_price = float(current_price_row[0] or 0) if current_price_row else 0.0
                reservation_conn = get_connection()
                admin_reserved_remaining = get_total_reserved_assignment(
                    reservation_conn.cursor(), item_code
                )
                reservation_conn.close()
                unassigned_quantity = max(
                    selected_base_quantity
                    - all_assigned_quantity
                    - total_personal_user_quantity
                    - admin_reserved_remaining
                    - total_written_off_quantity
                    - total_net_sold_quantity,
                    0
                )
                admin_assigned_quantity = (
                    get_assigned_product_quantity(st.session_state.username, item_code)
                    if not is_super_admin()
                    else 0
                )
                selected_access_username = ""
                selected_access_role = ""
                selected_user_assigned_quantity = 0
                selected_user_placed_quantity = 0
                selected_user_location_quantity = 0
                selected_user_written_off_quantity = 0
                selected_user_net_sold_quantity = 0
                selected_user_reserved_remaining = 0
                if is_super_admin():
                    assigned_user_options = {
                        "Unowned company stock": ("", ""),
                        **{
                            f"{username} ({role.title()})": (username, role)
                            for username, role in assigned_user_rows
                        },
                    }
                    selected_access_label = st.selectbox(
                        "Assigned Admin or Sales User",
                        list(assigned_user_options.keys()),
                        key=f"stock_assigned_user_{location_id}_{item_code}"
                    )
                    selected_access_username, selected_access_role = assigned_user_options[selected_access_label]
                    conn = get_connection()
                    if selected_access_role in {"admin", "sales"}:
                        selected_user_assigned_quantity = int(
                            conn.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_product_allocations
                                   WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                (selected_access_username, item_code)
                            ).fetchone()[0] or 0
                        )
                        selected_user_placed_quantity = int(
                            conn.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                (selected_access_username, item_code)
                            ).fetchone()[0] or 0
                        )
                        selected_user_location_quantity = int(
                            conn.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE LOWER(username)=LOWER(?) AND location_id=?
                                     AND LOWER(item_code)=LOWER(?)''',
                                (selected_access_username, location_id, item_code)
                            ).fetchone()[0] or 0
                        )
                        selected_user_written_off_quantity = int(
                            conn.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM returns
                                   WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                     AND condition_status<>'customer_return'
                                     AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                                         =LOWER(?)''',
                                (item_code, selected_access_username)
                            ).fetchone()[0] or 0
                        )
                        selected_user_net_sold_quantity = get_net_sold_quantity(
                            conn.cursor(), item_code, selected_access_username
                        )
                        selected_user_reserved_remaining = calculate_remaining_assignment(
                            selected_user_assigned_quantity,
                            selected_user_placed_quantity,
                            selected_user_written_off_quantity,
                            selected_user_net_sold_quantity,
                        )
                    conn.close()
                if selected_access_role in {"admin", "sales"}:
                    selected_user_assignment_note = (
                        f"{safe_html(selected_access_username)} · {selected_access_role.title()}; "
                        f"{selected_user_placed_quantity} placed total, "
                        f"{selected_user_location_quantity} here, "
                        f"{selected_user_written_off_quantity} written off, "
                        f"{selected_user_net_sold_quantity} sold, "
                        f"{selected_user_reserved_remaining} reserved"
                    )
                else:
                    selected_user_assignment_note = "No assigned user for this location and product"
                admin_added_quantity = 0
                current_admin_location_quantity = 0
                admin_written_off_quantity = 0
                admin_net_sold_quantity = 0
                if not is_super_admin():
                    conn = get_connection()
                    admin_stock_history_totals = pd.read_sql_query(
                        '''
                        SELECT COALESCE(SUM(h.quantity), 0) AS admin_added
                        FROM admin_location_stock h
                        WHERE LOWER(h.username)=LOWER(?) AND LOWER(h.item_code)=LOWER(?)
                        ''',
                        conn,
                        params=(
                            st.session_state.username,
                            item_code,
                        )
                    )
                    if not admin_stock_history_totals.empty:
                        admin_added_quantity = int(admin_stock_history_totals.iloc[0]["admin_added"] or 0)
                    current_admin_location_quantity = int(
                        conn.execute(
                            '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                               WHERE LOWER(username)=LOWER(?) AND location_id=?
                                 AND LOWER(item_code)=LOWER(?)''',
                            (st.session_state.username, location_id, item_code)
                        ).fetchone()[0] or 0
                    )
                    admin_written_off_quantity = int(
                        conn.execute(
                            '''SELECT COALESCE(SUM(quantity),0) FROM returns
                               WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                 AND condition_status<>'customer_return'
                                 AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                                     =LOWER(?)''',
                            (item_code, st.session_state.username)
                        ).fetchone()[0] or 0
                    )
                    admin_net_sold_quantity = get_net_sold_quantity(
                        conn.cursor(), item_code, st.session_state.username
                    )
                    conn.close()
                stock_mode_key = (
                    stock_page_mode.lower().replace(" ", "_").replace("/", "_")
                    if is_super_admin()
                    else "admin_add"
                )
                form_reset_counter = st.session_state.location_stock_form_reset_counter
                location_quantity_key = (
                    f"location_quantity_{stock_mode_key}_{location_id}_{item_code}_{form_reset_counter}"
                )
                if is_super_admin():
                    assigned_elsewhere_quantity = max(all_assigned_quantity - current_location_quantity, 0)
                    if selected_access_role in {"admin", "sales"}:
                        selected_location_unowned_quantity = max(
                            current_location_quantity - selected_location_admin_quantity, 0
                        )
                        unowned_company_stock_elsewhere = max(
                            all_assigned_quantity
                            - total_admin_placed_quantity
                            - selected_location_unowned_quantity,
                            0
                        )
                        selected_admin_capacity = calculate_admin_location_capacity(
                            selected_base_quantity,
                            all_assigned_quantity,
                            current_location_quantity,
                            selected_location_admin_quantity,
                            selected_user_reserved_remaining,
                            unowned_company_stock_elsewhere,
                            total_personal_user_quantity,
                            total_written_off_quantity,
                            total_net_sold_quantity,
                        )
                        max_for_selected_location = selected_admin_capacity["available"]
                    else:
                        selected_admin_capacity = None
                        max_for_selected_location = unassigned_quantity
                    location_quantity_label = (
                        "Quantity To Assign"
                        if selected_access_role in {"admin", "sales"} else "Quantity To Add"
                    )
                    location_quantity_value = 0
                    quantity_limit_note = (
                        f"This location currently has {current_location_quantity}. "
                        f"You can add up to {max_for_selected_location} more"
                        + (
                            f" from {selected_access_username}'s reserved assignment."
                            if selected_access_role in {"admin", "sales"}
                            else "."
                        )
                    )
                else:
                    admin_available_from_assignment = calculate_remaining_assignment(
                        admin_assigned_quantity,
                        admin_added_quantity,
                        admin_written_off_quantity,
                        admin_net_sold_quantity,
                    )
                    admin_location_unowned_quantity = max(
                        current_location_quantity - selected_location_admin_quantity, 0
                    )
                    admin_unowned_company_stock_elsewhere = max(
                        all_assigned_quantity
                        - total_admin_placed_quantity
                        - admin_location_unowned_quantity,
                        0
                    )
                    admin_capacity = calculate_admin_location_capacity(
                        selected_base_quantity,
                        all_assigned_quantity,
                        current_location_quantity,
                        selected_location_admin_quantity,
                        admin_available_from_assignment,
                        admin_unowned_company_stock_elsewhere,
                        total_personal_user_quantity,
                        total_written_off_quantity,
                        total_net_sold_quantity,
                    )
                    max_for_selected_location = admin_capacity["available"]
                    location_quantity_label = "Quantity To Add"
                    location_quantity_value = 0
                    location_quantity_help = (
                        "Enter only the new quantity to add to the selected location."
                    )

                    admin_qty_col1, admin_qty_col2, admin_qty_col3, admin_qty_col4, admin_qty_col5, admin_qty_col6 = st.columns(6)
                    with admin_qty_col1:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">Assigned To You</div>
                                <div class="dashboard-card-value">{admin_assigned_quantity}</div>
                                <div class="dashboard-card-note">Total quantity available for your admin account</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with admin_qty_col2:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">Added By You</div>
                                <div class="dashboard-card-value">{admin_added_quantity}</div>
                                <div class="dashboard-card-note">Current stock you own across assigned locations</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with admin_qty_col3:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">Your Available Assignment</div>
                                <div class="dashboard-card-value">{max_for_selected_location}</div>
                                <div class="dashboard-card-note">Usable now; {admin_available_from_assignment} reservation remaining before company-stock limits</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with admin_qty_col4:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">Written Off / Damaged</div>
                                <div class="dashboard-card-value">{admin_written_off_quantity}</div>
                                <div class="dashboard-card-note">Permanent item loss charged to your assignment</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with admin_qty_col5:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">Net Sold</div>
                                <div class="dashboard-card-value">{admin_net_sold_quantity}</div>
                                <div class="dashboard-card-note">Sold units minus completed customer returns</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with admin_qty_col6:
                        st.markdown(
                            f"""
                            <div class="dashboard-card">
                                <div class="dashboard-card-label">My Quantity Here</div>
                                <div class="dashboard-card-value">{current_admin_location_quantity}</div>
                                <div class="dashboard-card-note">Your owned quantity at this selected location</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    if admin_assigned_quantity <= 0:
                        st.warning(
                            "This product is assigned to your admin account, but no quantity has been assigned to you yet. "
                            "Super Admin needs to assign a quantity before you can add stock to a location."
                        )
                    elif max_for_selected_location < admin_available_from_assignment:
                        st.info(
                            f"Your remaining reservation is {admin_available_from_assignment}, but only "
                            f"{max_for_selected_location} unit(s) are currently available to add after "
                            "physical stock, user stock, and permanent write-offs are considered."
                        )
                    elif admin_added_quantity + admin_written_off_quantity + admin_net_sold_quantity > admin_assigned_quantity:
                        st.warning(
                            "You already added more quantity than Super Admin assigned to your admin account. "
                            f"Assigned To You is {admin_assigned_quantity}, Added By You is {admin_added_quantity}, "
                            f"Written Off is {admin_written_off_quantity}, and Net Sold is {admin_net_sold_quantity}. "
                            "Super Admin should increase Assigned Quantity before more stock can be added."
                        )

                # Keep stock and price controls outside a form so Streamlit reruns on
                # every edit and both Admin and Super Admin previews stay live.
                with st.container(border=True):
                    location_quantity = st.number_input(
                        location_quantity_label,
                        min_value=0,
                        step=1,
                        value=location_quantity_value,
                        help=None if is_super_admin() else location_quantity_help,
                        key=location_quantity_key
                    )
                    if is_super_admin():
                        ownership_from_existing_preview = (
                            min(int(location_quantity), selected_admin_capacity["unowned_at_location"])
                            if selected_access_role in {"admin", "sales"} and selected_admin_capacity
                            else 0
                        )
                        physical_add_preview = int(location_quantity) - ownership_from_existing_preview
                        relocation_from_elsewhere_preview = (
                            min(physical_add_preview, selected_admin_capacity["unowned_elsewhere"])
                            if selected_access_role in {"admin", "sales"} and selected_admin_capacity
                            else 0
                        )
                        selected_location_after_save = current_location_quantity + physical_add_preview
                        total_in_locations_after_save = (
                            all_assigned_quantity + physical_add_preview - relocation_from_elsewhere_preview
                        )
                        quantity_to_add_is_valid = int(location_quantity) <= max_for_selected_location
                        ruth_card_values = [
                            (
                                "Base Item Quantity",
                                selected_base_quantity,
                                "Total quantity created for this item",
                            ),
                            (
                                "Physical Stock — All Locations",
                                all_assigned_quantity,
                                "Actual saved stock across every location",
                            ),
                            (
                                "Physical Stock — Selected Location",
                                current_location_quantity,
                                f"Actual saved stock; {selected_location_admin_quantity} owned by assigned users here",
                            ),
                            (
                                "Selected User Assignment",
                                selected_user_assigned_quantity,
                                selected_user_assignment_note,
                            ),
                            (
                                "Available To Add",
                                max_for_selected_location,
                                (
                                    f"{selected_user_reserved_remaining} remaining assignment; uses available company stock"
                                    if selected_access_role in {"admin", "sales"}
                                    else f"After location stock and {admin_reserved_remaining} user-reserved units"
                                ),
                            ),
                        ]
                        ruth_card_cols = st.columns(5)
                        for ruth_card_col, (label, value, note) in zip(ruth_card_cols, ruth_card_values):
                            with ruth_card_col:
                                st.markdown(
                                    f'''<div class="dashboard-card">
                                        <div class="dashboard-card-label">{label}</div>
                                        <div class="dashboard-card-value">{value}</div>
                                        <div class="dashboard-card-note">{note}</div>
                                    </div>''',
                                    unsafe_allow_html=True,
                                )
                        if quantity_to_add_is_valid:
                            st.caption(
                                f"{quantity_limit_note} After save, this location will show "
                                f"{selected_location_after_save}, and total in all locations will be "
                                f"{total_in_locations_after_save}. "
                                + (
                                    f"{ownership_from_existing_preview} unit(s) will be assigned from existing location stock."
                                    if ownership_from_existing_preview > 0 else ""
                                )
                            )
                        else:
                            st.warning(
                                f"You entered {int(location_quantity)}, but only {max_for_selected_location} is available to add. "
                                f"Current selected location stock will stay {current_location_quantity}."
                            )
                    else:
                        admin_ownership_from_existing_preview = min(
                            int(location_quantity), admin_capacity["unowned_at_location"]
                        )
                        admin_physical_add_preview = (
                            int(location_quantity) - admin_ownership_from_existing_preview
                        )
                        new_location_quantity_preview = (
                            current_location_quantity + admin_physical_add_preview
                        )
                        new_admin_location_quantity_preview = (
                            current_admin_location_quantity + int(location_quantity)
                        )
                        exceeds_admin_assignment = (
                            int(location_quantity) > max_for_selected_location
                        )
                        if exceeds_admin_assignment:
                            st.warning(
                                f"You entered {int(location_quantity)}, but only "
                                f"{max_for_selected_location} is available from your assignment and company stock."
                            )
                        elif int(location_quantity) <= max_for_selected_location:
                            st.caption(
                                f"Your quantity at this location is {current_admin_location_quantity}. "
                                f"You can add up to "
                                f"{max_for_selected_location} from your remaining assignment. "
                                f"After save, your quantity here will be "
                                f"{new_admin_location_quantity_preview}."
                            )
                        else:
                            st.warning(
                                f"You entered {int(location_quantity)}, but your remaining Users & Access "
                                f"assignment is {admin_available_from_assignment}. Ask Super Admin to increase "
                                "your Assigned Quantity before adding more stock."
                            )
                    location_price_text = st.text_input(
                        "Selling Price",
                        value=f"{current_location_price:.2f}" if current_location_price > 0 else "",
                        placeholder=(
                            f"Must be greater than purchase cost ${selected_purchase_cost:,.2f}"
                            if is_super_admin()
                            else "Enter selling price"
                        ),
                        key=f"location_price_{location_id}_{item_code}_{form_reset_counter}"
                    )
                    if is_super_admin():
                        st.caption(
                            f"Selling Price is separate from Single Cost / Purchase Cost. "
                            f"Purchase cost for this item is ${selected_purchase_cost:,.2f}."
                        )
                    cleaned_price_preview = location_price_text.strip()
                    try:
                        live_price_preview = float(cleaned_price_preview) if cleaned_price_preview else 0.0
                        live_price_is_numeric = math.isfinite(live_price_preview)
                    except (TypeError, ValueError):
                        live_price_preview = 0.0
                        live_price_is_numeric = False
                    live_stock_now = (
                        current_location_quantity
                        if is_super_admin()
                        else current_admin_location_quantity
                    )
                    live_stock_after = (
                        selected_location_after_save
                        if is_super_admin()
                        else new_admin_location_quantity_preview
                    )
                    live_available_after = max(
                        max_for_selected_location - int(location_quantity), 0
                    )
                    live_preview_cols = st.columns(4)
                    live_preview_cols[0].metric(
                        "Physical Stock Now" if is_super_admin() else "My Quantity Now",
                        live_stock_now
                    )
                    live_preview_cols[1].metric(
                        "Stock After Save" if is_super_admin() else "My Quantity After Save",
                        live_stock_after
                    )
                    live_preview_cols[2].metric("Available After Save", live_available_after)
                    live_preview_cols[3].metric(
                        "Selling Price After Save",
                        f"${live_price_preview:,.2f}" if live_price_is_numeric else "Invalid"
                    )
                    if not live_price_is_numeric:
                        st.error("Selling Price must be a valid number.")
                    elif cleaned_price_preview and live_price_preview <= selected_purchase_cost:
                        st.warning(
                            f"Selling Price must be greater than purchase cost (${selected_purchase_cost:,.2f})."
                        )
                    save_location_stock = st.button(
                        "Save Stock / Price",
                        type="primary",
                        width="stretch",
                        key=f"save_location_stock_{location_id}_{item_code}_{form_reset_counter}"
                    )

                if save_location_stock:
                    cleaned_location_price = location_price_text.strip()

                    if not cleaned_location_price:
                        st.error("Selling Price is required before saving stock and pricing.")
                        st.stop()

                    try:
                        parsed_location_price = validate_location_selling_price(
                            cleaned_location_price, selected_purchase_cost
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                        st.stop()

                    if (
                        is_super_admin()
                        and int(location_quantity) > max_for_selected_location
                    ):
                        st.error(
                            "Quantity To Add cannot be greater than the available unassigned quantity. "
                            f"Available to add is {max_for_selected_location}."
                        )
                        st.stop()

                    if (
                        not is_super_admin()
                        and int(location_quantity) > max_for_selected_location
                    ):
                        required_admin_assignment = (
                            admin_added_quantity + admin_written_off_quantity + int(location_quantity)
                        )
                        st.error(
                            "Quantity To Add cannot be greater than the quantity assigned to you in Users & Access. "
                            f"Assigned to you: {admin_assigned_quantity}; added by you: "
                            f"{admin_added_quantity}; written off: {admin_written_off_quantity}; "
                            f"your available assignment: "
                            f"{max_for_selected_location}. "
                            f"Ask Super Admin to increase Assigned Quantity to at least {required_admin_assignment}."
                        )
                        st.stop()

                    conn = get_connection()
                    c = conn.cursor()
                    try:
                        c.execute("BEGIN IMMEDIATE")
                        quantity_set = int(location_quantity)
                        c.execute(
                            "SELECT COALESCE(quantity, 0),COALESCE(cost,0) FROM inventory WHERE LOWER(item_code)=LOWER(?)",
                            (item_code,)
                        )
                        locked_base_row = c.fetchone()
                        if not locked_base_row:
                            raise ValueError("The selected inventory item no longer exists.")
                        locked_base_quantity = int(locked_base_row[0] or 0)
                        parsed_location_price = validate_location_selling_price(
                            parsed_location_price, locked_base_row[1]
                        )
                        c.execute(
                            "SELECT COALESCE(SUM(quantity), 0) FROM location_inventory WHERE LOWER(item_code)=LOWER(?)",
                            (item_code,)
                        )
                        locked_location_total = int(c.fetchone()[0] or 0)
                        c.execute(
                            "SELECT COALESCE(SUM(quantity),0) FROM admin_product_allocations WHERE LOWER(item_code)=LOWER(?)",
                            (item_code,)
                        )
                        locked_admin_assigned_total = int(c.fetchone()[0] or 0)
                        c.execute(
                            "SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock WHERE LOWER(item_code)=LOWER(?)",
                            (item_code,)
                        )
                        locked_admin_placed_total = int(c.fetchone()[0] or 0)
                        c.execute(
                            "SELECT COALESCE(SUM(quantity),0) FROM user_inventory WHERE LOWER(item_code)=LOWER(?)",
                            (item_code,)
                        )
                        locked_personal_user_total = int(c.fetchone()[0] or 0)
                        c.execute(
                            '''SELECT COALESCE(SUM(quantity),0) FROM returns
                               WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                 AND condition_status<>'customer_return' ''',
                            (item_code,)
                        )
                        locked_written_off_total = int(c.fetchone()[0] or 0)
                        c.execute(
                            '''SELECT COALESCE(SUM(quantity),0) FROM returns
                               WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                 AND condition_status<>'customer_return'
                                 AND COALESCE(affected_owner_username,'')<>'' ''',
                            (item_code,)
                        )
                        locked_owner_written_off_total = int(c.fetchone()[0] or 0)
                        locked_net_sold_total = get_net_sold_quantity(c, item_code)
                        c.execute(
                            '''SELECT DISTINCT username FROM admin_product_allocations
                               WHERE LOWER(item_code)=LOWER(?)''',
                            (item_code,)
                        )
                        locked_allocation_owners = [row[0] for row in c.fetchall()]
                        locked_owner_net_sold_total = sum(
                            get_net_sold_quantity(c, item_code, owner)
                            for owner in locked_allocation_owners
                        )
                        locked_admin_reserved = get_total_reserved_assignment(c, item_code)
                        locked_selected_user_remaining = 0
                        locked_ownership_from_existing = 0
                        if is_super_admin() and selected_access_role in {"admin", "sales"}:
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_product_allocations
                                   WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                (selected_access_username, item_code)
                            )
                            locked_selected_user_assigned = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                (selected_access_username, item_code)
                            )
                            locked_selected_user_placed = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM returns
                                   WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                     AND condition_status<>'customer_return'
                                     AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                                         =LOWER(?)''',
                                (item_code, selected_access_username)
                            )
                            locked_selected_user_written_off = int(c.fetchone()[0] or 0)
                            locked_selected_user_sold = get_net_sold_quantity(
                                c, item_code, selected_access_username
                            )
                            locked_selected_user_remaining = calculate_remaining_assignment(
                                locked_selected_user_assigned,
                                locked_selected_user_placed,
                                locked_selected_user_written_off,
                                locked_selected_user_sold,
                            )
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (location_id, item_code)
                            )
                            locked_location_admin_owned = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''SELECT COALESCE(quantity,0) FROM location_inventory
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (location_id, item_code)
                            )
                            locked_selected_location_row = c.fetchone()
                            locked_selected_location_quantity = (
                                int(locked_selected_location_row[0] or 0)
                                if locked_selected_location_row else 0
                            )
                            locked_selected_capacity = calculate_admin_location_capacity(
                                locked_base_quantity,
                                locked_location_total,
                                locked_selected_location_quantity,
                                locked_location_admin_owned,
                                locked_selected_user_remaining,
                                max(
                                    locked_location_total
                                    - locked_admin_placed_total
                                    - max(locked_selected_location_quantity - locked_location_admin_owned, 0),
                                    0
                                ),
                                locked_personal_user_total,
                                locked_written_off_total,
                                locked_net_sold_total,
                            )
                            locked_company_available = locked_selected_capacity["available"]
                            locked_ownership_from_existing = min(
                                quantity_set,
                                locked_selected_capacity["unowned_at_location"]
                            )
                        else:
                            locked_company_available = max(
                                locked_base_quantity
                                - locked_location_total
                                - locked_personal_user_total
                                - locked_admin_reserved
                                - locked_written_off_total
                                - locked_net_sold_total,
                                0
                            )
                        if is_super_admin() and quantity_set > locked_company_available:
                            conn.rollback()
                            st.error(
                                "Stock changed while this form was open. Quantity To Add exceeds the "
                                f"available quantity of {locked_company_available} for this selection."
                            )
                            st.stop()

                        if not is_super_admin():
                            c.execute(
                                '''
                                SELECT COALESCE(SUM(quantity), 0)
                                FROM admin_product_allocations
                                WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                                ''',
                                (st.session_state.username, item_code)
                            )
                            locked_admin_assignment = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''
                                SELECT COALESCE(SUM(h.quantity), 0)
                                FROM admin_location_stock h
                                WHERE LOWER(h.username)=LOWER(?) AND LOWER(h.item_code)=LOWER(?)
                                ''',
                                (st.session_state.username, item_code)
                            )
                            locked_admin_added = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM returns
                                   WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                     AND condition_status<>'customer_return'
                                     AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                                         =LOWER(?)''',
                                (item_code, st.session_state.username)
                            )
                            locked_admin_written_off = int(c.fetchone()[0] or 0)
                            locked_admin_sold = get_net_sold_quantity(
                                c, item_code, st.session_state.username
                            )
                            locked_admin_available = calculate_remaining_assignment(
                                locked_admin_assignment,
                                locked_admin_added,
                                locked_admin_written_off,
                                locked_admin_sold,
                            )
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (location_id, item_code)
                            )
                            locked_location_admin_owned = int(c.fetchone()[0] or 0)
                            c.execute(
                                '''SELECT COALESCE(quantity,0) FROM location_inventory
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (location_id, item_code)
                            )
                            locked_selected_location_row = c.fetchone()
                            locked_selected_location_quantity = (
                                int(locked_selected_location_row[0] or 0)
                                if locked_selected_location_row else 0
                            )
                            locked_selected_capacity = calculate_admin_location_capacity(
                                locked_base_quantity,
                                locked_location_total,
                                locked_selected_location_quantity,
                                locked_location_admin_owned,
                                locked_admin_available,
                                max(
                                    locked_location_total
                                    - locked_admin_placed_total
                                    - max(locked_selected_location_quantity - locked_location_admin_owned, 0),
                                    0
                                ),
                                locked_personal_user_total,
                                locked_written_off_total,
                                locked_net_sold_total,
                            )
                            locked_ownership_from_existing = min(
                                quantity_set, locked_selected_capacity["unowned_at_location"]
                            )
                            if quantity_set > locked_selected_capacity["available"]:
                                conn.rollback()
                                st.error(
                                    "Available company stock or your assignment changed while this form was open. "
                                    f"Quantity To Add cannot exceed {locked_selected_capacity['available']}."
                                )
                                st.stop()

                        c.execute(
                            '''
                            SELECT COALESCE(quantity, 0)
                            FROM location_inventory
                            WHERE location_id=? AND item_code=?
                            ''',
                            (location_id, item_code)
                        )
                        stock_quantity_row = c.fetchone()
                        quantity_before = int(stock_quantity_row[0] or 0) if stock_quantity_row else 0
                        physical_quantity_to_add = (
                            quantity_set - locked_ownership_from_existing
                            if (is_super_admin() and selected_access_role in {"admin", "sales"}) or not is_super_admin()
                            else quantity_set
                        )
                        relocation_quantity = (
                            min(physical_quantity_to_add, locked_selected_capacity["unowned_elsewhere"])
                            if (is_super_admin() and selected_access_role in {"admin", "sales"}) or not is_super_admin()
                            else 0
                        )
                        remaining_relocation = relocation_quantity
                        if remaining_relocation > 0:
                            c.execute(
                                '''SELECT li.location_id,li.quantity,
                                          COALESCE((SELECT SUM(als.quantity) FROM admin_location_stock als
                                                    WHERE als.location_id=li.location_id
                                                      AND LOWER(als.item_code)=LOWER(li.item_code)),0) AS owned
                                   FROM location_inventory li
                                   WHERE li.location_id<>? AND LOWER(li.item_code)=LOWER(?)
                                   ORDER BY li.location_id''',
                                (location_id, item_code)
                            )
                            for source_location_id, source_quantity, source_owned in c.fetchall():
                                source_unowned = max(int(source_quantity or 0) - int(source_owned or 0), 0)
                                moved_quantity = min(source_unowned, remaining_relocation)
                                if moved_quantity <= 0:
                                    continue
                                source_after = int(source_quantity or 0) - moved_quantity
                                c.execute(
                                    '''UPDATE location_inventory SET quantity=?
                                       WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                    (source_after, source_location_id, item_code)
                                )
                                if source_after == 0:
                                    c.execute(
                                        "DELETE FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                        (source_location_id, item_code)
                                    )
                                c.execute(
                                    '''INSERT INTO location_stock_history
                                       (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                       VALUES (?,?,?,?,?,?,?,?)''',
                                    (source_location_id, item_code, int(source_quantity or 0), -moved_quantity,
                                     source_after, "Reserve Transfer Out", st.session_state.username,
                                     datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                )
                                c.execute(
                                    '''INSERT INTO transactions
                                       (username,item_code,quantity_used,quantity_before,quantity_after,
                                        transaction_type,source_type,location_id,transaction_time)
                                       VALUES (?,?,?,?,?,?,?,?,?)''',
                                    (
                                        st.session_state.username, item_code, moved_quantity,
                                        int(source_quantity or 0), source_after,
                                        "stock_relocation_out", "location_stock", source_location_id,
                                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    ),
                                )
                                remaining_relocation -= moved_quantity
                                if remaining_relocation <= 0:
                                    break
                            if remaining_relocation > 0:
                                raise ValueError("Available unowned company stock changed while this form was open.")
                        quantity_after = quantity_before + physical_quantity_to_add
                        action_type = (
                            "Assign Existing Stock"
                            if quantity_set > 0 and physical_quantity_to_add == 0
                            else "Assign / Add"
                            if locked_ownership_from_existing > 0
                            else "Add"
                        )
                        if physical_quantity_to_add > 0:
                            c.execute(
                                '''
                                INSERT INTO location_inventory (location_id,item_code,quantity)
                                VALUES (?,?,?)
                                ON CONFLICT(location_id,item_code)
                                DO UPDATE SET quantity=location_inventory.quantity + excluded.quantity
                                ''',
                                (location_id, item_code, physical_quantity_to_add)
                            )
                        c.execute(
                            '''
                            INSERT INTO location_stock_history
                            (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                            VALUES (?,?,?,?,?,?,?,?)
                            ''',
                            (
                                location_id,
                                item_code,
                                quantity_before,
                                physical_quantity_to_add,
                                quantity_after,
                                action_type,
                                st.session_state.username,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
                        )
                        stock_owner_username = (
                            selected_access_username
                            if is_super_admin() and selected_access_role in {"admin", "sales"}
                            else st.session_state.username
                            if not is_super_admin()
                            else ""
                        )
                        if stock_owner_username and quantity_set > 0:
                            c.execute(
                                '''
                                INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                                VALUES (?,?,?,?)
                                ON CONFLICT(username,location_id,item_code)
                                DO UPDATE SET quantity=admin_location_stock.quantity + excluded.quantity
                                ''',
                                (stock_owner_username, location_id, item_code, quantity_set)
                            )
                        if quantity_set > 0:
                            c.execute(
                                '''INSERT INTO transactions
                                   (username,item_code,quantity_used,quantity_before,quantity_after,
                                    transaction_type,source_type,location_id,transaction_time,
                                    affected_owner_username)
                                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                (
                                    st.session_state.username, item_code, quantity_set,
                                    quantity_before, quantity_after,
                                    "stock_ownership_assignment"
                                    if stock_owner_username else "location_stock_add",
                                    "location_stock", location_id,
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    stock_owner_username or None,
                                ),
                            )
                        c.execute(
                            '''
                            INSERT INTO location_prices (location_id,item_code,price)
                            VALUES (?,?,?)
                            ON CONFLICT(location_id,item_code)
                            DO UPDATE SET price=excluded.price
                            ''',
                            (location_id, item_code, parsed_location_price)
                        )
                        conn.commit()
                        if is_super_admin():
                            st.success("Location stock and selling price saved successfully for the selected item.")
                        else:
                            st.success("Quantity was added to the selected location and selling price was saved.")
                        st.session_state.location_stock_form_reset_counter += 1
                        st.rerun()
                    except (ValueError, sqlite3.Error) as exc:
                        conn.rollback()
                        st.error(str(exc))
                    finally:
                        conn.close()

                if is_super_admin():
                    selected_location_stock_rows = location_stock_df[
                        (location_stock_df["location_id"] == location_id)
                        & (location_stock_df["item_code"] == item_code)
                    ].copy()
                    if selected_location_stock_rows.empty:
                        selected_location_stock_rows = pd.DataFrame(
                            [{
                                "location": selected_location.split(" (ID ")[0],
                                "item_code": item_code,
                                "item_name": selected_inventory_rows.iloc[0]["item_name"] if not selected_inventory_rows.empty else "",
                                "quantity": 0,
                                "price": current_location_price,
                            }]
                        )
                    selected_location_stock_rows["price"] = selected_location_stock_rows["price"].fillna(0).astype(float)
                    selected_location_stock_rows["quantity"] = selected_location_stock_rows["quantity"].fillna(0).astype(int)
                    selected_location_stock_rows["inventory_value"] = (
                        selected_location_stock_rows["quantity"] * selected_location_stock_rows["price"]
                    )
                    selected_location_stock_rows = selected_location_stock_rows.rename(
                        columns={
                            "location": "Location",
                            "item_code": "Item Code",
                            "item_name": "Item Name",
                            "quantity": "Saved Location Quantity",
                            "price": "Selling Price",
                            "inventory_value": "Location Sales Value",
                        }
                    )
                    st.markdown(
                        '<div class="dashboard-section-title">Selected Location Stock</div>',
                        unsafe_allow_html=True
                    )
                    st.dataframe(
                        selected_location_stock_rows[
                            [
                                "Location",
                                "Item Code",
                                "Item Name",
                                "Saved Location Quantity",
                                "Selling Price",
                                "Location Sales Value",
                            ]
                        ],
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Selling Price": st.column_config.NumberColumn("Selling Price", format="$%.2f"),
                            "Location Sales Value": st.column_config.NumberColumn("Location Sales Value", format="$%.2f"),
                        },
                    )

        if stock_table_col is None:
            st.stop()

        with stock_table_col:
            render_location_stock_table(location_stock_df, inventory_df)


    if menu == "Financials" and has_admin_access():
        if st.session_state.pop("invoice_form_reset_pending", False):
            invoice_widget_prefixes = (
                "invoice_item_selector_", "invoice_quantity_", "invoice_unit_price_", "create_invoice_"
            )
            for state_key in list(st.session_state.keys()):
                if state_key in {"invoice_location_selector", "invoice_customer_name"} or state_key.startswith(
                    invoice_widget_prefixes
                ):
                    st.session_state.pop(state_key, None)
        conn = get_connection()
        ensure_financial_schema(conn)
        locations_df = pd.read_sql_query("SELECT id, name FROM locations WHERE active=1 ORDER BY name", conn)
        inventory_df = pd.read_sql_query("SELECT item_code, item_name FROM inventory ORDER BY item_name", conn)
        invoices_df = pd.read_sql_query(
            '''
            SELECT inv.id, inv.location_id, inv.invoice_number, l.name AS location,
                   (SELECT GROUP_CONCAT(DISTINCT ii.item_code) FROM invoice_items ii
                    WHERE ii.invoice_id=inv.id) AS item_codes,
                   inv.customer_name, inv.created_by, inv.total,
                   COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id), 0) AS paid,
                   COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id), 0) AS credits,
                   COALESCE((SELECT SUM(rf.amount) FROM refunds rf
                             WHERE rf.invoice_id=inv.id AND rf.status='completed'),0) AS refunded,
                   MAX(inv.total
                       - COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id), 0)
                       - COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id), 0),0)
                       AS outstanding,
                   MAX(
                       COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id),0)
                       + COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id),0)
                       - inv.total
                       - COALESCE((SELECT SUM(rf.amount) FROM refunds rf
                                   WHERE rf.invoice_id=inv.id AND rf.status='completed'),0),0)
                       AS refund_due,
                   inv.status, inv.created_at
            FROM invoices inv
            LEFT JOIN locations l ON inv.location_id = l.id
            ORDER BY inv.id DESC
            ''',
            conn
        )
        payments_df = pd.read_sql_query(
            '''
            SELECT p.id, inv.location_id, inv.invoice_number,
                   GROUP_CONCAT(DISTINCT ii.item_code) AS item_codes,
                   p.amount, p.payment_method, inv.status AS invoice_status,
                   inv.created_by AS invoice_created_by,
                   p.reference_number, p.received_by, p.paid_at
            FROM payments p
            LEFT JOIN invoices inv ON p.invoice_id = inv.id
            LEFT JOIN invoice_items ii ON ii.invoice_id = inv.id
            GROUP BY p.id
            ORDER BY p.id DESC
            ''',
            conn
        )
        refunds_df = pd.read_sql_query(
            '''SELECT rf.id,inv.location_id,inv.invoice_number,inv.customer_name,
                      inv.created_by AS invoice_created_by,
                      rf.amount,rf.refund_method,rf.reference_number,rf.status,
                      rf.processed_by,rf.processed_at
               FROM refunds rf JOIN invoices inv ON inv.id=rf.invoice_id
               ORDER BY rf.id DESC''',
            conn,
        )
        invoice_lines_df = pd.read_sql_query(
            '''SELECT inv.invoice_number,inv.location_id,inv.created_by AS invoice_created_by,
                      ii.item_code,i.item_name,
                      ii.quantity,ii.unit_price,ii.line_total,
                      COALESCE(ii.generic_quantity,0) AS generic_quantity,
                      ii.owner_username,COALESCE(ii.owner_quantity,0) AS owner_quantity
               FROM invoice_items ii JOIN invoices inv ON inv.id=ii.invoice_id
               LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(ii.item_code)
               ORDER BY inv.id DESC,ii.id''',
            conn,
        )
        conn.close()

        assigned_location_ids = get_assigned_location_ids()
        if not is_super_admin():
            supplied_item_codes = set(get_supplied_item_codes())
            locations_df = locations_df[locations_df["id"].isin(assigned_location_ids)].copy()
            invoices_df = invoices_df[invoices_df["location_id"].isin(assigned_location_ids)].copy()
            payments_df = payments_df[payments_df["location_id"].isin(assigned_location_ids)].copy()
            refunds_df = refunds_df[refunds_df["location_id"].isin(assigned_location_ids)].copy()
            invoice_lines_df = invoice_lines_df[
                invoice_lines_df["location_id"].isin(assigned_location_ids)
            ].copy()
            refunds_df = refunds_df[
                refunds_df["invoice_created_by"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()
            invoice_lines_df = invoice_lines_df[
                invoice_lines_df["invoice_created_by"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()
            invoices_df = invoices_df.loc[
                invoices_df["created_by"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()
            payments_df = payments_df.loc[
                payments_df["invoice_created_by"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()
            inventory_df = inventory_df[inventory_df["item_code"].isin(supplied_item_codes)].copy()

            if supplied_item_codes:
                invoices_df = invoices_df.loc[
                    invoices_df["item_codes"].fillna("").apply(
                        lambda item_codes: bool(set(item_codes.split(",")) & supplied_item_codes)
                    ).astype(bool)
                ].copy()
                payments_df = payments_df.loc[
                    payments_df["item_codes"].fillna("").apply(
                        lambda item_codes: bool(set(item_codes.split(",")) & supplied_item_codes)
                    ).astype(bool)
                ].copy()
            else:
                invoices_df = invoices_df.iloc[0:0].copy()
                payments_df = payments_df.iloc[0:0].copy()

        st.markdown(
            f"""
            <div class="page-header">
                <div class="page-eyebrow">{'Owner Finance' if is_super_admin() else 'My Finance'}</div>
                <div class="page-title">Financials</div>
                <p class="page-subtitle">{'View company invoices and payments across all locations.' if is_super_admin() else 'View only invoices and payments created by your Admin account for assigned locations and products.'}</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        if "invoice_created_message" in st.session_state:
            st.success(st.session_state.pop("invoice_created_message"))

        if "financial_page_mode" not in st.session_state:
            st.session_state.financial_page_mode = "overview"
        financial_nav_items = [
            ("Overview", "overview"),
            ("Create Invoice", "create_invoice"),
            ("Record Payment", "record_payment"),
            ("Record Refund", "record_refund"),
            ("View Records", "view_records"),
        ]
        if is_super_admin():
            financial_nav_items.insert(-1, ("Void Invoice", "void_invoice"))
        financial_nav_cols = st.columns(len(financial_nav_items))
        for nav_col, (nav_label, nav_mode) in zip(financial_nav_cols, financial_nav_items):
            with nav_col:
                if st.button(
                    nav_label,
                    type="primary" if st.session_state.financial_page_mode == nav_mode else "secondary",
                    width="stretch",
                    key=f"financial_nav_{nav_mode}"
                ):
                    st.session_state.financial_page_mode = nav_mode
                    st.rerun()

        excluded_financial_statuses = {"cancelled", "canceled", "void"}
        summary_invoices_df = invoices_df[
            ~invoices_df["status"].fillna("").astype(str).str.lower().isin(excluded_financial_statuses)
        ].copy()
        summary_payments_df = payments_df[
            ~payments_df["invoice_status"].fillna("").astype(str).str.lower().isin(excluded_financial_statuses)
        ].copy()
        total_invoice_amount = float(summary_invoices_df["total"].sum()) if not summary_invoices_df.empty else 0
        total_paid = float(summary_invoices_df["paid"].sum()) if not summary_invoices_df.empty else 0
        total_credits = float(summary_invoices_df["credits"].sum()) if not summary_invoices_df.empty else 0
        total_net_sales = total_invoice_amount - total_credits
        total_refund_due = float(summary_invoices_df["refund_due"].sum()) if not summary_invoices_df.empty else 0
        total_refunded = float(summary_invoices_df["refunded"].sum()) if not summary_invoices_df.empty else 0
        total_net_cash = total_paid - total_refunded
        total_outstanding = float(summary_invoices_df["outstanding"].sum()) if not summary_invoices_df.empty else 0
        financial_col1, financial_col2, financial_col3, financial_col4 = st.columns(4)
        financial_col5, financial_col6, financial_col7, financial_col8 = st.columns(4)

        with financial_col1:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Invoice Total</div>
                    <div class="dashboard-card-value">${total_invoice_amount:,.2f}</div>
                        <div class="dashboard-card-note">{'All company locations' if is_super_admin() else 'Your created invoices'}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with financial_col2:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Paid</div>
                    <div class="dashboard-card-value">${total_paid:,.2f}</div>
                    <div class="dashboard-card-note">Received payments</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with financial_col3:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Return Credits</div>
                    <div class="dashboard-card-value">${total_credits:,.2f}</div>
                    <div class="dashboard-card-note">Credits issued for customer returns</div>
                </div>
                """,
                unsafe_allow_html=True
            )
        with financial_col4:
            st.markdown(
                f"""<div class="dashboard-card"><div class="dashboard-card-label">Net Sales</div>
                <div class="dashboard-card-value">${total_net_sales:,.2f}</div>
                <div class="dashboard-card-note">Invoice total minus return credits</div></div>""",
                unsafe_allow_html=True
            )
        with financial_col5:
            st.markdown(
                f"""<div class="dashboard-card"><div class="dashboard-card-label">Refund Due</div>
                <div class="dashboard-card-value">${total_refund_due:,.2f}</div>
                <div class="dashboard-card-note">Customer money still to refund</div></div>""",
                unsafe_allow_html=True
            )
        with financial_col6:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Outstanding</div>
                    <div class="dashboard-card-value">${total_outstanding:,.2f}</div>
                    <div class="dashboard-card-note">Open balance</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown('<div class="dashboard-section-title">Payment Summary by Method</div>', unsafe_allow_html=True)

        if summary_payments_df.empty:
            st.info("No payments have been recorded for the records you can access yet.")
        else:
            payment_summary_df = (
                summary_payments_df.groupby("payment_method", as_index=False)["amount"]
                .sum()
                .sort_values("amount", ascending=False)
            )
            st.dataframe(
                payment_summary_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "payment_method": "Payment Method",
                    "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
                }
            )
        with financial_col7:
            st.markdown(
                f'''<div class="dashboard-card"><div class="dashboard-card-label">Refunded</div>
                <div class="dashboard-card-value">${total_refunded:,.2f}</div>
                <div class="dashboard-card-note">Completed customer refunds</div></div>''',
                unsafe_allow_html=True,
            )
        with financial_col8:
            st.markdown(
                f'''<div class="dashboard-card"><div class="dashboard-card-label">Net Cash</div>
                <div class="dashboard-card-value">${total_net_cash:,.2f}</div>
                <div class="dashboard-card-note">Payments minus completed refunds</div></div>''',
                unsafe_allow_html=True,
            )

        if st.session_state.financial_page_mode == "overview":
            return

        invoice_form_col = st.empty()
        payment_form_col = st.empty()
        refund_form_col = st.empty()
        void_form_col = st.empty()

        with invoice_form_col.container():
            st.markdown('<div class="dashboard-section-title">Create Invoice</div>', unsafe_allow_html=True)

            if locations_df.empty or inventory_df.empty:
                if is_super_admin():
                    st.info("Create at least one active location and one inventory item before creating invoices.")
                elif locations_df.empty and inventory_df.empty:
                    show_next_step(
                        "This admin is missing both location access and supplied-product access.",
                        "Ruth should assign a location in Locations, then assign supplied products in User Management."
                    )
                elif locations_df.empty:
                    show_next_step(
                        "This admin is not assigned to an active location.",
                        "Ruth should open Locations and assign this admin to the correct storage location."
                    )
                else:
                    show_next_step(
                        "This admin has no supplied products assigned.",
                        "Ruth should open User Management and assign the products this admin supplies."
                    )
            else:
                location_options = {
                    f"{row['name']} (ID {row['id']})": int(row["id"])
                    for _, row in locations_df.iterrows()
                }

                st.markdown(
                    """
                    <div class="workflow-panel">
                        <div class="workflow-kicker">Step 1</div>
                        <div class="workflow-title">Select Location</div>
                        <div class="workflow-text">Choose the location this invoice will come from. The item list updates to show only stock available at that location.</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                invoice_location = st.selectbox(
                    "Location",
                    list(location_options.keys()),
                    key="invoice_location_selector"
                )
                location_id = location_options[invoice_location]

                conn = get_connection()
                available_items_df = pd.read_sql_query(
                    '''
                    SELECT li.item_code, i.item_name, li.quantity, COALESCE(lp.price, 0) AS price
                    FROM location_inventory li
                    LEFT JOIN inventory i ON li.item_code = i.item_code
                    LEFT JOIN location_prices lp
                        ON lp.location_id = li.location_id AND lp.item_code = li.item_code
                    WHERE li.location_id=? AND li.quantity > 0 AND COALESCE(lp.price,0) > 0
                    ORDER BY i.item_name
                    ''',
                    conn,
                    params=(location_id,)
                )
                conn.close()

                allowed_item_codes = set(inventory_df["item_code"].astype(str).tolist())
                location_has_stock = not available_items_df.empty
                available_items_df = available_items_df[
                    available_items_df["item_code"].astype(str).isin(allowed_item_codes)
                ].copy()
                if not is_super_admin() and not available_items_df.empty:
                    ownership_conn = get_connection()
                    owned_items_df = pd.read_sql_query(
                        '''SELECT item_code,COALESCE(quantity,0) AS owned_quantity
                           FROM admin_location_stock
                           WHERE LOWER(username)=LOWER(?) AND location_id=?''',
                        ownership_conn,
                        params=(st.session_state.username, location_id)
                    )
                    ownership_conn.close()
                    available_items_df["item_code_key"] = (
                        available_items_df["item_code"].astype(str).str.lower()
                    )
                    owned_items_df["item_code_key"] = owned_items_df["item_code"].astype(str).str.lower()
                    available_items_df = available_items_df.merge(
                        owned_items_df[["item_code_key", "owned_quantity"]],
                        on="item_code_key",
                        how="left"
                    )
                    available_items_df["owned_quantity"] = (
                        available_items_df["owned_quantity"].fillna(0).astype(int)
                    )
                    available_items_df["physical_quantity"] = available_items_df["quantity"].astype(int)
                    available_items_df["quantity"] = available_items_df.apply(
                        lambda row: calculate_invoice_available_quantity(
                            "admin", row["physical_quantity"], row["owned_quantity"]
                        ),
                        axis=1
                    )
                    available_items_df = available_items_df[
                        available_items_df["quantity"] > 0
                    ].copy()

                if available_items_df.empty:
                    if not location_has_stock:
                        show_next_step(
                            "The selected location has no sellable stock with a positive price.",
                            "Add stock and a positive selling price in Location Inventory, or choose another location."
                        )
                    elif not is_super_admin():
                        show_next_step(
                            "This location has stock, but you do not personally own sellable quantity for an assigned product here.",
                            "Check Added By You in Location Inventory, or ask Ruth to assign product quantity to your account."
                        )
                    else:
                        st.info("The selected location has stock, but none of the stocked items match the current invoice product list. Check Location Inventory and the master inventory list.")
                else:
                    item_options = {
                        f"{row['item_name']} ({row['item_code']}) - {int(row['quantity'])} available - ${float(row['price']):.2f}":
                        row["item_code"]
                        for _, row in available_items_df.iterrows()
                    }
                    st.markdown(
                        """
                        <div class="workflow-panel">
                            <div class="workflow-kicker">Step 2</div>
                            <div class="workflow-title">Select Item</div>
                            <div class="workflow-text">Pick an item from the selected location. The default price comes from that location's pricing setup.</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    invoice_item = st.selectbox(
                        "Item",
                        list(item_options.keys()),
                        key=f"invoice_item_selector_{location_id}"
                    )
                    item_code = item_options[invoice_item]
                    selected_item_row = available_items_df[
                        available_items_df["item_code"] == item_code
                    ].iloc[0]
                    available_quantity = int(selected_item_row["quantity"])
                    default_unit_price = float(selected_item_row["price"])
                    invoice_affected_owner = None
                    if is_super_admin():
                        owner_conn = get_connection()
                        try:
                            invoice_owner_df = pd.read_sql_query(
                                '''SELECT als.username,u.role,
                                          als.quantity AS owned_quantity
                                   FROM admin_location_stock als
                                   INNER JOIN users u ON LOWER(u.username)=LOWER(als.username)
                                   WHERE als.location_id=? AND LOWER(als.item_code)=LOWER(?)
                                     AND als.quantity>0 AND u.role IN ('admin','sales')
                                   ORDER BY u.role,als.username''',
                                owner_conn,
                                params=(location_id, item_code)
                            )
                        finally:
                            owner_conn.close()
                        total_owned_for_invoice = (
                            int(invoice_owner_df["owned_quantity"].sum())
                            if not invoice_owner_df.empty else 0
                        )
                        generic_for_invoice = max(available_quantity - total_owned_for_invoice, 0)
                        owner_options = {}
                        if generic_for_invoice > 0:
                            owner_options["Unowned company stock only"] = (None, 0)
                        owner_options.update({
                            f"{row['username']} ({str(row['role']).title()})": (
                                str(row["username"]), int(row["owned_quantity"])
                            ) for _, row in invoice_owner_df.iterrows()
                        })
                        selected_invoice_owner = st.selectbox(
                            "Stock Owner Used by Invoice",
                            list(owner_options.keys()),
                            disabled=not owner_options,
                            key=f"invoice_owner_{location_id}_{item_code}"
                        )
                        invoice_affected_owner, selected_owner_quantity = (
                            owner_options[selected_invoice_owner] if owner_options else (None, 0)
                        )
                        available_quantity = min(
                            available_quantity, generic_for_invoice + selected_owner_quantity
                        )
                        st.caption(
                            f"Unowned stock: {generic_for_invoice}; selected owner stock: "
                            f"{selected_owner_quantity}. The invoice cannot consume another user's stock."
                        )
                    create_invoice = False

                    with st.container(border=True):
                        st.markdown(
                            """
                            <div class="workflow-kicker">Step 3</div>
                            <div class="workflow-title">Confirm Invoice Details</div>
                            """,
                            unsafe_allow_html=True
                        )
                        st.caption(
                            f"{'Your owned stock available' if not is_super_admin() else 'Available at this location'}: "
                            f"{available_quantity} unit(s). "
                            f"Default location price: ${default_unit_price:.2f}."
                        )
                        st.markdown(
                            '<div class="modern-form-note">Add the customer, quantity, and price for this location invoice.</div>',
                            unsafe_allow_html=True
                        )
                        customer_name = st.text_input(
                            "Customer Name",
                            placeholder="Customer or company name",
                            key="invoice_customer_name"
                        )
                        quantity_col, price_col = st.columns(2)
                        with quantity_col:
                            invoice_quantity = st.number_input(
                                "Quantity",
                                min_value=1,
                                max_value=max(available_quantity, 1),
                                value=None,
                                step=1,
                                placeholder="Enter quantity",
                                disabled=available_quantity <= 0,
                                key=f"invoice_quantity_{location_id}_{item_code}"
                            )
                        with price_col:
                            invoice_unit_price = st.number_input(
                                "Unit Price",
                                min_value=0.01,
                                value=default_unit_price,
                                step=0.01,
                                format="%.2f",
                                disabled=True,
                                help="The invoice uses the selling price saved for this location.",
                                key=f"invoice_unit_price_{location_id}_{item_code}"
                            )

                        invoice_quantity_preview = int(invoice_quantity or 0)
                        invoice_total_preview = invoice_quantity_preview * float(invoice_unit_price)
                        invoice_stock_after = max(available_quantity - invoice_quantity_preview, 0)
                        st.markdown(
                            f"""
                            <div class="modern-form-summary">
                                <div class="modern-form-summary-title">Invoice Preview</div>
                                <div class="modern-form-summary-grid">
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Available</div>
                                        <div class="modern-form-summary-value">{available_quantity} units</div>
                                    </div>
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Invoice Total</div>
                                        <div class="modern-form-summary-value">${invoice_total_preview:,.2f}</div>
                                    </div>
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Stock After</div>
                                        <div class="modern-form-summary-value">{invoice_stock_after} units</div>
                                    </div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        preview_customer = safe_html(customer_name.strip() or "Customer name not entered")
                        preview_location = safe_html(invoice_location)
                        preview_item_name = safe_html(str(selected_item_row["item_name"] or item_code))
                        preview_item_code = safe_html(item_code)
                        preview_quantity_text = (
                            f"{invoice_quantity_preview:,}" if invoice_quantity is not None else "—"
                        )
                        st.markdown(
                            f"""
                            <div style="background:#ffffff;border:1px solid #dbe3ee;border-radius:16px;padding:22px;margin-top:14px;box-shadow:0 8px 24px rgba(15,23,42,.06);">
                                <div style="display:flex;justify-content:space-between;gap:20px;border-bottom:2px solid #e5e7eb;padding-bottom:16px;margin-bottom:18px;">
                                    <div>
                                        <div style="font-size:12px;font-weight:800;letter-spacing:.12em;color:#64748b;">LIVE DRAFT</div>
                                        <div style="font-size:26px;font-weight:800;color:#172033;">INVOICE</div>
                                    </div>
                                    <div style="text-align:right;color:#475569;font-size:13px;">
                                        <div><strong>Invoice #:</strong> Assigned after save</div>
                                        <div><strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')}</div>
                                    </div>
                                </div>
                                <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px;">
                                    <div>
                                        <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Bill To</div>
                                        <div style="font-size:16px;font-weight:700;color:#172033;">{preview_customer}</div>
                                    </div>
                                    <div style="text-align:right;">
                                        <div style="font-size:11px;font-weight:800;color:#64748b;text-transform:uppercase;">Fulfilled From</div>
                                        <div style="font-size:16px;font-weight:700;color:#172033;">{preview_location}</div>
                                    </div>
                                </div>
                                <table style="width:100%;border-collapse:collapse;font-size:14px;">
                                    <thead>
                                        <tr style="background:#f1f5f9;color:#334155;text-align:left;">
                                            <th style="padding:11px;">Item</th>
                                            <th style="padding:11px;text-align:right;">Quantity</th>
                                            <th style="padding:11px;text-align:right;">Unit Price</th>
                                            <th style="padding:11px;text-align:right;">Line Total</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr style="border-bottom:1px solid #e5e7eb;">
                                            <td style="padding:13px 11px;"><strong>{preview_item_name}</strong><br><span style="color:#64748b;">{preview_item_code}</span></td>
                                            <td style="padding:13px 11px;text-align:right;">{preview_quantity_text}</td>
                                            <td style="padding:13px 11px;text-align:right;">${float(invoice_unit_price):,.2f}</td>
                                            <td style="padding:13px 11px;text-align:right;font-weight:700;">${invoice_total_preview:,.2f}</td>
                                        </tr>
                                    </tbody>
                                </table>
                                <div style="margin-left:auto;margin-top:16px;max-width:310px;">
                                    <div style="display:flex;justify-content:space-between;padding:7px 0;color:#475569;"><span>Subtotal</span><span>${invoice_total_preview:,.2f}</span></div>
                                    <div style="display:flex;justify-content:space-between;padding:11px 0;border-top:2px solid #172033;font-size:19px;font-weight:800;color:#172033;"><span>Total</span><span>${invoice_total_preview:,.2f}</span></div>
                                    <div style="display:flex;justify-content:space-between;padding:7px 0;color:#0f766e;font-weight:700;"><span>Amount Due</span><span>${invoice_total_preview:,.2f}</span></div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        st.caption(
                            "Live preview only — stock and invoice records are not saved until Create Invoice is clicked."
                        )
                        create_invoice = st.button(
                            "Create Invoice",
                            type="primary",
                            width="stretch",
                            disabled=(
                                available_quantity <= 0
                                or invoice_quantity is None
                                or not customer_name.strip()
                            ),
                            key=f"create_invoice_{location_id}_{item_code}"
                        )

                    if create_invoice:
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if invoice_quantity is None or int(invoice_quantity) <= 0:
                            st.error("Quantity must be greater than zero before creating an invoice.")
                            st.stop()
                        quantity_int = int(invoice_quantity)
                        if not customer_name.strip():
                            st.error("Customer Name is required before creating an invoice.")
                            st.stop()
                        if float(invoice_unit_price) <= 0:
                            st.error("A positive location selling price is required before creating an invoice.")
                            st.stop()
                        conn = get_connection()
                        c = conn.cursor()

                        try:
                            c.execute("BEGIN IMMEDIATE")
                            c.execute(
                                '''
                                SELECT quantity FROM location_inventory
                                WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                ''',
                                (location_id, item_code)
                            )
                            stock_row = c.fetchone()
                            current_available_quantity = int(stock_row[0]) if stock_row else 0
                            c.execute(
                                '''SELECT COALESCE(price,0) FROM location_prices
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (location_id, item_code)
                            )
                            locked_price_row = c.fetchone()
                            locked_location_price = round(
                                float(locked_price_row[0] or 0) if locked_price_row else 0.0, 2
                            )
                            c.execute("SELECT active FROM locations WHERE id=?", (location_id,))
                            active_location_row = c.fetchone()

                            if not active_location_row or int(active_location_row[0] or 0) != 1:
                                raise ValueError("The selected location is no longer active.")
                            if quantity_int > current_available_quantity:
                                raise ValueError("Not enough stock is available at the selected location to create this invoice.")
                            if locked_location_price <= 0:
                                raise ValueError("This item does not have a positive selling price at the selected location.")
                            if locked_location_price != round(float(invoice_unit_price), 2):
                                raise ValueError(
                                    "The location selling price changed while this form was open. Refresh and try again."
                                )
                            else:
                                unit_price = locked_location_price
                                invoice_total = quantity_int * unit_price
                                if is_super_admin():
                                    c.execute(
                                        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                           WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                             AND quantity>0''',
                                        (location_id, item_code),
                                    )
                                    locked_total_owned = int(c.fetchone()[0] or 0)
                                    locked_generic_available = max(
                                        current_available_quantity - locked_total_owned, 0
                                    )
                                    locked_owner_available = 0
                                    if invoice_affected_owner:
                                        c.execute(
                                            '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                               WHERE LOWER(username)=LOWER(?) AND location_id=?
                                                 AND LOWER(item_code)=LOWER(?)''',
                                            (invoice_affected_owner, location_id, item_code),
                                        )
                                        locked_owner_row = c.fetchone()
                                        locked_owner_available = (
                                            int(locked_owner_row[0] or 0) if locked_owner_row else 0
                                        )
                                    generic_quantity_used, owner_quantity_used = (
                                        calculate_invoice_ownership_split(
                                            quantity_int,
                                            locked_generic_available,
                                            locked_owner_available,
                                        )
                                    )
                                else:
                                    generic_quantity_used, owner_quantity_used = 0, quantity_int
                                consumed_owner_username = consume_invoice_location_ownership(
                                    c, get_current_role(), st.session_state.username,
                                    location_id, item_code, quantity_int, invoice_affected_owner
                                )
                                c.execute(
                                    '''
                                    UPDATE location_inventory
                                    SET quantity=?
                                    WHERE location_id=? AND item_code=?
                                    ''',
                                    (current_available_quantity - quantity_int, location_id, item_code)
                                )
                                c.execute(
                                    '''
                                    INSERT INTO location_stock_history
                                    (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                    VALUES (?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        location_id,
                                        item_code,
                                        current_available_quantity,
                                        -quantity_int,
                                        current_available_quantity - quantity_int,
                                        "Sale",
                                        st.session_state.username,
                                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    )
                                )
                                c.execute(
                                    '''
                                    INSERT INTO invoices
                                    (location_id,customer_name,created_by,subtotal,total,status,created_at)
                                    VALUES (?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        location_id,
                                        customer_name.strip(),
                                        st.session_state.username,
                                        invoice_total,
                                        invoice_total,
                                        "open",
                                        now
                                    )
                                )
                                invoice_id = c.lastrowid
                                invoice_number = f"INV-{invoice_id:05d}"
                                c.execute("UPDATE invoices SET invoice_number=? WHERE id=?", (invoice_number, invoice_id))
                                c.execute(
                                    '''
                                    INSERT INTO invoice_items
                                    (invoice_id,item_code,quantity,unit_price,line_total,owner_username,
                                     generic_quantity,owner_quantity)
                                    VALUES (?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        invoice_id,
                                        item_code,
                                        quantity_int,
                                        unit_price,
                                        invoice_total,
                                        consumed_owner_username,
                                        generic_quantity_used,
                                        owner_quantity_used,
                                    )
                                )
                                c.execute(
                                    '''
                                    INSERT INTO transactions
                                    (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,
                                     source_type,location_id,transaction_time,affected_owner_username)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        st.session_state.username,
                                        item_code,
                                        quantity_int,
                                        current_available_quantity,
                                        current_available_quantity - quantity_int,
                                        "sale",
                                        "location_stock",
                                        location_id,
                                        now,
                                        consumed_owner_username
                                    )
                                )
                                conn.commit()
                                st.session_state.invoice_created_message = (
                                    f"Invoice {invoice_number} created successfully. "
                                    "Location inventory was reduced automatically and the form was cleared."
                                )
                                st.session_state.invoice_form_reset_pending = True
                                st.rerun()
                        except ValueError as exc:
                            conn.rollback()
                            st.error(str(exc))
                        except sqlite3.Error as exc:
                            conn.rollback()
                            st.error(f"Invoice could not be created: {exc}")
                        finally:
                            conn.close()

        with payment_form_col.container():
            st.markdown('<div class="dashboard-section-title">Record Payment</div>', unsafe_allow_html=True)

            payable_invoices_df = invoices_df[
                ~invoices_df["status"].fillna("").astype(str).str.lower().isin(
                    excluded_financial_statuses
                )
                & (invoices_df["outstanding"].astype(float) > 0.005)
            ].copy()
            if payable_invoices_df.empty:
                show_next_step(
                    "No open invoices with an outstanding balance are available for payment recording.",
                    "Create an invoice first, or review paid and closed invoices in View Records."
                )
            else:
                invoice_options = {
                    f"{row['invoice_number']} - {row['customer_name']} (${float(row['outstanding']):,.2f} due)": int(row["id"])
                    for _, row in payable_invoices_df.iterrows()
                }

                with st.form("record_payment_form"):
                    selected_invoice = st.selectbox("Invoice", list(invoice_options.keys()))
                    payment_amount = st.number_input("Payment Amount", min_value=0.0, step=0.01, format="%.2f")
                    payment_method = st.selectbox("Payment Method", ["cash", "check", "wire", "credit_card"])
                    reference_number = st.text_input("Reference Number")
                    record_payment = st.form_submit_button("Record Payment", type="primary", width="stretch")

                if record_payment:
                    normalized_payment_amount = float(money(payment_amount))
                    if normalized_payment_amount <= 0:
                        st.error("Payment amount must be greater than zero before it can be recorded.")
                    else:
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        invoice_id = invoice_options[selected_invoice]
                        conn = get_connection()
                        c = conn.cursor()
                        try:
                            c.execute("BEGIN IMMEDIATE")
                            c.execute("SELECT status FROM invoices WHERE id=?", (invoice_id,))
                            locked_status_row = c.fetchone()
                            if not locked_status_row:
                                raise ValueError("The selected invoice could not be found. Refresh and try again.")
                            locked_status = str(locked_status_row[0] or "").lower()
                            if locked_status in excluded_financial_statuses:
                                raise ValueError(
                                    f"Payments cannot be recorded for an invoice with status '{locked_status or 'unknown'}'."
                                )
                            outstanding_balance = get_invoice_balance(c, invoice_id)

                            if outstanding_balance is None:
                                raise ValueError("The selected invoice could not be found. Refresh and try again.")
                            if normalized_payment_amount > float(money(outstanding_balance)):
                                raise ValueError(
                                    f"Payment cannot exceed the outstanding balance of ${outstanding_balance:,.2f}."
                                )
                            c.execute(
                                '''INSERT INTO payments
                                   (invoice_id,amount,payment_method,reference_number,received_by,paid_at)
                                   VALUES (?,?,?,?,?,?)''',
                                (invoice_id, normalized_payment_amount, payment_method, reference_number.strip(),
                                 st.session_state.username, now)
                            )
                            if float(money(outstanding_balance - normalized_payment_amount)) <= 0:
                                c.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))
                            conn.commit()
                            st.success("Payment recorded successfully. Invoice status was updated if the balance is fully paid.")
                            st.rerun()
                        except ValueError as exc:
                            conn.rollback()
                            st.error(str(exc))
                        except sqlite3.Error as exc:
                            conn.rollback()
                            st.error(f"Payment could not be recorded: {exc}")
                        finally:
                            conn.close()

        with refund_form_col.container():
            st.markdown('<div class="dashboard-section-title">Record Customer Refund</div>', unsafe_allow_html=True)
            refundable_invoices_df = invoices_df[
                ~invoices_df["status"].fillna("").astype(str).str.lower().isin(excluded_financial_statuses)
                & (invoices_df["refund_due"].astype(float) > 0.005)
            ].copy()
            if refundable_invoices_df.empty:
                st.info("No customer refunds are currently due for the invoices you can access.")
            else:
                refund_invoice_options = {
                    f"{row['invoice_number']} - {row['customer_name']} (${float(row['refund_due']):,.2f} due)": int(row["id"])
                    for _, row in refundable_invoices_df.iterrows()
                }
                with st.form("record_refund_form"):
                    selected_refund_invoice = st.selectbox("Invoice", list(refund_invoice_options.keys()))
                    refund_amount = st.number_input("Refund Amount", min_value=0.0, step=0.01, format="%.2f")
                    refund_method = st.selectbox(
                        "Refund Method", ["cash", "check", "wire", "credit_card", "store_credit"]
                    )
                    refund_reference = st.text_input("Refund Reference")
                    record_refund = st.form_submit_button(
                        "Record Refund", type="primary", width="stretch"
                    )
                if record_refund:
                    normalized_refund_amount = float(money(refund_amount))
                    if normalized_refund_amount <= 0:
                        st.error("Refund amount must be greater than zero.")
                    else:
                        invoice_id = refund_invoice_options[selected_refund_invoice]
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn = get_connection()
                        c = conn.cursor()
                        try:
                            c.execute("BEGIN IMMEDIATE")
                            c.execute(
                                '''SELECT inv.total,
                                          COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id),0),
                                          COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id),0),
                                          COALESCE((SELECT SUM(rf.amount) FROM refunds rf
                                                    WHERE rf.invoice_id=inv.id AND rf.status='completed'),0),
                                          inv.status
                                   FROM invoices inv WHERE inv.id=?''',
                                (invoice_id,)
                            )
                            locked_refund_row = c.fetchone()
                            if not locked_refund_row:
                                raise ValueError("The selected invoice no longer exists.")
                            total, paid, credits, already_refunded, invoice_status = locked_refund_row
                            if str(invoice_status or "").lower() in excluded_financial_statuses:
                                raise ValueError("A refund cannot be recorded for a void or cancelled invoice.")
                            locked_refund_due = float(max(
                                money(paid) + money(credits) - money(total) - money(already_refunded),
                                Decimal("0.00"),
                            ))
                            if normalized_refund_amount > locked_refund_due:
                                raise ValueError(
                                    f"Refund cannot exceed the current refund due of ${locked_refund_due:,.2f}."
                                )
                            c.execute(
                                '''INSERT INTO refunds
                                   (invoice_id,amount,refund_method,reference_number,status,processed_by,processed_at)
                                   VALUES (?,?,?,?,?,?,?)''',
                                (
                                    invoice_id, normalized_refund_amount, refund_method,
                                    refund_reference.strip(), "completed",
                                    st.session_state.username, now,
                                )
                            )
                            conn.commit()
                            st.success("Customer refund recorded successfully.")
                            st.rerun()
                        except ValueError as exc:
                            conn.rollback()
                            st.error(str(exc))
                        except sqlite3.Error as exc:
                            conn.rollback()
                            st.error(f"Refund could not be recorded: {exc}")
                        finally:
                            conn.close()

        with void_form_col.container():
            if is_super_admin():
                st.markdown('<div class="dashboard-section-title">Void Invoice</div>', unsafe_allow_html=True)
                voidable_df = invoices_df[
                    ~invoices_df["status"].fillna("").astype(str).str.lower().isin(
                        excluded_financial_statuses
                    )
                ].copy()
                if voidable_df.empty:
                    st.info("No active invoice is available to void.")
                else:
                    void_options = {
                        f"{row['invoice_number']} - {row['customer_name']} (${float(row['total']):,.2f})": int(row["id"])
                        for _, row in voidable_df.iterrows()
                    }
                    selected_void_label = st.selectbox("Invoice", list(void_options), key="void_invoice_selector")
                    confirm_void = st.checkbox(
                        "I understand this restores stock and permanently marks the invoice as void.",
                        key="confirm_void_invoice",
                    )
                    if st.button(
                        "Void Invoice", type="primary", width="stretch",
                        disabled=not confirm_void, key="void_invoice_button",
                    ):
                        conn = get_connection()
                        try:
                            void_invoice(
                                conn, void_options[selected_void_label], st.session_state.username
                            )
                            st.success("Invoice voided and its stock ownership was restored.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                        except sqlite3.Error as exc:
                            st.error(f"Invoice could not be voided: {exc}")
                        finally:
                            conn.close()

        if st.session_state.financial_page_mode == "create_invoice":
            payment_form_col.empty()
            refund_form_col.empty()
            void_form_col.empty()
            return
        if st.session_state.financial_page_mode == "record_payment":
            invoice_form_col.empty()
            refund_form_col.empty()
            void_form_col.empty()
            return
        if st.session_state.financial_page_mode == "record_refund":
            invoice_form_col.empty()
            payment_form_col.empty()
            void_form_col.empty()
            return
        if st.session_state.financial_page_mode == "void_invoice" and is_super_admin():
            invoice_form_col.empty()
            payment_form_col.empty()
            refund_form_col.empty()
            return

        invoice_form_col.empty()
        payment_form_col.empty()
        refund_form_col.empty()
        void_form_col.empty()
        st.markdown('<div class="dashboard-section-title">Invoices</div>', unsafe_allow_html=True)
        if invoices_df.empty:
            st.info("No invoices have been created for the records you can access yet.")
        else:
            invoice_filter_col1, invoice_filter_col2 = st.columns([1.3, 0.7])
            with invoice_filter_col1:
                invoice_search = st.text_input(
                    "Search invoices",
                    placeholder="Search invoice, customer, location, or item",
                    key="invoice_table_search"
                )
            with invoice_filter_col2:
                invoice_status_filter = st.selectbox(
                    "Financial Status",
                    ["All", "Paid", "Partially Paid", "Unpaid", "Fully Credited",
                     "Paid and Refunded", "Partially Refunded"],
                    key="invoice_status_filter"
                )

            invoice_display_df = invoices_df.copy()
            invoice_display_df["status_label"] = invoice_display_df.apply(
                lambda row: financial_status(
                    row["total"], row["paid"], row["credits"], row["refunded"]
                )["label"],
                axis=1
            )

            if invoice_search:
                invoice_search_value = invoice_search.lower().strip()
                invoice_display_df = invoice_display_df[
                    invoice_display_df["invoice_number"].fillna("").str.lower().str.contains(invoice_search_value)
                    | invoice_display_df["customer_name"].fillna("").str.lower().str.contains(invoice_search_value)
                    | invoice_display_df["location"].fillna("").str.lower().str.contains(invoice_search_value)
                    | invoice_display_df["item_codes"].fillna("").str.lower().str.contains(invoice_search_value)
                ].copy()

            if invoice_status_filter != "All":
                invoice_display_df = invoice_display_df[
                    invoice_display_df["status_label"] == invoice_status_filter
                ].copy()

            if invoice_display_df.empty:
                st.info("No invoices match the selected search or status filter.")
            else:
                invoice_display_df["balance_status"] = invoice_display_df["status_label"]
                invoice_display_df["total_display"] = invoice_display_df["total"].apply(format_currency)
                invoice_display_df["paid_display"] = invoice_display_df["paid"].apply(format_currency)
                invoice_display_df["credits_display"] = invoice_display_df["credits"].apply(format_currency)
                invoice_display_df["refunded_display"] = invoice_display_df["refunded"].apply(format_currency)
                invoice_display_df["refund_due_display"] = invoice_display_df["refund_due"].apply(format_currency)
                invoice_display_df["outstanding_display"] = invoice_display_df["outstanding"].apply(format_currency)
                invoice_display_df = invoice_display_df[
                    [
                        "invoice_number",
                        "location",
                        "item_codes",
                        "customer_name",
                        "total_display",
                        "paid_display",
                        "credits_display",
                        "refunded_display",
                        "refund_due_display",
                        "outstanding_display",
                        "balance_status",
                        "created_at",
                    ]
                ]

            st.dataframe(
                invoice_display_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "invoice_number": "Invoice",
                    "location": "Location",
                    "item_codes": "Items",
                    "customer_name": "Customer",
                    "total_display": "Total",
                    "paid_display": "Paid",
                    "credits_display": "Return Credits",
                    "refunded_display": "Refunded",
                    "refund_due_display": "Refund Due",
                    "outstanding_display": "Outstanding",
                    "balance_status": "Financial Status",
                    "created_at": "Created",
                }
            )

        st.markdown('<div class="dashboard-section-title">Invoice Line Details</div>', unsafe_allow_html=True)
        if invoice_lines_df.empty:
            st.info("No invoice line details are available.")
        else:
            invoice_line_display_df = invoice_lines_df.copy()
            invoice_line_display_df["unit_price"] = invoice_line_display_df["unit_price"].apply(format_currency)
            invoice_line_display_df["line_total"] = invoice_line_display_df["line_total"].apply(format_currency)
            st.dataframe(
                invoice_line_display_df[
                    ["invoice_number", "item_code", "item_name", "quantity", "unit_price",
                     "generic_quantity", "owner_username", "owner_quantity", "line_total"]
                ],
                width="stretch", hide_index=True,
                column_config={
                    "invoice_number": "Invoice", "item_code": "Item Code",
                    "item_name": "Item", "quantity": "Quantity", "unit_price": "Unit Price",
                    "generic_quantity": "Company Stock Used", "owner_username": "Stock Owner",
                    "owner_quantity": "Owner Stock Used", "line_total": "Line Total",
                },
            )

        st.markdown('<div class="dashboard-section-title">Payments</div>', unsafe_allow_html=True)
        if payments_df.empty:
            st.info("No payments have been recorded for the records you can access yet.")
        else:
            payment_filter_col1, payment_filter_col2 = st.columns([1.3, 0.7])
            with payment_filter_col1:
                payment_search = st.text_input(
                    "Search payments",
                    placeholder="Search invoice, method, reference, or receiver",
                    key="payment_table_search"
                )
            with payment_filter_col2:
                payment_method_filter = st.selectbox(
                    "Payment Method",
                    ["All", "cash", "check", "wire", "credit_card"],
                    key="payment_method_filter"
                )

            payment_display_df = payments_df.copy()

            if payment_search:
                payment_search_value = payment_search.lower().strip()
                payment_display_df = payment_display_df[
                    payment_display_df["invoice_number"].fillna("").str.lower().str.contains(payment_search_value)
                    | payment_display_df["payment_method"].fillna("").str.lower().str.contains(payment_search_value)
                    | payment_display_df["reference_number"].fillna("").str.lower().str.contains(payment_search_value)
                    | payment_display_df["received_by"].fillna("").str.lower().str.contains(payment_search_value)
                ].copy()

            if payment_method_filter != "All":
                payment_display_df = payment_display_df[
                    payment_display_df["payment_method"] == payment_method_filter
                ].copy()

            if payment_display_df.empty:
                st.info("No payments match the selected search or method filter.")
            else:
                payment_display_df["amount_display"] = payment_display_df["amount"].apply(format_currency)
                payment_display_df = payment_display_df[
                    [
                        "invoice_number",
                        "amount_display",
                        "payment_method",
                        "reference_number",
                        "received_by",
                        "paid_at",
                    ]
                ]

                st.dataframe(
                    payment_display_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "invoice_number": "Invoice",
                        "amount_display": "Amount",
                        "payment_method": "Method",
                        "reference_number": "Reference",
                        "received_by": "Received By",
                        "paid_at": "Paid At",
                    }
                )

        st.markdown('<div class="dashboard-section-title">Refunds</div>', unsafe_allow_html=True)
        if refunds_df.empty:
            st.info("No refunds have been recorded for the records you can access.")
        else:
            refund_display_df = refunds_df.copy()
            refund_display_df["amount_display"] = refund_display_df["amount"].apply(format_currency)
            st.dataframe(
                refund_display_df[
                    ["invoice_number", "customer_name", "amount_display", "refund_method",
                     "reference_number", "status", "processed_by", "processed_at"]
                ],
                width="stretch", hide_index=True,
                column_config={
                    "invoice_number": "Invoice", "customer_name": "Customer",
                    "amount_display": "Amount", "refund_method": "Method",
                    "reference_number": "Reference", "status": "Status",
                    "processed_by": "Processed By", "processed_at": "Processed At",
                },
            )


    if menu == "Returns" and (has_admin_access() or get_current_role() == "sales"):
        if "returns_saved_message" in st.session_state:
            st.success(st.session_state.pop("returns_saved_message"))
        if "returns_form_reset_counter" not in st.session_state:
            st.session_state.returns_form_reset_counter = 0
        returns_form_reset_counter = st.session_state.returns_form_reset_counter
        conn = get_connection()
        locations_df = pd.read_sql_query("SELECT id, name FROM locations WHERE active=1 ORDER BY name", conn)
        inventory_df = pd.read_sql_query("SELECT item_code, item_name FROM inventory ORDER BY item_name", conn)
        return_stock_df = pd.read_sql_query(
            '''SELECT li.location_id,li.item_code,i.item_name,li.quantity
               FROM location_inventory li
               LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(li.item_code)
               WHERE li.quantity>0''',
            conn
        )
        returns_df = pd.read_sql_query(
            '''
            SELECT r.id, r.invoice_id, inv.invoice_number, inv.created_by AS invoice_created_by,
                   r.location_id, l.name AS location,
                   r.item_code, i.item_name, r.quantity, r.reason,
                   r.condition_status, r.affected_owner_username,
                   r.recorded_by, r.status, r.created_at,
                   r.quantity_before, r.quantity_after, r.inventory_action
            FROM returns r
            LEFT JOIN invoices inv ON inv.id = r.invoice_id
            LEFT JOIN locations l ON r.location_id = l.id
            LEFT JOIN inventory i ON r.item_code = i.item_code
            ORDER BY r.id DESC
            ''',
            conn
        )
        conn.close()

        assigned_location_ids = get_assigned_location_ids()
        if not is_super_admin():
            locations_df = locations_df[locations_df["id"].isin(assigned_location_ids)].copy()
            return_stock_df = return_stock_df[
                return_stock_df["location_id"].isin(assigned_location_ids)
            ].copy()
            returns_df = returns_df[returns_df["location_id"].isin(assigned_location_ids)].copy()
            current_username_lower = str(st.session_state.username).lower()
            if get_current_role() == "sales":
                returns_df = returns_df.loc[
                    (returns_df["recorded_by"].astype(str).str.lower() == current_username_lower)
                    | (returns_df["invoice_created_by"].astype(str).str.lower() == current_username_lower)
                    | (returns_df["affected_owner_username"].astype(str).str.lower() == current_username_lower)
                ].copy()
            else:
                returns_df = returns_df.loc[
                    returns_df["recorded_by"].astype(str).str.lower()
                    == current_username_lower
                ].copy()

            if get_current_role() in {"admin", "sales"}:
                supplied_item_codes = {str(code).lower() for code in get_supplied_item_codes()}
                inventory_df = inventory_df[
                    inventory_df["item_code"].astype(str).str.lower().isin(supplied_item_codes)
                ].copy()
                return_stock_df = return_stock_df[
                    return_stock_df["item_code"].astype(str).str.lower().isin(supplied_item_codes)
                ].copy()
                returns_df = returns_df[
                    returns_df["item_code"].astype(str).str.lower().isin(supplied_item_codes)
                ].copy()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Quality Control</div>
                <div class="page-title">Returns / Bad Items</div>
                <p class="page-subtitle">Record returned, damaged, defective, or otherwise bad inventory by location.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if st.session_state.get("returns_page_mode") not in {"customer_return", "damage", "view"}:
            st.session_state.returns_page_mode = "customer_return"
        if get_current_role() == "sales" and st.session_state.returns_page_mode == "damage":
            st.session_state.returns_page_mode = "customer_return"
        return_page_col, damage_page_col, view_page_col = st.columns(3)
        with return_page_col:
            if st.button(
                "Customer Return",
                type="primary" if st.session_state.returns_page_mode == "customer_return" else "secondary",
                width="stretch",
                key="show_customer_return_page"
            ):
                st.session_state.returns_page_mode = "customer_return"
                st.rerun()
        with damage_page_col:
            if st.button(
                "Damage / Bad Item" if get_current_role() != "sales" else "Damage / Bad Item (Admin Only)",
                type="primary" if st.session_state.returns_page_mode == "damage" else "secondary",
                width="stretch",
                key="show_damage_page",
                disabled=get_current_role() == "sales"
            ):
                st.session_state.returns_page_mode = "damage"
                st.rerun()
        with view_page_col:
            if st.button(
                "View Records",
                type="primary" if st.session_state.returns_page_mode == "view" else "secondary",
                width="stretch",
                key="show_returns_records_page"
            ):
                st.session_state.returns_page_mode = "view"
                st.rerun()

        if st.session_state.returns_page_mode == "view":
            render_returns_damage_records(returns_df)
            return

        st.session_state.returns_damage_mode = st.session_state.returns_page_mode
        is_customer_return = st.session_state.returns_page_mode == "customer_return"

        return_form_col = st.container()

        with return_form_col:
            form_title = "Record Customer Return" if is_customer_return else "Record Damage / Bad Item"
            st.markdown(f'<div class="dashboard-section-title">{form_title}</div>', unsafe_allow_html=True)

            if locations_df.empty or inventory_df.empty:
                show_next_step(
                    "No active locations are available for your account.",
                    "Ruth should assign your account to an active location before returns can be recorded."
                )

            else:
                location_options = {
                    f"{row['name']} (ID {row['id']})": int(row["id"])
                    for _, row in locations_df.iterrows()
                }
                selected_location = st.selectbox(
                    "Location",
                    list(location_options.keys()),
                    key=f"return_location_{returns_form_reset_counter}"
                )
                location_id = location_options[selected_location]
                selected_return_invoice_id = None

                if is_customer_return:
                    invoice_conn = get_connection()
                    creator_filter = ""
                    invoice_params = [location_id]
                    if get_current_role() in {"admin", "sales"}:
                        creator_filter = " AND LOWER(inv.created_by)=LOWER(?)"
                        invoice_params.append(st.session_state.username)
                    eligible_items_df = pd.read_sql_query(
                        f'''SELECT inv.id AS invoice_id, inv.invoice_number, inv.customer_name,
                                  inv.created_by AS invoice_created_by,
                                  ii.item_code, i.item_name, SUM(ii.quantity) AS sold_quantity,
                                  COALESCE((SELECT SUM(r.quantity) FROM returns r
                                            WHERE r.invoice_id=inv.id
                                              AND LOWER(r.item_code)=LOWER(ii.item_code)
                                              AND r.condition_status IN ('customer_return','customer_return_damaged')
                                              AND r.status='completed'),0) AS returned_quantity
                           FROM invoices inv
                           JOIN invoice_items ii ON ii.invoice_id=inv.id
                           LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(ii.item_code)
                           WHERE inv.location_id=?
                             AND LOWER(COALESCE(inv.status,'')) NOT IN ('cancelled','canceled','void')
                             {creator_filter}
                           GROUP BY inv.id, LOWER(ii.item_code)
                           ORDER BY inv.id DESC''',
                        invoice_conn,
                        params=tuple(invoice_params)
                    )
                    invoice_conn.close()
                    if get_current_role() in {"admin", "sales"}:
                        eligible_items_df = eligible_items_df[
                            eligible_items_df["item_code"].isin(supplied_item_codes)
                        ].copy()
                    if not eligible_items_df.empty:
                        eligible_items_df["returnable_quantity"] = (
                            eligible_items_df["sold_quantity"].astype(int)
                            - eligible_items_df["returned_quantity"].astype(int)
                        ).clip(lower=0)
                        eligible_items_df = eligible_items_df[
                            eligible_items_df["returnable_quantity"] > 0
                        ].copy()
                    if not eligible_items_df.empty:
                        invoice_options = {
                            (
                                f"{row['invoice_number']} - {row['customer_name']}"
                                + (
                                    f" - Created by {row['invoice_created_by']}"
                                    if is_super_admin() else ""
                                )
                            ): int(row["invoice_id"])
                            for _, row in eligible_items_df.drop_duplicates("invoice_id").iterrows()
                        }
                        selected_invoice = st.selectbox(
                            "Customer Invoice",
                            list(invoice_options),
                            key=f"return_invoice_{returns_form_reset_counter}"
                        )
                        selected_return_invoice_id = invoice_options[selected_invoice]
                        eligible_items_df = eligible_items_df[
                            eligible_items_df["invoice_id"] == selected_return_invoice_id
                        ].copy()
                else:
                    eligible_items_df = return_stock_df[
                        return_stock_df["location_id"] == location_id
                    ][["item_code", "item_name"]].drop_duplicates().copy()
                    if get_current_role() == "admin" and not eligible_items_df.empty:
                        owned_items_conn = get_connection()
                        try:
                            owned_item_codes = {
                                str(row[0]).lower()
                                for row in owned_items_conn.execute(
                                    '''SELECT item_code FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=? AND quantity>0''',
                                    (st.session_state.username, location_id)
                                ).fetchall()
                            }
                        finally:
                            owned_items_conn.close()
                        eligible_items_df = eligible_items_df[
                            eligible_items_df["item_code"].astype(str).str.lower().isin(owned_item_codes)
                        ].copy()

                item_options = {
                    f"{row['item_name']} ({row['item_code']})": row["item_code"]
                    for _, row in eligible_items_df.iterrows()
                }
                if not item_options:
                    empty_message = (
                        "No items are available for customer returns at this location."
                        if is_customer_return
                        else "This location has no physical stock available to mark as damaged."
                    )
                    st.info(empty_message)
                else:
                    selected_item = st.selectbox(
                        "Item",
                        list(item_options.keys()),
                        key=f"return_item_{returns_form_reset_counter}"
                    )
                    item_code = item_options[selected_item]
                    stock_match = return_stock_df[
                        (return_stock_df["location_id"] == location_id)
                        & (return_stock_df["item_code"].str.lower() == str(item_code).lower())
                    ]
                    current_stock = int(stock_match["quantity"].iloc[0]) if not stock_match.empty else 0
                    affected_owner_username = None
                    selected_owner_available = 0
                    unowned_here = current_stock
                    visible_current_stock = current_stock
                    if get_current_role() in {"admin", "sales"}:
                        visible_conn = get_connection()
                        try:
                            visible_current_stock = int(
                                visible_conn.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=?
                                         AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, location_id, item_code)
                                ).fetchone()[0] or 0
                            )
                        finally:
                            visible_conn.close()
                    stock_effect = "increase" if is_customer_return else "decrease"
                    st.caption(
                        (
                            f"Your current stock here: {visible_current_stock}. "
                            if get_current_role() in {"admin", "sales"}
                            else f"Current physical stock here: {current_stock}. "
                        )
                        + f"Saving will {stock_effect} this quantity immediately."
                    )
                    if is_super_admin() and not is_customer_return:
                        ownership_conn = get_connection()
                        try:
                            ownership_df = pd.read_sql_query(
                                '''SELECT als.username, COALESCE(u.role,'unknown') AS role,
                                          als.quantity AS owned_quantity
                                   FROM admin_location_stock als
                                   LEFT JOIN users u ON LOWER(u.username)=LOWER(als.username)
                                   WHERE als.location_id=? AND LOWER(als.item_code)=LOWER(?)
                                     AND als.quantity>0
                                   ORDER BY u.role,als.username''',
                                ownership_conn,
                                params=(location_id, item_code)
                            )
                        finally:
                            ownership_conn.close()
                        owned_here = (
                            int(ownership_df["owned_quantity"].sum())
                            if not ownership_df.empty else 0
                        )
                        unowned_here = max(current_stock - owned_here, 0)
                        st.caption(
                            f"Assigned-user ownership here: {owned_here}; "
                            f"unowned company stock here: {unowned_here}. "
                            "Select an owner only when the damage must also reduce assigned stock."
                        )
                        if not ownership_df.empty:
                            st.dataframe(
                                ownership_df,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "username": "Admin / Sales User",
                                    "role": "Role",
                                    "owned_quantity": "Owned Quantity Here",
                                }
                            )
                            damage_owner_options = {"Unowned company stock only": (None, 0)}
                            damage_owner_options.update({
                                f"{row['username']} ({str(row['role']).title()})": (
                                    str(row["username"]), int(row["owned_quantity"])
                                )
                                for _, row in ownership_df.iterrows()
                            })
                            selected_damage_owner = st.selectbox(
                                "Stock Owner Affected by Damage",
                                list(damage_owner_options.keys()),
                                key=f"damage_owner_{location_id}_{item_code}_{returns_form_reset_counter}"
                            )
                            affected_owner_username, selected_owner_available = (
                                damage_owner_options[selected_damage_owner]
                            )

                    limit_conn = get_connection()
                    limit_c = limit_conn.cursor()
                    try:
                        if is_customer_return:
                            limit_c.execute(
                                '''SELECT COALESCE(SUM(ii.quantity),0) FROM invoice_items ii
                                   JOIN invoices inv ON inv.id=ii.invoice_id
                                   WHERE inv.id=? AND inv.location_id=? AND LOWER(ii.item_code)=LOWER(?)
                                     AND LOWER(COALESCE(inv.status,'')) NOT IN ('cancelled','canceled','void')''',
                                (selected_return_invoice_id, location_id, item_code)
                            )
                            sold_quantity_preview = int(limit_c.fetchone()[0] or 0)
                            limit_c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM returns
                                   WHERE invoice_id=? AND location_id=? AND LOWER(item_code)=LOWER(?)
                                     AND condition_status IN ('customer_return','customer_return_damaged')
                                     AND status='completed' ''',
                                (selected_return_invoice_id, location_id, item_code)
                            )
                            maximum_allowed = max(
                                sold_quantity_preview - int(limit_c.fetchone()[0] or 0), 0
                            )
                            if get_current_role() in {"admin", "sales"}:
                                limit_c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                assigned_preview = int(limit_c.fetchone()[0] or 0)
                                limit_c.execute(
                                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                placed_preview = int(limit_c.fetchone()[0] or 0)
                                limit_c.execute(
                                    '''SELECT COALESCE(SUM(quantity),0) FROM returns
                                       WHERE LOWER(item_code)=LOWER(?) AND status='completed'
                                         AND condition_status<>'customer_return'
                                         AND LOWER(COALESCE(NULLIF(affected_owner_username,''),recorded_by))
                                             =LOWER(?)''',
                                    (item_code, st.session_state.username)
                                )
                                remaining_assignment_preview = calculate_remaining_assignment(
                                    assigned_preview, placed_preview, int(limit_c.fetchone()[0] or 0)
                                )
                                maximum_allowed = min(maximum_allowed, remaining_assignment_preview)
                        else:
                            maximum_allowed = current_stock
                            if get_current_role() == "admin":
                                limit_c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=?
                                         AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, location_id, item_code)
                                )
                                maximum_allowed = min(
                                    current_stock, int(limit_c.fetchone()[0] or 0)
                                )
                            elif is_super_admin():
                                maximum_allowed = min(
                                    current_stock,
                                    unowned_here + selected_owner_available
                                )
                    finally:
                        limit_conn.close()

                    # These controls intentionally stay outside st.form so the
                    # before/after preview reruns immediately on every edit.
                    with st.container(border=True):
                        return_quantity = st.number_input(
                            "Quantity",
                            min_value=1,
                            value=None,
                            step=1,
                            placeholder="Enter quantity",
                            key=f"return_quantity_{st.session_state.returns_damage_mode}_{location_id}_{item_code}"
                            + f"_{returns_form_reset_counter}"
                        )
                        if is_customer_return:
                            return_disposition = st.selectbox(
                                "Returned Item Condition",
                                ["Sellable — return to stock", "Damaged / defective — write off"],
                                key=f"return_disposition_{returns_form_reset_counter}"
                            )
                            condition_status = (
                                "customer_return"
                                if return_disposition.startswith("Sellable")
                                else "customer_return_damaged"
                            )
                            st.info(
                                "Sellable returns add stock back. Damaged/defective returns create a permanent "
                                "write-off without increasing stock. Both create an invoice credit and cannot "
                                "exceed sold quantity minus earlier returns."
                            )
                        else:
                            condition_status = st.selectbox(
                                "Condition",
                                ["damaged", "defective", "expired", "bad"],
                                key=f"return_condition_{returns_form_reset_counter}"
                            )
                        return_reason = st.text_area(
                            "Reason",
                            key=(
                                f"return_reason_{st.session_state.returns_damage_mode}_"
                                f"{location_id}_{item_code}_{returns_form_reset_counter}"
                            )
                        )
                        return_quantity_preview = int(return_quantity or 0)
                        quantity_after_preview = (
                            visible_current_stock + return_quantity_preview
                            if is_customer_return and condition_status == "customer_return"
                            else visible_current_stock
                            if is_customer_return
                            else max(visible_current_stock - return_quantity_preview, 0)
                        )
                        quantity_is_valid = (
                            return_quantity is not None
                            and return_quantity_preview > 0
                            and return_quantity_preview <= maximum_allowed
                        )
                        preview_col1, preview_col2, preview_col3 = st.columns(3)
                        preview_col1.metric(
                            "Your Stock Here"
                            if get_current_role() in {"admin", "sales"}
                            else "Physical Stock Now",
                            visible_current_stock
                        )
                        preview_col2.metric("Maximum Allowed", maximum_allowed)
                        preview_col3.metric("After Save", quantity_after_preview)
                        if return_quantity is not None and return_quantity_preview > maximum_allowed:
                            st.warning(
                                f"Only {maximum_allowed} unit(s) are allowed for this action."
                            )
                        submit_label = "Receive Customer Return" if is_customer_return else "Record Damage and Remove Stock"
                        save_return = st.button(
                            submit_label,
                            type="primary",
                            width="stretch",
                            disabled=not quantity_is_valid or not return_reason.strip(),
                            key=(
                                f"save_return_{st.session_state.returns_damage_mode}_"
                                f"{location_id}_{item_code}_{returns_form_reset_counter}"
                            )
                        )

                    if save_return:
                        if not return_reason.strip():
                            st.error("Reason is required.")
                        else:
                            conn = get_connection()
                            try:
                                result = record_return_stock(
                                    conn, st.session_state.username, get_current_role(), location_id,
                                    item_code, return_quantity, return_reason, condition_status,
                                    selected_return_invoice_id, affected_owner_username
                                )
                                st.session_state.returns_saved_message = (
                                    f"{'Return' if is_customer_return else 'Damage / bad item'} saved. "
                                    f"Your stock at this location is now {quantity_after_preview}."
                                    if get_current_role() in {"admin", "sales"}
                                    else f"Stock updated from {result['quantity_before']} to {result['quantity_after']}."
                                )
                                st.session_state.returns_form_reset_counter += 1
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                            finally:
                                conn.close()

    if menu == "Transfers" and has_admin_access():
        if "transfer_message" in st.session_state:
            st.success(st.session_state.pop("transfer_message"))
        if "transfer_form_reset_counter" not in st.session_state:
            st.session_state.transfer_form_reset_counter = 0
        transfer_form_reset_counter = st.session_state.transfer_form_reset_counter
        conn = get_connection()
        locations_df = pd.read_sql_query("SELECT id, name FROM locations WHERE active=1 ORDER BY name", conn)
        inventory_df = pd.read_sql_query("SELECT item_code, item_name FROM inventory ORDER BY item_name", conn)
        transfer_stock_df = pd.read_sql_query(
            '''
            SELECT li.location_id, li.item_code, i.item_name, li.quantity,
                   COALESCE(lp.price,0) AS price,
                   COALESCE((SELECT SUM(t.quantity) FROM inventory_transfers t
                             WHERE t.source_location_id=li.location_id
                               AND LOWER(t.item_code)=LOWER(li.item_code)
                               AND LOWER(t.status)='pending'),0) AS pending_quantity
            FROM location_inventory li
            LEFT JOIN inventory i ON LOWER(i.item_code)=LOWER(li.item_code)
            LEFT JOIN location_prices lp
                ON lp.location_id=li.location_id AND LOWER(lp.item_code)=LOWER(li.item_code)
            WHERE li.quantity>0
            ''',
            conn
        )
        transfers_df = pd.read_sql_query(
            '''
            SELECT t.id, t.source_location_id, t.destination_location_id,
                   t.item_code, i.item_name, src.name AS source_location,
                   dest.name AS destination_location, t.quantity, t.requested_by,
                   t.approved_by, t.status, t.created_at, t.completed_at,
                   COALESCE((SELECT li.quantity FROM location_inventory li
                             WHERE li.location_id=t.source_location_id
                               AND LOWER(li.item_code)=LOWER(t.item_code)),0) AS source_current_quantity,
                   COALESCE((SELECT li.quantity FROM location_inventory li
                             WHERE li.location_id=t.destination_location_id
                               AND LOWER(li.item_code)=LOWER(t.item_code)),0) AS destination_current_quantity
            FROM inventory_transfers t
            LEFT JOIN inventory i ON t.item_code = i.item_code
            LEFT JOIN locations src ON t.source_location_id = src.id
            LEFT JOIN locations dest ON t.destination_location_id = dest.id
            ORDER BY t.id DESC
            ''',
            conn
        )
        conn.close()

        assigned_location_ids = get_assigned_location_ids()
        if not is_super_admin():
            locations_df = locations_df[locations_df["id"].isin(assigned_location_ids)].copy()
            transfer_stock_df = transfer_stock_df[
                transfer_stock_df["location_id"].isin(assigned_location_ids)
            ].copy()
            supplied_item_codes = set(get_supplied_item_codes())
            transfer_stock_df = transfer_stock_df[
                transfer_stock_df["item_code"].isin(supplied_item_codes)
            ].copy()
            inventory_df = inventory_df[inventory_df["item_code"].isin(supplied_item_codes)].copy()
            transfers_df = transfers_df[
                transfers_df["source_location_id"].isin(assigned_location_ids)
                | transfers_df["destination_location_id"].isin(assigned_location_ids)
            ].copy()
            transfers_df = transfers_df.loc[
                transfers_df["requested_by"].astype(str).str.lower()
                == str(st.session_state.username).lower()
            ].copy()

        st.markdown(
            f"""
            <div class="page-header">
                <div class="page-eyebrow">Logistics</div>
                <div class="page-title">Inventory Transfers</div>
                <p class="page-subtitle">{
                    "Track company-wide inventory movement requests between storage locations."
                    if is_super_admin()
                    else "Create and review transfers using only your assigned stock and locations."
                }</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if "transfer_page_mode" not in st.session_state:
            st.session_state.transfer_page_mode = "create"
        create_transfer_col, view_transfer_col = st.columns(2)
        with create_transfer_col:
            if st.button(
                "Create Transfer",
                type="primary" if st.session_state.transfer_page_mode == "create" else "secondary",
                width="stretch",
                key="show_create_transfer_page"
            ):
                st.session_state.transfer_page_mode = "create"
                st.rerun()
        with view_transfer_col:
            if st.button(
                "View Transfers",
                type="primary" if st.session_state.transfer_page_mode == "view" else "secondary",
                width="stretch",
                key="show_transfer_records_page"
            ):
                st.session_state.transfer_page_mode = "view"
                st.rerun()

        if st.session_state.transfer_page_mode == "view":
            render_transfer_records(transfers_df)
            return

        transfer_form_col = st.container()

        with transfer_form_col:
            st.markdown('<div class="dashboard-section-title">Create Transfer</div>', unsafe_allow_html=True)

            if len(locations_df) < 2 or inventory_df.empty:
                show_next_step(
                    "Transfers require at least two active assigned locations and one inventory item.",
                    "Ruth should assign another location, or add inventory before creating a transfer."
                )
            else:
                location_options = {
                    f"{row['name']} (ID {row['id']})": int(row["id"])
                    for _, row in locations_df.iterrows()
                }
                source_location = st.selectbox(
                    "From Location",
                    list(location_options.keys()),
                    key=f"transfer_source_location_{transfer_form_reset_counter}"
                )
                source_location_id_preview = location_options[source_location]
                source_items_df = transfer_stock_df[
                    transfer_stock_df["location_id"] == source_location_id_preview
                ].copy()
                if not is_super_admin() and not source_items_df.empty:
                    conn = get_connection()
                    owned_rows = pd.read_sql_query(
                        '''SELECT als.item_code, als.quantity AS owned_quantity,
                                  COALESCE((SELECT SUM(t.quantity) FROM inventory_transfers t
                                            WHERE t.source_location_id=als.location_id
                                              AND LOWER(t.item_code)=LOWER(als.item_code)
                                              AND LOWER(t.requested_by)=LOWER(?)
                                              AND LOWER(t.status)='pending'),0) AS own_pending_quantity
                           FROM admin_location_stock als
                           WHERE LOWER(als.username)=LOWER(?) AND als.location_id=?''',
                        conn,
                        params=(st.session_state.username, st.session_state.username, source_location_id_preview)
                    )
                    conn.close()
                    source_items_df = source_items_df.merge(owned_rows, on="item_code", how="left")
                    source_items_df["owned_quantity"] = source_items_df["owned_quantity"].fillna(0).astype(int)
                    source_items_df["own_pending_quantity"] = source_items_df["own_pending_quantity"].fillna(0).astype(int)
                else:
                    source_items_df["owned_quantity"] = source_items_df.get("quantity", pd.Series(dtype=int))
                    source_items_df["own_pending_quantity"] = source_items_df.get("pending_quantity", pd.Series(dtype=int))
                if not source_items_df.empty:
                    physical_available = source_items_df["quantity"] - source_items_df["pending_quantity"]
                    owned_available = source_items_df["owned_quantity"] - source_items_df["own_pending_quantity"]
                    source_items_df["transfer_available"] = pd.concat(
                        [physical_available, owned_available], axis=1
                    ).min(axis=1).clip(lower=0).astype(int)
                    source_items_df = source_items_df[source_items_df["transfer_available"] > 0].copy()
                item_options = {
                    f"{row['item_name']} ({row['item_code']}) - {int(row['transfer_available'])} available": row["item_code"]
                    for _, row in source_items_df.iterrows()
                }

                save_transfer = False
                if not item_options:
                    st.info("The selected source has no transferable scoped stock after pending reservations.")
                else:
                    transfer_item = st.selectbox(
                        "Item", list(item_options.keys()),
                        key=f"transfer_item_{transfer_form_reset_counter}"
                    )
                    item_code_preview = item_options[transfer_item]
                    preview_row = source_items_df[source_items_df["item_code"] == item_code_preview].iloc[0]
                    transfer_owner_username = ""
                    selected_owner_capacity = int(preview_row["transfer_available"])
                    if is_super_admin():
                        owner_conn = get_connection()
                        try:
                            transfer_owners_df = pd.read_sql_query(
                                '''SELECT als.username,COALESCE(u.role,'unknown') AS role,als.quantity
                                   FROM admin_location_stock als
                                   LEFT JOIN users u ON LOWER(u.username)=LOWER(als.username)
                                   WHERE als.location_id=? AND LOWER(als.item_code)=LOWER(?)
                                     AND als.quantity>0 ORDER BY u.role,als.username''',
                                owner_conn,
                                params=(source_location_id_preview, item_code_preview),
                            )
                        finally:
                            owner_conn.close()
                        total_owned_preview = int(transfer_owners_df["quantity"].sum()) if not transfer_owners_df.empty else 0
                        generic_preview = max(int(preview_row["quantity"]) - total_owned_preview, 0)
                        transfer_owner_options = {
                            f"Unowned company stock only ({generic_preview} available)": ("", generic_preview),
                            **{
                                f"{row['username']} ({str(row['role']).title()}) — "
                                f"{generic_preview} generic + {int(row['quantity'])} owned":
                                (str(row["username"]), generic_preview + int(row["quantity"]))
                                for _, row in transfer_owners_df.iterrows()
                            },
                        }
                        selected_transfer_owner_label = st.selectbox(
                            "Stock Owner Included in Transfer",
                            list(transfer_owner_options.keys()),
                            key=f"transfer_owner_{transfer_form_reset_counter}_{source_location_id_preview}_{item_code_preview}",
                        )
                        transfer_owner_username, selected_owner_capacity = transfer_owner_options[
                            selected_transfer_owner_label
                        ]
                    destination_options = {
                        label: location_id for label, location_id in location_options.items()
                        if location_id != source_location_id_preview
                    }
                    # Keep transfer controls outside a form so the quantity/status
                    # preview updates immediately on every change.
                    with st.container(border=True):
                        destination_location = st.selectbox(
                            "To Location", list(destination_options.keys()),
                            key=f"transfer_destination_location_{transfer_form_reset_counter}"
                        )
                        transfer_quantity = st.number_input(
                            "Quantity",
                            min_value=1,
                            value=None,
                            step=1,
                            placeholder="Enter quantity to transfer",
                            key=f"transfer_quantity_{transfer_form_reset_counter}"
                        )
                        transfer_status = st.selectbox(
                            "Status",
                            ["completed", "pending"],
                            format_func=lambda status: (
                                "Completed — move stock now"
                                if status == "completed"
                                else "Pending — reserve only"
                            ),
                            key=f"transfer_status_{transfer_form_reset_counter}"
                        )
                        destination_location_id_preview = destination_options[destination_location]
                        destination_preview_rows = transfer_stock_df[
                            (transfer_stock_df["location_id"] == destination_location_id_preview)
                            & (transfer_stock_df["item_code"] == item_code_preview)
                        ]
                        destination_before_preview = (
                            int(destination_preview_rows.iloc[0]["quantity"])
                            if not destination_preview_rows.empty else 0
                        )
                        owned_destination_before_preview = destination_before_preview
                        if not is_super_admin():
                            conn = get_connection()
                            try:
                                owned_destination_row = conn.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=?
                                         AND LOWER(item_code)=LOWER(?)''',
                                    (
                                        st.session_state.username,
                                        destination_location_id_preview,
                                        item_code_preview,
                                    )
                                ).fetchone()
                                owned_destination_before_preview = (
                                    int(owned_destination_row[0] or 0)
                                    if owned_destination_row else 0
                                )
                            finally:
                                conn.close()
                        transfer_quantity_preview = int(transfer_quantity or 0)
                        transfer_available_preview = min(
                            int(preview_row["transfer_available"]), int(selected_owner_capacity)
                        )
                        transfer_quantity_is_valid = (
                            transfer_quantity is not None
                            and transfer_quantity_preview > 0
                            and transfer_quantity_preview <= transfer_available_preview
                        )
                        moves_now = transfer_status == "completed"
                        preview_cols = st.columns(4)
                        if is_super_admin():
                            preview_values = [
                                ("Source Physical Stock", int(preview_row["quantity"])),
                                ("Company Stock Reserved", int(preview_row["pending_quantity"])),
                                (
                                    "Source Physical After",
                                    max(int(preview_row["quantity"]) - transfer_quantity_preview, 0)
                                    if moves_now else int(preview_row["quantity"])
                                ),
                                (
                                    "Destination Physical After",
                                    destination_before_preview + transfer_quantity_preview
                                    if moves_now else destination_before_preview
                                ),
                            ]
                        else:
                            owned_source_preview = int(preview_row["owned_quantity"])
                            own_pending_preview = int(preview_row["own_pending_quantity"])
                            preview_values = [
                                ("My Source Qty", owned_source_preview),
                                ("My Pending Transfers", own_pending_preview),
                                (
                                    "My Source Qty After",
                                    max(owned_source_preview - transfer_quantity_preview, 0)
                                    if moves_now else owned_source_preview
                                ),
                                (
                                    "My Destination Qty After",
                                    owned_destination_before_preview + transfer_quantity_preview
                                    if moves_now else owned_destination_before_preview
                                ),
                            ]
                        for preview_col, (preview_label, preview_value) in zip(preview_cols, preview_values):
                            with preview_col:
                                st.metric(preview_label, preview_value)
                        if transfer_status == "pending":
                            st.info(
                                "Pending reserves this quantity from your available stock but does not move "
                                "your source or destination quantity until the transfer is completed."
                                if not is_super_admin()
                                else "Pending reserves the quantity but does not change either location until completed."
                            )
                        if transfer_quantity is not None and transfer_quantity_preview > transfer_available_preview:
                            st.warning(
                                f"Only {transfer_available_preview} unit(s) are available to transfer."
                            )
                        save_transfer = st.button(
                            "Save Transfer",
                            type="primary",
                            width="stretch",
                            disabled=not transfer_quantity_is_valid,
                            key=f"save_inventory_transfer_{transfer_form_reset_counter}"
                        )

                if save_transfer:
                    if source_location == destination_location:
                        st.error("Source and destination locations must be different for an inventory transfer.")
                    else:
                        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        conn = get_connection()
                        c = conn.cursor()
                        item_code = item_options[transfer_item]
                        source_location_id = location_options[source_location]
                        destination_location_id = location_options[destination_location]
                        transfer_quantity_int = int(transfer_quantity)

                        try:
                            c.execute("BEGIN IMMEDIATE")
                            c.execute(
                                '''SELECT li.quantity FROM location_inventory li
                                   JOIN locations src ON src.id=li.location_id AND src.active=1
                                   JOIN locations dst ON dst.id=? AND dst.active=1
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (destination_location_id, source_location_id, item_code)
                            )
                            locked_source_row = c.fetchone()
                            locked_source_quantity = int(locked_source_row[0] or 0) if locked_source_row else 0
                            c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM inventory_transfers
                                   WHERE source_location_id=? AND LOWER(item_code)=LOWER(?)
                                     AND LOWER(status)='pending' ''',
                                (source_location_id, item_code)
                            )
                            locked_pending_quantity = int(c.fetchone()[0] or 0)
                            locked_owned_quantity = locked_source_quantity
                            locked_own_pending_quantity = locked_pending_quantity
                            if get_current_role() == "admin":
                                c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=?
                                         AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, source_location_id, item_code)
                                )
                                locked_owned_row = c.fetchone()
                                locked_owned_quantity = int(locked_owned_row[0] or 0) if locked_owned_row else 0
                                c.execute(
                                    '''SELECT COALESCE(SUM(quantity),0) FROM inventory_transfers
                                       WHERE source_location_id=? AND LOWER(item_code)=LOWER(?)
                                         AND LOWER(requested_by)=LOWER(?)
                                         AND LOWER(status)='pending' ''',
                                    (source_location_id, item_code, st.session_state.username)
                                )
                                locked_own_pending_quantity = int(c.fetchone()[0] or 0)
                            locked_transfer_available = max(
                                min(
                                    locked_source_quantity - locked_pending_quantity,
                                    locked_owned_quantity - locked_own_pending_quantity
                                ),
                                0
                            )
                            if is_super_admin():
                                c.execute(
                                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                       WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                    (source_location_id, item_code),
                                )
                                locked_total_owned = int(c.fetchone()[0] or 0)
                                locked_generic = max(locked_source_quantity - locked_total_owned, 0)
                                locked_selected_owner = 0
                                if transfer_owner_username:
                                    c.execute(
                                        '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                           WHERE LOWER(username)=LOWER(?) AND location_id=?
                                             AND LOWER(item_code)=LOWER(?)''',
                                        (transfer_owner_username, source_location_id, item_code),
                                    )
                                    locked_selected_owner = int(c.fetchone()[0] or 0)
                                locked_transfer_available = min(
                                    locked_transfer_available,
                                    locked_generic + locked_selected_owner,
                                )
                            if transfer_quantity_int > locked_transfer_available:
                                conn.rollback()
                                st.error(
                                    f"Only {locked_transfer_available} unit(s) remain transferable after "
                                    "source stock, Admin ownership, and pending reservations are checked."
                                )
                                st.stop()

                            if transfer_status == "completed":
                                c.execute(
                                    '''
                                    SELECT quantity FROM location_inventory
                                    WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                    ''',
                                    (source_location_id, item_code)
                                )
                                source_stock = c.fetchone()
                                source_quantity = int(source_stock[0]) if source_stock else 0

                                c.execute(
                                    '''
                                    UPDATE location_inventory
                                    SET quantity=?
                                    WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                    ''',
                                    (source_quantity - transfer_quantity_int, source_location_id, item_code)
                                )
                                if source_quantity - transfer_quantity_int == 0:
                                    c.execute(
                                        "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                        (source_location_id, item_code)
                                    )
                                if get_current_role() == "admin":
                                    c.execute(
                                        '''
                                        SELECT COALESCE(quantity, 0) FROM admin_location_stock
                                        WHERE LOWER(username)=LOWER(?) AND location_id=?
                                          AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (st.session_state.username, source_location_id, item_code)
                                    )
                                    owned_source_row = c.fetchone()
                                    owned_quantity_to_move = min(
                                        int(owned_source_row[0] or 0) if owned_source_row else 0,
                                        transfer_quantity_int
                                    )
                                    if owned_quantity_to_move > 0:
                                        c.execute(
                                            '''
                                            UPDATE admin_location_stock SET quantity=quantity-?
                                            WHERE LOWER(username)=LOWER(?) AND location_id=?
                                              AND LOWER(item_code)=LOWER(?)
                                            ''',
                                            (owned_quantity_to_move, st.session_state.username, source_location_id, item_code)
                                        )
                                        c.execute(
                                            '''
                                            INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                                            VALUES (?,?,?,?)
                                            ON CONFLICT(username,location_id,item_code)
                                            DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity
                                            ''',
                                            (st.session_state.username, destination_location_id, item_code, owned_quantity_to_move)
                                        )
                                else:
                                    c.execute(
                                        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                           WHERE location_id=? AND LOWER(item_code)=LOWER(?) AND quantity>0''',
                                        (source_location_id, item_code)
                                    )
                                    total_owned_at_source = int(c.fetchone()[0] or 0)
                                    unowned_at_source = max(source_quantity - total_owned_at_source, 0)
                                    remaining_owned_move = max(transfer_quantity_int - unowned_at_source, 0)
                                    if remaining_owned_move > 0:
                                        owner_username = transfer_owner_username
                                        owner_move = remaining_owned_move
                                        c.execute(
                                            '''UPDATE admin_location_stock SET quantity=quantity-?
                                               WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                                            (owner_move, owner_username, source_location_id, item_code)
                                        )
                                        c.execute(
                                            '''INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                                               VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                                               DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                                            (owner_username, destination_location_id, item_code, owner_move)
                                        )
                                c.execute(
                                    '''
                                    INSERT INTO location_stock_history
                                    (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                    VALUES (?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        source_location_id, item_code, source_quantity,
                                        -transfer_quantity_int, source_quantity - transfer_quantity_int,
                                        "Transfer Out", st.session_state.username, now
                                    )
                                )
                                c.execute(
                                    '''
                                    SELECT COALESCE(quantity, 0) FROM location_inventory
                                    WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                    ''',
                                    (destination_location_id, item_code)
                                )
                                destination_stock_row = c.fetchone()
                                destination_quantity_before = (
                                    int(destination_stock_row[0] or 0) if destination_stock_row else 0
                                )
                                c.execute(
                                    '''
                                    INSERT INTO location_inventory (location_id,item_code,quantity)
                                    VALUES (?,?,?)
                                    ON CONFLICT(location_id,item_code)
                                    DO UPDATE SET quantity=location_inventory.quantity + excluded.quantity
                                    ''',
                                    (destination_location_id, item_code, transfer_quantity_int)
                                )
                                c.execute(
                                    '''SELECT price FROM location_prices
                                       WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                    (destination_location_id, item_code)
                                )
                                if c.fetchone() is None:
                                    c.execute(
                                        '''INSERT INTO location_prices (location_id,item_code,price)
                                           SELECT ?,item_code,price FROM location_prices
                                           WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                        (destination_location_id, source_location_id, item_code)
                                    )
                                c.execute(
                                    '''
                                    INSERT INTO location_stock_history
                                    (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                    VALUES (?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        destination_location_id, item_code, destination_quantity_before,
                                        transfer_quantity_int, destination_quantity_before + transfer_quantity_int,
                                        "Transfer In", st.session_state.username, now
                                    )
                                )
                                audit_owner_username = (
                                    st.session_state.username
                                    if get_current_role() == "admin"
                                    else transfer_owner_username or None
                                )
                                for audit_location_id, audit_before, audit_after, audit_type in (
                                    (source_location_id, source_quantity,
                                     source_quantity - transfer_quantity_int, "transfer_out"),
                                    (destination_location_id, destination_quantity_before,
                                     destination_quantity_before + transfer_quantity_int, "transfer_in"),
                                ):
                                    c.execute(
                                        '''INSERT INTO transactions
                                           (username,item_code,quantity_used,quantity_before,quantity_after,
                                            transaction_type,source_type,location_id,transaction_time,
                                            affected_owner_username)
                                           VALUES (?,?,?,?,?,?,?,?,?,?)''',
                                        (
                                            st.session_state.username, item_code, transfer_quantity_int,
                                            audit_before, audit_after, audit_type, "location_stock",
                                            audit_location_id, now, audit_owner_username,
                                        ),
                                    )

                            c.execute(
                                '''
                                INSERT INTO inventory_transfers
                                (item_code,source_location_id,destination_location_id,quantity,requested_by,
                                 approved_by,status,created_at,completed_at,affected_owner_username)
                                VALUES (?,?,?,?,?,?,?,?,?,?)
                                ''',
                                (
                                    item_code,
                                    source_location_id,
                                    destination_location_id,
                                    transfer_quantity_int,
                                    st.session_state.username,
                                    st.session_state.username if transfer_status == "completed" else None,
                                    transfer_status,
                                    now,
                                    now if transfer_status == "completed" else None,
                                    transfer_owner_username or (
                                        st.session_state.username if get_current_role() == "admin" else None
                                    )
                                )
                            )
                            conn.commit()
                            if transfer_status == "completed":
                                st.session_state.transfer_message = (
                                    f"Transfer completed. Source quantity changed from {source_quantity} to "
                                    f"{source_quantity-transfer_quantity_int}; destination changed from "
                                    f"{destination_quantity_before} to "
                                    f"{destination_quantity_before+transfer_quantity_int}."
                                )
                            else:
                                st.session_state.transfer_message = (
                                    f"Pending transfer saved. {transfer_quantity_int} unit(s) are reserved; "
                                    "location quantities have not changed."
                                )
                            st.session_state.transfer_form_reset_counter += 1
                            st.rerun()
                        finally:
                            conn.close()

        # Create mode ends here; transfer history is rendered only by View Transfers.
        return
