# Ruth User Guide

This guide explains how to use the app as Ruth, the `super_admin` user. Ruth can set up the business, create users, manage inventory, assign access, review sales, track payments, and audit transactions.

## Start Here

1. Run the app.
2. Open the local app URL in your browser.
3. Log in with the `Ruth` account.
4. Use the left sidebar to move between pages.

Recommended setup order:

1. Create locations.
2. Create users.
3. Assign users to locations.
4. Add inventory entries.
5. Assign inventory products to admins or sales users if needed.
6. Add or adjust stock and pricing by location.
7. Let sales/admin users create sales.
8. Review payments, returns, transfers, sales reports, and transaction logs.

## Dashboard

Use **Dashboard** to see the overall business status.

1. Click **Overview** in the sidebar.
2. Review setup checklist items.
3. Review total inventory, location stock, sales, low-stock items, and recent transactions.
4. If a checklist item is missing, go to the matching setup page and complete it.

## Locations

Use **Locations** to create sites and assign users to sites.

### Create a Location

1. Click **Locations**.
2. In **Create Location**, enter the location name.
3. Enter the address or notes.
4. Choose an owner/admin if needed.
5. Click **Save Location**.

### Edit a Location

1. Click **Locations**.
2. Find **Existing Locations**.
3. Select the location to edit.
4. Change the name, address, owner, or active status.
5. Click **Update Location**.

### Assign a User to a Location

1. Click **Locations**.
2. Go to **Assign Users to Locations**.
3. Select an admin or sales user.
4. Select a location.
5. Click **Assign Location**.
6. Use **Remove Location** if the assignment is no longer needed.

## Users & Access

Use **Users & Access** to create users and assign product access.

### Create a User

1. Click **Users & Access**.
2. Enter a username.
3. Enter a password.
4. Select a role: `user`, `sales`, `admin`, or `super_admin`.
5. Click **Create User**.

Only the `Ruth` account should be `super_admin`.

### Delete a User

1. Click **Users & Access**.
2. Find **Existing Users**.
3. Select the user in **Delete User**.
4. Click **Delete Selected User**.

The app removes related stock, location, and product assignments for that user.

### Assign Inventory Products

Use this when you want to limit an admin or sales user to specific products.

1. Click **Users & Access**.
2. Go to **Assign Inventory Products**.
3. Select an admin or sales user.
4. Select a product.
5. Click **Assign Product**.

For sales users, product assignment is optional. If a sales user has product assignments, they can only sell those products within their assigned locations. If they have no product assignments, they can sell all stocked products at their assigned locations.

## Inventory Entry

Use **Inventory Entry** to add a new item and its first location stock record.

1. Click **Inventory Entry**.
2. Enter **Item Code**.
3. Enter **Item Name**.
4. Enter **Description**.
5. Enter **Location Name**.
6. Enter **Location Address**.
7. Enter **Quantity**.
8. Enter **Inventory Cost**.
9. Review the preview.
10. Click **Save Inventory Entry**.

The app creates the master inventory item, creates or updates the location, adds location stock, saves cost, and generates a QR code.

## Inventory View

Use **Inventory View** to review, search, edit, or delete inventory.

1. Click **Inventory View**.
2. Use the search box to find an item by code, name, description, location, or address.
3. Review columns for item code, item name, description, location, address, quantity, and cost.
4. Click **Edit** beside an item to change its details.
5. Update item code, name, description, quantity, or cost.
6. Click **Update Item**.
7. To delete an item, select it, confirm deletion, then click **Delete Item**.

## Stock & Pricing

Use **Stock & Pricing** to set or change stock and price for a location.

1. Click **Stock & Pricing**.
2. Select a location.
3. Select an inventory item.
4. Enter location quantity.
5. Enter location price.
6. Click **Save Stock / Price**.
7. Review all location stock in the table.

## Financials

Use **Financials** to create invoices, record payments, and review balances.

### Create an Invoice

1. Click **Financials**.
2. In **Create Invoice**, select a location.
3. Select an item from that location.
4. Enter customer name.
5. Enter quantity.
6. Confirm or change unit price.
7. Review invoice preview.
8. Click **Create Invoice**.

The app reduces stock at the selected location and creates an invoice.

### Record a Payment

1. Click **Financials**.
2. In **Record Payment**, select an invoice.
3. Enter payment amount.
4. Select payment method.
5. Enter reference number if needed.
6. Click **Record Payment**.

The app prevents payments larger than the outstanding balance.

### Review Financial Reports

1. Click **Financials**.
2. Review invoice totals, paid totals, and outstanding totals.
3. Use invoice filters to view open, paid, or partially paid invoices.
4. Review payment summary by method.
5. Review payment history.

## Returns / Damaged

Use **Returns / Damaged** to record returned or damaged inventory.

1. Click **Returns / Damaged**.
2. Select a location.
3. Select an item.
4. Enter quantity.
5. Select condition.
6. Enter reason.
7. Click **Save Return**.
8. Review return records in the table.

## Transfers

Use **Transfers** to move stock between locations.

