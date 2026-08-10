
import streamlit as st
import streamlit.components.v1 as components
import importlib
import sqlite3
import sys
import pandas as pd
from datetime import datetime

import auth
from auth import add_default_admin, hash_password, login
from db import get_connection, init_db
from utils import decode_qr_from_image, generate_qr, image_to_base64, safe_html

for role_module_name in (
    "role_modules.admin_pages",
    "role_modules.sales_pages",
    "role_modules.super_admin_pages",
    "role_modules.user_pages",
):
    sys.modules.pop(role_module_name, None)

admin_pages = importlib.import_module("role_modules.admin_pages")
sales_pages = importlib.import_module("role_modules.sales_pages")
super_admin_pages = importlib.import_module("role_modules.super_admin_pages")
user_pages = importlib.import_module("role_modules.user_pages")

init_db()
add_default_admin()

st.set_page_config(page_title="Inventory Management", layout="wide")

SUPER_ADMIN_USERNAME = getattr(auth, "SUPER_ADMIN_USERNAME", "Ruth")
ADMIN_ROLES = {"super_admin", "admin"}
STANDARD_WORKFLOW_ROLES = {"user", "sales"}


def normalize_role(username, role):
    if hasattr(auth, "normalize_role"):
        return auth.normalize_role(username, role)

    valid_roles = {"super_admin", "admin", "sales", "user"}
    if role not in valid_roles:
        return "user"

    if role == "super_admin" and username.strip().lower() != SUPER_ADMIN_USERNAME.lower():
        return "admin"

    return role


def get_current_role():
    return normalize_role(
        st.session_state.get("username", ""),
        st.session_state.get("role", "user")
    )


def has_admin_access():
    return get_current_role() in ADMIN_ROLES


def is_super_admin():
    return get_current_role() == "super_admin"


def logout_user():
    keys_to_clear = [
        "logged_in",
        "username",
        "role",
        "menu",
    ]

    for key in keys_to_clear:
        st.session_state.pop(key, None)

    st.session_state.logged_in = False


def get_assigned_location_ids(username=None):
    username = username or st.session_state.get("username", "")

    if not username:
        return []

    conn = get_connection()
    assigned_df = pd.read_sql_query(
        "SELECT location_id FROM user_locations WHERE LOWER(username)=LOWER(?)",
        conn,
        params=(username,)
    )
    conn.close()

    if assigned_df.empty:
        return []

    return assigned_df["location_id"].astype(int).tolist()


def get_supplied_item_codes(username=None):
    username = username or st.session_state.get("username", "")

    if not username:
        return []

    conn = get_connection()
    supplied_df = pd.read_sql_query(
        "SELECT item_code FROM product_suppliers WHERE LOWER(username)=LOWER(?)",
        conn,
        params=(username,)
    )
    conn.close()

    if supplied_df.empty:
        return []

    return supplied_df["item_code"].astype(str).tolist()


def get_assigned_product_quantity(username, item_code):
    if not username or not item_code:
        return 0

    conn = get_connection()
    c = conn.cursor()
    c.execute(
        '''
        SELECT COALESCE(SUM(quantity), 0)
        FROM admin_product_allocations
        WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
        ''',
        (username, item_code)
    )
    allocation_row = c.fetchone()
    conn.close()

    return int(allocation_row[0] or 0) if allocation_row else 0


ITEM_CODE_REFERENCE_TABLES = [
    ("user_inventory", "item_code"),
    ("transactions", "item_code"),
    ("location_inventory", "item_code"),
    ("location_prices", "item_code"),
    ("invoice_items", "item_code"),
    ("returns", "item_code"),
    ("inventory_transfers", "item_code"),
    ("product_suppliers", "item_code"),
    ("admin_product_allocations", "item_code"),
    ("admin_location_stock", "item_code"),
]


LIVE_ITEM_CODE_REFERENCE_TABLES = [
    ("user_inventory", "item_code"),
    ("location_inventory", "item_code"),
    ("location_prices", "item_code"),
    ("product_suppliers", "item_code"),
    ("admin_product_allocations", "item_code"),
    ("admin_location_stock", "item_code"),
]


def update_item_code_references(cursor, old_item_code, new_item_code):
    for table_name, column_name in ITEM_CODE_REFERENCE_TABLES:
        cursor.execute(
            f"UPDATE {table_name} SET {column_name}=? WHERE LOWER({column_name})=LOWER(?)",
            (new_item_code, old_item_code)
        )


def delete_item_code_references(cursor, item_code):
    for table_name, column_name in LIVE_ITEM_CODE_REFERENCE_TABLES:
        cursor.execute(
            f"DELETE FROM {table_name} WHERE {column_name}=?",
            (item_code,)
        )


def get_item_delete_blockers(cursor, item_code):
    blocker_queries = [
        ("assigned user stock", "SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_code=?", "stock unit(s)"),
        ("location stock", "SELECT COALESCE(SUM(quantity), 0) FROM location_inventory WHERE item_code=?", "stock unit(s)"),
        ("location pricing", "SELECT COUNT(*) FROM location_prices WHERE item_code=?", "pricing record(s)"),
        ("supplier assignments", "SELECT COUNT(*) FROM product_suppliers WHERE item_code=?", "assignment(s)"),
        ("admin assigned quantities", "SELECT COUNT(*) FROM admin_product_allocations WHERE item_code=?", "assignment(s)"),
        ("transactions", "SELECT COUNT(*) FROM transactions WHERE item_code=?", "transaction(s)"),
        ("invoice items", "SELECT COUNT(*) FROM invoice_items WHERE item_code=?", "invoice item(s)"),
        ("returns", "SELECT COUNT(*) FROM returns WHERE item_code=?", "return record(s)"),
        ("inventory transfers", "SELECT COUNT(*) FROM inventory_transfers WHERE item_code=?", "transfer record(s)"),
    ]
    blockers = []

    for label, query, unit_label in blocker_queries:
        cursor.execute(query, (item_code,))
        related_count = int(cursor.fetchone()[0] or 0)
        if related_count > 0:
            blockers.append(f"{label}: {related_count} {unit_label}")

    return blockers


def get_invoice_balance(cursor, invoice_id):
    cursor.execute(
        '''
        SELECT MAX(
                   inv.total
                   - COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id),0)
                   - COALESCE((SELECT SUM(ic.amount) FROM invoice_credits ic WHERE ic.invoice_id=inv.id),0),
                   0
               )
        FROM invoices inv
        WHERE inv.id=?
        ''',
        (invoice_id,)
    )
    balance_row = cursor.fetchone()
    return float(balance_row[0]) if balance_row else None


