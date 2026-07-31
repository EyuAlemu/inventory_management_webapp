from role_modules.sales_pages import calculate_sales_receive_capacity, validate_sales_sale_access


def calculate_user_receive_capacity(assigned_quantity, received_quantity, company_available_quantity):
    """Limit a Standard User receipt by their reservation and available company stock."""
    remaining_assignment = max(
        int(assigned_quantity or 0) - int(received_quantity or 0),
        0,
    )
    return min(remaining_assignment, max(int(company_available_quantity or 0), 0))


def validate_user_sale_access(cursor, username, item_code):
    """Confirm a Standard User still has product access and personally held stock."""
    cursor.execute(
        '''SELECT 1
           FROM users u
           JOIN product_suppliers ps ON LOWER(ps.username)=LOWER(u.username)
           WHERE LOWER(u.username)=LOWER(?) AND LOWER(u.role)='user'
             AND LOWER(ps.item_code)=LOWER(?)
           LIMIT 1''',
        (username, item_code),
    )
    if cursor.fetchone() is None:
        raise ValueError(
            "This product is not assigned to your account. Choose a product assigned by Super Admin."
        )

    cursor.execute(
        '''SELECT COALESCE(quantity,0) FROM user_inventory
           WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
        (username, item_code),
    )
    owned_row = cursor.fetchone()
    owned_quantity = int(owned_row[0] or 0) if owned_row else 0
    if owned_quantity <= 0:
        raise ValueError("You do not have any personal quantity of this item available to sell.")
    return owned_quantity


def configure(context):
    globals().update(
        {
            key: value
            for key, value in context.items()
            if not key.startswith("__")
        }
    )


def render(menu):
    if menu == "Dashboard" and get_current_role() == "user":
        username_safe = safe_html(st.session_state.username)
        conn = get_connection()
        user_transactions_df = pd.read_sql_query(
            "SELECT * FROM transactions WHERE username=? ORDER BY id DESC",
            conn,
            params=(st.session_state.username,)
        )
        user_stock_df = pd.read_sql_query(
            '''
            SELECT ui.item_code, ui.quantity, i.item_name
            FROM user_inventory ui
            LEFT JOIN inventory i ON ui.item_code = i.item_code
            WHERE ui.username=?
            ORDER BY ui.quantity DESC
            ''',
            conn,
            params=(st.session_state.username,)
        )
        conn.close()

        if not user_transactions_df.empty:
            user_transactions_df["transaction_type"] = user_transactions_df["transaction_type"].fillna("legacy")

        user_total_stock = int(user_stock_df["quantity"].sum()) if not user_stock_df.empty else 0
        user_total_sold = (
            int(user_transactions_df.loc[user_transactions_df["transaction_type"] == "sale", "quantity_used"].sum())
            if not user_transactions_df.empty else 0
        )
        user_total_allocated = (
            int(user_transactions_df.loc[user_transactions_df["transaction_type"] == "allocation", "quantity_used"].sum())
            if not user_transactions_df.empty else 0
        )
        user_item_count = int((user_stock_df["quantity"] > 0).sum()) if not user_stock_df.empty else 0
        user_stock_chart_html = '<div class="analytics-empty">No assigned stock yet.</div>'

        if not user_stock_df.empty:
            stock_chart_df = user_stock_df[user_stock_df["quantity"] > 0].head(6)

            if not stock_chart_df.empty:
                max_user_stock = max(int(stock_chart_df["quantity"].max()), 1)
                stock_chart_rows = []

                for _, row in stock_chart_df.iterrows():
                    item_label = safe_html(row["item_name"] or row["item_code"])
                    item_code_safe = safe_html(row["item_code"])
                    quantity = int(row["quantity"])
                    percent = min(int((quantity / max_user_stock) * 100), 100)
                    stock_chart_rows.append(
                        f"""
                        <div class="user-stock-row">
                            <div>
                                <div class="user-stock-name">{item_label}</div>
                                <div class="user-stock-meta">{item_code_safe}</div>
                                <div class="user-stock-track">
                                    <div class="user-stock-fill" style="width: {percent}%"></div>
                                </div>
                            </div>
                            <div class="user-stock-qty">{quantity}</div>
                        </div>
                        """
                    )

                user_stock_chart_html = "".join(stock_chart_rows)

        user_activity_chart_html = '<div class="analytics-empty">No activity yet.</div>'
        user_activity_total = user_total_sold + user_total_allocated

        if user_activity_total:
            received_percent = round((user_total_allocated / user_activity_total) * 100, 1)
            sold_percent = round((user_total_sold / user_activity_total) * 100, 1)
            user_activity_chart_html = (
                f'<div class="donut-layout">'
                f'<div class="donut-chart" style="background: conic-gradient(#0ea5e9 0% {received_percent}%, #14b8a6 {received_percent}% 100%);"></div>'
                f'<div class="donut-legend">'
                f'<div class="donut-legend-row"><span class="donut-dot" style="background: #0ea5e9;"></span><span>Received</span><span class="donut-percent">{received_percent}%</span></div>'
                f'<div class="donut-legend-row"><span class="donut-dot" style="background: #14b8a6;"></span><span>Sold</span><span class="donut-percent">{sold_percent}%</span></div>'
                f'</div>'
                f'</div>'
            )

        st.markdown(
            f"""
            <div class="page-header">
                <div class="page-eyebrow">User Dashboard</div>
                <div class="page-title">Welcome, {username_safe}</div>
                <p class="page-subtitle">Track your assigned stock, sales activity, and recent inventory movement.</p>
            </div>
            """,
            unsafe_allow_html=True
        )
        st.markdown('<div class="dashboard-section-title">My Reports & Analytics</div>', unsafe_allow_html=True)
        report_col1, report_col2, report_col3, report_col4 = st.columns(4)

        with report_col1:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">My Stock</div>
                    <div class="user-metric-value">{user_total_stock}</div>
                    <div class="user-metric-note">Units currently assigned</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with report_col2:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Items Held</div>
                    <div class="user-metric-value">{user_item_count}</div>
                    <div class="user-metric-note">Items with available quantity</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with report_col3:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Sold</div>
                    <div class="user-metric-value">{user_total_sold}</div>
                    <div class="user-metric-note">Units sold by you</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with report_col4:
            st.markdown(
                f"""
                <div class="user-metric-card">
                    <div class="user-metric-label">Received</div>
                    <div class="user-metric-value">{user_total_allocated}</div>
                    <div class="user-metric-note">Units added from inventory</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        chart_col1, chart_col2 = st.columns([1.15, 0.85])

        with chart_col1:
            st.html(
                f"""
                <div class="user-chart-card">
                    <div class="analytics-card-header">
                        <div class="user-chart-title">My Stock by Item</div>
                        <div class="user-chart-badge">Current stock</div>
                    </div>
                    {user_stock_chart_html}
                </div>
                """
            )

        with chart_col2:
            st.html(
                f"""
                <div class="user-chart-card">
                    <div class="analytics-card-header">
                        <div class="user-chart-title">Received vs Sold</div>
                        <div class="user-chart-badge">Activity mix</div>
                    </div>
                    {user_activity_chart_html}
                </div>
                """
            )

        user_report_col1, user_report_col2 = st.columns(2)

        with user_report_col1:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">My Current Stock</div>', unsafe_allow_html=True)
                if user_stock_df.empty:
                    st.info("No stock is assigned to your account yet. Ask an admin to allocate inventory before selling items.")
                else:
                    stock_display_df = user_stock_df.rename(
                        columns={
                            "item_code": "Item Code",
                            "item_name": "Item Name",
                            "quantity": "My Quantity",
                        }
                    )
                    st.dataframe(stock_display_df, width="stretch", hide_index=True)

        with user_report_col2:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Recent Activity</div>', unsafe_allow_html=True)
                if user_transactions_df.empty:
                    st.info("No activity has been recorded for your account yet. Your allocations and sales will appear here.")
                else:
                    recent_user_df = user_transactions_df.head(5)[
                        ["item_code", "transaction_type", "quantity_used", "quantity_after", "transaction_time"]
                    ].copy()
                    recent_user_df["transaction_type"] = recent_user_df["transaction_type"].replace({
                        "allocation": "Added to My Stock",
                        "sale": "Sold Item",
                        "return": "Returned to Inventory",
                        "take_out": "Taken Out",
                        "legacy": "Legacy Record",
                    })
                    recent_user_df = recent_user_df.rename(
                        columns={
                            "item_code": "Item Code",
                            "transaction_type": "Action",
                            "quantity_used": "Quantity",
                            "quantity_after": "My Qty After",
                            "transaction_time": "Time",
                        }
                    )
                    st.dataframe(recent_user_df, width="stretch", hide_index=True)


    if menu == "Scan QR / Barcode":

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Camera Scanner</div>
                <div class="page-title">Scan QR / Barcode</div>
                <p class="page-subtitle">Open the webcam, capture the item code, and continue to inventory lookup.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        scanner_col, info_col = st.columns([1.1, 0.9])

        with scanner_col:
            st.markdown(
                """
                <div class="scanner-card">
                    <div class="scanner-icon">▣</div>
                    <div class="dashboard-card-label">Webcam Scanner</div>
                    <div class="item-name" style="font-size: 1.15rem;">Scan QR / Barcode</div>
                    <div class="item-meta">Center the QR code or barcode in the camera image, then capture it.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            scanned_image = st.camera_input(
                "Open Webcam",
                key="qr_barcode_scanner"
            )

      
                    

        if scanned_image:
            scanned_code, scan_error = decode_qr_from_image(scanned_image)

            if scanned_code:
                st.session_state.prefill_scan_item_code = scanned_code
                st.session_state.menu = "Scan Inventory"
                st.success(f"Code detected: {scanned_code}. The item code has been copied into the inventory lookup flow.")
                st.rerun()
            elif scan_error:
                st.warning(scan_error)


    if menu == "Scan Inventory":

        if st.session_state.pop("scan_reset_receive_quantity", False):
            st.session_state.pop("scan_transfer_quantity", None)
        if st.session_state.pop("scan_reset_user_actions", False):
            st.session_state.pop("return_leftover_quantity", None)
            st.session_state.pop("take_out_quantity", None)

        if "scan_inventory_message" in st.session_state:
            st.success(st.session_state.scan_inventory_message)
            del st.session_state.scan_inventory_message

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Manual Stock Entry</div>
                <div class="page-title">Receive Stock</div>
                <p class="page-subtitle">Choose a location and available item to receive stock into a sales or user account.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        assigned_location_ids = get_assigned_location_ids()
        supplied_item_codes = set(get_supplied_item_codes())
        conn = get_connection()
        manual_locations_df = pd.read_sql_query(
            "SELECT id, name, address FROM locations WHERE active=1 ORDER BY name",
            conn
        )
        manual_inventory_df = pd.read_sql_query(
            "SELECT item_code, item_name, description, quantity FROM inventory WHERE quantity > 0 ORDER BY item_name",
            conn
        )
        conn.close()

        if get_current_role() == "sales":
            manual_locations_df = manual_locations_df[
                manual_locations_df["id"].isin(assigned_location_ids)
            ].copy()

        if get_current_role() in {"sales", "user"}:
            manual_inventory_df = manual_inventory_df[
                manual_inventory_df["item_code"].isin(supplied_item_codes)
            ].copy()

        lookup_col, detail_col = st.columns([0.9, 1.1])

        with lookup_col:
            if "prefill_scan_item_code" in st.session_state:
                st.session_state.scan_lookup_code = st.session_state.prefill_scan_item_code
                st.session_state.scan_selected_item_code = st.session_state.prefill_scan_item_code
                del st.session_state.prefill_scan_item_code

            st.markdown(
                """
                <div class="workflow-panel">
                    <div class="workflow-kicker">Step 1</div>
                    <div class="workflow-title">Manual Stock Entry</div>
                    <div class="workflow-text">Select the location and item being received. Scanned QR codes still prefill the item when available.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            if manual_locations_df.empty:
                st.info("No active location is available for this account.")
            elif manual_inventory_df.empty:
                st.info("No available inventory items are ready to receive for this account.")
            else:
                location_options = {
                    f"{row['name']} - {row['address'] or 'No address'}": int(row["id"])
                    for _, row in manual_locations_df.iterrows()
                }
                if get_current_role() == "sales":
                    item_options = {
                        f"{row['item_name']} ({row['item_code']})": row["item_code"]
                        for _, row in manual_inventory_df.iterrows()
                    }
                else:
                    item_options = {
                        f"{row['item_name']} ({row['item_code']})": row["item_code"]
                        for _, row in manual_inventory_df.iterrows()
                    }

                with st.form("scan_inventory_lookup_form"):
                    selected_manual_location = st.selectbox(
                        "Location",
                        list(location_options.keys()),
                        key="manual_receive_location"
                    )
                    selected_manual_item = st.selectbox(
                        "Available Item",
                        list(item_options.keys()),
                        key="manual_receive_item"
                    )
                    scan_lookup_code = st.text_input(
                        "Scanned or Typed Item Code",
                        key="scan_lookup_code",
                        placeholder="Optional QR/barcode item code"
                    )
                    lookup_submitted = st.form_submit_button(
                        "View Item Details",
                        type="primary",
                        width="stretch"
                    )

                if lookup_submitted:
                    selected_item_code = scan_lookup_code.strip() or item_options[selected_manual_item]
                    st.session_state.scan_selected_item_code = selected_item_code
                    st.session_state.scan_selected_location_id = location_options[selected_manual_location]

            item_code = st.session_state.get("scan_selected_item_code", "").strip()
            selected_location_id = st.session_state.get("scan_selected_location_id")
            allowed_manual_item_codes = {
                str(code).lower(): str(code)
                for code in manual_inventory_df["item_code"].astype(str).tolist()
            }
            if item_code:
                canonical_item_code = allowed_manual_item_codes.get(item_code.lower())
                if canonical_item_code is None:
                    st.session_state.pop("scan_selected_item_code", None)
                    item_code = ""
                    st.warning("That item is not available for this account. Choose an item from the available-item dropdown.")
                else:
                    item_code = canonical_item_code
                    st.session_state.scan_selected_item_code = canonical_item_code

        with detail_col:
            st.markdown('<div class="dashboard-section-title">Receive Stock</div>', unsafe_allow_html=True)

            if not item_code:
                st.info("Select a location and item on the left to receive stock into this account.")

        if item_code:

            conn = get_connection()
            c = conn.cursor()

            c.execute(
                "SELECT * FROM inventory WHERE LOWER(item_code)=LOWER(?)",
                (item_code,)
            )

            item = c.fetchone()

            if item:

                item_name_safe = safe_html(item[2])
                item_description_safe = safe_html(item[3])
                c.execute(
                    '''
                    SELECT quantity FROM user_inventory
                    WHERE username=? AND item_code=?
                    ''',
                    (st.session_state.username, item_code)
                )
                user_inventory_row = c.fetchone()
                user_quantity = int(user_inventory_row[0]) if user_inventory_row else 0
                c.execute(
                    '''
                    SELECT quantity FROM location_inventory
                    WHERE location_id=? AND item_code=?
                    ''',
                    (selected_location_id, item_code)
                )
                location_inventory_row = c.fetchone()
                location_quantity = int(location_inventory_row[0]) if location_inventory_row else 0
                receiving_sales_stock = get_current_role() == "sales"
                receiving_standard_user_stock = get_current_role() == "user"
                sales_assigned_quantity = 0
                sales_total_received_quantity = 0
                sales_location_quantity = 0
                if receiving_sales_stock:
                    c.execute(
                        '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                           WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                        (st.session_state.username, item_code)
                    )
                    sales_assignment_row = c.fetchone()
                    sales_assigned_quantity = int(sales_assignment_row[0] or 0) if sales_assignment_row else 0
                    c.execute(
                        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                           WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                        (st.session_state.username, item_code)
                    )
                    sales_total_received_quantity = int(c.fetchone()[0] or 0)
                    c.execute(
                        '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                           WHERE LOWER(username)=LOWER(?) AND location_id=?
                             AND LOWER(item_code)=LOWER(?)''',
                        (st.session_state.username, selected_location_id, item_code)
                    )
                    sales_location_row = c.fetchone()
                    sales_location_quantity = int(sales_location_row[0] or 0) if sales_location_row else 0
                    c.execute(
                        '''SELECT COALESCE(SUM(quantity),0) FROM location_inventory
                           WHERE LOWER(item_code)=LOWER(?)''',
                        (item_code,)
                    )
                    total_physical_quantity = int(c.fetchone()[0] or 0)
                    c.execute(
                        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                           WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                        (selected_location_id, item_code)
                    )
                    selected_location_owned_quantity = int(c.fetchone()[0] or 0)
                else:
                    total_physical_quantity = 0
                    selected_location_owned_quantity = 0
                user_assigned_quantity = 0
                if receiving_standard_user_stock:
                    c.execute(
                        '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                           WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                        (st.session_state.username, item_code)
                    )
                    user_assignment_row = c.fetchone()
                    user_assigned_quantity = (
                        int(user_assignment_row[0] or 0) if user_assignment_row else 0
                    )
                user_available_to_receive = calculate_user_receive_capacity(
                    user_assigned_quantity,
                    user_quantity,
                    int(item[4]),
                )
                sales_available_to_receive = calculate_sales_receive_capacity(
                    sales_assigned_quantity,
                    sales_total_received_quantity,
                    int(item[4]),
                    total_physical_quantity,
                    location_quantity,
                    selected_location_owned_quantity,
                )
                account_quantity = sales_location_quantity if receiving_sales_stock else user_quantity
                account_label = "Location Qty" if receiving_sales_stock else "My Current Qty"
                visible_status_quantity = (
                    sales_available_to_receive
                    if receiving_sales_stock else user_available_to_receive
                )
                status_class = "low" if visible_status_quantity <= 5 else "ok"
                status_text = "Low availability" if visible_status_quantity <= 5 else "Ready"

                with detail_col:
                    quantity_label = (
                        "ASSIGNED TO YOU"
                        if receiving_sales_stock or receiving_standard_user_stock
                        else "MY CURRENT QUANTITY"
                    )
                    quantity_value = (
                        sales_assigned_quantity
                        if receiving_sales_stock else user_assigned_quantity
                    )
                    st.markdown(
                        f"""
                        <div class="item-card">
                            <div class="item-status {status_class}">{status_text}</div>
                            <div class="item-name">{item_name_safe}</div>
                            <div class="item-meta">{item_description_safe}</div>
                            <div class="quantity-pill">
                                <div class="quantity-pill-label">{quantity_label}</div>
                                <div class="quantity-pill-value">{quantity_value}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    transfer_qty = st.number_input(
                        "Quantity to Receive",
                        min_value=1,
                        value=None,
                        step=1,
                        placeholder="Enter quantity",
                        key="scan_transfer_quantity"
                    )

                    transfer_qty_preview = int(transfer_qty or 0)
                    account_after_preview = account_quantity + transfer_qty_preview

                    if receiving_sales_stock:
                        preview_cards = (
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Your Location Qty</div>'
                            f'<div class="action-summary-value">{account_quantity}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Available To Receive</div>'
                            f'<div class="action-summary-value">{sales_available_to_receive}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Receiving</div>'
                            f'<div class="action-summary-value">{transfer_qty_preview}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Your Location Qty After</div>'
                            f'<div class="action-summary-value">{account_after_preview}</div>'
                            '</div>'
                        )
                    else:
                        preview_cards = (
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Assigned To You</div>'
                            f'<div class="action-summary-value">{user_assigned_quantity}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            f'<div class="action-summary-label">{account_label}</div>'
                            f'<div class="action-summary-value">{account_quantity}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Available To Receive</div>'
                            f'<div class="action-summary-value">{user_available_to_receive}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            '<div class="action-summary-label">Receiving</div>'
                            f'<div class="action-summary-value">{transfer_qty_preview}</div>'
                            '</div>'
                            '<div class="action-summary-card">'
                            f'<div class="action-summary-label">{account_label} After</div>'
                            f'<div class="action-summary-value">{account_after_preview}</div>'
                            '</div>'
                        )

                    preview_html = (
                        '<div class="content-panel">'
                        '<div class="workflow-kicker">Stock Preview</div>'
                        '<div class="action-summary-grid">'
                        f'{preview_cards}'
                        '</div>'
                        '</div>'
                    )
                    st.markdown(preview_html, unsafe_allow_html=True)

                    receive_button_label = (
                        "Receive Into Location"
                        if get_current_role() == "sales"
                        else "Add to My Stock"
                    )
                    receive_capacity_preview = (
                        sales_available_to_receive
                        if receiving_sales_stock else user_available_to_receive
                    )
                    receive_quantity_is_valid = (
                        transfer_qty is not None
                        and transfer_qty_preview > 0
                        and transfer_qty_preview <= receive_capacity_preview
                    )
                    if transfer_qty is not None and transfer_qty_preview > receive_capacity_preview:
                        st.warning(
                            f"You can receive only {receive_capacity_preview} more unit(s) from your assignment."
                        )
                    if st.button(
                        receive_button_label,
                        type="primary",
                        width="stretch",
                        disabled=not receive_quantity_is_valid,
                    ):
                        if transfer_qty is None or int(transfer_qty) <= 0:
                            st.error("Enter a quantity greater than zero before receiving stock.")
                            st.stop()
                        transfer_conn = get_connection()
                        transfer_c = transfer_conn.cursor()

                        try:
                            transfer_c.execute("BEGIN IMMEDIATE")
                            if get_current_role() == "sales":
                                try:
                                    validate_sales_sale_access(
                                        transfer_c,
                                        st.session_state.username,
                                        selected_location_id,
                                        item_code
                                    )
                                except ValueError as access_error:
                                    transfer_conn.rollback()
                                    st.error(str(access_error))
                                    st.stop()
                                transfer_c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                locked_assignment_row = transfer_c.fetchone()
                                locked_assigned_quantity = (
                                    int(locked_assignment_row[0] or 0)
                                    if locked_assignment_row else 0
                                )
                                transfer_c.execute(
                                    '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                locked_received_quantity = int(transfer_c.fetchone()[0] or 0)
                                transfer_c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND location_id=?
                                         AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, selected_location_id, item_code)
                                )
                                locked_sales_location_row = transfer_c.fetchone()
                                locked_sales_location_quantity = (
                                    int(locked_sales_location_row[0] or 0)
                                    if locked_sales_location_row else 0
                                )
                            else:
                                transfer_c.execute(
                                    '''SELECT 1 FROM product_suppliers
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                if transfer_c.fetchone() is None:
                                    transfer_conn.rollback()
                                    st.error("This product is no longer assigned to your account. Refresh and select an assigned item.")
                                    st.stop()
                                transfer_c.execute(
                                    '''SELECT COALESCE(quantity,0) FROM admin_product_allocations
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (st.session_state.username, item_code)
                                )
                                locked_user_assignment_row = transfer_c.fetchone()
                                locked_user_assigned_quantity = (
                                    int(locked_user_assignment_row[0] or 0)
                                    if locked_user_assignment_row else 0
                                )
                            transfer_c.execute(
                                "SELECT id, quantity FROM inventory WHERE item_code=?",
                                (item_code,)
                            )
                            current_inventory = transfer_c.fetchone()

                            transfer_c.execute(
                                '''
                                SELECT quantity FROM user_inventory
                                WHERE username=? AND item_code=?
                                ''',
                                (st.session_state.username, item_code)
                            )
                            current_user_inventory = transfer_c.fetchone()

                            transfer_c.execute(
                                '''
                                SELECT quantity FROM location_inventory
                                WHERE location_id=? AND item_code=?
                                ''',
                                (selected_location_id, item_code)
                            )
                            current_location_inventory = transfer_c.fetchone()
                            transfer_c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM location_inventory
                                   WHERE LOWER(item_code)=LOWER(?)''',
                                (item_code,)
                            )
                            locked_total_physical_quantity = int(transfer_c.fetchone()[0] or 0)
                            transfer_c.execute(
                                '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                (selected_location_id, item_code)
                            )
                            locked_selected_location_owned = int(transfer_c.fetchone()[0] or 0)

                            if not selected_location_id:
                                transfer_conn.rollback()
                                st.error("Select a receiving location before adding stock.")
                            elif not current_inventory:
                                transfer_conn.rollback()
                                st.error("Item not found. Check the item code and try again.")
                            else:
                                system_quantity_before = int(current_inventory[1])
                                user_quantity_before = int(current_user_inventory[0]) if current_user_inventory else 0
                                location_quantity_before = int(current_location_inventory[0]) if current_location_inventory else 0
                                transfer_qty_int = int(transfer_qty)
                                receiving_sales_stock = get_current_role() == "sales"
                                if receiving_sales_stock:
                                    locked_available_to_receive = calculate_sales_receive_capacity(
                                        locked_assigned_quantity,
                                        locked_received_quantity,
                                        system_quantity_before,
                                        locked_total_physical_quantity,
                                        location_quantity_before,
                                        locked_selected_location_owned,
                                    )
                                    if transfer_qty_int > locked_available_to_receive:
                                        transfer_conn.rollback()
                                        st.error(
                                            f"You can receive only {locked_available_to_receive} more unit(s). "
                                            "This limit uses your remaining assignment and company physical capacity."
                                        )
                                        st.stop()

                                if not receiving_sales_stock:
                                    locked_user_available_to_receive = calculate_user_receive_capacity(
                                        locked_user_assigned_quantity,
                                        user_quantity_before,
                                        system_quantity_before,
                                    )
                                    if transfer_qty_int > locked_user_available_to_receive:
                                        transfer_conn.rollback()
                                        st.error(
                                            f"You can receive only {locked_user_available_to_receive} more unit(s). "
                                            "This limit uses your remaining assigned quantity and current availability."
                                        )
                                        st.stop()

                                if transfer_qty_int > 0:
                                    system_quantity_after = (
                                        system_quantity_before
                                        if receiving_sales_stock
                                        else system_quantity_before - transfer_qty_int
                                    )
                                    account_quantity_before = (
                                        locked_sales_location_quantity
                                        if receiving_sales_stock else user_quantity_before
                                    )
                                    account_quantity_after = account_quantity_before + transfer_qty_int
                                    ownership_from_existing = (
                                        min(
                                            transfer_qty_int,
                                            max(
                                                location_quantity_before
                                                - locked_selected_location_owned,
                                                0,
                                            ),
                                        )
                                        if receiving_sales_stock else 0
                                    )
                                    physical_quantity_to_add = (
                                        transfer_qty_int - ownership_from_existing
                                        if receiving_sales_stock else 0
                                    )
                                    physical_location_quantity_after = (
                                        location_quantity_before + physical_quantity_to_add
                                    )

                                    if not receiving_sales_stock:
                                        transfer_c.execute(
                                            '''
                                            UPDATE inventory
                                            SET quantity=?
                                            WHERE id=?
                                            ''',
                                            (system_quantity_after, int(current_inventory[0]))
                                        )

                                    if receiving_sales_stock:
                                        transfer_c.execute(
                                            '''
                                            INSERT INTO location_inventory (location_id,item_code,quantity)
                                            VALUES (?,?,?)
                                            ON CONFLICT(location_id,item_code)
                                            DO UPDATE SET quantity=excluded.quantity
                                            ''',
                                            (selected_location_id, item_code, physical_location_quantity_after)
                                        )
                                        transfer_c.execute(
                                            '''INSERT INTO admin_location_stock
                                               (username,location_id,item_code,quantity)
                                               VALUES (?,?,?,?)
                                               ON CONFLICT(username,location_id,item_code)
                                               DO UPDATE SET quantity=excluded.quantity''',
                                            (
                                                st.session_state.username,
                                                selected_location_id,
                                                item_code,
                                                account_quantity_after
                                            )
                                        )
                                        transfer_c.execute(
                                            '''
                                            INSERT INTO location_stock_history
                                            (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                            VALUES (?,?,?,?,?,?,?,?)
                                            ''',
                                            (
                                                selected_location_id,
                                                item_code,
                                                location_quantity_before,
                                                physical_quantity_to_add,
                                                physical_location_quantity_after,
                                                (
                                                    "Assign Existing Stock"
                                                    if physical_quantity_to_add == 0
                                                    else "Assign / Receive"
                                                ),
                                                st.session_state.username,
                                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            )
                                        )
                                    else:
                                        transfer_c.execute(
                                            '''
                                            INSERT INTO user_inventory (username,item_code,quantity)
                                            VALUES (?,?,?)
                                            ON CONFLICT(username,item_code)
                                            DO UPDATE SET quantity=excluded.quantity
                                            ''',
                                            (st.session_state.username, item_code, account_quantity_after)
                                        )

                                    transfer_c.execute(
                                        '''
                                        INSERT INTO transactions
                                        (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,source_type,location_id,transaction_time)
                                        VALUES (?,?,?,?,?,?,?,?,?)
                                        ''',
                                        (
                                            st.session_state.username,
                                            item_code,
                                            transfer_qty_int,
                                            account_quantity_before,
                                            account_quantity_after,
                                            "allocation",
                                            "location_stock" if receiving_sales_stock else "user_stock",
                                            selected_location_id,
                                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        )
                                    )

                                    transfer_conn.commit()
                                    st.session_state.scan_inventory_message = (
                                        f"{transfer_qty_int} unit(s) received into the selected location. "
                                        f"Location quantity is now {account_quantity_after}."
                                        if receiving_sales_stock
                                        else
                                        f"{transfer_qty_int} unit(s) received. Account quantity is now "
                                        f"{account_quantity_after}."
                                    )
                                    st.session_state.scan_reset_receive_quantity = True
                                    st.rerun()

                        finally:
                            transfer_conn.close()

                    if st.button("Go to Sell Item", width="stretch"):
                        st.session_state.prefill_sell_item_code = item_code
                        st.session_state.menu = "Sell Item"
                        st.rerun()

                    if get_current_role() == "user":
                        st.markdown('<div class="dashboard-section-title">User Account Actions</div>', unsafe_allow_html=True)

                        if user_quantity <= 0:
                            st.info("No user-account stock is available to return or take out for this item.")
                        else:
                            action_col1, action_col2 = st.columns(2)
                            with action_col1:
                                return_qty = st.number_input(
                                    "Return Leftover Quantity",
                                    min_value=1,
                                    max_value=max(user_quantity, 1),
                                    value=None,
                                    step=1,
                                    placeholder="Enter quantity to return",
                                    key="return_leftover_quantity"
                                )
                                if st.button(
                                    "Return to Inventory",
                                    type="secondary",
                                    width="stretch",
                                    disabled=return_qty is None,
                                ):
                                    return_conn = get_connection()
                                    return_c = return_conn.cursor()

                                    try:
                                        return_c.execute("BEGIN IMMEDIATE")
                                        return_c.execute(
                                            "SELECT id, quantity FROM inventory WHERE item_code=?",
                                            (item_code,)
                                        )
                                        current_inventory = return_c.fetchone()
                                        return_c.execute(
                                            '''
                                            SELECT quantity FROM user_inventory
                                            WHERE username=? AND item_code=?
                                            ''',
                                            (st.session_state.username, item_code)
                                        )
                                        current_user_inventory = return_c.fetchone()

                                        user_quantity_before = int(current_user_inventory[0]) if current_user_inventory else 0
                                        return_qty_int = int(return_qty)

                                        if not current_inventory:
                                            return_conn.rollback()
                                            st.error("Item not found. Check the item code and try again.")
                                        elif return_qty_int > user_quantity_before:
                                            return_conn.rollback()
                                            st.error("You do not have enough stock to return that quantity.")
                                        else:
                                            user_quantity_after = user_quantity_before - return_qty_int
                                            system_quantity_after = int(current_inventory[1]) + return_qty_int
                                            return_c.execute(
                                                "UPDATE inventory SET quantity=? WHERE id=?",
                                                (system_quantity_after, int(current_inventory[0]))
                                            )
                                            return_c.execute(
                                                '''
                                                UPDATE user_inventory
                                                SET quantity=?
                                                WHERE username=? AND item_code=?
                                                ''',
                                                (user_quantity_after, st.session_state.username, item_code)
                                            )
                                            return_c.execute(
                                                '''
                                                INSERT INTO transactions
                                                (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,source_type,location_id,transaction_time)
                                                VALUES (?,?,?,?,?,?,?,?,?)
                                                ''',
                                                (
                                                    st.session_state.username,
                                                    item_code,
                                                    return_qty_int,
                                                    user_quantity_before,
                                                    user_quantity_after,
                                                    "return",
                                                    "user_stock",
                                                    selected_location_id,
                                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                )
                                            )
                                            return_conn.commit()
                                            st.session_state.scan_inventory_message = (
                                                f"{return_qty_int} unit(s) returned to inventory. Your quantity is now {user_quantity_after}."
                                            )
                                            st.session_state.scan_reset_user_actions = True
                                            st.rerun()
                                    finally:
                                        return_conn.close()

                            with action_col2:
                                take_out_qty = st.number_input(
                                    "Take Out Quantity",
                                    min_value=1,
                                    max_value=max(user_quantity, 1),
                                    value=None,
                                    step=1,
                                    placeholder="Enter quantity to take out",
                                    key="take_out_quantity"
                                )
                                if st.button(
                                    "Take Out",
                                    type="secondary",
                                    width="stretch",
                                    disabled=take_out_qty is None,
                                ):
                                    take_out_conn = get_connection()
                                    take_out_c = take_out_conn.cursor()

                                    try:
                                        take_out_c.execute("BEGIN IMMEDIATE")
                                        take_out_c.execute(
                                            '''
                                            SELECT quantity FROM user_inventory
                                            WHERE username=? AND item_code=?
                                            ''',
                                            (st.session_state.username, item_code)
                                        )
                                        current_user_inventory = take_out_c.fetchone()

                                        user_quantity_before = int(current_user_inventory[0]) if current_user_inventory else 0
                                        take_out_qty_int = int(take_out_qty)

                                        if take_out_qty_int > user_quantity_before:
                                            take_out_conn.rollback()
                                            st.error("You do not have enough stock to take out that quantity.")
                                        else:
                                            user_quantity_after = user_quantity_before - take_out_qty_int
                                            take_out_c.execute(
                                                '''
                                                UPDATE user_inventory
                                                SET quantity=?
                                                WHERE username=? AND item_code=?
                                                ''',
                                                (user_quantity_after, st.session_state.username, item_code)
                                            )
                                            take_out_c.execute(
                                                '''
                                                INSERT INTO transactions
                                                (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,source_type,location_id,transaction_time)
                                                VALUES (?,?,?,?,?,?,?,?,?)
                                                ''',
                                                (
                                                    st.session_state.username,
                                                    item_code,
                                                    take_out_qty_int,
                                                    user_quantity_before,
                                                    user_quantity_after,
                                                    "take_out",
                                                    "user_stock",
                                                    selected_location_id,
                                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                                )
                                            )
                                            take_out_conn.commit()
                                            st.session_state.scan_inventory_message = (
                                                f"{take_out_qty_int} unit(s) taken out of your account. Your quantity is now {user_quantity_after}."
                                            )
                                            st.session_state.scan_reset_user_actions = True
                                            st.rerun()
                                    finally:
                                        take_out_conn.close()

            else:
                with detail_col:
                    st.error("Item not found. Check the item code and try again.")

            conn.close()


    if menu == "Sell Item" and get_current_role() != "sales":

        if st.session_state.pop("sell_reset_quantity", False):
            st.session_state.pop("sell_quantity_sold", None)

        if "sell_item_message" in st.session_state:
            st.success(st.session_state.sell_item_message)
            del st.session_state.sell_item_message

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">User Sale</div>
                <div class="page-title">Sell Item</div>
                <p class="page-subtitle">Choose one of your assigned items, enter the quantity sold, and review the live stock preview.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        sale_items_conn = get_connection()
        try:
            user_sale_items_df = pd.read_sql_query(
                '''SELECT i.item_code, i.item_name, COALESCE(ui.quantity,0) AS quantity
                   FROM user_inventory ui
                   JOIN inventory i ON LOWER(i.item_code)=LOWER(ui.item_code)
                   JOIN product_suppliers ps
                     ON LOWER(ps.username)=LOWER(ui.username)
                    AND LOWER(ps.item_code)=LOWER(ui.item_code)
                   WHERE LOWER(ui.username)=LOWER(?) AND COALESCE(ui.quantity,0)>0
                   ORDER BY i.item_name, i.item_code''',
                sale_items_conn,
                params=(st.session_state.username,),
            )
        finally:
            sale_items_conn.close()

        sell_lookup_col, sell_detail_col = st.columns([0.9, 1.1])

        with sell_lookup_col:
            prefill_sell_item_code = st.session_state.pop("prefill_sell_item_code", "")

            st.markdown(
                """
                <div class="workflow-panel">
                    <div class="workflow-kicker">Step 1</div>
                    <div class="workflow-title">Find Item to Sell</div>
                    <div class="workflow-text">Select an item name and code from products currently available in your personal stock.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            if user_sale_items_df.empty:
                st.info("No assigned personal stock is currently available to sell.")
                sell_item_code = ""
            else:
                sell_item_search = st.text_input(
                    "Search Item Name / Item Code",
                    key="sell_item_search",
                    placeholder="Type an item name or code",
                ).strip()
                filtered_sale_items_df = user_sale_items_df.copy()
                if sell_item_search:
                    normalized_search = sell_item_search.lower()
                    filtered_sale_items_df = filtered_sale_items_df[
                        filtered_sale_items_df["item_name"].fillna("").astype(str).str.lower().str.contains(
                            normalized_search, regex=False
                        )
                        | filtered_sale_items_df["item_code"].fillna("").astype(str).str.lower().str.contains(
                            normalized_search, regex=False
                        )
                    ].copy()
                sell_item_options = {
                    f"{row['item_name']} ({row['item_code']})": str(row["item_code"])
                    for _, row in filtered_sale_items_df.iterrows()
                }
                sell_item_labels = list(sell_item_options)
                if not sell_item_labels:
                    st.info("No assigned item matches that name or code.")
                    sell_item_code = ""
                else:
                    selected_index = 0
                    if prefill_sell_item_code:
                        for option_index, option_label in enumerate(sell_item_labels):
                            if sell_item_options[option_label].lower() == str(prefill_sell_item_code).lower():
                                selected_index = option_index
                                break
                    selected_sell_item = st.selectbox(
                        "Available Item",
                        sell_item_labels,
                        index=selected_index,
                        key="sell_item_dropdown",
                    )
                    sell_item_code = sell_item_options[selected_sell_item]

        with sell_detail_col:
            st.markdown('<div class="dashboard-section-title">Record Sale</div>', unsafe_allow_html=True)

            if not sell_item_code:
                st.info("Select an assigned item with available personal stock before saving a sale.")

        if sell_item_code:
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT * FROM inventory WHERE LOWER(item_code)=LOWER(?)",
                (sell_item_code,)
            )
            item = c.fetchone()
            c.execute(
                '''
                SELECT quantity FROM user_inventory
                WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                ''',
                (st.session_state.username, sell_item_code)
            )
            user_inventory_row = c.fetchone()
            c.execute(
                '''SELECT 1 FROM product_suppliers
                   WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                (st.session_state.username, sell_item_code),
            )
            has_product_access = c.fetchone() is not None
            conn.close()

            if item and has_product_access:
                user_quantity = int(user_inventory_row[0]) if user_inventory_row else 0
                item_name_safe = safe_html(item[2])
                item_description_safe = safe_html(item[3])
                status_class = "low" if user_quantity <= 5 else "ok"
                status_text = "Low user stock" if user_quantity <= 5 else "Ready to sell"

                with sell_detail_col:
                    st.markdown(
                        f"""
                        <div class="item-card">
                            <div class="item-status {status_class}">{status_text}</div>
                            <div class="item-name">{item_name_safe}</div>
                            <div class="item-meta">{item_description_safe}</div>
                            <div class="quantity-pill">
                                <div class="quantity-pill-label">MY QUANTITY AVAILABLE</div>
                                <div class="quantity-pill-value">{user_quantity}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    quantity_sold = st.number_input(
                        "Quantity Sold",
                        min_value=1,
                        value=None,
                        step=1,
                        placeholder="Enter quantity sold",
                        key="sell_quantity_sold"
                    )

                    quantity_sold_preview = int(quantity_sold or 0)
                    quantity_after_preview = max(user_quantity - quantity_sold_preview, 0)
                    sale_quantity_is_valid = (
                        quantity_sold is not None
                        and quantity_sold_preview > 0
                        and quantity_sold_preview <= user_quantity
                    )

                    st.markdown(
                        f"""
                        <div class="content-panel">
                            <div class="workflow-kicker">Sale Preview</div>
                            <div class="action-summary-grid">
                                <div class="action-summary-card">
                                    <div class="action-summary-label">My Qty Before</div>
                                    <div class="action-summary-value">{user_quantity}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">Sold</div>
                                    <div class="action-summary-value">{quantity_sold_preview}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">My Qty After</div>
                                    <div class="action-summary-value">{quantity_after_preview}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    if quantity_sold is not None and quantity_sold_preview > user_quantity:
                        st.warning(
                            f"You can sell only {user_quantity} unit(s) from your personal stock."
                        )

                    if st.button(
                        "Save Sale",
                        type="primary",
                        width="stretch",
                        disabled=not sale_quantity_is_valid,
                    ):
                        sale_conn = get_connection()
                        sale_c = sale_conn.cursor()

                        try:
                            sale_c.execute("BEGIN IMMEDIATE")
                            try:
                                validate_user_sale_access(
                                    sale_c,
                                    st.session_state.username,
                                    sell_item_code,
                                )
                            except ValueError as access_error:
                                sale_conn.rollback()
                                st.error(str(access_error))
                                st.stop()
                            sale_c.execute(
                                '''
                                SELECT quantity FROM user_inventory
                                WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                                ''',
                                (st.session_state.username, sell_item_code)
                            )
                            current_user_item = sale_c.fetchone()

                            sale_c.execute(
                                "SELECT id, item_name, quantity FROM inventory WHERE LOWER(item_code)=LOWER(?)",
                                (sell_item_code,)
                            )
                            current_item = sale_c.fetchone()

                            if not current_item:
                                sale_conn.rollback()
                                st.error("Item not found. Check the item code and try again.")
                            else:
                                quantity_before = int(current_user_item[0]) if current_user_item else 0
                                quantity_sold_int = int(quantity_sold)

                                if quantity_sold_int > quantity_before:
                                    sale_conn.rollback()
                                    st.error("Not enough quantity is available in your personal stock. Add stock from Scan Inventory first.")
                                else:
                                    quantity_after = quantity_before - quantity_sold_int

                                    sale_c.execute(
                                        '''
                                        UPDATE user_inventory
                                        SET quantity=?
                                        WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (quantity_after, st.session_state.username, sell_item_code)
                                    )

                                    sale_c.execute(
                                        '''
                                        INSERT INTO transactions
                                        (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,source_type,location_id,transaction_time)
                                        VALUES (?,?,?,?,?,?,?,?,?)
                                        ''',
                                        (
                                            st.session_state.username,
                                            sell_item_code,
                                            quantity_sold_int,
                                            quantity_before,
                                            quantity_after,
                                            "sale",
                                            "user_stock",
                                            None,
                                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        )
                                    )

                                    sale_conn.commit()
                                    st.session_state.sell_item_message = (
                                        f"Sale saved successfully. Sold {quantity_sold_int} unit(s) from your personal stock; remaining quantity is {quantity_after}."
                                    )
                                    st.session_state.sell_reset_quantity = True
                                    st.rerun()

                        finally:
                            sale_conn.close()

            elif item and not has_product_access:
                with sell_detail_col:
                    st.error("This product is not assigned to your account. Choose a product assigned by Super Admin.")
            else:
                with sell_detail_col:
                    st.error("Item not found. Check the item code and try again.")


    if menu == "Transaction Logs":

        conn = get_connection()

        df = pd.read_sql_query(
            "SELECT * FROM transactions ORDER BY id DESC",
            conn
        )

        conn.close()

        if has_admin_access() and not is_super_admin():
            assigned_location_ids = get_assigned_location_ids()
            supplied_item_codes = set(get_supplied_item_codes())
            df = df[df["location_id"].isin(assigned_location_ids)].copy()

            if supplied_item_codes:
                df = df[df["item_code"].isin(supplied_item_codes)].copy()
            else:
                df = df.iloc[0:0].copy()
        elif not has_admin_access() and not df.empty:
            df = df[df["username"] == st.session_state.username].copy()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Activity</div>
                <div class="page-title">Transaction Logs</div>
                <p class="page-subtitle">Review inventory usage history by user, item code, quantity, and time.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if not df.empty:
            df["transaction_type"] = df["transaction_type"].fillna("legacy")
            df["source_type"] = df["source_type"].fillna("legacy")
            df["quantity_before"] = df["quantity_before"].fillna(0).astype(int)
            df["quantity_used"] = df["quantity_used"].fillna(0).astype(int)
            df["quantity_after"] = df["quantity_after"].fillna(0).astype(int)
            df["verification"] = df.apply(transaction_verification_status, axis=1)

        total_logs = len(df)
        total_allocated = int(df.loc[df["transaction_type"] == "allocation", "quantity_used"].sum()) if not df.empty else 0
        total_sold = int(df.loc[df["transaction_type"] == "sale", "quantity_used"].sum()) if not df.empty else 0
        unique_items_used = df["item_code"].nunique() if not df.empty else 0
        active_users = df["username"].nunique() if not df.empty else 0
        verified_logs = int((df["verification"] == "Verified").sum()) if not df.empty else 0

        log_col1, log_col2, log_col3, log_col4 = st.columns(4)

        with log_col1:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Total Logs</div>
                    <div class="dashboard-card-value">{total_logs}</div>
                    <div class="dashboard-card-note">Recorded transactions</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with log_col2:
            st.markdown(
                f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Quantity Sold</div>
                        <div class="dashboard-card-value">{total_sold}</div>
                        <div class="dashboard-card-note">Units sold from location or user stock</div>
                    </div>
                """,
                unsafe_allow_html=True
            )

        with log_col3:
            st.markdown(
                f"""
                <div class="dashboard-card">
                    <div class="dashboard-card-label">Quantity Allocated</div>
                    <div class="dashboard-card-value">{total_allocated}</div>
                    <div class="dashboard-card-note">Units added to user stock</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with log_col4:
            st.markdown(
                f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Verified</div>
                        <div class="dashboard-card-value">{verified_logs}</div>
                        <div class="dashboard-card-note">Rows with matching deduction math</div>
                    </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown(
            '<div class="dashboard-section-title">Usage History</div>',
            unsafe_allow_html=True
        )

        if df.empty:
            st.info("No transactions are available for the records you can access yet.")
        else:
            search_term = st.text_input(
                "Search logs",
                placeholder="Search by user or item code",
                label_visibility="collapsed"
            )

            display_df = df.copy()

            if search_term:
                search_term = search_term.lower().strip()
                display_df = display_df[
                    display_df["username"].str.lower().str.contains(search_term, na=False)
                    | display_df["item_code"].str.lower().str.contains(search_term, na=False)
                ]

            display_df = display_df.copy()
            display_df["verification"] = display_df.get("verification", "Unverified")
            display_df["source_type"] = display_df["source_type"].replace({
                "location_stock": "Sales Account",
                "user_stock": "User Account",
                "legacy": "Legacy",
            })
            display_df["transaction_type"] = display_df["transaction_type"].replace({
                "allocation": "Added to My Stock",
                "sale": "Sold Item",
                "return": "Returned to Inventory",
                "take_out": "Taken Out",
                "legacy": "Legacy Record",
            })
            display_columns = [
                "id",
                "item_code",
                "transaction_type",
                "source_type",
                "quantity_before",
                "quantity_used",
                "quantity_after",
                "verification",
                "transaction_time",
            ]
            if has_admin_access():
                display_columns.insert(1, "username")
            display_df = display_df[display_columns]

            st.dataframe(
                display_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "id": "ID",
                    "username": "User",
                    "item_code": "Item Code",
                    "transaction_type": "Action",
                    "source_type": "Source",
                    "quantity_before": "Qty Before",
                    "quantity_used": "Quantity Changed",
                    "quantity_after": "Qty After",
                    "verification": "Verification",
                    "transaction_time": "Transaction Time",
                }
            )


    if menu == "Logout":
        st.session_state.logged_in = False
        st.rerun()

