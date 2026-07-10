# Sales User Guide

This guide explains how to use the app as a `sales` user. Sales users work at assigned locations, receive stock into location inventory, create sales invoices, record credit/payment status, and review their own activity.

## Before You Start

Ruth must set up your account first.

You need:

1. A `sales` user account.
2. At least one assigned location.
3. Stock available at that assigned location.
4. Optional product assignments if Ruth wants to limit which products you can sell.

If a page says no locations or stock are available, ask Ruth to assign your location or add location stock.

## Dashboard

Use **Overview** to see your assigned sales activity.

1. Log in with your sales account.
2. Click **Overview**.
3. Review assigned locations.
4. Review available stock.
5. Review recent sales invoices.

## Receive Stock

Use **Receive Stock** when stock is manually received into one of your assigned locations.

1. Click **Receive Stock**.
2. Select the location receiving stock.
3. Select an available item.
4. Optional: enter or scan an item code.
5. Click **View Item Details**.
6. Review system quantity and current location quantity.
7. Enter **Quantity to Receive**.
8. Click **Add to My Stock**.

For a sales user, this adds stock to the selected location. It also records a transaction with source `Sales Account`.

## Create Sale

Use **Create Sale** to sell from location stock.

1. Click **Create Sale**.
2. Select the assigned location.
3. Select the item being sold.
4. Enter customer name.
5. Enter quantity.
6. Confirm or adjust unit price.
7. Select **Credit Sale**:
   - `No`: not a credit sale; customer paid the full sale amount.
   - `Yes`: credit sale; customer has not paid yet.
   - `Partially Paid`: credit sale with a partial payment received.
8. If payment fields appear, select payment method and enter reference if needed.
9. Review the sale preview.
10. Click **Create Sale**.

The app creates an invoice, reduces location inventory, records payment if provided, and writes a verified transaction.

## Returns / Damaged

Use **Returns / Damaged** when a customer returns an item or an item is bad, damaged, defective, expired, or otherwise not sellable.

1. Click **Returns / Damaged**.
2. Select the location.
3. Select the item.
4. Enter quantity.
5. Select condition.
6. Enter reason.
7. Click **Save Return**.
8. Review return records below the form.

## Activity Logs

Use **Activity Logs** to review your sales and stock activity.

1. Click **Activity Logs**.
2. Search by user or item code if needed.
3. Review action type.
4. Review quantity before, quantity changed, and quantity after.
5. Confirm verification says `Verified`.

## Detailed Walkthrough: Receive Stock and Sell It

### Step 1: Receive Stock

1. Log in as the sales user.
2. Click **Receive Stock**.
3. Select your assigned location.
4. Select an item.
5. Click **View Item Details**.
6. Enter quantity to receive.
7. Click **Add to My Stock**.

### Step 2: Create a Sale

1. Click **Create Sale**.
2. Select the same location.
3. Select the item.
4. Enter customer name.
5. Enter quantity sold.
6. Select credit sale status.
7. Enter payment details if needed.
8. Click **Create Sale**.

### Step 3: Verify the Sale

1. Click **Activity Logs**.
2. Search for the item code.
3. Confirm the sale appears.
4. Confirm source is `Sales Account`.
5. Confirm verification is `Verified`.