def transaction_verification_status(row):
    transaction_type = row.get("transaction_type", "legacy")
    quantity_before = int(row.get("quantity_before") or 0)
    quantity_used = int(row.get("quantity_used") or 0)
    quantity_after = int(row.get("quantity_after") or 0)

    transaction_type = str(transaction_type or "legacy").strip().lower()
    decrease_types = {
        "sale", "return", "take_out", "damage", "transfer_out",
        "stock_relocation_out", "inventory_move_out", "inventory_adjustment_remove",
        "inventory_location_remove",
    }
    increase_types = {
        "allocation", "customer_return", "invoice_void", "inventory_entry",
        "transfer_in", "stock_relocation_in", "inventory_move_in",
        "inventory_adjustment_add", "location_stock_add",
    }
    unchanged_types = {"customer_return_damaged"}
    if transaction_type in decrease_types:
        expected_after = quantity_before - quantity_used
    elif transaction_type in increase_types:
        expected_after = quantity_before + quantity_used
    elif transaction_type in unchanged_types:
        expected_after = quantity_before
    elif transaction_type == "stock_ownership_assignment":
        return "Verified" if quantity_before <= quantity_after <= quantity_before + quantity_used else "Review"
    else:
        return "Unverified"

    return "Verified" if expected_after == quantity_after else "Review"


def render_setup_checklist():
    role = get_current_role()
    username = st.session_state.get("username", "")

    conn = get_connection()
    locations_count = conn.execute(
        "SELECT COUNT(*) FROM locations WHERE active=1"
    ).fetchone()[0]
    inventory_count = conn.execute(
        "SELECT COUNT(*) FROM inventory"
    ).fetchone()[0]
    location_stock_count = conn.execute(
        "SELECT COUNT(*) FROM location_inventory WHERE quantity > 0"
    ).fetchone()[0]
    assigned_location_count = conn.execute(
        "SELECT COUNT(*) FROM user_locations WHERE username=?",
        (username,)
    ).fetchone()[0]
    supplied_product_count = conn.execute(
        "SELECT COUNT(*) FROM product_suppliers WHERE username=?",
        (username,)
    ).fetchone()[0]
    personal_stock_count = conn.execute(
        "SELECT COUNT(*) FROM user_inventory WHERE username=? AND quantity > 0",
        (username,)
    ).fetchone()[0]

    assigned_stock_count = 0
    supplied_assigned_stock_count = 0

    if assigned_location_count:
        assigned_stock_count = conn.execute(
            '''
            SELECT COUNT(*)
            FROM location_inventory li
            INNER JOIN user_locations ul ON ul.location_id = li.location_id
            INNER JOIN location_prices lp
                ON lp.location_id=li.location_id AND lp.item_code=li.item_code
            WHERE ul.username=? AND li.quantity > 0 AND lp.price > 0
              AND (
                  NOT EXISTS (SELECT 1 FROM product_suppliers ps0 WHERE ps0.username=?)
                  OR EXISTS (
                      SELECT 1 FROM product_suppliers ps
                      WHERE ps.username=? AND ps.item_code=li.item_code
                  )
              )
            ''',
            (username, username, username)
        ).fetchone()[0]

    if assigned_location_count and supplied_product_count:
        supplied_assigned_stock_count = conn.execute(
            '''
            SELECT COUNT(*)
            FROM location_inventory li
            INNER JOIN user_locations ul ON ul.location_id = li.location_id
            INNER JOIN product_suppliers ps ON ps.item_code = li.item_code
            WHERE ul.username=? AND ps.username=? AND li.quantity > 0
            ''',
            (username, username)
        ).fetchone()[0]

    conn.close()

    if role == "super_admin":
        checks = [
            ("Active locations", locations_count > 0, "Create at least one storage location."),
            ("Master inventory", inventory_count > 0, "Add inventory items to the master list."),
            ("Location stock", location_stock_count > 0, "Add quantity and pricing in Location Inventory."),
        ]
    elif role == "admin":
        checks = [
            ("Assigned location", assigned_location_count > 0, "Ruth must assign this admin to a location."),
            ("Supplied products", supplied_product_count > 0, "Ruth must assign products supplied by this admin."),
            ("Invoice-ready stock", supplied_assigned_stock_count > 0, "Add stock for supplied products at assigned locations."),
        ]
    elif role == "sales":
        checks = [
            ("Assigned location", assigned_location_count > 0, "Ruth must assign this sales user to a location."),
            ("Sellable stock", assigned_stock_count > 0, "Add stock and pricing for assigned locations."),
        ]
    else:
        checks = [
            ("Master inventory available", inventory_count > 0, "An admin must add inventory first."),
            ("Personal stock", personal_stock_count > 0, "Use Scan Inventory to add stock to your account."),
        ]

    complete_count = sum(1 for _, complete, _ in checks if complete)
    total_count = len(checks)
    setup_percent = int((complete_count / max(total_count, 1)) * 100)
    progress_segments = []
    detail_rows = []

    for index, (label, complete, next_step) in enumerate(checks, start=1):
        status = "Ready" if complete else "Needs setup"
        segment_class = "ready" if complete else "pending"
        segment_title = safe_html(f"{label}: {status}")
        label_safe = safe_html(label)
        detail_safe = safe_html("Complete" if complete else next_step)

        progress_segments.append(
            f'<div class="setup-level-segment {segment_class}" title="{segment_title}">'
            f'<span>{label_safe}</span>'
            f'</div>'
        )
        detail_rows.append(
            f'<div class="setup-barcode-row">'
            f'<span class="setup-barcode-index">{index}</span>'
            f'<span class="setup-barcode-name">{label_safe}</span>'
            f'<span class="setup-barcode-status {segment_class}">{status}</span>'
            f'</div>'
            f'<div class="setup-barcode-detail">{detail_safe}</div>'
        )

    st.markdown(
        f"""
        <style>
        .setup-barcode-card {{
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.72);
            padding: 0.65rem 0.75rem;
            margin-bottom: 0.8rem;
        }}

        .setup-barcode-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.45rem;
        }}

        .setup-barcode-title {{
            color: #0f172a;
            font-size: 0.9rem;
            font-weight: 800;
        }}

        .setup-barcode-level {{
            color: #475569;
            font-size: 0.78rem;
            font-weight: 700;
            white-space: nowrap;
        }}

        .setup-level-track {{
            display: grid;
            grid-template-columns: repeat({total_count}, minmax(0, 1fr));
            gap: 6px;
            min-height: 32px;
            margin-bottom: 0.5rem;
        }}

        .setup-level-segment {{
            position: relative;
            min-width: 0;
            border-radius: 999px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0 0.25rem;
            border: 1px solid rgba(15, 23, 42, 0.1);
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
        }}

        .setup-level-segment.ready {{
            background: linear-gradient(135deg, #15803d, #22c55e);
        }}

        .setup-level-segment.pending {{
            background: #f8fafc;
        }}

        .setup-level-segment span {{
            max-width: 100%;
            color: #ffffff;
            padding: 0.08rem 0.35rem;
            font-size: 0.68rem;
            font-weight: 800;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}

        .setup-level-segment.pending span {{
            color: #334155;
        }}

        .setup-barcode-progress {{
            height: 5px;
            background: #e2e8f0;
            border-radius: 999px;
            overflow: hidden;
            margin-bottom: 0.45rem;
        }}

        .setup-barcode-progress-fill {{
            height: 100%;
            width: {setup_percent}%;
            background: #16a34a;
        }}

        .setup-barcode-row {{
            display: grid;
            grid-template-columns: 1.7rem 1fr auto;
            gap: 0.45rem;
            align-items: center;
            color: #0f172a;
            font-size: 0.76rem;
            line-height: 1.2;
        }}

        .setup-barcode-index {{
            color: #64748b;
            font-weight: 800;
        }}

        .setup-barcode-name {{
            font-weight: 800;
        }}

        .setup-barcode-status {{
            font-weight: 800;
            font-size: 0.72rem;
        }}

        .setup-barcode-status.ready {{
            color: #15803d;
        }}

        .setup-barcode-status.pending {{
            color: #b45309;
        }}

        .setup-barcode-detail {{
            color: #64748b;
            font-size: 0.72rem;
            margin: 0.05rem 0 0.28rem 2.15rem;
            line-height: 1.2;
        }}
        </style>
        <div class="setup-barcode-card">
            <div class="setup-barcode-head">
                <div class="setup-barcode-title">Setup Progress</div>
                <div class="setup-barcode-level">{complete_count}/{total_count} ready · {setup_percent}%</div>
            </div>
            <div class="setup-level-track">
                {''.join(progress_segments)}
            </div>
            <div class="setup-barcode-progress">
                <div class="setup-barcode-progress-fill"></div>
            </div>
            {''.join(detail_rows)}
        </div>
        """,
        unsafe_allow_html=True
    )


