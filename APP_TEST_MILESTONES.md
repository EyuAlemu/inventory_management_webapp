# App Test Milestones

Use this checklist to test the whole inventory app from setup to reporting. Test in order because later milestones depend on earlier setup.

## Milestone 1: Start the App and Log In

Goal: Confirm the app opens and Ruth can sign in.

1. Start the app with `streamlit run app.py`.
2. Open the local URL in your browser.
3. Log in as `Ruth`.
4. Confirm the sidebar shows Ruth-only pages:
   - Overview
   - Stock & Pricing
   - Returns / Damaged
   - Transfers
   - Financials
   - Locations
   - Users & Access
   - Inventory Entry
   - Inventory View
   - QR Labels
   - Sales Reports
   - Activity Logs

Pass result:

- Ruth can log in and see owner-level navigation.

## Milestone 2: Create Locations

Goal: Confirm Ruth can create and manage locations.

1. Open **Locations**.
2. Create `Main Store` with an address.
3. Create `Warehouse` with an address.
4. Confirm both locations appear in **Existing Locations**.
5. Edit one location address.
6. Save the update.
7. Confirm the change appears in the table.

Pass result:

- Locations can be created, edited, and viewed.

## Milestone 3: Create Users

Goal: Confirm Ruth can create all user roles.

1. Open **Users & Access**.
2. Create an admin user, for example `admin1`.
3. Create a sales user, for example `sales1`.
4. Create a standard user, for example `user1`.
5. Confirm all users appear in **Existing Users** with the correct roles.

Pass result:

- Admin, sales, and standard user accounts are created.

## Milestone 4: Assign Users to Locations

Goal: Confirm admins and sales users can be assigned to locations.

1. Open **Locations**.
2. Assign `admin1` to `Main Store`.
3. Assign `admin1` to `Warehouse`.
4. Assign `sales1` to `Main Store`.
5. Confirm the assignments appear in the location assignment table.

Pass result:

- Admin and sales users are connected to the correct locations.

## Milestone 5: Create Inventory Entries

Goal: Confirm Ruth can create inventory with location, address, quantity, and cost.

1. Open **Inventory Entry**.
2. Create item `ITEM-001`, for example `Test Product A`.
3. Use location `Main Store`.
4. Enter quantity, for example `50`.
5. Enter inventory cost, for example `10.00`.
6. Save the inventory entry.
7. Create item `ITEM-002`, for example `Test Product B`.
8. Use location `Warehouse`.
9. Enter quantity and cost.
10. Save the inventory entry.

Pass result:

- Inventory items are created and QR codes are generated.

## Milestone 6: Review Inventory View

Goal: Confirm Ruth can view inventory with location fields.

1. Open **Inventory View**.
2. Search for `ITEM-001`.
3. Confirm the table shows:
   - Item Code
   - Item Name
   - Description
   - Location
   - Address
   - Quantity
   - Cost
4. Click **Edit** for an item.
5. Update cost or description.
6. Save the update.
7. Confirm the table reflects the update.

Pass result:

- Inventory View displays location, address, and cost correctly.

## Milestone 7: Assign Inventory Products

Goal: Confirm Ruth can assign products to admin and sales users.

1. Open **Users & Access**.
2. Go to **Assign Inventory Products**.
3. Assign `ITEM-001` to `admin1`.
4. Assign `ITEM-001` to `sales1`.
5. Confirm the assignments show in the product assignment table.

Pass result:

- Admin and sales users can be assigned products.

## Milestone 8: Stock & Pricing

Goal: Confirm location stock and price can be managed.

1. Open **Stock & Pricing** as Ruth.
2. Select `Main Store`.
3. Select `ITEM-001`.
4. Set quantity, for example `50`.
5. Set price, for example `20.00`.
6. Save.
7. Confirm the stock table shows the location, item, quantity, and price.

Pass result:

- Location quantity and price are saved.

## Milestone 9: Admin Login and Scoped Access

Goal: Confirm admin sees only assigned data.

1. Sign out.
2. Log in as `admin1`.
3. Open **Overview**.
4. Confirm assigned-location and supplied-product information appears.
5. Open **Stock & Pricing**.
6. Confirm only assigned locations/products are available.
7. Open **Financials**.
8. Confirm admin can create invoices only for accessible location/product records.

Pass result:

- Admin access is scoped correctly.

## Milestone 10: Admin Creates Invoice

Goal: Confirm admin invoice creation reduces stock and creates transaction history.

1. Log in as `admin1`.
2. Open **Financials**.
3. Select `Main Store`.
4. Select `ITEM-001`.
5. Enter customer name.
6. Enter quantity, for example `2`.
7. Confirm unit price.
8. Click **Create Invoice**.
9. Open **Activity Logs**.
10. Search for `ITEM-001`.
11. Confirm a sale transaction appears and verification is `Verified`.

Pass result:

- Admin invoice reduces stock and creates a verified sale transaction.

## Milestone 11: Record Payment

Goal: Confirm payment tracking works and prevents overpayment.

1. Log in as Ruth or `admin1`.
2. Open **Financials**.
3. Select the invoice from Milestone 10.
4. Record a partial payment.
5. Confirm invoice status becomes partially paid/open balance.
6. Try recording a payment greater than the outstanding amount.
7. Confirm the app blocks the overpayment.
8. Record the remaining valid balance.
9. Confirm status becomes paid.

Pass result:

- Payments update invoice status and overpayments are blocked.

## Milestone 12: Sales Login and Sale Workflow

