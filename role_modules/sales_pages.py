from role_modules.admin_pages import consume_invoice_location_ownership


def configure(context):
    globals().update(
        {
            key: value
            for key, value in context.items()
            if not key.startswith("__")
        }
    )


def render(menu):
    if menu == "Dashboard" and get_current_role() == "sales":
        username_safe = safe_html(st.session_state.username)
        assigned_location_ids = get_assigned_location_ids()
        supplied_item_codes = set(get_supplied_item_codes())

        conn = get_connection()
        sales_locations_df = pd.read_sql_query(
            "SELECT id, name FROM locations WHERE active=1",
            conn
        )
        sales_stock_df = pd.read_sql_query(
            '''
            SELECT li.location_id, l.name AS location, li.item_code, i.item_name,
                   li.quantity, COALESCE(lp.price, 0) AS price
            FROM location_inventory li
            LEFT JOIN locations l ON li.location_id = l.id
            LEFT JOIN inventory i ON li.item_code = i.item_code
            LEFT JOIN location_prices lp ON lp.location_id = li.location_id AND lp.item_code = li.item_code
            WHERE li.quantity > 0
            ''',
            conn
        )
        sales_invoice_df = pd.read_sql_query(
            '''
            SELECT inv.invoice_number, inv.location_id, l.name AS location, inv.customer_name,
                   inv.total, inv.status, inv.created_at
            FROM invoices inv
            LEFT JOIN locations l ON inv.location_id = l.id
            WHERE inv.created_by=?
            ORDER BY inv.id DESC
            ''',
            conn,
            params=(st.session_state.username,)
        )
        conn.close()

        sales_locations_df = sales_locations_df[
            sales_locations_df["id"].isin(assigned_location_ids)
        ].copy()
        sales_stock_df = sales_stock_df[
            sales_stock_df["location_id"].isin(assigned_location_ids)
        ].copy()
        if supplied_item_codes:
            sales_stock_df = sales_stock_df[
                sales_stock_df["item_code"].isin(supplied_item_codes)
            ].copy()
        sales_stock_df = sales_stock_df[sales_stock_df["price"] > 0].copy()
        sales_invoice_df = sales_invoice_df[
            sales_invoice_df["location_id"].isin(assigned_location_ids)
        ].copy()

        assigned_location_count = len(sales_locations_df)
        available_items = sales_stock_df["item_code"].nunique() if not sales_stock_df.empty else 0
        available_units = int(sales_stock_df["quantity"].sum()) if not sales_stock_df.empty else 0
        invoices_created = len(sales_invoice_df)
        invoice_total = float(sales_invoice_df["total"].sum()) if not sales_invoice_df.empty else 0

        st.markdown(
            f"""
            <div class="page-header">
                <div class="page-eyebrow">Sales Dashboard</div>
                <div class="page-title">Welcome, {username_safe}</div>
                <p class="page-subtitle">Review assigned locations, available stock, and your recent sales activity.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        sales_col1, sales_col2, sales_col3, sales_col4 = st.columns(4)

        with sales_col1:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Locations</div>
                    <div class="user-metric-value">{assigned_location_count}</div>
                    <div class="user-metric-note">Assigned active locations</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with sales_col2:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Sellable Items</div>
                    <div class="user-metric-value">{available_items}</div>
                    <div class="user-metric-note">Items with available stock</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with sales_col3:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Available Units</div>
                    <div class="user-metric-value">{available_units}</div>
                    <div class="user-metric-note">Total assigned-location stock</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with sales_col4:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">My Invoices</div>
                    <div class="user-metric-value">{invoices_created}</div>
                    <div class="user-metric-note">{format_currency(invoice_total)} total created</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        stock_col, invoice_col = st.columns(2)

        with stock_col:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Assigned Location Stock</div>', unsafe_allow_html=True)

                if sales_stock_df.empty:
                    show_next_step(
                        "No sellable inventory exists for your assigned locations yet.",
                        "Ask Ruth or an admin to add stock and pricing in Location Inventory."
                    )
                else:
                    stock_display_df = sales_stock_df[
                        ["location", "item_code", "item_name", "quantity", "price"]
                    ].copy()
                    stock_display_df["stock_status"] = stock_display_df["quantity"].apply(stock_status)
                    st.dataframe(
                        stock_display_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "location": "Location",
                            "item_code": "Item Code",
                            "item_name": "Item Name",
                            "quantity": "Quantity",
                            "stock_status": "Stock Status",
                            "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                        }
                    )

        with invoice_col:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Recent Sales Invoices</div>', unsafe_allow_html=True)

                if sales_invoice_df.empty:
                    st.info("No sales invoices have been created by your account yet.")
                else:
                    recent_sales_df = sales_invoice_df.head(6).copy()
                    recent_sales_df["total_display"] = recent_sales_df["total"].apply(format_currency)
                    recent_sales_df = recent_sales_df[
                        ["invoice_number", "location", "customer_name", "total_display", "status", "created_at"]
                    ]
                    st.dataframe(
                        recent_sales_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "invoice_number": "Invoice",
                            "location": "Location",
                            "customer_name": "Customer",
                            "total_display": "Total",
                            "status": "Status",
                            "created_at": "Created",
                        }
                    )


    if menu == "Sell Item" and get_current_role() == "sales":
        if "sales_invoice_message" in st.session_state:
            st.success(st.session_state.sales_invoice_message)
            del st.session_state.sales_invoice_message

        assigned_location_ids = get_assigned_location_ids()
        supplied_item_codes = set(get_supplied_item_codes())

        conn = get_connection()
        locations_df = pd.read_sql_query(
            "SELECT id, name FROM locations WHERE active=1 ORDER BY name",
            conn
        )
        inventory_df = pd.read_sql_query(
            '''
            SELECT li.location_id, li.item_code, i.item_name, li.quantity,
                   COALESCE(lp.price, 0) AS price
            FROM location_inventory li
            LEFT JOIN inventory i ON li.item_code = i.item_code
            LEFT JOIN location_prices lp
                ON lp.location_id = li.location_id AND lp.item_code = li.item_code
            WHERE li.quantity > 0
            ORDER BY i.item_name
            ''',
            conn
        )
        conn.close()

        locations_df = locations_df[locations_df["id"].isin(assigned_location_ids)].copy()
        inventory_df = inventory_df[inventory_df["location_id"].isin(assigned_location_ids)].copy()
        if supplied_item_codes:
            inventory_df = inventory_df[inventory_df["item_code"].isin(supplied_item_codes)].copy()
        inventory_df = inventory_df[inventory_df["price"] > 0].copy()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Location Sale</div>
                <div class="page-title">Sell Item</div>
                <p class="page-subtitle">Create invoices from assigned location inventory using location-specific pricing.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        sale_form_col, sale_table_col = st.columns([0.9, 1.1])

        with sale_form_col:
            st.markdown('<div class="dashboard-section-title">Create Sale Invoice</div>', unsafe_allow_html=True)

            if locations_df.empty:
                show_next_step(
                    "You do not have any active assigned locations yet.",
                    "Ruth should open Locations and assign your sales account to a location."
                )
            elif inventory_df.empty:
                show_next_step(
                    "No sellable inventory exists for your assigned locations.",
                    "Ask Ruth or an admin to add stock and pricing in Location Inventory."
                )
            else:
                location_options = {
                    f"{row['name']} (ID {row['id']})": int(row["id"])
                    for _, row in locations_df.iterrows()
                }
                create_sale_invoice = False

                st.markdown(
                    """
                    <div class="workflow-panel">
                        <div class="workflow-kicker">Step 1</div>
                        <div class="workflow-title">Select Location</div>
                        <div class="workflow-text">Choose the assigned location where this sale is happening.</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                selected_location = st.selectbox(
                    "Location",
                    list(location_options.keys()),
                    key="sales_location_selector"
                )
                selected_location_id = location_options[selected_location]
                available_items_df = inventory_df[inventory_df["location_id"] == selected_location_id].copy()

                item_options = {
                    f"{row['item_name']} ({row['item_code']}) - {int(row['quantity'])} available - ${float(row['price']):.2f}":
                    row["item_code"]
                    for _, row in available_items_df.iterrows()
                }

                if not item_options:
                    st.info("This selected location has no available inventory to sell.")
                    st.button("Create Sale", disabled=True, width="stretch")
                else:
                    st.markdown(
                        """
                        <div class="workflow-panel">
                            <div class="workflow-kicker">Step 2</div>
                            <div class="workflow-title">Select Item</div>
                            <div class="workflow-text">Pick the item being sold. Available stock and price come from the selected location.</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    selected_item = st.selectbox(
                        "Item",
                        list(item_options.keys()),
                        key=f"sales_item_selector_{selected_location_id}"
                    )
                    selected_item_code = item_options[selected_item]
                    selected_item_row = available_items_df[
                        available_items_df["item_code"] == selected_item_code
                    ].iloc[0]
                    available_quantity = int(selected_item_row["quantity"])
                    default_price = float(selected_item_row["price"])

                    with st.form(f"sales_create_invoice_form_{selected_location_id}_{selected_item_code}"):
                        st.markdown(
                            """
                            <div class="workflow-kicker">Step 3</div>
                            <div class="workflow-title">Confirm Sale and Payment</div>
                            """,
                            unsafe_allow_html=True
                        )
                        st.caption(
                            f"Available at this location: {available_quantity} unit(s). "
                            f"Default location price: ${default_price:.2f}."
                        )
                        st.markdown(
                            '<div class="modern-form-note">Enter the sale details, then record the customer payment method before creating the invoice.</div>',
                            unsafe_allow_html=True
                        )
                        customer_name = st.text_input(
                            "Customer Name",
                            placeholder="Customer or company name"
                        )
                        quantity_col, price_col = st.columns(2)
                        with quantity_col:
                            sale_quantity = st.number_input(
                                "Quantity",
                                min_value=1,
                                max_value=max(available_quantity, 1),
                                step=1
                            )
                        with price_col:
                            unit_price = st.number_input(
                                "Unit Price",
                                min_value=0.01,
                                value=default_price,
                                step=0.01,
                                format="%.2f",
                                disabled=True,
                                help="Selling price is configured by Super Admin or Admin for this location."
                            )

                        sale_total_preview = int(sale_quantity) * float(unit_price)
                        credit_col, payment_status_col = st.columns([0.9, 1.1])
                        with credit_col:
                            credit_status = st.selectbox(
                                "Credit Sale",
                                ["No", "Yes", "Partially Paid"],
                                key=f"sales_credit_status_{selected_location_id}_{selected_item_code}"
                            )
                        with payment_status_col:
                            payment_status_label = {
                                "No": "Fully paid sale",
                                "Yes": "Credit sale - unpaid",
                                "Partially Paid": "Partial payment received",
                            }[credit_status]
                            st.text_input(
                                "Payment Status",
                                value=payment_status_label,
                                disabled=True,
                                key=f"sales_payment_status_{selected_location_id}_{selected_item_code}"
                            )

                        payment_amount = sale_total_preview if credit_status == "No" else 0.0
                        payment_method = "cash"
                        reference_number = ""

                        if credit_status in {"No", "Partially Paid"}:
                            payment_amount_col, payment_method_col = st.columns([1, 1])
                            with payment_amount_col:
                                payment_amount = st.number_input(
                                    "Payment Amount",
                                    min_value=0.0,
                                    max_value=sale_total_preview,
                                    value=sale_total_preview if credit_status == "No" else 0.0,
                                    step=0.01,
                                    format="%.2f",
                                    disabled=credit_status == "No",
                                    help="Full payment is automatic for No; enter the received amount for partially paid credit sales."
                                )
                            with payment_method_col:
                                payment_method = st.selectbox(
                                    "Payment Method",
                                    ["cash", "check", "wire", "credit_card"]
                                )
                            reference_number = st.text_input(
                                "Payment Reference",
                                placeholder="Check number, wire ID, card note, or receipt number"
                            )
                        else:
                            st.caption("No payment details are required for unpaid credit sales.")

                        if credit_status == "Partially Paid" and payment_amount <= 0:
                            st.warning("Enter the partial payment amount before creating the sale.")
                        paid_preview = float(payment_amount)
                        balance_preview = max(sale_total_preview - paid_preview, 0)
                        sale_stock_after = max(available_quantity - int(sale_quantity), 0)
                        st.markdown(
                            f"""
                            <div class="modern-form-summary">
                                <div class="modern-form-summary-title">Sale Preview</div>
                                <div class="modern-form-summary-grid four">
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Sale Total</div>
                                        <div class="modern-form-summary-value">${sale_total_preview:,.2f}</div>
                                    </div>
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Payment</div>
                                        <div class="modern-form-summary-value">${paid_preview:,.2f}</div>
                                    </div>
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Balance</div>
                                        <div class="modern-form-summary-value">${balance_preview:,.2f}</div>
                                    </div>
                                    <div class="modern-form-summary-card">
                                        <div class="modern-form-summary-label">Stock After</div>
                                        <div class="modern-form-summary-value">{sale_stock_after} units</div>
                                    </div>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        create_sale_invoice = st.form_submit_button("Create Sale", type="primary", width="stretch")

                if create_sale_invoice:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    quantity_int = int(sale_quantity)
                    line_total = round(quantity_int * float(unit_price), 2)
                    payment_amount_rounded = round(float(payment_amount), 2)
                    if not customer_name.strip():
                        st.error("Customer Name is required before creating a sale.")
                        st.stop()
                    if float(unit_price) <= 0:
                        st.error("A valid location selling price is required before creating a sale.")
                        st.stop()
                    if payment_amount_rounded > line_total:
                        st.error(f"Payment cannot exceed the sale total of ${line_total:,.2f}.")
                        st.stop()
                    if credit_status == "No" and payment_amount_rounded != line_total:
                        st.error("Credit Sale 'No' means the sale must be fully paid.")
                        st.stop()
                    if credit_status == "Yes" and payment_amount_rounded != 0:
                        st.error("Credit Sale 'Yes' means no payment has been received yet.")
                        st.stop()
                    if credit_status == "Partially Paid" and not (0 < payment_amount_rounded < line_total):
                        st.error("Credit Sale 'Partially Paid' requires a payment greater than 0 and less than the sale total.")
                        st.stop()

                    conn = get_connection()
                    c = conn.cursor()

                    try:
                        c.execute("BEGIN IMMEDIATE")
                        c.execute(
                            '''
                            SELECT quantity FROM location_inventory
                            WHERE location_id=? AND item_code=?
                            ''',
                            (selected_location_id, selected_item_code)
                        )
                        stock_row = c.fetchone()
                        current_quantity = int(stock_row[0]) if stock_row else 0

                        c.execute(
                            '''
                            SELECT COALESCE(price, 0) FROM location_prices
                            WHERE location_id=? AND item_code=?
                            ''',
                            (selected_location_id, selected_item_code)
                        )
                        locked_price_row = c.fetchone()
                        locked_location_price = round(
                            float(locked_price_row[0] or 0) if locked_price_row else 0.0,
                            2
                        )

                        if quantity_int > current_quantity:
                            conn.rollback()
                            st.error("Not enough inventory is available at this assigned location to complete the sale.")
                        elif locked_location_price <= 0:
                            conn.rollback()
                            st.error("This item no longer has a valid selling price at the selected location.")
                        elif locked_location_price != round(float(unit_price), 2):
                            conn.rollback()
                            st.error(
                                "The location selling price changed while this form was open. Refresh the page "
                                "and review the updated price before creating the sale."
                            )
                        else:
                            consume_invoice_location_ownership(
                                c, "super_admin", st.session_state.username,
                                selected_location_id, selected_item_code, quantity_int
                            )
                            c.execute(
                                '''
                                UPDATE location_inventory
                                SET quantity=?
                                WHERE location_id=? AND item_code=?
                                ''',
                                (current_quantity - quantity_int, selected_location_id, selected_item_code)
                            )
                            c.execute(
                                '''
                                INSERT INTO location_stock_history
                                (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                VALUES (?,?,?,?,?,?,?,?)
                                ''',
                                (
                                    selected_location_id,
                                    selected_item_code,
                                    current_quantity,
                                    -quantity_int,
                                    current_quantity - quantity_int,
                                    "Sale",
                                    st.session_state.username,
                                    now
                                )
                            )
                            c.execute(
                                '''
                                INSERT INTO invoices
                                (location_id,customer_name,created_by,subtotal,total,status,created_at)
                                VALUES (?,?,?,?,?,?,?)
                                ''',
                                (
                                    selected_location_id,
                                    customer_name.strip(),
                                    st.session_state.username,
                                    line_total,
                                    line_total,
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
                                (invoice_id,item_code,quantity,unit_price,line_total)
                                VALUES (?,?,?,?,?)
                                ''',
                                (invoice_id, selected_item_code, quantity_int, float(unit_price), line_total)
                            )
                            if payment_amount_rounded > 0:
                                c.execute(
                                    '''
                                    INSERT INTO payments
                                    (invoice_id,amount,payment_method,reference_number,received_by,paid_at)
                                    VALUES (?,?,?,?,?,?)
                                    ''',
                                    (
                                        invoice_id,
                                        payment_amount_rounded,
                                        payment_method,
                                        reference_number.strip(),
                                        st.session_state.username,
                                        now
                                    )
                                )
                                if payment_amount_rounded >= line_total:
                                    c.execute("UPDATE invoices SET status='paid' WHERE id=?", (invoice_id,))

                            c.execute(
                                '''
                                    INSERT INTO transactions
                                    (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,source_type,location_id,transaction_time)
                                    VALUES (?,?,?,?,?,?,?,?,?)
                                    ''',
                                    (
                                        st.session_state.username,
                                        selected_item_code,
                                        quantity_int,
                                        current_quantity,
                                        current_quantity - quantity_int,
                                        "sale",
                                        "location_stock",
                                        selected_location_id,
                                        now
                                    )
                                )
                            conn.commit()
                            st.session_state.sales_invoice_message = (
                                f"Sale invoice {invoice_number} created successfully. Assigned location inventory was reduced and payment details were saved if provided."
                            )
                            st.rerun()
                    finally:
                        conn.close()

        with sale_table_col:
            st.markdown('<div class="dashboard-section-title">Assigned Location Stock</div>', unsafe_allow_html=True)

            if inventory_df.empty:
                st.info("No assigned location stock is available for your sales account.")
            else:
                display_stock_df = inventory_df.merge(
                    locations_df.rename(columns={"id": "location_id", "name": "location"}),
                    on="location_id",
                    how="left"
                )[["location", "item_code", "item_name", "quantity", "price"]]
                st.dataframe(
                    display_stock_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "location": "Location",
                        "item_code": "Item Code",
                        "item_name": "Item Name",
                        "quantity": "Available",
                        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
                    }
                )


