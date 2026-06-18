# Inventory Management Web App

A Streamlit-based inventory and financial management system for tracking stock across storage locations, location-based pricing, invoices, payments, returns/damaged items, transfers, QR labels, and role-based dashboards.

## Features

- Role-based login for `super_admin`, `admin`, `sales`, and existing `user` accounts
- Ruth-only super admin access
- Location management for separate storage facilities
- Inventory quantities tracked per location
- Location-specific pricing
- Location-specific invoice creation
- Payment tracking by cash, check, wire, and credit card
- Outstanding balance reporting
- Returned/damaged item tracking
- Inventory transfers between locations
- Admin access scoped by assigned locations and supplied products
- Sales access scoped by assigned locations
- QR code generation and webcam scanning for the existing user workflow
- SQLite database created and updated automatically

## User Roles

### Super Admin: Ruth

Ruth is the owner-level user and can see the full business network.

Ruth can:

- Create, edit, activate, and deactivate storage locations
- Assign admins and sales users to locations
- Assign supplied products to admins
- Manage the master inventory list
- Manage location inventory and pricing
- Transfer inventory between locations
- View all invoices, payments, outstanding balances, returns, and operational reports
- Create users and manage access

Only the `Ruth` account can have the `super_admin` role.

### Admin: Storage Owner or Supplier

Admins have limited access based on what Ruth assigns to them.

Admins can:

- View dashboard data for assigned locations and supplied products
- Manage inventory and pricing for assigned locations
- View invoices related to supplied products
- View customer payments for those invoices
- Review outstanding balances
- View returned/damaged items for products they supplied
- Record or review transfers between assigned locations
- Review transaction activity related to assigned locations and supplied products

Admins cannot:

- Create, edit, deactivate, or delete locations
- Access Ruth's global location management
- Access company-wide inventory or financial data
- Manage Ruth-only user/location setup pages

### Sales

Sales users operate at the location level.

Sales users can:

- View only assigned active locations
- View available inventory for assigned locations
- Create sales invoices from assigned location stock
- Use the selected location's pricing
- Record payment method during a sale
- Automatically reduce location inventory after a sale
- Record returned/damaged items for assigned locations

Sales users cannot:

- Create or modify locations
- View company-wide inventory or financial summaries
- Use the old global scan/allocation workflow

### Standard User

The `user` role keeps the original workflow.

Standard users can:

- Scan QR/barcodes or manually enter item codes
- Receive stock from system inventory into personal stock
- Sell from personal assigned stock
- View their own dashboard and transaction logs

## First-Time Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

For the default admin account, set an initial password before the first run:

```bash
set INVENTORY_ADMIN_PASSWORD=your_admin_password
```

For Ruth's super admin account, set one of these before running:

```bash
set INVENTORY_SUPER_ADMIN_PASSWORD=your_ruth_password
```

or:

```bash
set INVENTORY_RUTH_PASSWORD=your_ruth_password
```

You can also use Streamlit secrets:

```toml
INITIAL_ADMIN_PASSWORD = "your_admin_password"
INITIAL_SUPER_ADMIN_PASSWORD = "your_ruth_password"
```

## Recommended Setup Order

1. Log in as Ruth.
2. Create storage locations in **Locations**.
3. Create users in **User Management**.
4. Assign admins and sales users to locations in **Locations**.
5. Add master inventory items in **Add Inventory**.
6. Assign supplied products to admins in **User Management**.
7. Add location stock and prices in **Location Inventory**.
8. Sales or admins can create invoices in **Sell Item** or **Financials**.
9. Record payments and review outstanding balances in **Financials**.
10. Record returned/damaged items in **Returns**.
11. Move stock between locations in **Transfers**.

## Super Admin Workflow

1. Log in as Ruth.
2. Open **Locations** to create, edit, activate, or deactivate storage facilities.
3. Use **Locations** to assign admins and sales users to the correct locations.
4. Open **User Management** to create users and assign supplied products to admins.
5. Open **Add Inventory** to maintain the master inventory list.
6. Open **Location Inventory** to set stock quantity and price for each item at each location.
7. Open **Transfers** to move inventory from one location to another.
8. Open **Financials** to view all invoices, payments, payment method summaries, and outstanding balances.
9. Open **Returns** to review returned or damaged items across locations.
10. Open **Dashboard**, **Manage Sales**, and **Transaction Logs** for company-wide operational reporting.

## Admin Workflow

Before an admin can work, Ruth must assign:

- at least one location
- at least one supplied product

Admin workflow:

