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
- Manual item-code lookup for recording quantity used/sold
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
- Transaction Logs

Admins open on the dashboard. Standard users can scan or enter an item code, review item details, enter quantity, and submit usage/sales.

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
2. User opens **Scan QR / Barcode** or **Scan Inventory**.
3. The app gets the item code from the camera scan or manual entry.
4. The app fetches item details from the SQLite inventory table.
5. User reviews item name, description, and available quantity.
6. User enters quantity used/sold.
7. The app checks stock with an atomic database update.
8. If enough stock exists, inventory is deducted.
9. A transaction record is saved with username, item code, quantity, and timestamp.
10. The user sees a success message.

## Manage Sales

The app does not create a separate sales table. Sales are based on the existing `transactions` table because users already record item usage/sales there.

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
- `transactions`

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