def format_currency(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def stock_status(quantity):
    quantity = int(quantity or 0)

    if quantity <= 0:
        return "Out of stock"
    if quantity <= 5:
        return "Low stock"
    return "In stock"


def invoice_status_label(status, outstanding):
    if str(status).lower() == "paid" or float(outstanding or 0) <= 0:
        return "Paid"
    return "Open balance"


def is_paid_label(total, paid, outstanding):
    if float(outstanding or 0) <= 0:
        return "Yes"
    if float(paid or 0) > 0:
        return "Partially Paid"
    return "No"


def show_next_step(message, next_step):
    st.info(f"{message}\n\nNext step: {next_step}")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.12), transparent 32rem),
                linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        [data-testid="stMain"] {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }

        .block-container {
            max-width: 420px !important;
            margin: 0 auto !important;
            padding: 2rem 1rem !important;
        }

        [data-testid="stMainBlockContainer"] {
            width: 100%;
            max-width: 420px;
        }

        [data-testid="stForm"] {
            width: 100%;
            background: #ffffff;
            border: 1px solid #d8e0ea;
            border-radius: 16px;
            padding: 1.5rem 1.75rem 1.65rem;
            box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
        }

        .login-logo {
            width: 84px;
            height: 84px;
            margin: 0 auto 1rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2563eb, #22c55e);
            color: #ffffff;
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: 0;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
            margin-bottom: 0.65rem;
        }

        [data-testid="stForm"] h1 {
            text-align: center;
            color: #111827;
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.1rem;
            padding-bottom: 0;
        }

        [data-testid="stForm"] p {
            text-align: center;
            color: #64748b;
            margin-top: 0;
            margin-bottom: 0.85rem;
        }

        [data-testid="stForm"] label {
            color: #334155;
            font-weight: 600;
        }

        [data-testid="stForm"] label p {
            margin: 0;
            line-height: 1.2;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] {
            margin-bottom: 0.55rem;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] > label {
            margin-bottom: 0.25rem;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] > div {
            margin-top: 0;
        }

        [data-testid="stForm"] input {
            border-radius: 10px;
        }

        [data-testid="stFormSubmitButton"] button {
            width: 100%;
            border: 0;
            border-radius: 10px;
            background: #2563eb;
            color: #ffffff;
            min-height: 2.5rem;
            height: 2.5rem;
            padding: 0 1rem;
            transition: background 0.15s ease, transform 0.15s ease;
        }

        [data-testid="stFormSubmitButton"] button p {
            color: #ffffff;
            font-weight: 700;
            line-height: 1;
            margin: 0;
            padding: 0;
        }

        [data-testid="stFormSubmitButton"] button:hover {
            background: #1d4ed8;
            color: #ffffff;
            transform: translateY(-1px);
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.form("login_form"):
        st.markdown('<div class="login-logo">IM</div>', unsafe_allow_html=True)
        st.title("Inventory Login")
        st.caption("Sign in to manage stock and usage logs.")

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        login_submitted = st.form_submit_button("Login")

    if login_submitted:
        user = login(username, password)

        if user:
            st.session_state.logged_in = True
            st.session_state.username = user[1]
            st.session_state.role = user[3]
            st.session_state.menu = "Dashboard"
            st.success("Login successful. Loading your role-based dashboard now.")
            st.rerun()
        else:
            st.error("Invalid username or password. Check the account details and try again.")

else:
    st.session_state.role = get_current_role()

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(111, 132, 23, 0.12), transparent 28rem),
                linear-gradient(135deg, #f8faf7 0%, #eef3f0 100%);
        }

        [data-testid="stMainBlockContainer"] {
            padding-top: 5rem;
        }

        [data-testid="stSidebar"] {
            background: #d9e4f2;
        }

        [data-testid="stSidebar"] > div:first-child {
            background: transparent;
            padding-top: 1.25rem;
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            margin-bottom: 0.85rem;
        }

        .sidebar-brand-mark {
            width: 42px;
            height: 42px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            font-size: 0.85rem;
            font-weight: 800;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.28);
        }

        .sidebar-brand-title {
            color: #0f172a;
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.1;
        }

        .sidebar-brand-subtitle {
            color: #475569;
            font-size: 0.78rem;
            font-weight: 500;
            line-height: 1.2;
            margin-top: 0.15rem;
        }

        .sidebar-section-label {
            color: #334155;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0;
            margin: 0.55rem 0 0.25rem;
            text-transform: uppercase;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] hr {
            margin-top: 0.25rem;
            margin-bottom: 0.25rem;
            border-color: rgba(15, 23, 42, 0.16);
        }

        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(hr) {
            margin: 0 !important;
            padding: 0 !important;
        }

        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
            justify-content: flex-start;
            text-align: left;
            border-radius: 6px;
            border: 0;
            background: transparent;
            color: #0f172a;
            box-shadow: none;
            font-size: 0.92rem;
            font-weight: 650;
            min-height: 2rem;
            padding: 0.25rem 0.65rem;
        }

        [data-testid="stSidebar"] .stButton > button div {
            justify-content: flex-start;
            text-align: left;
            width: 100%;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(255, 255, 255, 0.35);
            color: #0f172a;
            box-shadow: inset 3px 0 0 rgba(37, 99, 235, 0.65);
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: rgba(37, 99, 235, 0.12);
            color: #1d4ed8;
            box-shadow: inset 3px 0 0 #2563eb;
        }

        [data-testid="stSidebar"] .stButton > button p {
            color: inherit;
        }

        [data-testid="stSidebar"] .stButton > button p {
            margin: 0;
            line-height: 1.1;
            text-align: left;
            width: 100%;
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"] p {
            color: #1d4ed8;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }

        .page-header {
            margin-top: 0.25rem;
            margin-bottom: 1.25rem;
        }

        .page-eyebrow {
            color: #667d16;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }

        .page-title {
            color: #31333f;
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.15;
            margin-bottom: 0.25rem;
        }

        .page-subtitle {
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.98rem;
            margin-bottom: 0;
        }

        .dashboard-card {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            min-height: 118px;
        }

        .dashboard-card-label {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 0.45rem;
        }

        .dashboard-card-value {
            color: #31333f;
            font-size: 1.85rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.45rem;
        }

        .dashboard-card-note {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.8rem;
        }

        .dashboard-section-title {
            color: #31333f;
            font-size: 1.05rem;
            font-weight: 800;
            margin: 1.35rem 0 0.4rem;
        }

        :root,
        .stApp,
        [data-testid="stAppViewContainer"] {
            --primary-color: #1d4ed8 !important;
            --primary-color-hover: #2563eb !important;
            --primary-color-active: #1e40af !important;
        }

        div[data-testid="stTabs"] [role="tablist"] {
            gap: 0.8rem !important;
            border-bottom: 0 !important;
            margin: 0.65rem 0 1.1rem !important;
        }

        div[data-testid="stTabs"] button[role="tab"] {
            background: #eaf2ff !important;
            border: 2px solid #8bb7f0 !important;
            border-radius: 8px !important;
            color: #0f3f86 !important;
            font-size: 0.95rem !important;
            font-weight: 850 !important;
            min-height: 2.75rem !important;
            padding: 0.62rem 1.15rem !important;
            box-shadow: 0 8px 16px rgba(15, 63, 134, 0.11) !important;
        }

        div[data-testid="stTabs"] button[role="tab"] p {
            color: inherit !important;
            font-size: 0.95rem !important;
            font-weight: 850 !important;
        }

        div[data-testid="stTabs"] button[role="tab"]:hover {
            background: #dbeafe !important;
            border-color: #2563eb !important;
        }

        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
            background: #1d4ed8 !important;
            border-color: #1d4ed8 !important;
            color: #ffffff !important;
            box-shadow: 0 10px 20px rgba(29, 78, 216, 0.24) !important;
        }

        div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p {
            color: #ffffff !important;
        }

        div[data-testid="stSegmentedControl"] {
            --primary-color: #1d4ed8 !important;
        }

        div[data-testid="stSegmentedControl"] [role="radiogroup"] {
            gap: 0.45rem !important;
        }

        div[data-testid="stSegmentedControl"] button,
        div[data-testid="stSegmentedControl"] label,
        div[data-testid="stSegmentedControl"] [role="radio"] {
            background: #eaf2ff !important;
            border: 1.5px solid #8bb7f0 !important;
            border-radius: 8px !important;
            color: #0f3f86 !important;
            font-size: 0.95rem !important;
            font-weight: 850 !important;
            min-height: 2.65rem !important;
            padding: 0.55rem 1.05rem !important;
            box-shadow: 0 6px 14px rgba(29, 78, 216, 0.1) !important;
        }

        div[data-testid="stSegmentedControl"] button:hover,
        div[data-testid="stSegmentedControl"] label:hover,
        div[data-testid="stSegmentedControl"] [role="radio"]:hover {
            background: #dbeafe !important;
            border-color: #2563eb !important;
            color: #0f3f86 !important;
        }

        div[data-testid="stSegmentedControl"] button[aria-pressed="true"],
        div[data-testid="stSegmentedControl"] button[aria-checked="true"],
        div[data-testid="stSegmentedControl"] label[aria-checked="true"],
        div[data-testid="stSegmentedControl"] label[data-checked="true"],
        div[data-testid="stSegmentedControl"] [role="radio"][aria-checked="true"],
        div[data-testid="stSegmentedControl"] [data-selected="true"],
        div[data-testid="stSegmentedControl"] label:has(input:checked) {
            background: #1d4ed8 !important;
            border-color: #1d4ed8 !important;
            color: #ffffff !important;
            box-shadow: 0 9px 18px rgba(29, 78, 216, 0.22) !important;
        }

        div[data-testid="stSegmentedControl"] button[aria-pressed="true"] *,
        div[data-testid="stSegmentedControl"] button[aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] label[aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] label[data-checked="true"] *,
        div[data-testid="stSegmentedControl"] [role="radio"][aria-checked="true"] *,
        div[data-testid="stSegmentedControl"] [data-selected="true"] *,
        div[data-testid="stSegmentedControl"] label:has(input:checked) * {
            color: #ffffff !important;
        }

        .st-key-inventory_section_buttons div.stButton > button,
        .st-key-locations_section_buttons div.stButton > button {
            border-radius: 8px !important;
            min-height: 2.75rem !important;
            font-size: 0.95rem !important;
            font-weight: 850 !important;
            border: 1.5px solid #93c5fd !important;
            box-shadow: 0 8px 18px rgba(30, 64, 175, 0.1) !important;
        }

        .st-key-inventory_section_buttons div.stButton > button[kind="secondary"],
        .st-key-locations_section_buttons div.stButton > button[kind="secondary"] {
            background: #eff6ff !important;
            color: #1e3a8a !important;
        }

        .st-key-inventory_section_buttons div.stButton > button[kind="secondary"]:hover,
        .st-key-locations_section_buttons div.stButton > button[kind="secondary"]:hover {
            background: #dbeafe !important;
            border-color: #2563eb !important;
            color: #1d4ed8 !important;
            transform: translateY(-1px);
        }

        .st-key-inventory_section_buttons div.stButton > button[kind="primary"],
        .st-key-locations_section_buttons div.stButton > button[kind="primary"] {
            background: #1e40af !important;
            border-color: #1e40af !important;
            color: #ffffff !important;
            box-shadow: 0 12px 24px rgba(30, 64, 175, 0.25) !important;
        }

        .st-key-inventory_back_to_table div.stButton > button,
        .st-key-location_back_to_table div.stButton > button {
            background: #eff6ff !important;
            border: 1.5px solid #2563eb !important;
            border-radius: 8px !important;
            color: #1d4ed8 !important;
            font-size: 0.95rem !important;
            font-weight: 850 !important;
            min-height: 2.65rem !important;
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.13) !important;
        }

        .st-key-inventory_back_to_table div.stButton > button:hover,
        .st-key-location_back_to_table div.stButton > button:hover {
            background: #1d4ed8 !important;
            border-color: #1d4ed8 !important;
            color: #ffffff !important;
            transform: translateY(-1px);
        }

        .content-panel {
            background: #ffffff;
            border: 1px solid rgba(49, 51, 63, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(49, 51, 63, 0.07);
            padding: 1.1rem;
        }

        .workflow-panel {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.1), transparent 10rem),
                #ffffff;
            border: 1px solid rgba(14, 165, 233, 0.16);
            border-radius: 12px;
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
            padding: 1rem;
            margin-bottom: 0.85rem;
        }

        .workflow-kicker {
            color: #0e7490;
            font-size: 0.76rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }

        .workflow-title {
            color: #0f172a;
            font-size: 1.08rem;
            font-weight: 850;
            margin-bottom: 0.25rem;
        }

        .workflow-text {
            color: #64748b;
            font-size: 0.88rem;
            line-height: 1.4;
            margin-bottom: 0.7rem;
        }

        .action-summary-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.7rem;
            margin-top: 0.8rem;
        }

        .action-summary-card {
            background: #f8fafc;
            border: 1px solid rgba(14, 165, 233, 0.12);
            border-radius: 12px;
            padding: 0.85rem;
        }

        .action-summary-label {
            color: #64748b;
            font-size: 0.72rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: 0.3rem;
        }

        .action-summary-value {
            color: #0f172a;
            font-size: 1.25rem;
            font-weight: 850;
            line-height: 1;
        }

        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input {
            background: #ffffff !important;
            color: #0f172a !important;
            caret-color: #000000 !important;
            border: 1px solid rgba(37, 99, 235, 0.22) !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stTextArea"] textarea::placeholder,
        [data-testid="stNumberInput"] input::placeholder,
        [data-testid="stDateInput"] input::placeholder {
            color: #64748b !important;
            opacity: 1 !important;
        }

        [data-testid="stTextInput"] input:focus,
        [data-testid="stTextArea"] textarea:focus,
        [data-testid="stNumberInput"] input:focus,
        [data-testid="stDateInput"] input:focus {
            border-color: #2563eb !important;
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14), 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid rgba(37, 99, 235, 0.22) !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stTextInput"] label p,
        [data-testid="stTextArea"] label p,
        [data-testid="stNumberInput"] label p,
        [data-testid="stDateInput"] label p,
        [data-testid="stSelectbox"] label p {
            color: #0f172a !important;
            font-weight: 700 !important;
        }

        .item-card {
            background: #ffffff;
            border: 1px solid rgba(49, 51, 63, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(49, 51, 63, 0.07);
            padding: 1.15rem;
        }

        .item-status {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.2rem 0.55rem;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.75rem;
        }

        .item-status.ok {
            background: rgba(34, 197, 94, 0.12);
            color: #15803d;
        }

        .item-status.low {
            background: rgba(255, 75, 75, 0.12);
            color: rgb(211, 47, 47);
        }

        .item-name {
            color: #31333f;
            font-size: 1.35rem;
            font-weight: 850;
            line-height: 1.15;
            margin-bottom: 0.3rem;
        }

        .item-meta {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.9rem;
            margin-bottom: 0.85rem;
        }

        .quantity-pill {
            background: var(--secondary-background-color);
            border-radius: 12px;
            padding: 0.8rem;
        }

        .quantity-pill-label {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.76rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }

        .quantity-pill-value {
            color: #31333f;
            font-size: 1.65rem;
            font-weight: 850;
            line-height: 1;
        }

        .preview-list {
            display: grid;
            gap: 0.65rem;
        }

        .preview-row {
            background: var(--secondary-background-color);
            border-radius: 10px;
            padding: 0.7rem 0.8rem;
        }

        .preview-label {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.72rem;
            font-weight: 800;
            margin-bottom: 0.2rem;
            text-transform: uppercase;
        }

        .preview-value {
            color: #31333f;
            font-size: 0.95rem;
            font-weight: 700;
            word-break: break-word;
        }

        .user-flow-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.8rem;
            margin-top: 0.75rem;
        }

        .user-dashboard-hero {
            background:
                linear-gradient(135deg, rgba(18, 36, 23, 0.96), rgba(86, 107, 22, 0.88)),
                radial-gradient(circle at top right, rgba(255, 255, 255, 0.2), transparent 18rem);
            border-radius: 18px;
            box-shadow: 0 18px 42px rgba(18, 36, 23, 0.18);
            padding: 1.35rem;
            color: #ffffff;
        }

        .user-dashboard-hero-grid {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1rem;
            align-items: end;
        }

        .user-hero-stat {
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 14px;
            min-width: 130px;
            padding: 0.8rem;
        }

        .user-hero-stat-value {
            color: #ffffff;
            font-size: 1.6rem;
            font-weight: 850;
            line-height: 1;
        }

        .user-hero-stat-label {
            color: rgba(255, 255, 255, 0.68);
            font-size: 0.75rem;
            font-weight: 750;
            margin-top: 0.35rem;
        }

        .user-dashboard-hero .dashboard-card-label,
        .user-dashboard-hero .item-meta {
            color: rgba(255, 255, 255, 0.72);
        }

        .user-dashboard-hero .item-name {
            color: #ffffff;
            font-size: 1.55rem;
        }

        .user-metric-card {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.14), transparent 8rem),
                linear-gradient(145deg, #ffffff 0%, #f4fbff 100%);
            border: 1px solid rgba(14, 165, 233, 0.16);
            border-radius: 8px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
            padding: 1rem;
            min-height: 118px;
            position: relative;
        }

        .user-metric-card::after {
            content: "";
            position: absolute;
            left: 1rem;
            right: 1rem;
            bottom: 0.7rem;
            height: 3px;
            border-radius: 999px;
            background: linear-gradient(90deg, #0ea5e9, #14b8a6);
        }

        .user-metric-label {
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
        }

        .user-metric-value {
            color: #0f172a;
            font-size: 1.85rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.5rem;
        }

        .user-metric-note {
            color: #64748b;
            font-size: 0.8rem;
            padding-bottom: 0.55rem;
        }

        .user-chart-card {
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
            border: 1px solid rgba(14, 165, 233, 0.14);
            border-radius: 8px;
            box-shadow: 0 16px 32px rgba(15, 23, 42, 0.07);
            padding: 1.05rem;
            min-height: 320px;
        }

        .user-chart-title {
            color: #0f172a;
            font-size: 1.02rem;
            font-weight: 850;
            margin-bottom: 0.7rem;
        }

        .user-chart-badge {
            background: #ecfeff;
            border-radius: 999px;
            color: #0e7490;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.25rem 0.55rem;
            white-space: nowrap;
        }

        .user-stock-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.68rem 0;
            border-bottom: 1px solid rgba(14, 165, 233, 0.12);
        }

        .user-stock-row:last-child {
            border-bottom: 0;
        }

        .user-stock-name {
            color: #0f172a;
            font-size: 0.88rem;
            font-weight: 850;
        }

        .user-stock-meta {
            color: #64748b;
            font-size: 0.76rem;
            margin-top: 0.15rem;
        }

        .user-stock-qty {
            color: #0e7490;
            font-size: 0.95rem;
            font-weight: 850;
        }

        .user-stock-track {
            height: 8px;
            background: #e0f2fe;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 0.45rem;
        }

        .user-stock-fill {
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, #0ea5e9, #14b8a6);
        }

        .quick-action-panel {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
        }

        .user-dashboard-grid {
            display: grid;
            grid-template-columns: 1.15fr 0.85fr;
            gap: 1rem;
            margin-top: 1rem;
        }

        .lookup-preview-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.1rem;
        }

        .scanner-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.1rem;
            margin-top: 1rem;
        }

        .scanner-icon {
            width: 42px;
            height: 42px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #eef3dc;
            color: #5f7414;
            font-size: 1.25rem;
            margin-bottom: 0.7rem;
        }

        .lookup-preview-field {
            background: var(--secondary-background-color);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 12px;
            padding: 0.75rem 0.85rem;
            margin-top: 0.75rem;
        }

        .lookup-preview-label {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.75rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }

        .lookup-preview-value {
            color: rgba(49, 51, 63, 0.72);
            font-size: 0.92rem;
            font-weight: 650;
        }

        .user-action-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 1rem;
        }

        .user-action-chip {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(32, 48, 24, 0.07);
            padding: 0.85rem;
        }

        .user-action-chip-title {
            color: #203018;
            font-size: 0.9rem;
            font-weight: 850;
            margin-bottom: 0.2rem;
        }

        .user-action-chip-text {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.78rem;
            line-height: 1.35;
        }

        .user-action-card {
            display: none;
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.35rem;
            min-height: 170px;
        }

        .user-action-icon {
            width: 40px;
            height: 40px;
            border-radius: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #eef3dc;
            color: #5f7414;
            font-size: 1.15rem;
            margin-bottom: 0.85rem;
        }

        .user-dashboard-actions .stButton > button {
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #8fa82b, #667d16);
            color: #ffffff;
            font-weight: 750;
            box-shadow: 0 12px 24px rgba(102, 125, 22, 0.22);
        }

        .user-dashboard-actions .stButton > button:hover {
            background: linear-gradient(135deg, #7f9822, #566b12);
            color: #ffffff;
            box-shadow: 0 14px 28px rgba(102, 125, 22, 0.28);
        }

        .user-dashboard-actions .stButton > button p {
            color: #ffffff;
            font-weight: 750;
        }

        .user-flow-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            min-height: 128px;
        }

        .user-flow-number {
            width: 30px;
            height: 30px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(102, 125, 22, 0.12);
            color: #667d16;
            font-size: 0.8rem;
            font-weight: 850;
            margin-bottom: 0.55rem;
        }

        .user-flow-title {
            color: #31333f;
            font-size: 0.95rem;
            font-weight: 850;
            line-height: 1.2;
            margin-bottom: 0.3rem;
        }

        .user-flow-text {
            color: rgba(49, 51, 63, 0.64);
            font-size: 0.82rem;
            line-height: 1.35;
        }

        .admin-dashboard-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.4rem;
            background:
                radial-gradient(circle at 88% 20%, rgba(37, 99, 235, 0.16), transparent 15rem),
                radial-gradient(circle at 18% 0%, rgba(14, 165, 233, 0.12), transparent 14rem),
                linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(244, 248, 252, 0.98));
            border: 1px solid rgba(30, 64, 175, 0.1);
            border-radius: 18px;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
            padding: 1.25rem;
        }

        .admin-dashboard-title {
            color: #0f172a;
            font-size: 2.25rem;
            font-weight: 850;
            line-height: 1.1;
            margin-bottom: 0.35rem;
        }

        .admin-dashboard-subtitle {
            color: #64748b;
            font-size: 0.98rem;
        }

        .admin-profile-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.65rem;
            background: #ffffff;
            border: 1px solid rgba(37, 99, 235, 0.12);
            border-radius: 999px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
            padding: 0.55rem 0.85rem;
            white-space: nowrap;
        }

        .admin-profile-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #dbeafe;
            color: #1d4ed8;
            font-weight: 850;
        }

        .admin-profile-name {
            color: #0f172a;
            font-size: 0.9rem;
            font-weight: 800;
            line-height: 1.1;
        }

        .admin-profile-role {
            color: #64748b;
            font-size: 0.76rem;
        }

        .admin-stat-card {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 16px;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.07);
            min-height: 138px;
            padding: 1rem;
            position: relative;
            overflow: hidden;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }

        .admin-stat-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--stat-accent, #2563eb);
        }

        .admin-stat-card:hover,
        .dashboard-card:hover,
        .user-flow-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 20px 42px rgba(15, 23, 42, 0.12);
        }

        .stat-blue {
            --stat-accent: #2563eb;
            --stat-soft: #dbeafe;
            --stat-ink: #1d4ed8;
        }

        .stat-cyan {
            --stat-accent: #0891b2;
            --stat-soft: #cffafe;
            --stat-ink: #0e7490;
        }

        .stat-amber {
            --stat-accent: #f59e0b;
            --stat-soft: #fef3c7;
            --stat-ink: #b45309;
        }

        .stat-violet {
            --stat-accent: #7c3aed;
            --stat-soft: #ede9fe;
            --stat-ink: #6d28d9;
        }

        .stat-emerald {
            --stat-accent: #059669;
            --stat-soft: #d1fae5;
            --stat-ink: #047857;
        }

        .admin-stat-icon {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--stat-soft, #dbeafe);
            color: var(--stat-ink, #1d4ed8);
            font-size: 1.15rem;
            margin-bottom: 0.7rem;
        }

        .admin-stat-label {
            color: #64748b;
            font-size: 0.82rem;
            font-weight: 750;
            margin-bottom: 0.3rem;
        }

        .admin-stat-value {
            color: #0f172a;
            font-size: 1.75rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.55rem;
        }

        .admin-stat-note {
            color: var(--stat-ink, #1d4ed8);
            font-size: 0.78rem;
            font-weight: 700;
        }

        .admin-panel {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.07);
            padding: 1rem;
        }

        .admin-panel-title {
            color: #0f172a;
            font-size: 1.02rem;
            font-weight: 850;
            margin-bottom: 0.7rem;
        }

        .analytics-card {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.07);
            padding: 1.05rem;
            min-height: 320px;
        }

        .analytics-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.9rem;
        }

        .analytics-badge {
            background: #eff6ff;
            border-radius: 999px;
            color: #1d4ed8;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.25rem 0.55rem;
            white-space: nowrap;
        }

        .analytics-bar-chart {
            display: grid;
            grid-template-columns: 42px 1fr;
            gap: 0.75rem;
            align-items: end;
            min-height: 190px;
            padding: 0.35rem 0.15rem 0;
        }

        .analytics-y-axis {
            display: grid;
            grid-template-rows: repeat(4, 1fr);
            height: 138px;
            padding-bottom: 1.8rem;
            color: #94a3b8;
            font-size: 0.7rem;
            font-weight: 750;
            text-align: right;
        }

        .analytics-plot {
            position: relative;
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.72rem;
            align-items: end;
            min-height: 170px;
            padding: 0 0.1rem;
        }

        .analytics-plot::before {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            top: 0;
            height: 138px;
            background:
                linear-gradient(to bottom,
                    rgba(148, 163, 184, 0.16) 0,
                    rgba(148, 163, 184, 0.16) 1px,
                    transparent 1px,
                    transparent 33.33%,
                    rgba(148, 163, 184, 0.16) 33.33%,
                    rgba(148, 163, 184, 0.16) calc(33.33% + 1px),
                    transparent calc(33.33% + 1px),
                    transparent 66.66%,
                    rgba(148, 163, 184, 0.16) 66.66%,
                    rgba(148, 163, 184, 0.16) calc(66.66% + 1px),
                    transparent calc(66.66% + 1px),
                    transparent calc(100% - 1px),
                    rgba(15, 23, 42, 0.28) calc(100% - 1px),
                    rgba(15, 23, 42, 0.28) 100%);
            pointer-events: none;
        }

        .analytics-bar-item {
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-rows: auto 1fr auto;
            gap: 0.4rem;
            min-height: 170px;
            align-items: end;
        }

        .analytics-bar-value {
            color: #0f172a;
            font-size: 0.74rem;
            font-weight: 850;
            line-height: 1;
            text-align: center;
        }

        .analytics-bar-track {
            position: relative;
            width: 100%;
            height: 154px;
            border-radius: 8px 8px 0 0;
            background: transparent;
            overflow: hidden;
        }

        .analytics-bar-fill {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            min-height: 8px;
            border-radius: 8px 8px 0 0;
            background: linear-gradient(180deg, #2563eb, #06b6d4);
            box-shadow: 0 10px 20px rgba(37, 99, 235, 0.22);
        }

        .analytics-bar-label {
            color: #64748b;
            font-size: 0.7rem;
            font-weight: 800;
            text-align: center;
            white-space: nowrap;
        }

        .analytics-empty {
            background: #f8fafc;
            border-radius: 14px;
            color: #64748b;
            font-size: 0.9rem;
            font-weight: 650;
            padding: 1rem;
        }

        .donut-layout {
            display: grid;
            grid-template-columns: 150px 1fr;
            gap: 1rem;
            align-items: center;
            min-height: 220px;
        }

        .donut-chart {
            width: 150px;
            height: 150px;
            border-radius: 50%;
            position: relative;
            box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18), 0 12px 26px rgba(15, 23, 42, 0.08);
        }

        .donut-chart::after {
            content: "";
            position: absolute;
            width: 70px;
            height: 70px;
            border-radius: 50%;
            background: #ffffff;
            top: 40px;
            left: 40px;
            box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.12);
        }

        .donut-legend {
            display: grid;
            gap: 0.7rem;
        }

        .donut-legend-row {
            display: grid;
            grid-template-columns: 12px 1fr auto;
            gap: 0.55rem;
            align-items: center;
            color: #334155;
            font-size: 0.84rem;
            font-weight: 700;
        }

        .donut-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .donut-percent {
            color: #0f172a;
            font-weight: 850;
        }

        .inventory-action-buttons .stButton > button {
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #2563eb, #06b6d4);
            color: #ffffff;
            font-weight: 800;
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
        }

        .inventory-action-buttons .stButton > button:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2);
            color: #ffffff;
            box-shadow: 0 10px 22px rgba(37, 99, 235, 0.24);
        }

        .inventory-action-buttons .stButton > button p {
            color: inherit;
            font-weight: 800;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"],
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2) !important;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"]:hover,
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            box-shadow: 0 10px 22px rgba(37, 99, 235, 0.26) !important;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"] p,
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"] p {
            color: #ffffff !important;
            font-weight: 800;
        }

        .inventory-action-buttons [data-testid="stHorizontalBlock"] {
            gap: 0 !important;
        }

        .inventory-action-buttons [data-testid="column"] {
            padding: 0 !important;
        }

        .inventory-action-buttons [data-testid="stElementContainer"] {
            margin: 0 !important;
        }

        .inventory-stream-cell {
            min-height: 50px;
            display: flex;
            align-items: center;
            padding: 0.75rem 0.9rem;
            background: #ffffff;
            border-right: 1px solid rgba(148, 163, 184, 0.18);
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
            color: #334155;
            font-size: 0.9rem;
            font-weight: 650;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .inventory-stream-cell.strong {
            color: #0f172a;
            font-weight: 800;
        }

        .inventory-stream-cell.header {
            min-height: 42px;
            background: #f8fafc;
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
        }

        .inventory-action-buttons [data-testid="stButton"] {
            margin: 0 !important;
            padding: 0.42rem 0.65rem !important;
            min-height: 50px;
            display: flex;
            align-items: center;
            background: #ffffff;
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
        }

        .inventory-action-buttons [data-testid="stButton"] button {
            margin: 0 !important;
        }

        .qr-print-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .qr-label-card {
            background: #ffffff;
            border: 1px solid rgba(32, 48, 24, 0.1);
            border-radius: 14px;
            box-shadow: 0 12px 28px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            text-align: center;
        }

        .qr-label-title {
            color: #203018;
            font-size: 1rem;
            font-weight: 850;
            margin-top: 0.65rem;
        }

        .qr-label-meta {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.82rem;
            font-weight: 650;
            margin-top: 0.2rem;
        }

        .qr-print-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #8fa82b, #667d16);
            color: #ffffff !important;
            font-weight: 800;
            padding: 0.65rem 1rem;
            text-decoration: none !important;
            cursor: pointer;
            box-shadow: 0 12px 24px rgba(102, 125, 22, 0.22);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button p {
            color: #ffffff !important;
        }

        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button[kind="primary"],
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24) !important;
        }

        [data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3) !important;
        }

        [data-testid="stFormSubmitButton"] button p,
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"] p {
            color: #ffffff !important;
            font-weight: 750;
        }

        @media print {
            [data-testid="stSidebar"],
            [data-testid="stToolbar"],
            [data-testid="stHeader"],
            .stButton,
            .page-header,
            .dashboard-section-title,
            .qr-print-controls {
                display: none !important;
            }

            .qr-print-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 12px;
            }

            .qr-label-card {
                box-shadow: none;
                break-inside: avoid;
                border: 1px solid #222;
            }
        }

        .admin-status-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.6rem 0;
            border-bottom: 1px solid rgba(32, 48, 24, 0.08);
        }

        .admin-status-row:last-child {
            border-bottom: 0;
        }

        .admin-status-name {
            color: #203018;
            font-size: 0.86rem;
            font-weight: 750;
        }

        .admin-status-meta {
            color: rgba(32, 48, 24, 0.58);
            font-size: 0.76rem;
            margin-top: 0.15rem;
        }

        .admin-status-qty {
            color: #203018;
            font-size: 0.9rem;
            font-weight: 850;
            text-align: right;
        }

        .admin-progress {
            height: 7px;
            background: #eef1e6;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 0.45rem;
        }

        .admin-progress-fill {
            height: 100%;
            border-radius: inherit;
            background: #6f8417;
        }

        .admin-progress-fill.low {
            background: #f0a51a;
        }

        .admin-progress-fill.empty {
            background: #e54b4b;
        }

        .page-header {
            margin-top: 0;
            margin-bottom: 0.85rem;
        }

        .page-title {
            font-size: 1.55rem;
            line-height: 1.12;
            margin-bottom: 0.15rem;
        }

        .page-subtitle {
            font-size: 0.88rem;
            line-height: 1.35;
        }

        .dashboard-section-title,
        .admin-panel-title {
            margin-top: 0.45rem;
            margin-bottom: 0.4rem;
            font-size: 0.98rem;
        }

        .dashboard-card,
        .content-panel,
        .analytics-card,
        .user-chart-card,
        .admin-panel,
        .workflow-panel,
        .item-card {
            border-radius: 10px;
            padding: 0.75rem;
        }

        .dashboard-card,
        .user-metric-card,
        .admin-stat-card {
            min-height: 92px;
        }

        .admin-stat-value,
        .dashboard-card-value,
        .user-metric-value {
            font-size: 1.55rem;
            line-height: 1.05;
        }

        .admin-stat-label,
        .dashboard-card-label,
        .user-metric-label,
        .preview-label,
        .action-summary-label {
            font-size: 0.72rem;
        }

        .admin-stat-note,
        .dashboard-card-note,
        .user-metric-note,
        .workflow-text,
        .item-meta {
            font-size: 0.76rem;
            line-height: 1.3;
        }

        .workflow-kicker {
            font-size: 0.68rem;
            margin-bottom: 0.12rem;
        }

        .workflow-title {
            font-size: 0.95rem;
            margin-bottom: 0.12rem;
        }

        .modern-form-note {
            color: #475569;
            font-size: 0.78rem;
            line-height: 1.35;
            margin: -0.1rem 0 0.35rem;
        }

        .modern-form-summary {
            border: 1px solid rgba(15, 23, 42, 0.1);
            border-radius: 10px;
            background: linear-gradient(180deg, #ffffff, #f8fafc);
            padding: 0.65rem;
            margin: 0.35rem 0 0.7rem;
        }

        .modern-form-summary-title {
            color: #0f172a;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.45rem;
        }

        .modern-form-summary-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.45rem;
        }

        .modern-form-summary-grid.four {
            grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .modern-form-summary-card {
            min-width: 0;
            border: 1px solid rgba(15, 23, 42, 0.08);
            border-radius: 8px;
            background: #ffffff;
            padding: 0.55rem;
        }

        .modern-form-summary-label {
            color: #64748b;
            font-size: 0.67rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0;
            margin-bottom: 0.16rem;
        }

        .modern-form-summary-value {
            color: #0f172a;
            font-size: 0.92rem;
            font-weight: 850;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .action-summary-grid {
            gap: 0.45rem;
        }

        .action-summary-card {
            min-height: 72px;
            padding: 0.65rem;
            border-radius: 10px;
        }

        .preview-row,
        .admin-status-row {
            padding: 0.45rem 0;
        }

        [data-testid="stDataFrame"] {
            margin-top: 0.25rem;
        }

        [data-testid="stForm"] {
            padding: 0.85rem 1rem;
            border-radius: 10px;
        }

        [data-testid="stForm"] [data-testid="stTextInput"],
        [data-testid="stForm"] [data-testid="stNumberInput"],
        [data-testid="stForm"] [data-testid="stSelectbox"],
        [data-testid="stForm"] [data-testid="stTextArea"] {
            margin-bottom: 0.35rem;
        }

        [data-testid="stFormSubmitButton"] button,
        [data-testid="stButton"] button {
            min-height: 2.15rem;
        }

        .stDataFrame,
        [data-testid="stDataFrame"] {
            border-radius: 8px;
            overflow: hidden;
        }

        [data-testid="stVerticalBlock"] {
            gap: 0.65rem;
        }

        @media (max-width: 900px) {
            .modern-form-summary-grid,
            .modern-form-summary-grid.four {
                grid-template-columns: 1fr 1fr;
            }

            .user-flow-grid {
                grid-template-columns: 1fr;
            }

            .user-dashboard-grid,
            .user-action-strip {
                grid-template-columns: 1fr;
            }

            .admin-dashboard-header {
                display: block;
            }
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-mark">TE</div>
            <div>
                <div class="sidebar-brand-title">Tarakji Enterprise</div>
                <div class="sidebar-brand-subtitle">Stock control panel</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.sidebar.button("Sign out", key="logout_button_top", type="secondary", width="stretch"):
        logout_user()
        st.rerun()

    st.sidebar.markdown("---")

    if "menu" not in st.session_state:
        st.session_state.menu = "Dashboard"

    menu_icons = {
        "Dashboard": "📊",
        "Scan Inventory": "🔎",
        "Scan QR / Barcode": "▣",
        "Transaction Logs": "🧾",
        "Add Inventory": "➕",
        "View Inventory": "📦",
        "Print QR Codes": "▣",
        "User Management": "👤",
        "Logout": "↩",
    }

    menu_icons["Manage Sales"] = "$"
    menu_icons["Sell Item"] = "$"
    menu_icons["Locations"] = "LOC"
    menu_icons["Location Inventory"] = "STK"
    menu_icons["Financials"] = "FIN"
    menu_icons["Returns"] = "RET"
    menu_icons["Transfers"] = "TRN"

    menu_icons.update({
        "Dashboard": "📊",
        "Scan Inventory": "📥",
        "Scan QR / Barcode": "▣",
        "Transaction Logs": "🧾",
        "Add Inventory": "➕",
        "View Inventory": "📦",
        "Print QR Codes": "🏷️",
        "User Management": "👤",
        "Manage Sales": "📈",
        "Sell Item": "💳",
        "Locations": "📍",
        "Location Inventory": "🏬",
        "Financials": "💵",
        "Returns": "↩️",
        "Transfers": "⇄",
        "Logout": "⏻",
    })

    menu_labels = {
        "Dashboard": "Overview",
        "Scan Inventory": "Receive Stock",
        "Scan QR / Barcode": "Scan QR / Barcode",
        "Transaction Logs": "Activity Logs",
        "Add Inventory": "Inventory Entry",
        "View Inventory": "Inventory View",
        "Print QR Codes": "QR Labels",
        "User Management": "Users & Access",
        "Manage Sales": "Sales Reports",
        "Sell Item": "Create Sale",
        "Locations": "Locations",
        "Location Inventory": "Stock & Pricing",
        "Financials": "Financials",
        "Returns": "Returns / Damaged",
        "Transfers": "Transfers",
        "Logout": "Sign Out",
    }

    if is_super_admin():
        nav_sections = [
            ("Operations", ["Dashboard", "Location Inventory", "Returns", "Transfers"]),
            ("Finance", ["Financials"]),
            ("Setup", ["Locations", "Add Inventory", "User Management", "View Inventory", "Print QR Codes"]),
            ("Reports", ["Manage Sales", "Transaction Logs"]),
        ]
    elif get_current_role() == "admin":
        nav_sections = [
            ("Operations", ["Dashboard", "Location Inventory", "Returns", "Transfers"]),
            ("Finance", ["Financials"]),
            ("Reports", ["Transaction Logs"]),
        ]
    elif get_current_role() == "sales":
        nav_sections = [
            ("Operations", ["Dashboard", "Scan Inventory", "Sell Item", "Returns"]),
            ("Reports", ["Transaction Logs"]),
        ]
    else:
        nav_sections = [
            ("Operations", ["Dashboard", "Scan Inventory", "Scan QR / Barcode", "Sell Item"]),
            ("Reports", ["Transaction Logs"]),
        ]

    allowed_items = [
        item
        for _, section_items in nav_sections
        for item in section_items
    ] + ["Logout"]

    if st.session_state.menu not in allowed_items:
        st.session_state.menu = "Dashboard"

    for section_index, (section_name, section_items) in enumerate(nav_sections):
        if section_index:
            st.sidebar.markdown("---")

        st.sidebar.markdown(
            f'<div class="sidebar-section-label">{section_name}</div>',
            unsafe_allow_html=True
        )

        for item in section_items:
            if st.sidebar.button(
                f"{menu_icons.get(item, '•')}  {menu_labels.get(item, item)}",
                key=f"menu_{item}",
                type="primary" if st.session_state.menu == item else "secondary",
                width="stretch"
            ):
                st.session_state.menu = item
                st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="sidebar-section-label">Account</div>',
        unsafe_allow_html=True
    )

    if st.sidebar.button(
        f"{menu_icons['Logout']}  {menu_labels['Logout']}",
        key="logout_button",
        type="secondary",
        width="stretch"
    ):
        logout_user()
        st.rerun()

    menu = st.session_state.menu

    if menu == "Dashboard":
        render_setup_checklist()

    role_page_context = globals()
    super_admin_pages.configure(role_page_context)
    admin_pages.configure(role_page_context)
    sales_pages.configure(role_page_context)
    user_pages.configure(role_page_context)

    super_admin_pages.render(menu)
    admin_pages.render(menu)
    sales_pages.render(menu)
    user_pages.render(menu)