1. Log in with an `admin` account.
2. Open **Dashboard** to view assigned-location and supplied-product activity.
3. Open **Location Inventory** to review or manage stock and pricing for assigned locations.
4. Open **Financials** to create invoices for assigned locations using supplied products.
5. In **Financials**, review invoice totals, payments, outstanding balances, and payment summaries.
6. Record customer payments against accessible invoices.
7. Open **Returns** to review returned/damaged items tied to supplied products.
8. Open **Transfers** to record or review movement between assigned locations.
9. Open **Transaction Logs** to review sales activity related to assigned locations and supplied products.

If an admin sees an assignment message, Ruth needs to assign the missing location or supplied product first.

## Sales Workflow

Before a sales user can sell, Ruth must assign the sales user to at least one active location.

Sales workflow:

1. Log in with a `sales` account.
2. Open **Sell Item**.
3. Select an assigned location.
4. Review available inventory for that location.
5. Select the item being sold.
6. Confirm quantity, unit price, customer name, and payment method.
7. Create the sale.
8. The app creates an invoice and reduces inventory for that location.
9. If payment is entered, the app records the payment and updates invoice status when fully paid.
10. Open **Returns** when customers return damaged or bad items.

## Standard User Workflow

This is the original scan-and-personal-stock workflow.

1. Log in with a `user` account.
2. Open **Scan QR / Barcode** or **Scan Inventory**.
3. Scan or enter an item code.
4. Review system stock and personal assigned stock.
5. Add quantity from system stock into personal stock.
6. Open **Sell Item**.
7. Enter item code and quantity sold.
8. The app reduces personal stock and records a sale transaction.
9. Open **Transaction Logs** to review personal activity.

## Feature Guide

### Locations

Used by Ruth only.

Use this page to:

- Create storage facilities
- Edit name, address, owner/admin, and active status
- Deactivate locations that should no longer be used
- Assign admins and sales users to locations

### User Management

Used by Ruth only.

Use this page to:

- Create users
- Assign roles
- Delete users when needed
- Assign supplied products to admins

Supplied product assignment controls what invoice, payment, balance, and return records an admin can see.

### Add Inventory

Used by Ruth to maintain the master item list.

Use this page to:

- Add item code
- Add item name
- Add description
- Add master quantity
- Generate QR code labels

### View Inventory

Used by Ruth to manage the master item list.

Use this page to:

- Search inventory
- Edit item details
- Delete inventory items
- Review low-stock master inventory

### Location Inventory

Used by Ruth and assigned admins.

Use this page to:

- Select a location
- Select an inventory item
- Set location-specific quantity
- Set location-specific price
- Review stock by location

Invoices and sales use this location stock and price data.

### Financials

Used by Ruth and assigned admins.

Use this page to:

- View invoice totals
- View paid amounts
- View outstanding balances
- View payment summary by method
- Create invoices
- Record customer payments
- Review invoice status
- Review payment history

Admins only see records for assigned locations and supplied products.

### Returns

Used by Ruth, admins, and sales users.

Use this page to:

- Record returned items
- Record damaged or bad items
- Select location, item, quantity, condition, and reason
- Review return history

Sales users only record returns for assigned locations. Admins see returns related to products they supplied.

### Transfers

Used by Ruth and assigned admins.

Use this page to:

- Select an item
- Select source location
- Select destination location
- Enter transfer quantity
- Mark transfer as pending or completed

Completed transfers reduce stock at the source location and increase stock at the destination location.

### Manage Sales

Used by Ruth only.

Use this page to:

- Review company-wide sales records
- Filter sales by user, item, and date range
- View sales by item
- View sales by user

### Transaction Logs

Used by all roles, with different visibility.

- Ruth sees company-wide operational history.
- Admins see activity related to assigned locations and supplied products.
- Sales users see their sales activity.
- Standard users see their own personal stock activity.

## Database Tables

The app uses SQLite and creates these tables automatically:

- `users`
- `inventory`
- `user_inventory`
- `transactions`
- `locations`
- `user_locations`
- `location_inventory`
- `location_prices`
- `invoices`
- `invoice_items`
- `payments`
- `returns`
- `inventory_transfers`
- `product_suppliers`

## Project Files

```text
app.py                  Main Streamlit application
auth.py                 Authentication and role helpers
db.py                   SQLite schema setup
utils.py                QR/image/helper functions
inventory.db            SQLite database
requirements.txt        Python dependencies
.streamlit/config.toml  Streamlit theme settings
qr_*.png                Generated QR code images
```

## Notes

- QR codes are generated as PNG files in the project folder.
- Webcam QR/barcode scanning requires browser camera permission.
- The app uses OpenCV for QR/barcode decoding.
- `.streamlit/config.toml` controls the base Streamlit theme, while `app.py` contains custom UI styling.
- Existing plain-text passwords from older versions are automatically upgraded to hashed passwords after a successful login.