1. Click **Transfers**.
2. Select an item.
3. Select the source location.
4. Select the destination location.
5. Enter quantity.
6. Choose status:
   - `pending`: record the transfer request only.
   - `completed`: immediately reduce source stock and increase destination stock.
7. Click **Save Transfer**.
8. Review transfer records.

## Sales Reports

Use **Sales Reports** to review sales across users, items, dates, and locations.

1. Click **Sales Reports**.
2. Filter by user if needed.
3. Filter by item code if needed.
4. Filter by location if needed.
5. Filter by date range if needed.
6. Review **Sales by Item**.
7. Review **Sales by User**.
8. Review **Sales by Location**.
9. Review detailed sales records.

## Activity Logs

Use **Activity Logs** to verify transaction history.

1. Click **Activity Logs**.
2. Search by user or item code.
3. Review action type.
4. Review source:
   - `Sales Account`
   - `User Account`
   - `Legacy`
5. Review quantity before, quantity changed, and quantity after.
6. Review verification:
   - `Verified`: quantity math matches.
   - `Review`: quantity math does not match.
   - `Unverified`: older or legacy record.

## QR Labels

Use **QR Labels** to print item labels.

1. Click **QR Labels**.
2. Select the items you want labels for.
3. Review printable labels.
4. Print from your browser if needed.

## Detailed Walkthrough: Complete Sale Lifecycle

This example shows one full workflow from setup to sale review.

### Goal

Create a location, create a sales user, add inventory, assign access, sell an item, record payment, and verify the transaction.

### Step 1: Create the Location

1. Log in as Ruth.
2. Click **Locations**.
3. Enter location name, for example `Main Store`.
4. Enter address, for example `100 Market Street`.
5. Click **Save Location**.

### Step 2: Create the Sales User

1. Click **Users & Access**.
2. Enter username, for example `sales1`.
3. Enter a password.
4. Select role `sales`.
5. Click **Create User**.

### Step 3: Assign the Sales User to the Location

1. Click **Locations**.
2. Go to **Assign Users to Locations**.
3. Select `sales1`.
4. Select `Main Store`.
5. Click **Assign Location**.

### Step 4: Add Inventory

1. Click **Inventory Entry**.
2. Enter item code, for example `ITEM-001`.
3. Enter item name, for example `Test Product`.
4. Enter a description.
5. Enter location name `Main Store`.
6. Enter location address `100 Market Street`.
7. Enter quantity, for example `50`.
8. Enter inventory cost, for example `10.00`.
9. Click **Save Inventory Entry**.

### Step 5: Confirm Stock and Price

1. Click **Stock & Pricing**.
2. Select `Main Store`.
3. Select `Test Product`.
4. Confirm quantity.
5. Confirm or set location price.
6. Click **Save Stock / Price** if changes are needed.

### Step 6: Optional Product Restriction

Use this only if the sales user should sell only specific products.

1. Click **Users & Access**.
2. Go to **Assign Inventory Products**.
3. Select `sales1`.
4. Select `Test Product`.
5. Click **Assign Product**.

### Step 7: Create the Sale as the Sales User

1. Sign out.
2. Log in as `sales1`.
3. Click **Create Sale**.
4. Select `Main Store`.
5. Select `Test Product`.
6. Enter customer name.
7. Enter quantity sold.
8. Confirm unit price.
9. Choose **Credit Sale**:
   - `No`: not a credit sale; full payment is received now.
   - `Yes`: credit sale; no payment has been received yet.
   - `Partially Paid`: credit sale with a partial payment received.
10. If payment options appear, select payment method and enter reference if needed.
11. Click **Create Sale**.

The app creates an invoice, records payment if provided, reduces location stock, and records a transaction.

### Step 8: Review the Sale as Ruth

1. Sign out.
2. Log in as Ruth.
3. Click **Sales Reports**.
4. Filter by `sales1`, `Test Product`, or `Main Store`.
5. Confirm the sale appears with the correct location.
6. Review **Sales by Location**.

### Step 9: Review Financials

1. Click **Financials**.
2. Find the invoice.
3. Confirm total, paid amount, outstanding amount, and status.
4. If more payment is received later, use **Record Payment**.

### Step 10: Verify the Transaction

1. Click **Activity Logs**.
2. Search for `sales1` or `ITEM-001`.
3. Confirm source is `Sales Account`.
4. Confirm quantity before minus quantity changed equals quantity after.
5. Confirm verification says `Verified`.

## Detailed Walkthrough: User Account Leftover Return

Use this when a standard `user` has personal stock and needs to return leftover items or take items out.

1. Log in as the standard user.
2. Click **Receive Stock**.
3. Select a location.
4. Select an available item.
5. Click **View Item Details**.
6. If the user needs stock first, enter quantity and click **Add to My Stock**.
7. Under **User Account Actions**, enter **Return Leftover Quantity**.
8. Click **Return to Inventory**.
9. To remove stock without returning it to system inventory, enter **Take Out Quantity**.
10. Click **Take Out**.
11. Click **Activity Logs** to confirm the action appears as `Returned to Inventory` or `Taken Out`.
