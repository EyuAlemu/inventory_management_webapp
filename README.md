# Inventory Management Web App

A Streamlit-based inventory management system for tracking stock, user item usage/sales, QR labels, transaction history, and admin reporting.

## Features

- Role-based login for admin and standard users
- Password hashing with PBKDF2
- Admin dashboard with inventory, transaction, low-stock, and usage analytics
- Add inventory items and automatically generate QR codes
- View, search, edit, and delete inventory records
- Print QR code labels for selected inventory items
- User dashboard with quick access to QR/barcode scanning and manual lookup
- QR/barcode scanner using the webcam
- Manual item-code lookup for assigning system stock to a user
- Dedicated Sell Item page for selling from the user's assigned quantity
- Atomic stock deduction to prevent overselling
- Transaction logs for all usage/sales records
- Admin Manage Sales page using existing transaction records
- User management for creating and deleting accounts
- SQLite database created automatically on first run

## User Roles

**Admin**

- Dashboard
- Transaction Logs
- Add Inventory
- View Inventory
- Print QR Codes
- Manage Sales
- User Management

**Standard User**

- Dashboard
- Scan Inventory
- Scan QR / Barcode
- Sell Item
- Transaction Logs

Admins open on the dashboard. Standard users can scan or enter an item code, add quantity from system stock into their own stock, then use Sell Item to sell from their assigned quantity.

## Admin Setup

For a fresh database, the app creates the first admin only when an initial admin password is provided.

Set one of these before running the app:

```bash
set INVENTORY_ADMIN_PASSWORD=your_admin_password
```

Or add this to Streamlit secrets:

```toml
INITIAL_ADMIN_PASSWORD = "your_admin_password"
```

Then log in with:

```text
Username: admin
Password: your_admin_password
```

Existing plain-text passwords from older versions are automatically upgraded to hashed passwords after a successful login.

## User Inventory Scan Flow

1. User logs in.
2. User opens **Scan QR / Barcode** or **Scan Inventory** to find an item.
3. The app gets the item code from the camera scan or manual entry.
4. The app fetches item details from the SQLite inventory table.
5. User reviews item name, description, system available quantity, and their current assigned quantity.
6. User enters quantity to add to their own stock.
7. The app deducts that quantity from system inventory and adds it to the user's stock.
8. The app saves an `allocation` transaction.
9. User opens **Sell Item**.
10. User enters the item code and quantity sold.
11. The app sells only from the user's assigned quantity.
12. The app saves a `sale` transaction with before quantity, quantity sold, remaining user quantity, and timestamp.
13. Admin tracks only sale records in **Manage Sales**.

## Manage Sales

The app does not create a separate sales table. Sales are based on `transactions` records where `transaction_type = "sale"`.

The admin **Manage Sales** page includes:

- Sales Records
- Quantity Sold
- Sales Users
- Top Sold Item
- Filter by user
- Filter by item code
- Filter by date range
- Sales by item
- Sales by user
- Full sales records table

## Database Tables

The app uses SQLite and creates these tables automatically:

- `users`
- `inventory`
- `user_inventory`
- `transactions`

The `user_inventory` table stores each user's assigned stock:

- `username`
- `item_code`
- `quantity`

The `transactions` table stores sales/usage history, including:

- `quantity_used`
- `quantity_before`
- `quantity_after`
- `transaction_type`

## Project Files

```text
app.py                  Main Streamlit application
inventory.db            SQLite database
requirements.txt        Python dependencies
.streamlit/config.toml  Streamlit theme settings
qr_*.png                Generated QR code images
```

## Install Dependencies

```bash
pip install -r requirements.txt
```

## Run Application

```bash
streamlit run app.py
```

## Notes

- QR codes are generated as PNG files in the project folder.
- Webcam QR/barcode scanning requires browser camera permission.
- The app uses OpenCV for QR/barcode decoding.
- `.streamlit/config.toml` controls the base Streamlit theme, while `app.py` contains custom UI styling.