Goal: Confirm sales users can sell from assigned locations.

1. Sign out.
2. Log in as `sales1`.
3. Open **Create Sale**.
4. Select `Main Store`.
5. Select `ITEM-001`.
6. Enter customer name.
7. Enter quantity, for example `1`.
8. Select **Credit Sale**:
   - Test `No` for a fully paid non-credit sale.
   - Test `Yes` for an unpaid credit sale.
   - Test `Partially Paid` for a credit sale with partial payment.
9. Confirm payment options display for `No` and `Partially Paid`.
10. Create the sale.
11. Open **Activity Logs**.
12. Confirm the sale is listed and verification is `Verified`.

Pass result:

- Sales user can create a sale, stock is reduced, payment UI works, and transaction verifies.

## Milestone 13: Sales Receive Stock

Goal: Confirm sales users can manually receive stock into assigned locations.

1. Log in as `sales1`.
2. Open **Receive Stock**.
3. Select `Main Store`.
4. Select an available item.
5. Click **View Item Details**.
6. Enter quantity to receive.
7. Click **Add to My Stock**.
8. Open **Activity Logs**.
9. Confirm source shows `Sales Account` and verification is `Verified`.

Pass result:

- Sales stock receiving updates location stock and creates a verified transaction.

## Milestone 14: Standard User Receive Stock

Goal: Confirm standard users can receive stock into personal inventory.

1. Sign out.
2. Log in as `user1`.
3. Open **Receive Stock**.
4. Select a location.
5. Select an available item.
6. Click **View Item Details**.
7. Enter quantity to receive.
8. Click **Add to My Stock**.
9. Open **Overview**.
10. Confirm personal stock increased.

Pass result:

- Standard user can receive personal stock.

## Milestone 15: Standard User Sale

Goal: Confirm standard users can sell from personal stock.

1. Log in as `user1`.
2. Open **Create Sale**.
3. Enter the item code received in Milestone 14.
4. Click **View Sale Details**.
5. Enter quantity sold.
6. Click **Save Sale**.
7. Open **Activity Logs**.
8. Confirm sale transaction appears and verification is `Verified`.

Pass result:

- Standard user sale reduces personal stock and verifies.

## Milestone 16: User Return and Take Out

Goal: Confirm standard users can return leftovers or take items out.

1. Log in as `user1`.
2. Open **Receive Stock**.
3. Select an item that exists in personal stock.
4. Click **View Item Details**.
5. Enter **Return Leftover Quantity**.
6. Click **Return to Inventory**.
7. Confirm activity says `Returned to Inventory`.
8. Repeat with **Take Out Quantity**.
9. Click **Take Out**.
10. Confirm activity says `Taken Out`.

Pass result:

- User account stock can be returned or taken out, and both actions are logged.

## Milestone 17: Returns / Damaged

Goal: Confirm returns can be recorded by Ruth, admin, or sales.

1. Log in as Ruth or `sales1`.
2. Open **Returns / Damaged**.
3. Select location.
4. Select item.
5. Enter quantity.
6. Select condition.
7. Enter reason.
8. Click **Save Return**.
9. Confirm return appears in the records table.

Pass result:

- Return/damaged records are saved and visible.

## Milestone 18: Transfers

Goal: Confirm stock can move between locations.

1. Log in as Ruth.
2. Open **Transfers**.
3. Select item.
4. Select source location.
5. Select destination location.
6. Enter quantity.
7. Select `completed`.
8. Click **Save Transfer**.
9. Open **Stock & Pricing**.
10. Confirm source stock decreased and destination stock increased.

Pass result:

- Completed transfers update both locations.

## Milestone 19: Sales Reports

Goal: Confirm Ruth can review sales by user, item, date, and location.

1. Log in as Ruth.
2. Open **Sales Reports**.
3. Filter by user.
4. Filter by item code.
5. Filter by location.
6. Filter by date range.
7. Review:
   - Sales by Item
   - Sales by User
   - Sales by Location
   - Sales Records

Pass result:

- Sales reports show correct totals and location information.

## Milestone 20: Activity Logs and Verification

Goal: Confirm transaction verification works.

1. Log in as Ruth.
2. Open **Activity Logs**.
3. Search for test item codes.
4. Review source:
   - Sales Account
   - User Account
   - Legacy
5. Review quantity before, quantity changed, and quantity after.
6. Confirm new transactions show `Verified`.

Pass result:

- Transaction logs accurately reflect quantity changes.

## Milestone 21: QR Labels and Scanner

Goal: Confirm QR code label and scan workflow works.

1. Log in as Ruth.
2. Open **QR Labels**.
3. Select an item.
4. Confirm printable label appears.
5. Log in as a standard user.
6. Open **Scan QR / Barcode**.
7. Scan or capture the QR code.
8. Confirm the item code is copied into **Receive Stock**.

Pass result:

- QR labels generate and scanner routes to receive stock.

## Final Acceptance Checklist

The app passes full testing when:

- Ruth can create locations, users, inventory, assignments, stock, prices, transfers, and reports.
- Admin can manage assigned stock, invoices, payments, returns, transfers, and logs.
- Sales can receive location stock, create sales, record credit/payment status, and review activity.
- Standard users can receive personal stock, sell, return leftovers, take items out, and review activity.
- Inventory View shows location, address, quantity, and cost.
- Manage Sales shows location and Sales by Location.
- Transaction Logs show verified quantity math for new transactions.
- Credit sale options use `Yes`, `No`, and `Partially Paid`, with payment fields shown when money is received.
