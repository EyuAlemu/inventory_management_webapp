from datetime import datetime
import math


def calculate_new_base_quantity(current_quantity, quantity_to_add):
    """Return an additive base quantity without allowing a negative addition."""
    current_quantity = int(current_quantity)
    quantity_to_add = int(quantity_to_add)
    if quantity_to_add < 0:
        raise ValueError("Quantity To Add cannot be negative.")
    return current_quantity + quantity_to_add


def create_inventory_entry(
    conn, item_code, item_name, description, quantity, cost, location_id, created_by, selling_price=0
):
    """Create a master item and place its full starting quantity in the selected active location."""
    item_code = str(item_code or "").strip()
    item_name = str(item_name or "").strip()
    quantity = int(quantity)
    if not item_code or not item_name:
        raise ValueError("Item code and item name are required.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    cost = float(cost)
    selling_price = float(selling_price)
    if not math.isfinite(cost) or cost <= 0:
        raise ValueError("Unit Purchase Cost is required and must be greater than zero.")
    if not math.isfinite(selling_price):
        raise ValueError("Location Selling Price must be a valid number.")
    if selling_price < 0:
        raise ValueError("Selling Price cannot be negative.")
    if selling_price > 0 and selling_price < cost:
        raise ValueError("Location Selling Price cannot be lower than Unit Purchase Cost.")
    cost = round(cost, 2)
    selling_price = round(selling_price, 2)

    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT active FROM locations WHERE id=?", (location_id,))
        location_row = cursor.fetchone()
        if not location_row:
            raise ValueError("The selected location does not exist.")
        if int(location_row[0] or 0) != 1:
            raise ValueError("The selected location is inactive. Select an active location.")
        cursor.execute("SELECT COUNT(*) FROM inventory WHERE LOWER(item_code)=LOWER(?)", (item_code,))
        if int(cursor.fetchone()[0] or 0):
            raise ValueError("This item code already exists. Item codes are case-insensitive.")
        cursor.execute(
            '''INSERT INTO inventory (item_code,item_name,description,quantity,cost)
               VALUES (?,?,?,?,?)''',
            (item_code, item_name, str(description or "").strip(), quantity, cost)
        )
        cursor.execute(
            '''INSERT INTO location_inventory (location_id,item_code,quantity)
               VALUES (?,?,?)''',
            (location_id, item_code, quantity)
        )
        if selling_price > 0:
            cursor.execute(
                '''INSERT INTO location_prices (location_id,item_code,price)
                   VALUES (?,?,?)''',
                (location_id, item_code, selling_price)
            )
        cursor.execute(
            '''INSERT INTO location_stock_history
               (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
               VALUES (?,?,?,?,?,?,?,?)''',
            (
                location_id, item_code, 0, quantity, quantity, "Inventory Entry",
                created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
        return {"item_code": item_code, "location_id": int(location_id), "quantity": quantity}
    except Exception:
        conn.rollback()
        raise


def get_location_assignment_removal_blockers(cursor, username, location_id):
    """Return active dependencies that must be resolved before location access is removed."""
    blockers = []
    cursor.execute(
        "SELECT COUNT(*) FROM locations WHERE id=? AND LOWER(COALESCE(owner_username,''))=LOWER(?)",
        (location_id, username)
    )
    if int(cursor.fetchone()[0] or 0):
        blockers.append("this user is the Primary Location Admin; select a different owner first")

    cursor.execute(
        '''SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock
           WHERE LOWER(username)=LOWER(?) AND location_id=?''',
        (username, location_id)
    )
    owned_stock = int(cursor.fetchone()[0] or 0)
    if owned_stock > 0:
        blockers.append(
            f"this user still owns {owned_stock} stock unit(s) at the location; transfer or remove that stock first"
        )

    cursor.execute(
        '''SELECT COUNT(*) FROM inventory_transfers
           WHERE LOWER(COALESCE(requested_by,''))=LOWER(?) AND status='pending'
             AND (source_location_id=? OR destination_location_id=?)''',
        (username, location_id, location_id)
    )
    pending_transfers = int(cursor.fetchone()[0] or 0)
    if pending_transfers > 0:
        blockers.append(
            f"this user has {pending_transfers} pending transfer(s) involving the location; complete or cancel them first"
        )
    return blockers


def remove_location_assignment(conn, username, location_id):
    """Safely remove assigned access; return False when no assignment exists."""
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            '''SELECT COUNT(*) FROM user_locations
               WHERE LOWER(username)=LOWER(?) AND location_id=?''',
            (username, location_id)
        )
        if int(cursor.fetchone()[0] or 0) == 0:
            conn.rollback()
            return False
        blockers = get_location_assignment_removal_blockers(cursor, username, location_id)
        if blockers:
            raise ValueError("Location assignment cannot be removed because " + "; ".join(blockers) + ".")
        cursor.execute(
            '''DELETE FROM user_locations
               WHERE LOWER(username)=LOWER(?) AND location_id=?''',
            (username, location_id)
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise


def get_user_deletion_blockers(cursor, username):
    blockers = []
    cursor.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM user_inventory WHERE LOWER(username)=LOWER(?)",
        (username,)
    )
    personal_stock = int(cursor.fetchone()[0] or 0)
    if personal_stock > 0:
        blockers.append(f"{personal_stock} personal stock unit(s)")
    cursor.execute(
        "SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock WHERE LOWER(username)=LOWER(?)",
        (username,)
    )
    owned_stock = int(cursor.fetchone()[0] or 0)
    if owned_stock > 0:
        blockers.append(f"{owned_stock} Admin-owned location stock unit(s)")
    cursor.execute(
        "SELECT COUNT(*) FROM inventory_transfers WHERE LOWER(COALESCE(requested_by,''))=LOWER(?) AND status='pending'",
        (username,)
    )
    pending_transfers = int(cursor.fetchone()[0] or 0)
    if pending_transfers:
        blockers.append(f"{pending_transfers} pending transfer(s)")
    cursor.execute(
        "SELECT COUNT(*) FROM locations WHERE LOWER(COALESCE(owner_username,''))=LOWER(?)",
        (username,)
    )
    owned_locations = int(cursor.fetchone()[0] or 0)
    if owned_locations:
        blockers.append(f"primary owner of {owned_locations} location(s)")
    cursor.execute(
        '''SELECT COUNT(*) FROM invoices inv
           WHERE LOWER(COALESCE(inv.created_by,''))=LOWER(?)
             AND inv.total-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id=inv.id),0)>0''',
        (username,)
    )
    open_invoices = int(cursor.fetchone()[0] or 0)
    if open_invoices:
        blockers.append(f"{open_invoices} invoice(s) with outstanding balances")
    return blockers


def delete_user_safely(conn, username):
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        blockers = get_user_deletion_blockers(cursor, username)
        if blockers:
            raise ValueError("User cannot be deleted because they have " + "; ".join(blockers) + ".")
        cursor.execute("DELETE FROM user_inventory WHERE LOWER(username)=LOWER(?)", (username,))
        cursor.execute("DELETE FROM user_locations WHERE LOWER(username)=LOWER(?)", (username,))
        cursor.execute("DELETE FROM product_suppliers WHERE LOWER(username)=LOWER(?)", (username,))
        cursor.execute("DELETE FROM admin_product_allocations WHERE LOWER(username)=LOWER(?)", (username,))
        cursor.execute("DELETE FROM admin_location_stock WHERE LOWER(username)=LOWER(?)", (username,))
        cursor.execute("DELETE FROM users WHERE LOWER(username)=LOWER(?)", (username,))
        if cursor.rowcount == 0:
            raise ValueError("The selected user no longer exists.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def configure(context):
    globals().update(
        {
            key: value
            for key, value in context.items()
            if not key.startswith("__")
        }
    )


def render(menu):
    if has_admin_access():

        if menu == "Add Inventory":
            conn = get_connection()
            existing_locations_df = pd.read_sql_query(
                "SELECT id, name, address FROM locations WHERE active=1 ORDER BY name",
                conn
            )
            conn.close()

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">Inventory Entry</div>
                    <p class="page-subtitle">Create a stock item with a base quantity, reference location, address, cost, and QR code.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            form_col, preview_col = st.columns([1.05, 0.95])

            with form_col:
                st.markdown('<div class="dashboard-section-title">Inventory Entry</div>', unsafe_allow_html=True)
                st.markdown('<div class="add-inventory-form">', unsafe_allow_html=True)

                selected_existing_location_id = None
                location_name = ""
                location_address = ""

                if existing_locations_df.empty:
                    st.info("Create an active location from the Locations page before adding inventory.")
                else:
                    location_options = [
                        f"{row['name']} (ID {int(row['id'])})"
                        for _, row in existing_locations_df.iterrows()
                    ]
                    selected_location_option = st.selectbox(
                        "Select Location Name",
                        location_options,
                        help="Select an existing location for this inventory entry.",
                        key="inventory_entry_location_selector"
                    )
                    selected_existing_location_id = int(
                        selected_location_option.rsplit("ID ", 1)[1].rstrip(")")
                    )
                    selected_location_row = existing_locations_df[
                        existing_locations_df["id"] == selected_existing_location_id
                    ].iloc[0]
                    location_name = str(selected_location_row["name"])
                    location_address = (
                        str(selected_location_row["address"])
                        if pd.notna(selected_location_row["address"])
                        else ""
                    )
                    st.text_area(
                        "Address / Notes",
                        value=location_address,
                        disabled=True,
                        key=f"inventory_location_address_{selected_existing_location_id}"
                    )

                with st.container(border=True):
                    item_code = st.text_input("Item Code", key="admin_item_code")
                    item_name = st.text_input("Item Name")
                    description = st.text_area("Description")
                    quantity = st.number_input(
                        "Quantity",
                        min_value=1,
                        value=None,
                        step=1,
                        placeholder="Enter starting quantity"
                    )
                    inventory_cost = st.number_input(
                        "Unit Purchase Cost",
                        min_value=0.01,
                        value=None,
                        step=0.01,
                        format="%.2f",
                        placeholder="Enter cost per unit"
                    )
                    selling_price = st.number_input(
                        "Location Selling Price (Optional)",
                        min_value=0.01,
                        value=None,
                        step=0.01,
                        format="%.2f",
                        placeholder="Enter selling price"
                    )
                    purchase_cost_valid = inventory_cost is not None and float(inventory_cost) > 0
                    selling_price_valid = (
                        selling_price is None
                        or (
                            float(selling_price) > 0
                            and purchase_cost_valid
                            and float(selling_price) >= float(inventory_cost)
                        )
                    )
                    if inventory_cost is None:
                        st.caption("Unit Purchase Cost is required.")
                    if selling_price is not None and purchase_cost_valid and float(selling_price) < float(inventory_cost):
                        st.error("Location Selling Price cannot be lower than Unit Purchase Cost.")

                    save_inventory = st.button(
                        "Save Inventory Entry",
                        type="primary",
                        width="stretch",
                        disabled=(
                            existing_locations_df.empty
                            or quantity is None
                            or not purchase_cost_valid
                            or not selling_price_valid
                        ),
                        key="save_inventory_entry"
                    )

                st.markdown('</div>', unsafe_allow_html=True)

            with preview_col:
                st.markdown('<div class="dashboard-section-title">Preview</div>', unsafe_allow_html=True)
                item_code_preview = safe_html(item_code or "Not entered")
                item_name_preview = safe_html(item_name or "Not entered")
                location_name_preview = safe_html(location_name or "Not entered")
                location_address_preview = safe_html(location_address or "Not entered")
                quantity_preview = int(quantity or 0)
                unit_cost_preview = float(inventory_cost or 0)
                selling_price_preview = float(selling_price or 0)
                total_purchase_cost_preview = quantity_preview * unit_cost_preview
                st.markdown(
                    f"""
                    <div class="content-panel">
                        <div class="preview-list">
                            <div class="preview-row">
                                <div class="preview-label">Item Code</div>
                                <div class="preview-value">{item_code_preview}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Item Name</div>
                                <div class="preview-value">{item_name_preview}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Location</div>
                                <div class="preview-value">{location_name_preview}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Address</div>
                                <div class="preview-value">{location_address_preview}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Quantity</div>
                                <div class="preview-value">{quantity_preview}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Unit Purchase Cost</div>
                                <div class="preview-value">${unit_cost_preview:,.2f}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Total Purchase Cost</div>
                                <div class="preview-value">${total_purchase_cost_preview:,.2f}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Location Selling Price</div>
                                <div class="preview-value">${selling_price_preview:,.2f}</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                st.caption(
                    "Live preview only — nothing is saved until Save Inventory Entry is clicked. "
                    "Starting stock is company-owned until it is assigned to an Admin."
                )

            if save_inventory:

                if not item_code.strip() or not item_name.strip() or selected_existing_location_id is None:
                    st.error("Item code, item name, and location are required before an inventory entry can be saved.")
                else:
                    conn = get_connection()

                    try:
                        create_inventory_entry(
                            conn,
                            item_code,
                            item_name,
                            description,
                            quantity,
                            inventory_cost,
                            selected_existing_location_id,
                            st.session_state.username,
                            selling_price or 0
                        )

                        st.success(
                            f"Inventory entry created successfully with {int(quantity)} unit(s) in {location_name}. "
                            + (
                                f"Selling price was saved as ${float(selling_price):,.2f}."
                                if selling_price else "Use Set Stock / Price to configure its selling price."
                            )
                        )
                        try:
                            qr_path = generate_qr(item_code.strip())
                            st.image(qr_path, caption=f"QR Code: {item_code.strip()}", width=180)
                        except Exception as qr_error:
                            st.warning(
                                f"Inventory was saved, but its QR code could not be generated: {qr_error}"
                            )

                    except sqlite3.IntegrityError:
                        conn.rollback()
                        st.error("This item code already exists. Use a unique code or edit the existing item.")

                    except ValueError as exc:
                        conn.rollback()
                        st.error(str(exc))

                    finally:
                        conn.close()

        if menu == "View Inventory":

            conn = get_connection()

            df = pd.read_sql_query(
                '''
                SELECT i.id, i.item_code, i.item_name, i.description,
                       i.quantity AS inventory_quantity,
                       COALESCE(SUM(li.quantity), 0) AS quantity,
                       COALESCE((
                           SELECT SUM(apa.quantity)
                           FROM admin_product_allocations apa
                           WHERE LOWER(apa.item_code)=LOWER(i.item_code)
                       ), 0) AS admin_assigned_quantity,
                       COALESCE((
                           SELECT SUM(als.quantity)
                           FROM admin_location_stock als
                           WHERE LOWER(als.item_code)=LOWER(i.item_code)
                       ), 0) AS admin_added_quantity,
                       i.cost,
                       li.location_id,
                       COALESCE(l.name, '') AS location_name,
                       COALESCE(l.address, '') AS location_address
                FROM inventory i
                LEFT JOIN location_inventory li ON li.item_code = i.item_code
                LEFT JOIN locations l ON l.id = li.location_id
                GROUP BY i.id, i.item_code, i.item_name, i.description, i.quantity,
                         i.cost, li.location_id, l.name, l.address
                ORDER BY i.item_name, l.name
                ''',
                conn
            )
            inventory_locations_df = pd.read_sql_query(
                "SELECT id, name, address, active FROM locations ORDER BY active DESC, name",
                conn
            )

            conn.close()

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">Inventory View</div>
                    <p class="page-subtitle">Browse current stock by item, location, address, quantity, and cost.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            if not df.empty:
                df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
                df["inventory_quantity"] = pd.to_numeric(df["inventory_quantity"], errors="coerce").fillna(0).astype(int)
                df["cost"] = pd.to_numeric(df["cost"], errors="coerce").fillna(0.0)
                df["assigned_quantity"] = df.groupby("item_code")["quantity"].transform("sum").astype(int)
                df["available_quantity"] = (df["inventory_quantity"] - df["assigned_quantity"]).astype(int)
                df["admin_assigned_quantity"] = pd.to_numeric(
                    df["admin_assigned_quantity"], errors="coerce"
                ).fillna(0).astype(int)
                df["admin_added_quantity"] = pd.to_numeric(
                    df["admin_added_quantity"], errors="coerce"
                ).fillna(0).clip(lower=0).astype(int)
                df["admin_remaining_quantity"] = (
                    df["admin_assigned_quantity"] - df["admin_added_quantity"]
                ).clip(lower=0).astype(int)
                df["quantity_integrity"] = df["available_quantity"].apply(
                    lambda available: "Over-allocated" if int(available) < 0 else "Valid"
                )
                df["total_cost"] = df["quantity"] * df["cost"]
                df["location_total_cost"] = df.groupby(
                    df["location_id"].fillna("unassigned")
                )["total_cost"].transform("sum")

            unique_inventory_df = df.drop_duplicates(subset=["id"]) if not df.empty else df
            total_items = len(unique_inventory_df)
            total_quantity = int(unique_inventory_df["inventory_quantity"].sum()) if not unique_inventory_df.empty else 0
            low_stock = int((unique_inventory_df["assigned_quantity"] <= 5).sum()) if not unique_inventory_df.empty else 0

            inv_col1, inv_col2, inv_col3 = st.columns(3)

            with inv_col1:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Items</div>
                        <div class="dashboard-card-value">{total_items}</div>
                        <div class="dashboard-card-note">Total inventory records</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with inv_col2:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Base Stock Units</div>
                        <div class="dashboard-card-value">{total_quantity}</div>
                        <div class="dashboard-card-note">Total quantity created on master inventory items</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with inv_col3:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Low Stock</div>
                        <div class="dashboard-card-value">{low_stock}</div>
                        <div class="dashboard-card-note">Items with 5 or fewer units currently in locations</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            st.markdown(
                '<div class="dashboard-section-title">Inventory Records</div>',
                unsafe_allow_html=True
            )

            if df.empty:
                st.info("No inventory items match the current view or search.")
            else:
                search_term = st.text_input(
                    "Search inventory",
                    placeholder="Search by item code, name, description, location, or address",
                    label_visibility="collapsed"
                )

                display_df = df.copy()

                if search_term:
                    search_term = search_term.lower().strip()
                    display_df = display_df[
                        display_df["item_code"].str.lower().str.contains(search_term, na=False)
                        | display_df["item_name"].str.lower().str.contains(search_term, na=False)
                        | display_df["description"].str.lower().str.contains(search_term, na=False)
                        | display_df["location_name"].str.lower().str.contains(search_term, na=False)
                        | display_df["location_address"].str.lower().str.contains(search_term, na=False)
                    ]

                st.markdown(
                    '<div class="dashboard-section-title">Inventory Table</div>',
                    unsafe_allow_html=True
                )

                if "inventory_message" in st.session_state:
                    st.success(st.session_state.inventory_message)
                    del st.session_state.inventory_message

                inventory_section = None

                if display_df.empty:
                    st.info("No inventory items match the current search.")
                else:
                    table_df = display_df.copy()
                    table_df["Location"] = table_df["location_name"].replace("", "Unassigned")
                    table_df["Address"] = table_df["location_address"].replace("", "No address")
                    table_df["Item Code"] = table_df["item_code"]
                    table_df["Item Name"] = table_df["item_name"]
                    table_df["Description"] = table_df["description"]
                    table_df["Base Quantity"] = table_df["inventory_quantity"]
                    table_df["Location Quantity"] = table_df["quantity"]
                    table_df["Total In Locations"] = table_df["assigned_quantity"]
                    table_df["Assigned To Admins"] = table_df["admin_assigned_quantity"]
                    table_df["Added By Admins"] = table_df["admin_added_quantity"]
                    table_df["Admin Assignment Remaining"] = table_df["admin_remaining_quantity"]
                    table_df["Available Quantity"] = table_df["available_quantity"]
                    table_df["Quantity Integrity"] = table_df["quantity_integrity"]
                    table_df["Single Cost"] = table_df["cost"]
                    table_df["Total Cost"] = table_df["total_cost"]
                    table_df["Location Total Cost"] = table_df["location_total_cost"]
                    table_df["Edit Label"] = table_df.apply(
                        lambda item_row: (
                            f"{item_row['item_code']} - {item_row['item_name']} "
                            f"({item_row['Location']})"
                        ),
                        axis=1
                    )

                    location_summary_df = (
                        table_df.groupby(["Location", "Address"], as_index=False)
                        .agg(
                            Items=("Item Code", "count"),
                            **{"Location Quantity": ("Location Quantity", "sum")},
                            **{"Location Total Cost": ("Total Cost", "sum")}
                        )
                        .sort_values("Location")
                    )

                    visible_columns = [
                        "Location",
                        "Address",
                        "Item Code",
                        "Item Name",
                        "Description",
                        "Base Quantity",
                        "Location Quantity",
                        "Total In Locations",
                        "Assigned To Admins",
                        "Added By Admins",
                        "Admin Assignment Remaining",
                        "Available Quantity",
                        "Quantity Integrity",
                        "Single Cost",
                        "Total Cost",
                        "Location Total Cost"
                    ]
                    location_item_columns = [
                        "Item Code",
                        "Item Name",
                        "Description",
                        "Base Quantity",
                        "Location Quantity",
                        "Total In Locations",
                        "Assigned To Admins",
                        "Added By Admins",
                        "Admin Assignment Remaining",
                        "Available Quantity",
                        "Quantity Integrity",
                        "Single Cost",
                        "Total Cost"
                    ]
                    column_config = {
                        "Base Quantity": st.column_config.NumberColumn("Base Quantity"),
                        "Location Quantity": st.column_config.NumberColumn("Location Quantity"),
                        "Total In Locations": st.column_config.NumberColumn("Total In Locations"),
                        "Assigned To Admins": st.column_config.NumberColumn("Assigned To Admins"),
                        "Added By Admins": st.column_config.NumberColumn("Added By Admins"),
                        "Admin Assignment Remaining": st.column_config.NumberColumn("Admin Assignment Remaining"),
                        "Available Quantity": st.column_config.NumberColumn("Available Quantity"),
                        "Single Cost": st.column_config.NumberColumn("Single Cost", format="$%.2f"),
                        "Total Cost": st.column_config.NumberColumn("Total Cost", format="$%.2f"),
                        "Location Total Cost": st.column_config.NumberColumn(
                            "Location Total Cost",
                            format="$%.2f"
                        ),
                    }

                    def select_inventory_row(selected_edit_row):
                        st.session_state.manage_inventory_id = int(selected_edit_row["id"])
                        st.session_state.manage_inventory_location_id = (
                            int(selected_edit_row["location_id"])
                            if "location_id" in selected_edit_row and pd.notna(selected_edit_row["location_id"])
                            else None
                        )
                        st.session_state.inventory_view_section = "Edit Location Stock"
                        st.rerun()

                    def select_main_inventory_row(selected_edit_row):
                        st.session_state.manage_main_inventory_id = int(selected_edit_row["id"])
                        st.session_state.inventory_view_section = "Edit Main Items"
                        st.rerun()

                    if "inventory_view_section" not in st.session_state:
                        st.session_state.inventory_view_section = "View Inventory"

                    if st.session_state.get("manage_inventory_id"):
                        st.session_state.inventory_view_section = "Edit Location Stock"

                    if st.session_state.get("manage_main_inventory_id"):
                        st.session_state.inventory_view_section = "Edit Main Items"

                    with st.container(key="inventory_section_buttons"):
                        section_cols = st.columns(4, gap="medium")
                        for section_col, section_label in zip(
                            section_cols,
                            ["View Inventory", "Edit Main Items", "Edit Location Stock", "Cost Summary by Location"]
                        ):
                            with section_col:
                                if st.button(
                                    section_label,
                                    key=f"inventory_section_{section_label.replace(' ', '_').lower()}",
                                    type=(
                                        "primary"
                                        if st.session_state.inventory_view_section == section_label
                                        else "secondary"
                                    ),
                                    width="stretch"
                                ):
                                    if section_label != "Edit Location Stock":
                                        st.session_state.manage_inventory_id = None
                                        st.session_state.manage_inventory_location_id = None
                                    if section_label != "Edit Main Items":
                                        st.session_state.manage_main_inventory_id = None
                                    st.session_state.inventory_view_section = section_label
                                    st.rerun()

                    inventory_section = st.session_state.inventory_view_section
                    selected_item = None

                    if "manage_inventory_id" in st.session_state and st.session_state.manage_inventory_id:
                        selected_rows = df[df["id"] == st.session_state.manage_inventory_id]
                        selected_location_id = st.session_state.get("manage_inventory_location_id")
                        if selected_location_id is not None and "location_id" in selected_rows:
                            selected_rows = selected_rows[selected_rows["location_id"] == selected_location_id]
                        if not selected_rows.empty:
                            selected_item = selected_rows.iloc[0]

                    selected_main_item = None
                    if "manage_main_inventory_id" in st.session_state and st.session_state.manage_main_inventory_id:
                        selected_main_rows = unique_inventory_df[
                            unique_inventory_df["id"] == st.session_state.manage_main_inventory_id
                        ]
                        if not selected_main_rows.empty:
                            selected_main_item = selected_main_rows.iloc[0]

                    if inventory_section == "View Inventory":
                        table_view = st.radio(
                            "Inventory table view",
                            ["Separate by Location", "All Locations"],
                            horizontal=True,
                            label_visibility="collapsed",
                            key="inventory_table_view_mode"
                        )

                        if table_view == "Separate by Location":
                            for location_name, location_df in table_df.sort_values(
                                ["Location", "Item Name", "Item Code"]
                            ).groupby("Location", sort=True):
                                location_total = float(location_df["Total Cost"].sum())
                                location_address = str(location_df["Address"].iloc[0] or "No address")
                                st.markdown(
                                    f"""
                                    <div class="dashboard-section-title">
                                        {safe_html(location_name)} - ${location_total:,.2f}
                                    </div>
                                    <div class="dashboard-card-note" style="margin-bottom: 0.45rem;">
                                        {safe_html(location_address)}
                                    </div>
                                    """,
                                    unsafe_allow_html=True
                                )
                                st.dataframe(
                                    location_df.sort_values(["Item Name", "Item Code"])[location_item_columns],
                                    width="stretch",
                                    hide_index=True,
                                    column_config=column_config
                                )
                        else:
                            st.dataframe(
                                table_df.sort_values(["Location", "Item Name", "Item Code"])[visible_columns],
                                width="stretch",
                                hide_index=True,
                                column_config=column_config
                            )

                    elif inventory_section == "Edit Main Items":
                        main_items_df = (
                            table_df.sort_values(["Item Name", "Item Code"])
                            .drop_duplicates(subset=["id"])
                            .copy()
                        )

                        if selected_main_item is not None:
                            _, back_col = st.columns([1.55, 0.45])
                            with back_col:
                                with st.container(key="main_inventory_back_to_table"):
                                    if st.button("Back to Main Items", type="secondary", width="stretch"):
                                        st.session_state.manage_main_inventory_id = None
                                        st.session_state.inventory_view_section = "Edit Main Items"
                                        st.rerun()
                        else:
                            st.markdown(
                                '<div class="dashboard-card-note" style="margin-bottom: 0.75rem;">Edit master item details, base quantity, and purchase cost here. Location quantities are edited separately in Edit Location Stock.</div>',
                                unsafe_allow_html=True
                            )
                            main_header_cols = st.columns([0.9, 1.1, 1.4, 0.7, 0.8, 0.8, 0.8, 0.6], gap=None)
                            for col, label in zip(
                                main_header_cols,
                                [
                                    "Item Code",
                                    "Item Name",
                                    "Description",
                                    "Base Qty",
                                    "In Locations",
                                    "Available Qty",
                                    "Single Cost",
                                    "Action"
                                ]
                            ):
                                with col:
                                    st.markdown(
                                        f'<div class="inventory-stream-cell header">{label}</div>',
                                        unsafe_allow_html=True
                                    )

                            for row_index, row in main_items_df.iterrows():
                                main_row_cols = st.columns([0.9, 1.1, 1.4, 0.7, 0.8, 0.8, 0.8, 0.6], gap=None)
                                main_row_values = [
                                    safe_html(row["Item Code"]),
                                    safe_html(row["Item Name"]),
                                    safe_html(row["Description"]),
                                    int(row["Base Quantity"]),
                                    int(row["Total In Locations"]),
                                    int(row["Available Quantity"]),
                                    f"${float(row['Single Cost']):,.2f}",
                                ]

                                for value_col, value in zip(main_row_cols[:7], main_row_values):
                                    with value_col:
                                        st.markdown(
                                            f'<div class="inventory-stream-cell strong">{value}</div>',
                                            unsafe_allow_html=True
                                        )

                                with main_row_cols[7]:
                                    if st.button(
                                        "Edit",
                                        key=f"manage_main_inventory_{row['id']}_{row_index}",
                                        type="primary",
                                        width="stretch"
                                    ):
                                        select_main_inventory_row(row)

                    elif inventory_section == "Edit Location Stock":
                        if selected_item is not None:
                            _, back_col = st.columns([1.55, 0.45])
                            with back_col:
                                with st.container(key="inventory_back_to_table"):
                                    if st.button("Back to Table", type="secondary", width="stretch"):
                                        st.session_state.manage_inventory_id = None
                                        st.session_state.manage_inventory_location_id = None
                                        st.session_state.inventory_view_section = "Edit Location Stock"
                                        st.rerun()
                        else:
                            edit_location_filter = st.selectbox(
                                "Location",
                                ["All Locations"] + sorted(table_df["Location"].unique().tolist()),
                                key="inventory_edit_location_filter"
                            )
                            edit_table_df = table_df.copy()
                            if edit_location_filter != "All Locations":
                                edit_table_df = edit_table_df[edit_table_df["Location"] == edit_location_filter]

                            if edit_table_df.empty:
                                st.info("No inventory rows match the selected location.")
                            else:
                                header_cols = st.columns(
                                    [1.0, 1.2, 0.8, 1.0, 1.2, 0.5, 0.8, 0.8, 0.9, 0.7],
                                    gap=None
                                )
                                for col, label in zip(
                                    header_cols,
                                    [
                                        "Location",
                                        "Address",
                                        "Item Code",
                                        "Item Name",
                                        "Description",
                                        "Location Qty",
                                        "Single Cost",
                                        "Total Cost",
                                        "Location Total",
                                        "Action"
                                    ]
                                ):
                                    with col:
                                        st.markdown(
                                            f'<div class="inventory-stream-cell header">{label}</div>',
                                            unsafe_allow_html=True
                                        )

                                for row_index, row in edit_table_df.sort_values(
                                    ["Location", "Item Name", "Item Code"]
                                ).iterrows():
                                    row_cols = st.columns(
                                        [1.0, 1.2, 0.8, 1.0, 1.2, 0.5, 0.8, 0.8, 0.9, 0.7],
                                        gap=None
                                    )
                                    row_values = [
                                        safe_html(row["Location"]),
                                        safe_html(row["Address"]),
                                        safe_html(row["Item Code"]),
                                        safe_html(row["Item Name"]),
                                        safe_html(row["Description"]),
                                        int(row["Location Quantity"]),
                                        f"${float(row['Single Cost']):,.2f}",
                                        f"${float(row['Total Cost']):,.2f}",
                                        f"${float(row['Location Total Cost']):,.2f}",
                                    ]

                                    for value_col, value in zip(row_cols[:9], row_values):
                                        with value_col:
                                            st.markdown(
                                                f'<div class="inventory-stream-cell strong">{value}</div>',
                                                unsafe_allow_html=True
                                            )

                                    with row_cols[9]:
                                        if st.button(
                                            "Edit",
                                            key=f"manage_inventory_{row['id']}_{row_index}",
                                            type="primary",
                                            width="stretch"
                                        ):
                                            select_inventory_row(row)

                    elif inventory_section == "Cost Summary by Location":
                        st.dataframe(
                            location_summary_df,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "Items": st.column_config.NumberColumn("Items"),
                                "Location Quantity": st.column_config.NumberColumn("Location Quantity"),
                                "Location Total Cost": st.column_config.NumberColumn(
                                    "Location Total Cost",
                                    format="$%.2f"
                                ),
                            }
                        )

                if inventory_section == "Edit Main Items" and selected_main_item is not None:
                    st.markdown('<div class="dashboard-section-title">Edit Main Item</div>', unsafe_allow_html=True)

                    main_item_id = int(selected_main_item["id"])
                    old_main_item_code = str(selected_main_item["item_code"])
                    current_main_base_quantity = (
                        int(selected_main_item["inventory_quantity"])
                        if "inventory_quantity" in selected_main_item
                        and pd.notna(selected_main_item["inventory_quantity"])
                        else 0
                    )
                    current_main_cost = (
                        float(selected_main_item["cost"])
                        if "cost" in selected_main_item
                        and pd.notna(selected_main_item["cost"])
                        else 0.0
                    )
                    current_main_assigned_quantity = (
                        int(selected_main_item["assigned_quantity"])
                        if "assigned_quantity" in selected_main_item
                        and pd.notna(selected_main_item["assigned_quantity"])
                        else 0
                    )
                    conn = get_connection()
                    current_main_admin_assigned_quantity = int(
                        conn.execute(
                            "SELECT COALESCE(SUM(quantity), 0) FROM admin_product_allocations WHERE LOWER(item_code)=LOWER(?)",
                            (old_main_item_code,)
                        ).fetchone()[0] or 0
                    )
                    conn.close()
                    with st.container(border=True):
                        edit_main_item_code = st.text_input(
                            "Item Code",
                            value=old_main_item_code,
                            key=f"edit_main_item_code_{main_item_id}"
                        )
                        edit_main_item_name = st.text_input(
                            "Item Name",
                            value=str(selected_main_item["item_name"]),
                            key=f"edit_main_item_name_{main_item_id}"
                        )
                        edit_main_description = st.text_area(
                            "Description",
                            value=str(selected_main_item["description"]),
                            key=f"edit_main_description_{main_item_id}"
                        )
                        edit_main_quantity_to_add = st.number_input(
                            "Quantity To Add To Base",
                            min_value=0,
                            step=1,
                            value=0,
                            help="This amount is added to the existing base quantity; it does not replace existing quantity.",
                            key=f"edit_main_quantity_to_add_{main_item_id}"
                        )
                        edit_main_cost = st.number_input(
                            "Single Cost / Purchase Cost",
                            min_value=0.0,
                            step=0.01,
                            value=current_main_cost,
                            format="%.2f",
                            key=f"edit_main_cost_{main_item_id}"
                        )
                        updated_main_base_preview = calculate_new_base_quantity(
                            current_main_base_quantity, edit_main_quantity_to_add
                        )
                        st.info(
                            f"Current Base Quantity: {current_main_base_quantity}. "
                            f"Quantity To Add: {int(edit_main_quantity_to_add)}. "
                            f"Base Quantity After Update: {updated_main_base_preview}."
                        )
                        st.caption(
                            f"Existing location stock ({current_main_assigned_quantity}) and Admin assignments "
                            f"({current_main_admin_assigned_quantity}) will not be changed."
                        )
                        st.caption(
                            "Live preview only — the main item is not changed until Update Main Item is clicked."
                        )
                        save_main_item = st.button(
                            "Update Main Item",
                            type="primary",
                            width="stretch",
                            key=f"update_main_item_{main_item_id}"
                        )

                    if save_main_item:
                        if not edit_main_item_code.strip() or not edit_main_item_name.strip():
                            st.error("Item code and item name are required before updating this main item.")
                        else:
                            conn = get_connection()
                            c = conn.cursor()
                            try:
                                c.execute("BEGIN IMMEDIATE")
                                c.execute("SELECT COALESCE(quantity,0) FROM inventory WHERE id=?", (main_item_id,))
                                locked_base_row = c.fetchone()
                                if not locked_base_row:
                                    raise ValueError("This inventory item no longer exists.")
                                locked_base_quantity = int(locked_base_row[0] or 0)
                                updated_main_base_quantity = calculate_new_base_quantity(
                                    locked_base_quantity, edit_main_quantity_to_add
                                )
                                c.execute(
                                    '''SELECT COUNT(*) FROM inventory
                                       WHERE id<>? AND LOWER(item_code)=LOWER(?)''',
                                    (main_item_id, edit_main_item_code.strip())
                                )
                                if int(c.fetchone()[0] or 0):
                                    raise ValueError(
                                        "Another inventory item already uses this item code. "
                                        "Item codes are case-insensitive."
                                    )
                                c.execute(
                                    '''
                                    UPDATE inventory
                                    SET item_code=?, item_name=?, description=?, quantity=?, cost=?
                                    WHERE id=?
                                    ''',
                                    (
                                        edit_main_item_code.strip(),
                                        edit_main_item_name.strip(),
                                        edit_main_description.strip(),
                                        updated_main_base_quantity,
                                        float(edit_main_cost),
                                        main_item_id
                                    )
                                )

                                if old_main_item_code != edit_main_item_code.strip():
                                    update_item_code_references(c, old_main_item_code, edit_main_item_code.strip())

                                conn.commit()
                                st.session_state.inventory_message = (
                                    f"Main item updated successfully. Base Quantity increased from "
                                    f"{locked_base_quantity} to {updated_main_base_quantity}."
                                )
                                st.session_state.manage_main_inventory_id = None
                                st.session_state.inventory_view_section = "Edit Main Items"
                                st.rerun()

                            except sqlite3.IntegrityError:
                                conn.rollback()
                                st.error("Another inventory item already uses this item code. Choose a unique item code.")

                            except ValueError as exc:
                                conn.rollback()
                                st.error(str(exc))

                            finally:
                                conn.close()

                if inventory_section == "Edit Location Stock" and selected_item is not None:
                    st.markdown('<div class="dashboard-section-title">Edit / Delete Location Stock</div>', unsafe_allow_html=True)

                    edit_col, delete_col = st.columns([1.2, 0.8])

                    with edit_col:
                        selected_item_id = int(selected_item["id"])
                        selected_location_id = (
                            int(selected_item["location_id"])
                            if "location_id" in selected_item and pd.notna(selected_item["location_id"])
                            else None
                        )
                        selected_update_location_id = selected_location_id
                        selected_update_location_address = (
                            str(selected_item["location_address"])
                            if "location_address" in selected_item
                            and pd.notna(selected_item["location_address"])
                            and str(selected_item["location_address"]).strip()
                            else "No address"
                        )

                        if is_super_admin():
                            location_choice_labels = []
                            location_choice_ids = {}

                            for _, location_row in inventory_locations_df.iterrows():
                                if int(location_row["active"]) != 1 and int(location_row["id"]) != selected_location_id:
                                    continue
                                location_status = "" if int(location_row["active"]) == 1 else " - Inactive"
                                location_label = (
                                    f"{location_row['name']} (ID {int(location_row['id'])}){location_status}"
                                )
                                location_choice_labels.append(location_label)
                                location_choice_ids[location_label] = int(location_row["id"])

                            current_location_label = location_choice_labels[0] if location_choice_labels else ""
                            if selected_location_id is not None:
                                matched_location = inventory_locations_df[
                                    inventory_locations_df["id"] == selected_location_id
                                ]
                                if not matched_location.empty:
                                    current_location_status = (
                                        "" if int(matched_location.iloc[0]["active"]) == 1 else " - Inactive"
                                    )
                                    current_location_label = (
                                        f"{matched_location.iloc[0]['name']} (ID {selected_location_id}){current_location_status}"
                                    )

                            selected_location_choice = st.selectbox(
                                "Location",
                                location_choice_labels,
                                index=(
                                    location_choice_labels.index(current_location_label)
                                    if current_location_label in location_choice_labels
                                    else 0
                                ),
                                key=f"edit_inventory_location_selector_{selected_item_id}_{selected_location_id or 'unassigned'}"
                            )
                            selected_update_location_id = location_choice_ids[selected_location_choice]

                            if selected_update_location_id is None:
                                selected_update_location_address = "No address"
                            else:
                                selected_update_location_row = inventory_locations_df[
                                    inventory_locations_df["id"] == selected_update_location_id
                                ].iloc[0]
                                selected_update_location_address = (
                                    str(selected_update_location_row["address"])
                                    if pd.notna(selected_update_location_row["address"])
                                    and str(selected_update_location_row["address"]).strip()
                                    else "No address"
                                )

                            st.text_area(
                                "Location Address",
                                value=selected_update_location_address,
                                disabled=True,
                                key=f"edit_inventory_location_address_{selected_item_id}_{selected_update_location_id or 'unassigned'}"
                            )

                        current_base_quantity = (
                            int(selected_item["inventory_quantity"])
                            if "inventory_quantity" in selected_item
                            and pd.notna(selected_item["inventory_quantity"])
                            else 0
                        )
                        current_location_quantity = (
                            int(selected_item["quantity"])
                            if "quantity" in selected_item
                            and pd.notna(selected_item["quantity"])
                            else 0
                        )
                        current_item_code = str(selected_item["item_code"])
                        moving_to_another_location = (
                            selected_location_id is not None
                            and selected_update_location_id != selected_location_id
                        )
                        assigned_elsewhere_for_edit = max(
                            int(selected_item["assigned_quantity"]) - current_location_quantity
                            if "assigned_quantity" in selected_item
                            and pd.notna(selected_item["assigned_quantity"])
                            else 0,
                            0
                        )
                        max_location_quantity_for_edit = max(
                            current_base_quantity - assigned_elsewhere_for_edit,
                            0
                        )

                        with st.form(f"edit_inventory_form_{selected_item_id}_{selected_location_id or 'unassigned'}"):
                            st.markdown(
                                f"""
                                <div class="content-panel">
                                    <div class="dashboard-card-label">Selected Item</div>
                                    <div class="item-name" style="font-size: 1.05rem;">{safe_html(selected_item["item_name"])}</div>
                                    <div class="item-meta">Code: {safe_html(current_item_code)} | Base Quantity: {current_base_quantity}</div>
                                    <div class="item-meta">Use Edit Main Items to change item code, name, description, base quantity, or purchase cost.</div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )
                            if selected_update_location_id is not None:
                                edit_location_quantity = st.number_input(
                                    "Quantity To Move" if moving_to_another_location else "Location Quantity",
                                    min_value=0,
                                    step=1,
                                    value=current_location_quantity,
                                    help=(
                                        "This quantity will be removed from the source and added to the destination."
                                        if moving_to_another_location
                                        else "Enter the exact replacement quantity for this location."
                                    ),
                                    key=f"edit_location_quantity_{selected_item_id}_{selected_location_id or 'unassigned'}"
                                )
                                if moving_to_another_location:
                                    st.caption(
                                        f"You can move up to {current_location_quantity}. Existing destination stock will be kept and increased."
                                    )
                                else:
                                    st.caption(
                                        f"This location can be set up to {max_location_quantity_for_edit} without exceeding the base quantity."
                                    )
                            else:
                                edit_location_quantity = 0
                            edit_total_cost = int(edit_location_quantity) * (
                                float(selected_item["cost"])
                                if "cost" in selected_item and pd.notna(selected_item["cost"])
                                else 0.0
                            )
                            st.markdown(
                                f"""
                                <div class="content-panel">
                                    <div class="dashboard-card-label">Selected Location Cost</div>
                                    <div class="dashboard-card-value">${edit_total_cost:,.2f}</div>
                                    <div class="dashboard-card-note">Location quantity multiplied by purchase cost</div>
                                </div>
                                """,
                                unsafe_allow_html=True
                            )

                            update_item = st.form_submit_button(
                                "Update Location Stock",
                                type="primary",
                                width="stretch"
                            )

                        if update_item:
                            if selected_update_location_id is None:
                                st.error("Select a location before saving location stock.")
                            elif moving_to_another_location and int(edit_location_quantity) > current_location_quantity:
                                st.error(
                                    f"Quantity To Move cannot exceed the source quantity of {current_location_quantity}."
                                )
                            elif (
                                not moving_to_another_location
                                and int(edit_location_quantity) > current_location_quantity
                                and int(edit_location_quantity) > max_location_quantity_for_edit
                            ):
                                st.error(
                                    "Location Quantity cannot be greater than the available base quantity for this location. "
                                    f"Base Quantity is {current_base_quantity}, assigned elsewhere is {assigned_elsewhere_for_edit}, "
                                    f"so this location can be set up to {max_location_quantity_for_edit}."
                                )
                            else:
                                conn = get_connection()
                                c = conn.cursor()

                                try:
                                    c.execute("BEGIN IMMEDIATE")
                                    c.execute(
                                        '''
                                        SELECT COALESCE(quantity, 0)
                                        FROM location_inventory
                                        WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (selected_update_location_id, current_item_code)
                                    )
                                    destination_before_row = c.fetchone()
                                    destination_quantity_before = (
                                        int(destination_before_row[0] or 0)
                                        if destination_before_row
                                        else 0
                                    )
                                    c.execute(
                                        '''
                                        SELECT COALESCE(quantity, 0) FROM location_inventory
                                        WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (selected_location_id, current_item_code)
                                    )
                                    locked_source_row = c.fetchone()
                                    locked_source_quantity = int(locked_source_row[0] or 0) if locked_source_row else 0
                                    requested_quantity = int(edit_location_quantity)

                                    if moving_to_another_location and requested_quantity > locked_source_quantity:
                                        conn.rollback()
                                        st.error(
                                            "Source stock changed while this form was open. "
                                            f"Only {locked_source_quantity} unit(s) can now be moved."
                                        )
                                        st.stop()

                                    if moving_to_another_location:
                                        source_quantity_after = locked_source_quantity - requested_quantity
                                        destination_quantity_after = destination_quantity_before + requested_quantity
                                        c.execute(
                                            "UPDATE location_inventory SET quantity=? WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                            (source_quantity_after, selected_location_id, current_item_code)
                                        )
                                        if source_quantity_after == 0:
                                            c.execute(
                                                "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                                (selected_location_id, current_item_code)
                                            )
                                        c.execute(
                                            '''
                                            INSERT INTO location_stock_history
                                            (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                            VALUES (?,?,?,?,?,?,?,?)
                                            ''',
                                            (
                                                selected_location_id,
                                                current_item_code,
                                                locked_source_quantity,
                                                -requested_quantity,
                                                source_quantity_after,
                                                "Move Out",
                                                st.session_state.username,
                                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            )
                                        )
                                        c.execute(
                                            '''
                                            INSERT INTO location_inventory (location_id,item_code,quantity)
                                            VALUES (?,?,?)
                                            ON CONFLICT(location_id,item_code)
                                            DO UPDATE SET quantity=excluded.quantity
                                            ''',
                                            (selected_update_location_id, current_item_code, destination_quantity_after)
                                        )
                                        c.execute(
                                            '''
                                            INSERT INTO location_stock_history
                                            (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                            VALUES (?,?,?,?,?,?,?,?)
                                            ''',
                                            (
                                                selected_update_location_id,
                                                current_item_code,
                                                destination_quantity_before,
                                                requested_quantity,
                                                destination_quantity_after,
                                                "Move In",
                                                st.session_state.username,
                                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            )
                                        )
                                        c.execute(
                                            '''
                                            SELECT price FROM location_prices
                                            WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                            ''',
                                            (selected_update_location_id, current_item_code)
                                        )
                                        if c.fetchone() is None:
                                            c.execute(
                                                '''
                                                INSERT INTO location_prices (location_id,item_code,price)
                                                SELECT ?, item_code, price FROM location_prices
                                                WHERE location_id=? AND LOWER(item_code)=LOWER(?)
                                                ''',
                                                (selected_update_location_id, selected_location_id, current_item_code)
                                            )
                                        if source_quantity_after == 0:
                                            c.execute(
                                                "DELETE FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                                (selected_location_id, current_item_code)
                                            )
                                        c.execute(
                                            '''
                                            SELECT username, quantity FROM admin_location_stock
                                            WHERE location_id=? AND LOWER(item_code)=LOWER(?) AND quantity>0
                                            ORDER BY id
                                            ''',
                                            (selected_location_id, current_item_code)
                                        )
                                        remaining_ownership_to_move = requested_quantity
                                        for owner_username, owner_quantity in c.fetchall():
                                            ownership_moved = min(int(owner_quantity), remaining_ownership_to_move)
                                            if ownership_moved <= 0:
                                                break
                                            c.execute(
                                                '''UPDATE admin_location_stock SET quantity=quantity-?
                                                   WHERE LOWER(username)=LOWER(?) AND location_id=? AND LOWER(item_code)=LOWER(?)''',
                                                (ownership_moved, owner_username, selected_location_id, current_item_code)
                                            )
                                            c.execute(
                                                '''INSERT INTO admin_location_stock (username,location_id,item_code,quantity)
                                                   VALUES (?,?,?,?) ON CONFLICT(username,location_id,item_code)
                                                   DO UPDATE SET quantity=admin_location_stock.quantity+excluded.quantity''',
                                                (owner_username, selected_update_location_id, current_item_code, ownership_moved)
                                            )
                                            remaining_ownership_to_move -= ownership_moved
                                    else:
                                        c.execute(
                                            "SELECT COALESCE(SUM(quantity),0) FROM location_inventory WHERE LOWER(item_code)=LOWER(?) AND location_id<>?",
                                            (current_item_code, selected_location_id)
                                        )
                                        locked_elsewhere_quantity = int(c.fetchone()[0] or 0)
                                        locked_max_quantity = max(current_base_quantity - locked_elsewhere_quantity, 0)
                                        if (
                                            requested_quantity > locked_source_quantity
                                            and requested_quantity > locked_max_quantity
                                        ):
                                            conn.rollback()
                                            st.error(
                                                "Stock changed while this form was open. This location can now be set "
                                                f"to at most {locked_max_quantity}."
                                            )
                                            st.stop()
                                        quantity_change = requested_quantity - locked_source_quantity
                                        if requested_quantity == 0:
                                            c.execute(
                                                "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                                (selected_location_id, current_item_code)
                                            )
                                            c.execute(
                                                "DELETE FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                                (selected_location_id, current_item_code)
                                            )
                                        else:
                                            c.execute(
                                                "UPDATE location_inventory SET quantity=? WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                                (requested_quantity, selected_location_id, current_item_code)
                                            )
                                        if quantity_change < 0:
                                            remaining_reduction = -quantity_change
                                            c.execute(
                                                '''SELECT id,quantity FROM admin_location_stock
                                                   WHERE location_id=? AND LOWER(item_code)=LOWER(?) AND quantity>0 ORDER BY id''',
                                                (selected_location_id, current_item_code)
                                            )
                                            for owner_id, owner_quantity in c.fetchall():
                                                reduction = min(int(owner_quantity), remaining_reduction)
                                                c.execute(
                                                    "UPDATE admin_location_stock SET quantity=quantity-? WHERE id=?",
                                                    (reduction, owner_id)
                                                )
                                                remaining_reduction -= reduction
                                                if remaining_reduction <= 0:
                                                    break
                                        c.execute(
                                            '''INSERT INTO location_stock_history
                                               (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                               VALUES (?,?,?,?,?,?,?,?)''',
                                            (
                                                selected_location_id, current_item_code, locked_source_quantity,
                                                quantity_change, requested_quantity,
                                                "Remove" if requested_quantity == 0 else "Edit",
                                                st.session_state.username,
                                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            )
                                        )

                                    conn.commit()
                                    st.session_state.inventory_message = (
                                        "Location stock updated successfully. Check Stock & Pricing to confirm the selling price for the selected location."
                                        if selected_update_location_id != selected_location_id
                                        else "Location stock updated successfully."
                                    )
                                    st.session_state.manage_inventory_id = None
                                    st.session_state.manage_inventory_location_id = None
                                    st.session_state.inventory_view_section = "Edit Location Stock"
                                    st.rerun()

                                except sqlite3.IntegrityError:
                                    conn.rollback()
                                    st.error("This item already has stock at the selected location.")

                                finally:
                                    conn.close()

                    with delete_col:
                        selected_item_name_safe = safe_html(selected_item["item_name"])
                        selected_location_name = (
                            str(selected_item["location_name"])
                            if "location_name" in selected_item and pd.notna(selected_item["location_name"]) and str(selected_item["location_name"]).strip()
                            else "Unassigned"
                        )
                        selected_location_name_safe = safe_html(selected_location_name)
                        delete_label = "Remove From Location" if selected_location_id is not None else "Delete Item"
                        selected_location_quantity = (
                            int(selected_item["quantity"] or 0)
                            if selected_location_id is not None and "quantity" in selected_item
                            else 0
                        )
                        delete_note = (
                            f"This removes the item only from {selected_location_name_safe}. The master item and other locations are kept."
                            if selected_location_id is not None
                            else "This removes the master item from inventory. Existing transaction logs are not deleted."
                        )
                        confirm_delete_label = (
                            f"Yes, remove {selected_item['item_name']} from {selected_location_name}."
                            if selected_location_id is not None
                            else "I understand this will delete the selected item everywhere."
                        )
                        st.markdown(
                            f"""
                            <div class="content-panel">
                                <div class="dashboard-card-label">{delete_label}</div>
                                <div class="item-name" style="font-size: 1.05rem;">{selected_item_name_safe}</div>
                                <div class="item-meta">{delete_note}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                        if selected_location_id is not None:
                            st.warning(
                                f"Are you sure you want to remove {selected_item['item_name']} "
                                f"({selected_item['item_code']}) from {selected_location_name}? "
                                f"This will remove {selected_location_quantity} stock unit(s) and the location selling price. "
                                "The master inventory item and stock in other locations will remain."
                            )

                        confirm_delete = st.checkbox(
                            confirm_delete_label,
                            key=(
                                f"confirm_delete_inventory_{selected_item['id']}_"
                                f"{selected_location_id if selected_location_id is not None else 'all'}"
                            )
                        )

                        if st.button(
                            delete_label,
                            disabled=not confirm_delete,
                            width="stretch"
                        ):
                            conn = get_connection()
                            c = conn.cursor()
                            item_code_to_delete = str(selected_item["item_code"])

                            if selected_location_id is not None:
                                try:
                                    c.execute("BEGIN IMMEDIATE")
                                    c.execute(
                                        '''SELECT COUNT(*) FROM inventory_transfers
                                           WHERE status='pending' AND LOWER(item_code)=LOWER(?)
                                             AND (source_location_id=? OR destination_location_id=?)''',
                                        (item_code_to_delete, selected_location_id, selected_location_id)
                                    )
                                    pending_item_transfers = int(c.fetchone()[0] or 0)
                                    if pending_item_transfers:
                                        raise ValueError(
                                            f"This stock cannot be removed because {pending_item_transfers} pending "
                                            "transfer(s) depend on this item and location."
                                        )
                                    c.execute(
                                        '''SELECT COALESCE(quantity,0) FROM location_inventory
                                           WHERE location_id=? AND LOWER(item_code)=LOWER(?)''',
                                        (selected_location_id, item_code_to_delete)
                                    )
                                    delete_quantity_row = c.fetchone()
                                    delete_quantity = int(delete_quantity_row[0] or 0) if delete_quantity_row else 0
                                    c.execute(
                                        '''INSERT INTO location_stock_history
                                           (location_id,item_code,quantity_before,quantity_set,quantity_after,action_type,updated_by,updated_at)
                                           VALUES (?,?,?,?,?,?,?,?)''',
                                        (
                                            selected_location_id, item_code_to_delete, delete_quantity,
                                            -delete_quantity, 0, "Remove From Location",
                                            st.session_state.username,
                                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        )
                                    )
                                    c.execute(
                                        "DELETE FROM admin_location_stock WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                        (selected_location_id, item_code_to_delete)
                                    )
                                except sqlite3.Error as exc:
                                    conn.rollback()
                                    conn.close()
                                    st.error(f"Location stock could not be removed: {exc}")
                                    st.stop()
                                except ValueError as exc:
                                    conn.rollback()
                                    conn.close()
                                    st.error(str(exc))
                                    st.stop()
                                c.execute(
                                    "DELETE FROM location_inventory WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                    (selected_location_id, item_code_to_delete)
                                )
                                c.execute(
                                    "DELETE FROM location_prices WHERE location_id=? AND LOWER(item_code)=LOWER(?)",
                                    (selected_location_id, item_code_to_delete)
                                )
                                st.session_state.inventory_message = (
                                    f"{selected_item['item_name']} removed from {selected_location_name}."
                                )
                            else:
                                delete_blockers = get_item_delete_blockers(c, item_code_to_delete)
                                if delete_blockers:
                                    st.error(
                                        "This item cannot be deleted yet because it has related information: "
                                        + "; ".join(delete_blockers)
                                        + ". Remove live stock, pricing, and assignments first. "
                                        + "Items with sales, return, transaction, or transfer history should stay in inventory for records."
                                    )
                                    conn.close()
                                    st.stop()
                                else:
                                    c.execute(
                                        "DELETE FROM inventory WHERE id=?",
                                        (int(selected_item["id"]),)
                                    )
                                    st.session_state.inventory_message = "Inventory item deleted successfully."

                            conn.commit()
                            conn.close()
                            st.session_state.manage_inventory_id = None
                            st.session_state.manage_inventory_location_id = None
                            st.session_state.inventory_view_section = "Edit Location Stock"
                            st.rerun()

        if menu == "Print QR Codes":

            conn = get_connection()

            df = pd.read_sql_query(
                "SELECT * FROM inventory ORDER BY item_name",
                conn
            )

            conn.close()

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">Print QR Codes</div>
                    <p class="page-subtitle">Create printable QR labels for inventory items.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            if df.empty:
                st.info("No inventory items are available for QR labels. Add inventory first, then return to print labels.")
            else:
                item_options = [str(row["item_code"]) for _, row in df.iterrows()]
                item_labels = {
                    str(row["item_code"]): f"{row['item_code']} - {row['item_name']}"
                    for _, row in df.iterrows()
                }

                st.markdown('<div class="dashboard-section-title">Select Labels</div>', unsafe_allow_html=True)

                selected_labels = st.multiselect(
                    "Inventory Items",
                    item_options,
                    default=item_options,
                    format_func=lambda code: item_labels.get(code, code),
                    label_visibility="collapsed"
                )

                selected_codes = selected_labels

                selected_df = df[df["item_code"].isin(selected_codes)]

                st.markdown('<div class="dashboard-section-title">Printable Labels</div>', unsafe_allow_html=True)

                if selected_df.empty:
                    st.info("Select one or more inventory items to preview printable QR labels.")
                else:
                    label_cards = []

                    for _, row in selected_df.iterrows():
                        qr_path = generate_qr(str(row["item_code"]))
                        qr_base64 = image_to_base64(qr_path)
                        item_name_safe = safe_html(row["item_name"])
                        item_code_safe = safe_html(row["item_code"])
                        quantity_safe = safe_html(row["quantity"])

                        label_cards.append(
                            f'<div class="qr-label-card">'
                            f'<img src="data:image/png;base64,{qr_base64}" width="140" />'
                            f'<div class="qr-label-title">{item_name_safe}</div>'
                            f'<div class="qr-label-meta">Code: {item_code_safe}</div>'
                            f'<div class="qr-label-meta">Qty: {quantity_safe}</div>'
                            f'</div>'
                        )

                    labels_html = "".join(label_cards)
                    component_height = min(760, 140 + ((len(label_cards) + 2) // 3) * 230)

                    components.html(
                        f"""
                        <style>
                            body {{
                                margin: 0;
                                font-family: Arial, sans-serif;
                                color: #1f2937;
                            }}

                            .qr-print-controls {{
                                margin-bottom: 1rem;
                            }}

                            .qr-print-button {{
                                border: 0;
                                border-radius: 10px;
                                background: #2563eb;
                                color: #ffffff;
                                padding: 0.85rem 1.2rem;
                                font-weight: 700;
                                cursor: pointer;
                            }}

                            .qr-print-grid {{
                                display: grid;
                                grid-template-columns: repeat(3, minmax(160px, 1fr));
                                gap: 1rem;
                            }}

                            .qr-label-card {{
                                border: 1px solid #d1d5db;
                                border-radius: 12px;
                                padding: 1rem;
                                text-align: center;
                                background: #ffffff;
                                break-inside: avoid;
                            }}

                            .qr-label-title {{
                                margin-top: 0.75rem;
                                font-size: 1rem;
                                font-weight: 800;
                            }}

                            .qr-label-meta {{
                                margin-top: 0.25rem;
                                color: #4b5563;
                                font-size: 0.86rem;
                            }}

                            @media print {{
                                .qr-print-controls {{
                                    display: none;
                                }}

                                .qr-print-grid {{
                                    grid-template-columns: repeat(3, 1fr);
                                }}
                            }}
                        </style>
                        <div class="qr-print-controls">
                            <button class="qr-print-button" onclick="window.print()">Print Selected QR Labels</button>
                        </div>
                        <div class="qr-print-grid">{labels_html}</div>
                        """,
                        height=component_height,
                        scrolling=True
                    )

        if menu == "User Management" and is_super_admin():

            conn = get_connection()

            users_df = pd.read_sql_query(
                "SELECT id, username, role FROM users ORDER BY id",
                conn
            )

            conn.close()

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">User Management</div>
                    <p class="page-subtitle">Create user accounts, assign roles, and manage access to the system.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            if st.session_state.get("user_management_mode") not in {"create", "assign", "view"}:
                st.session_state.user_management_mode = "create"
            user_nav_cols = st.columns(3)
            user_nav_items = [
                ("Create User", "create"),
                ("Assign Access", "assign"),
                ("View Users", "view"),
            ]
            for nav_col, (nav_label, nav_mode) in zip(user_nav_cols, user_nav_items):
                with nav_col:
                    if st.button(
                        nav_label,
                        type="primary" if st.session_state.user_management_mode == nav_mode else "secondary",
                        width="stretch",
                        key=f"user_management_nav_{nav_mode}"
                    ):
                        st.session_state.user_management_mode = nav_mode
                        st.rerun()

            total_users = len(users_df)
            super_admin_count = int((users_df["role"] == "super_admin").sum()) if not users_df.empty else 0
            admin_count = int((users_df["role"] == "admin").sum()) if not users_df.empty else 0
            sales_count = int((users_df["role"] == "sales").sum()) if not users_df.empty else 0
            user_count = int((users_df["role"] == "user").sum()) if not users_df.empty else 0

            user_col1, user_col2, user_col3 = st.columns(3)

            with user_col1:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Users</div>
                        <div class="dashboard-card-value">{total_users}</div>
                        <div class="dashboard-card-note">Total user accounts</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with user_col2:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Admins</div>
                        <div class="dashboard-card-value">{admin_count}</div>
                        <div class="dashboard-card-note">{super_admin_count} super admin</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with user_col3:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Sales / Users</div>
                        <div class="dashboard-card-value">{sales_count + user_count}</div>
                        <div class="dashboard-card-note">{sales_count} sales, {user_count} users</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            create_col = st.empty()
            manage_col = st.empty()

            with create_col.container():
                st.markdown('<div class="dashboard-section-title">Create User</div>', unsafe_allow_html=True)

                with st.form("create_user_form"):
                    new_username = st.text_input("Username", key="new_username")
                    new_password = st.text_input("Password", type="password", key="new_password")
                    role_options = ["user", "sales", "admin"]
                    if is_super_admin():
                        role_options.append("super_admin")
                    new_role = st.selectbox("Role", role_options, key="new_role")

                    create_user = st.form_submit_button(
                        "Create User",
                        type="primary",
                        width="stretch"
                    )

                if create_user:
                    new_username_clean = new_username.strip()
                    new_password_clean = new_password.strip()
                    normalized_new_role = normalize_role(new_username_clean, new_role)

                    if not new_username_clean or not new_password_clean:
                        st.error("Username and password are required before a new user can be created.")
                    elif new_role == "super_admin" and normalized_new_role != "super_admin":
                        st.error(f"Only the {SUPER_ADMIN_USERNAME} account can be assigned the super admin role.")
                    else:
                        conn = get_connection()
                        c = conn.cursor()

                        try:
                            c.execute(
                                "INSERT INTO users (username,password,role) VALUES (?,?,?)",
                                (new_username_clean, hash_password(new_password_clean), normalized_new_role)
                            )
                            conn.commit()
                            st.success("User account created successfully with the selected role.")
                            st.rerun()

                        except sqlite3.IntegrityError:
                            st.error("A user with this username already exists. Choose a different username.")

                        finally:
                            conn.close()

            with manage_col.container():
                st.markdown('<div class="dashboard-section-title">Existing Users</div>', unsafe_allow_html=True)

                if users_df.empty:
                    st.info("No user accounts are available to manage yet.")
                else:
                    st.dataframe(
                        users_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "id": "ID",
                            "username": "Username",
                            "role": "Role",
                        }
                    )

                    removable_users = users_df[
                        (users_df["username"] != st.session_state.username)
                        & (users_df["username"].str.lower() != SUPER_ADMIN_USERNAME.lower())
                    ]

                    if removable_users.empty:
                        st.info("There are no removable users. You cannot delete the account you are currently using or Ruth's super admin account.")
                    else:
                        user_to_delete = st.selectbox(
                            "Delete User",
                            removable_users["username"].tolist(),
                            key="delete_user_select"
                        )

                        confirm_delete_user = st.checkbox(
                            f"Are you sure you want to permanently delete {user_to_delete}?",
                            key=f"confirm_delete_user_{user_to_delete}"
                        )
                        if st.button(
                            "Delete Selected User", type="secondary", width="stretch",
                            disabled=not confirm_delete_user
                        ):
                            conn = get_connection()
                            try:
                                delete_user_safely(conn, user_to_delete)
                                st.success("User account and inactive access assignments were deleted successfully.")
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                            finally:
                                conn.close()

            if st.session_state.user_management_mode == "create":
                manage_col.empty()
                return
            if st.session_state.user_management_mode == "view":
                create_col.empty()
                return

            create_col.empty()
            manage_col.empty()
            conn = get_connection()
            inventory_df = pd.read_sql_query(
                "SELECT item_code, item_name, quantity FROM inventory ORDER BY item_name",
                conn
            )
            product_assignments_df = pd.read_sql_query(
                '''
                SELECT ps.id, ps.username, u.role, i.item_code, i.item_name,
                       COALESCE(SUM(apa.quantity), 0) AS assigned_quantity,
                       MAX(COALESCE((
                           SELECT SUM(als.quantity)
                           FROM admin_location_stock als
                           WHERE LOWER(als.username)=LOWER(ps.username)
                             AND LOWER(als.item_code)=LOWER(ps.item_code)
                       ), 0), 0) AS added_quantity
                FROM product_suppliers ps
                LEFT JOIN users u ON ps.username = u.username
                LEFT JOIN inventory i ON ps.item_code = i.item_code
                LEFT JOIN admin_product_allocations apa
                    ON LOWER(apa.username) = LOWER(ps.username)
                    AND LOWER(apa.item_code) = LOWER(ps.item_code)
                GROUP BY ps.id, ps.username, u.role, i.item_code, i.item_name
                ORDER BY ps.username, i.item_name
                ''',
                conn
            )
            if not product_assignments_df.empty:
                product_assignments_df["assigned_quantity"] = pd.to_numeric(
                    product_assignments_df["assigned_quantity"], errors="coerce"
                ).fillna(0).astype(int)
                product_assignments_df["added_quantity"] = pd.to_numeric(
                    product_assignments_df["added_quantity"], errors="coerce"
                ).fillna(0).clip(lower=0).astype(int)
                product_assignments_df["remaining_quantity"] = (
                    product_assignments_df["assigned_quantity"]
                    - product_assignments_df["added_quantity"]
                ).clip(lower=0).astype(int)
                product_assignments_df["assignment_status"] = product_assignments_df.apply(
                    lambda row: (
                        "Over assignment"
                        if int(row["added_quantity"]) > int(row["assigned_quantity"])
                        else "Available"
                        if int(row["remaining_quantity"]) > 0
                        else "Fully used"
                    ),
                    axis=1
                )
            conn.close()

            st.markdown("---")
            st.markdown('<div class="dashboard-section-title">Assign Product Access and Quantity</div>', unsafe_allow_html=True)

            assignable_product_users_df = users_df[users_df["role"].isin(["admin", "sales"])].copy()

            if assignable_product_users_df.empty or inventory_df.empty:
                st.info("Create at least one admin or sales account and one inventory item before assigning products.")
            else:
                supplier_col, supplier_table_col = st.columns([0.9, 1.1])

                with supplier_col:
                    supplier_username = st.selectbox(
                        "Admin or Sales User",
                        assignable_product_users_df["username"].tolist(),
                        key="supplier_assignment_user"
                    )
                    supplier_item_options = {
                        f"{row['item_name']} ({row['item_code']})": row["item_code"]
                        for _, row in inventory_df.iterrows()
                    }
                    supplier_item = st.selectbox(
                        "Supplied Product",
                        list(supplier_item_options.keys()),
                        key="supplier_assignment_item"
                    )
                    selected_supplier_item_code = supplier_item_options[supplier_item]
                    selected_supplier_user_role = (
                        assignable_product_users_df.loc[
                            assignable_product_users_df["username"] == supplier_username,
                            "role"
                        ].iloc[0]
                    )
                    selected_supplier_item_rows = inventory_df[
                        inventory_df["item_code"].astype(str).str.lower()
                        == selected_supplier_item_code.lower()
                    ]
                    selected_supplier_item_quantity = (
                        int(selected_supplier_item_rows.iloc[0]["quantity"])
                        if not selected_supplier_item_rows.empty
                        and pd.notna(selected_supplier_item_rows.iloc[0]["quantity"])
                        else 0
                    )
                    current_supplier_assignment_rows = product_assignments_df[
                        (
                            product_assignments_df["username"].astype(str).str.lower()
                            == supplier_username.lower()
                        )
                        & (
                            product_assignments_df["item_code"].astype(str).str.lower()
                            == selected_supplier_item_code.lower()
                        )
                    ]
                    current_supplier_assigned_quantity = (
                        int(current_supplier_assignment_rows.iloc[0]["assigned_quantity"])
                        if not current_supplier_assignment_rows.empty
                        and pd.notna(current_supplier_assignment_rows.iloc[0]["assigned_quantity"])
                        else 0
                    )
                    total_item_assigned_to_admins = 0
                    if not product_assignments_df.empty:
                        item_admin_assignment_rows = product_assignments_df[
                            (product_assignments_df["role"] == "admin")
                            & (
                                product_assignments_df["item_code"].astype(str).str.lower()
                                == selected_supplier_item_code.lower()
                            )
                        ]
                        total_item_assigned_to_admins = int(
                            item_admin_assignment_rows["assigned_quantity"].fillna(0).sum()
                        )
                    assigned_product_quantity = 0
                    if selected_supplier_user_role == "admin":
                        if "supplier_assignment_reset_counter" not in st.session_state:
                            st.session_state.supplier_assignment_reset_counter = 0
                        supplier_assignment_quantity_key = (
                            f"supplier_assignment_quantity_{supplier_username}_{selected_supplier_item_code}_"
                            f"{st.session_state.supplier_assignment_reset_counter}"
                        )
                        available_supplier_assignment_quantity = max(
                            selected_supplier_item_quantity
                            - total_item_assigned_to_admins,
                            0
                        )
                        assigned_product_quantity = st.number_input(
                            "Quantity To Assign",
                            min_value=0,
                            step=1,
                            value=0,
                            help="Adds quantity to this admin's existing assigned quantity.",
                            key=supplier_assignment_quantity_key
                        )
                        st.caption(
                            f"Current admin assigned quantity: {current_supplier_assigned_quantity}. "
                            f"Assigned to all admins: {total_item_assigned_to_admins}. "
                            f"Item base quantity: {selected_supplier_item_quantity}. "
                            f"Available to assign: {available_supplier_assignment_quantity}. "
                            f"After save, this admin will have {current_supplier_assigned_quantity + int(assigned_product_quantity)}."
                        )

                    supplier_assign_col, supplier_remove_col = st.columns(2)

                    with supplier_assign_col:
                        if st.button("Assign Product", type="primary", width="stretch"):
                            conn = get_connection()
                            c = conn.cursor()

                            try:
                                c.execute("BEGIN IMMEDIATE")
                                if selected_supplier_user_role == "admin":
                                    quantity_to_assign = int(
                                        st.session_state.get(
                                            supplier_assignment_quantity_key,
                                            assigned_product_quantity
                                        ) or 0
                                    )
                                    if quantity_to_assign < 0:
                                        st.error("Quantity To Assign cannot be negative.")
                                        conn.rollback()
                                        st.stop()
                                    if quantity_to_assign == 0:
                                        st.error("Quantity To Assign must be greater than 0.")
                                        conn.rollback()
                                        st.stop()
                                    c.execute(
                                        '''
                                        SELECT COALESCE(SUM(quantity), 0)
                                        FROM admin_product_allocations
                                        WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (supplier_username, selected_supplier_item_code)
                                    )
                                    existing_assignment_row = c.fetchone()
                                    existing_assigned_quantity = (
                                        int(existing_assignment_row[0] or 0)
                                        if existing_assignment_row
                                        else 0
                                    )
                                    c.execute(
                                        '''
                                        SELECT COALESCE(SUM(quantity), 0)
                                        FROM admin_product_allocations
                                        WHERE LOWER(item_code)=LOWER(?) AND LOWER(username)<>LOWER(?)
                                        ''',
                                        (selected_supplier_item_code, supplier_username)
                                    )
                                    assigned_to_other_admins = int(c.fetchone()[0] or 0)
                                    c.execute(
                                        "SELECT COALESCE(quantity,0) FROM inventory WHERE LOWER(item_code)=LOWER(?)",
                                        (selected_supplier_item_code,)
                                    )
                                    locked_item_row = c.fetchone()
                                    if not locked_item_row:
                                        raise ValueError("The selected inventory item no longer exists.")
                                    locked_item_base_quantity = int(locked_item_row[0] or 0)
                                    max_quantity_to_add = max(
                                        locked_item_base_quantity
                                        - assigned_to_other_admins
                                        - existing_assigned_quantity,
                                        0
                                    )
                                    if quantity_to_assign > max_quantity_to_add:
                                        st.error(
                                            "Quantity To Assign is greater than the remaining assignable quantity. "
                                            f"Item base quantity: {locked_item_base_quantity}; "
                                            f"this admin already has: {existing_assigned_quantity}; "
                                            f"other admins have: {assigned_to_other_admins}; "
                                            f"available to assign now: {max_quantity_to_add}."
                                        )
                                        conn.rollback()
                                        st.stop()
                                    updated_assigned_quantity = existing_assigned_quantity + quantity_to_assign
                                c.execute(
                                    '''
                                    INSERT OR IGNORE INTO product_suppliers (username,item_code)
                                    VALUES (?,?)
                                    ''',
                                    (supplier_username, selected_supplier_item_code)
                                )
                                if selected_supplier_user_role == "admin":
                                    c.execute(
                                        '''
                                        DELETE FROM admin_product_allocations
                                        WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)
                                        ''',
                                        (supplier_username, selected_supplier_item_code)
                                    )
                                    c.execute(
                                        '''
                                        INSERT INTO admin_product_allocations (username,item_code,quantity)
                                        VALUES (?,?,?)
                                        ''',
                                        (
                                            supplier_username,
                                            selected_supplier_item_code,
                                            updated_assigned_quantity
                                        )
                                    )
                                conn.commit()
                                st.success("Product assignment saved for the selected admin or sales user.")
                                if selected_supplier_user_role == "admin":
                                    st.session_state.supplier_assignment_reset_counter += 1
                                st.rerun()
                            except sqlite3.IntegrityError:
                                conn.rollback()
                                st.info("This product is already assigned to the selected user.")
                            except ValueError as exc:
                                conn.rollback()
                                st.error(str(exc))
                            finally:
                                conn.close()

                    with supplier_remove_col:
                        confirm_remove_product = st.checkbox(
                            f"Remove {selected_supplier_item_code} from {supplier_username}?",
                            key=f"confirm_remove_product_{supplier_username}_{selected_supplier_item_code}"
                        )
                        if st.button("Remove Product", width="stretch", disabled=not confirm_remove_product):
                            conn = get_connection()
                            c = conn.cursor()
                            try:
                                c.execute("BEGIN IMMEDIATE")
                                c.execute(
                                    '''SELECT COALESCE(SUM(quantity), 0) FROM admin_location_stock
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (supplier_username, supplier_item_options[supplier_item])
                                )
                                used_assignment_quantity = int(c.fetchone()[0] or 0)
                                if used_assignment_quantity > 0:
                                    raise ValueError(
                                        "This product assignment cannot be removed while the admin still has "
                                        f"{used_assignment_quantity} unit(s) added from it."
                                    )
                                c.execute(
                                    '''DELETE FROM product_suppliers
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (supplier_username, supplier_item_options[supplier_item])
                                )
                                c.execute(
                                    '''DELETE FROM admin_product_allocations
                                       WHERE LOWER(username)=LOWER(?) AND LOWER(item_code)=LOWER(?)''',
                                    (supplier_username, supplier_item_options[supplier_item])
                                )
                                conn.commit()
                                st.success("Product assignment removed for the selected user.")
                                st.rerun()
                            except ValueError as exc:
                                conn.rollback()
                                st.error(str(exc))
                            finally:
                                conn.close()

                with supplier_table_col:
                    if product_assignments_df.empty:
                        st.info("No product assignments exist yet. Assign products to admins or sales users to scope product access.")
                    else:
                        st.dataframe(
                            product_assignments_df,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "id": "ID",
                                "username": "User",
                                "role": "Role",
                                "item_code": "Item Code",
                                "item_name": "Item Name",
                                "assigned_quantity": "Assigned Quantity",
                                "added_quantity": "Added By Admin",
                                "remaining_quantity": "Remaining Assignment",
                                "assignment_status": "Assignment Status",
                            }
                        )


    if menu == "Locations" and is_super_admin():
        conn = get_connection()
        locations_df = pd.read_sql_query(
            "SELECT id, name, address, owner_username, active, created_at FROM locations ORDER BY name",
            conn
        )
        users_df = pd.read_sql_query(
            "SELECT username, role FROM users WHERE role IN ('super_admin', 'admin', 'sales') ORDER BY username",
            conn
        )
        assignments_df = pd.read_sql_query(
            '''
            SELECT ul.id, ul.username, u.role, l.name AS location
            FROM user_locations ul
            LEFT JOIN users u ON ul.username = u.username
            LEFT JOIN locations l ON ul.location_id = l.id
            ORDER BY ul.username, l.name
            ''',
            conn
        )
        conn.close()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Logistics</div>
                <div class="page-title">Locations</div>
                <p class="page-subtitle">Create and review separate storage facilities for location-based inventory, pricing, and invoicing.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if "locations_message" in st.session_state:
            st.success(st.session_state.locations_message)
            del st.session_state.locations_message

        if "locations_section" not in st.session_state:
            st.session_state.locations_section = "View Locations"

        with st.container(key="locations_section_buttons"):
            location_section_cols = st.columns(3, gap="medium")
            for section_col, section_label in zip(
                location_section_cols,
                ["View Locations", "Create Location", "Assign Users"]
            ):
                with section_col:
                    if st.button(
                        section_label,
                        key=f"locations_section_{section_label.replace(' ', '_').lower()}",
                        type=(
                            "primary"
                            if st.session_state.locations_section == section_label
                            else "secondary"
                        ),
                        width="stretch"
                    ):
                        if section_label != "View Locations":
                            st.session_state.selected_location_edit_id = None
                        st.session_state.locations_section = section_label
                        st.rerun()

        owner_users_df = users_df[users_df["role"].isin(["admin", "super_admin"])].copy()
        owner_options = [""] + owner_users_df["username"].tolist() if not owner_users_df.empty else [""]

        if st.session_state.locations_section == "Create Location":
            st.markdown('<div class="dashboard-section-title">Create Location</div>', unsafe_allow_html=True)

            with st.form("create_location_form"):
                location_name = st.text_input("Location Name")
                location_address = st.text_area("Address / Notes")
                owner_username = st.selectbox("Owner/Admin", owner_options)
                save_location = st.form_submit_button("Save Location", type="primary", width="stretch")

            if save_location:
                if not location_name.strip():
                    st.error("Location name is required before a storage location can be created.")
                else:
                    conn = get_connection()
                    c = conn.cursor()

                    try:
                        c.execute("BEGIN IMMEDIATE")
                        c.execute(
                            '''
                            INSERT INTO locations (name,address,owner_username,active,created_at)
                            VALUES (?,?,?,?,?)
                            ''',
                            (
                                location_name.strip(),
                                location_address.strip(),
                                owner_username or None,
                                1,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            )
                        )
                        new_location_id = c.lastrowid
                        if owner_username:
                            c.execute(
                                "INSERT OR IGNORE INTO user_locations(username,location_id) VALUES (?,?)",
                                (owner_username, new_location_id)
                            )
                        conn.commit()
                        st.session_state.locations_message = "Location created successfully."
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("A location with this name already exists. Use a unique location name.")
                    finally:
                        conn.close()

        elif st.session_state.locations_section == "View Locations":
            st.markdown('<div class="dashboard-section-title">Existing Locations</div>', unsafe_allow_html=True)

            if locations_df.empty:
                st.info("No storage locations have been created yet. Ruth can create the first location from the form on the left.")
            else:
                display_locations_df = locations_df.copy()
                display_locations_df["status"] = display_locations_df["active"].map({1: "Active", 0: "Inactive"})
                selected_location_id = st.session_state.get("selected_location_edit_id")
                selected_location = None

                if selected_location_id:
                    selected_location_rows = locations_df[locations_df["id"] == selected_location_id]
                    if not selected_location_rows.empty:
                        selected_location = selected_location_rows.iloc[0]

                if selected_location is None:
                    location_status_filter = st.selectbox(
                        "Filter Location Status",
                        ["All", "Active", "Inactive"],
                        key="location_status_filter"
                    )

                    if location_status_filter != "All":
                        display_locations_df = display_locations_df[
                            display_locations_df["status"] == location_status_filter
                        ].copy()

                    location_header_cols = st.columns([0.45, 1.1, 1.4, 1.0, 0.75, 1.0, 0.65], gap=None)
                    for col, label in zip(
                        location_header_cols,
                        ["ID", "Location", "Address / Notes", "Owner/Admin", "Status", "Created", "Action"]
                    ):
                        with col:
                            st.markdown(
                                f'<div class="inventory-stream-cell header">{label}</div>',
                                unsafe_allow_html=True
                            )

                    for row_index, row in display_locations_df.iterrows():
                        location_row_cols = st.columns([0.45, 1.1, 1.4, 1.0, 0.75, 1.0, 0.65], gap=None)
                        location_values = [
                            int(row["id"]),
                            safe_html(row["name"]),
                            safe_html(row["address"] if pd.notna(row["address"]) else ""),
                            safe_html(row["owner_username"] if pd.notna(row["owner_username"]) else "Unassigned"),
                            safe_html(row["status"]),
                            safe_html(row["created_at"] if pd.notna(row["created_at"]) else ""),
                        ]

                        for value_col, value in zip(location_row_cols[:6], location_values):
                            with value_col:
                                st.markdown(
                                    f'<div class="inventory-stream-cell strong">{value}</div>',
                                    unsafe_allow_html=True
                                )

                        with location_row_cols[6]:
                            if st.button(
                                "Edit",
                                key=f"edit_location_row_{row['id']}_{row_index}",
                                type="primary",
                                width="stretch"
                            ):
                                st.session_state.selected_location_edit_id = int(row["id"])
                                st.session_state.locations_section = "View Locations"
                                st.rerun()
                else:
                    _, back_col = st.columns([1.55, 0.45])
                    with back_col:
                        with st.container(key="location_back_to_table"):
                            if st.button("Back to Table", type="secondary", width="stretch"):
                                st.session_state.selected_location_edit_id = None
                                st.session_state.locations_section = "View Locations"
                                st.rerun()

                    st.markdown('<div class="dashboard-section-title">Edit / Delete Location</div>', unsafe_allow_html=True)
                    edit_location_col, delete_location_col = st.columns([1.2, 0.8])
                    selected_location_id = int(selected_location["id"])
                    current_owner = selected_location["owner_username"] if pd.notna(selected_location["owner_username"]) else ""
                    owner_index = owner_options.index(current_owner) if current_owner in owner_options else 0

                    with edit_location_col:
                        with st.form(f"edit_location_form_{selected_location_id}"):
                            edited_location_name = st.text_input(
                                "Location Name",
                                value=selected_location["name"],
                                key=f"edit_location_name_{selected_location_id}"
                            )
                            edited_location_address = st.text_area(
                                "Address / Notes",
                                value=selected_location["address"] if pd.notna(selected_location["address"]) else "",
                                key=f"edit_location_address_{selected_location_id}"
                            )
                            edited_owner_username = st.selectbox(
                                "Owner/Admin",
                                owner_options,
                                index=owner_index,
                                key=f"edit_location_owner_{selected_location_id}"
                            )
                            edited_active = st.checkbox(
                                "Active",
                                value=bool(selected_location["active"]),
                                key=f"edit_location_active_{selected_location_id}"
                            )
                            update_location = st.form_submit_button("Update Location", type="primary", width="stretch")

                        if update_location:
                            if not edited_location_name.strip():
                                st.error("Location name is required before this storage location can be updated.")
                            else:
                                conn = get_connection()
                                c = conn.cursor()

                                try:
                                    c.execute("BEGIN IMMEDIATE")
                                    c.execute(
                                        '''
                                        UPDATE locations
                                        SET name=?, address=?, owner_username=?, active=?
                                        WHERE id=?
                                        ''',
                                        (
                                            edited_location_name.strip(),
                                            edited_location_address.strip(),
                                            edited_owner_username or None,
                                            1 if edited_active else 0,
                                            selected_location_id
                                        )
                                    )
                                    if edited_owner_username:
                                        c.execute(
                                            "INSERT OR IGNORE INTO user_locations(username,location_id) VALUES (?,?)",
                                            (edited_owner_username, selected_location_id)
                                        )
                                    conn.commit()
                                    st.session_state.selected_location_edit_id = None
                                    st.session_state.locations_section = "View Locations"
                                    st.session_state.locations_message = "Location updated successfully."
                                    st.rerun()
                                except sqlite3.IntegrityError:
                                    st.error("A location with this name already exists. Use a unique location name.")
                                finally:
                                    conn.close()

                    with delete_location_col:
                        selected_location_name_safe = safe_html(selected_location["name"])
                        st.warning(
                            "Deleting a location is only allowed when it has no stock units and no invoice, return, or transfer history. "
                            "For locations with history, turn off Active instead."
                        )
                        st.markdown(
                            f"""
                            <div class="content-panel">
                                <div class="dashboard-card-label">Delete Location</div>
                                <div class="item-name" style="font-size: 1.05rem;">{selected_location_name_safe}</div>
                                <div class="item-meta">This permanently removes the selected location only when it is safe to delete.</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                        confirm_delete_location = st.checkbox(
                            "I understand this will permanently delete the selected location when it is safe to remove.",
                            key=f"confirm_delete_location_{selected_location_id}"
                        )

                        if st.button(
                            "Delete Location",
                            disabled=not confirm_delete_location,
                            key=f"delete_location_{selected_location_id}",
                            width="stretch"
                        ):
                            conn = get_connection()
                            c = conn.cursor()

                            try:
                                c.execute("BEGIN IMMEDIATE")
                                c.execute(
                                    "SELECT COALESCE(SUM(quantity), 0) FROM location_inventory WHERE location_id=?",
                                    (selected_location_id,)
                                )
                                stock_units = int(c.fetchone()[0] or 0)
                                c.execute("SELECT COUNT(*) FROM invoices WHERE location_id=?", (selected_location_id,))
                                invoice_count = int(c.fetchone()[0] or 0)
                                c.execute("SELECT COUNT(*) FROM returns WHERE location_id=?", (selected_location_id,))
                                return_count = int(c.fetchone()[0] or 0)
                                c.execute(
                                    '''
                                    SELECT COUNT(*) FROM inventory_transfers
                                    WHERE source_location_id=? OR destination_location_id=?
                                    ''',
                                    (selected_location_id, selected_location_id)
                                )
                                transfer_count = int(c.fetchone()[0] or 0)
                                c.execute("SELECT COUNT(*) FROM location_stock_history WHERE location_id=?", (selected_location_id,))
                                stock_history_count = int(c.fetchone()[0] or 0)
                                c.execute("SELECT COUNT(*) FROM transactions WHERE location_id=?", (selected_location_id,))
                                transaction_count = int(c.fetchone()[0] or 0)
                                c.execute("SELECT COALESCE(SUM(quantity),0) FROM admin_location_stock WHERE location_id=?", (selected_location_id,))
                                owned_stock_units = int(c.fetchone()[0] or 0)

                                delete_blockers = []
                                if stock_units > 0:
                                    delete_blockers.append(f"{stock_units} stock unit(s)")
                                if invoice_count > 0:
                                    delete_blockers.append(f"{invoice_count} invoice(s)")
                                if return_count > 0:
                                    delete_blockers.append(f"{return_count} return record(s)")
                                if transfer_count > 0:
                                    delete_blockers.append(f"{transfer_count} transfer record(s)")
                                if stock_history_count > 0:
                                    delete_blockers.append(f"{stock_history_count} stock history record(s)")
                                if transaction_count > 0:
                                    delete_blockers.append(f"{transaction_count} transaction record(s)")
                                if owned_stock_units > 0:
                                    delete_blockers.append(f"{owned_stock_units} Admin-owned stock unit(s)")

                                if delete_blockers:
                                    conn.rollback()
                                    st.error(
                                        "This location cannot be deleted because it has "
                                        + ", ".join(delete_blockers)
                                        + ". Set it to inactive instead to preserve history."
                                    )
                                else:
                                    c.execute("DELETE FROM user_locations WHERE location_id=?", (selected_location_id,))
                                    c.execute("DELETE FROM location_prices WHERE location_id=?", (selected_location_id,))
                                    c.execute("DELETE FROM location_inventory WHERE location_id=?", (selected_location_id,))
                                    c.execute("DELETE FROM locations WHERE id=?", (selected_location_id,))
                                    conn.commit()
                                    st.session_state.selected_location_edit_id = None
                                    st.session_state.locations_section = "View Locations"
                                    st.session_state.locations_message = "Location deleted successfully."
                                    st.rerun()

                            finally:
                                conn.close()

        elif st.session_state.locations_section == "Assign Users":
            st.markdown('<div class="dashboard-section-title">Assign Users to Locations</div>', unsafe_allow_html=True)

            if locations_df.empty or users_df.empty:
                st.info("Create at least one location and one admin or sales user before assigning location access.")
            else:
                assignment_col, assignment_table_col = st.columns([0.9, 1.1])

                with assignment_col:
                    assignable_users_df = users_df[users_df["role"].isin(["admin", "sales"])]

                    if assignable_users_df.empty:
                        st.info("Create an admin or sales user before assigning them to a location.")
                    else:
                        assignment_user = st.selectbox(
                            "User",
                            assignable_users_df["username"].tolist(),
                            key="assignment_user"
                        )
                        assignment_location_options = {
                            f"{row['name']} (ID {row['id']})": int(row["id"])
                            for _, row in locations_df.iterrows()
                        }
                        assignment_location = st.selectbox(
                            "Location",
                            list(assignment_location_options.keys()),
                            key="assignment_location"
                        )

                        assign_col, remove_col = st.columns(2)

                        with assign_col:
                            if st.button("Assign Location", type="primary", width="stretch"):
                                conn = get_connection()
                                c = conn.cursor()

                                try:
                                    c.execute(
                                        '''
                                        INSERT INTO user_locations (username, location_id)
                                        VALUES (?,?)
                                        ''',
                                        (assignment_user, assignment_location_options[assignment_location])
                                    )
                                    conn.commit()
                                    st.session_state.locations_message = "Location assignment saved."
                                    st.rerun()
                                except sqlite3.IntegrityError:
                                    st.info("This user already has access to the selected location.")
                                finally:
                                    conn.close()

                        with remove_col:
                            selected_assignment_location_id = assignment_location_options[assignment_location]
                            confirm_remove_assignment = st.checkbox(
                                f"Are you sure you want to remove {assignment_location} from {assignment_user}?",
                                key=(
                                    f"confirm_remove_assignment_{assignment_user}_"
                                    f"{selected_assignment_location_id}"
                                )
                            )
                            if st.button(
                                "Remove Assignment",
                                width="stretch",
                                disabled=not confirm_remove_assignment
                            ):
                                conn = get_connection()
                                try:
                                    assignment_removed = remove_location_assignment(
                                        conn, assignment_user, selected_assignment_location_id
                                    )
                                    if not assignment_removed:
                                        st.info("This user is not assigned to the selected location.")
                                    else:
                                        st.session_state.locations_message = (
                                            f"Location assignment removed for {assignment_user}."
                                        )
                                        st.rerun()
                                except ValueError as exc:
                                    st.error(str(exc))
                                finally:
                                    conn.close()

                with assignment_table_col:
                    if assignments_df.empty:
                        st.info("No location assignments exist yet. Assign admins or sales users to locations to enable role-scoped access.")
                    else:
                        st.dataframe(
                            assignments_df,
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "id": "ID",
                                "username": "User",
                                "role": "Role",
                                "location": "Location",
                            }
                        )


    if menu == "Manage Sales" and is_super_admin():

        conn = get_connection()
        sales_df = pd.read_sql_query(
            '''
            SELECT t.*, COALESCE(l.name, 'User Account') AS location
            FROM transactions t
            LEFT JOIN locations l ON l.id = t.location_id
            ORDER BY t.id DESC
            ''',
            conn
        )
        conn.close()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Admin</div>
                <div class="page-title">Manage Sales</div>
                <p class="page-subtitle">Review sales activity, item movement, location, and quantity sold from transaction records.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if not sales_df.empty:
            sales_df = sales_df[sales_df["transaction_type"] == "sale"].copy()

        if sales_df.empty:
            st.info("No sales records are available yet. Sales will appear here after users or sales staff complete sale transactions.")
        else:
            sales_df["quantity_before"] = sales_df["quantity_before"].fillna(0).astype(int)
            sales_df["quantity_after"] = sales_df["quantity_after"].fillna(0).astype(int)
            sales_df["sale_date"] = pd.to_datetime(
                sales_df["transaction_time"],
                errors="coerce"
            )

            total_sales_records = len(sales_df)
            total_quantity_sold = int(sales_df["quantity_used"].sum())
            active_sales_users = sales_df["username"].nunique()
            top_sold_item = (
                sales_df.groupby("item_code")["quantity_used"].sum().idxmax()
                if not sales_df.empty else "No sales yet"
            )

            sales_col1, sales_col2, sales_col3, sales_col4 = st.columns(4)

            with sales_col1:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Sales Records</div>
                        <div class="dashboard-card-value">{total_sales_records}</div>
                        <div class="dashboard-card-note">Saved user sales</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with sales_col2:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Quantity Sold</div>
                        <div class="dashboard-card-value">{total_quantity_sold}</div>
                        <div class="dashboard-card-note">Total units sold</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with sales_col3:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Sales Users</div>
                        <div class="dashboard-card-value">{active_sales_users}</div>
                        <div class="dashboard-card-note">Users with sales</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with sales_col4:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Top Sold Item</div>
                        <div class="dashboard-card-value" style="font-size: 1.35rem;">{safe_html(top_sold_item)}</div>
                        <div class="dashboard-card-note">Highest quantity sold</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            st.markdown('<div class="dashboard-section-title">Sales Filters</div>', unsafe_allow_html=True)
            filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1, 1, 1, 1.2])

            with filter_col1:
                user_options = ["All Users"] + sorted(sales_df["username"].dropna().unique().tolist())
                selected_user = st.selectbox("User", user_options, key="sales_user_filter")

            with filter_col2:
                item_options = ["All Items"] + sorted(sales_df["item_code"].dropna().unique().tolist())
                selected_item = st.selectbox("Item Code", item_options, key="sales_item_filter")

            with filter_col3:
                location_options = ["All Locations"] + sorted(sales_df["location"].dropna().unique().tolist())
                selected_location = st.selectbox("Location", location_options, key="sales_location_filter")

            with filter_col4:
                valid_dates = sales_df["sale_date"].dropna()
                if valid_dates.empty:
                    selected_dates = None
                    st.info("No valid sale dates are available for the current sales records.")
                else:
                    selected_dates = st.date_input(
                        "Date Range",
                        value=(valid_dates.min().date(), valid_dates.max().date()),
                        key="sales_date_filter"
                    )

            filtered_sales_df = sales_df.copy()

            if selected_user != "All Users":
                filtered_sales_df = filtered_sales_df[filtered_sales_df["username"] == selected_user]

            if selected_item != "All Items":
                filtered_sales_df = filtered_sales_df[filtered_sales_df["item_code"] == selected_item]

            if selected_location != "All Locations":
                filtered_sales_df = filtered_sales_df[filtered_sales_df["location"] == selected_location]

            if selected_dates and len(selected_dates) == 2:
                start_date, end_date = selected_dates
                filtered_sales_df = filtered_sales_df[
                    filtered_sales_df["sale_date"].dt.date.between(start_date, end_date)
                ]

            summary_col1, summary_col2, summary_col3 = st.columns([1, 1, 1])

            with summary_col1:
                st.markdown('<div class="dashboard-section-title">Sales by Item</div>', unsafe_allow_html=True)
                if filtered_sales_df.empty:
                    st.info("No item sales match the selected filters. Adjust the filters to broaden the results.")
                else:
                    item_sales_df = (
                        filtered_sales_df.groupby("item_code", as_index=False)["quantity_used"]
                        .sum()
                        .sort_values("quantity_used", ascending=False)
                    )
                    st.dataframe(
                        item_sales_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "item_code": "Item Code",
                            "quantity_used": "Quantity Sold",
                        }
                    )

            with summary_col2:
                st.markdown('<div class="dashboard-section-title">Sales by User</div>', unsafe_allow_html=True)
                if filtered_sales_df.empty:
                    st.info("No user sales match the selected filters. Adjust the filters to broaden the results.")
                else:
                    user_sales_df = (
                        filtered_sales_df.groupby("username", as_index=False)["quantity_used"]
                        .sum()
                        .sort_values("quantity_used", ascending=False)
                    )
                    st.dataframe(
                        user_sales_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "username": "User",
                            "quantity_used": "Quantity Sold",
                        }
                    )

            with summary_col3:
                st.markdown('<div class="dashboard-section-title">Sales by Location</div>', unsafe_allow_html=True)
                if filtered_sales_df.empty:
                    st.info("No location sales match the selected filters. Adjust the filters to broaden the results.")
                else:
                    location_sales_df = (
                        filtered_sales_df.groupby("location", as_index=False)["quantity_used"]
                        .sum()
                        .sort_values("quantity_used", ascending=False)
                    )
                    st.dataframe(
                        location_sales_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "location": "Location",
                            "quantity_used": "Quantity Sold",
                        }
                    )

            st.markdown('<div class="dashboard-section-title">Sales Records</div>', unsafe_allow_html=True)

            if filtered_sales_df.empty:
                st.info("No sales records match the selected filters. Try changing the user, item, or date range.")
            else:
                sales_record_search = st.text_input(
                    "Search Sales Records",
                    placeholder="Search by sales user or item code",
                    label_visibility="collapsed",
                    key="sales_record_search"
                )

                if sales_record_search:
                    sales_record_search = sales_record_search.lower().strip()
                    filtered_sales_df = filtered_sales_df[
                        filtered_sales_df["username"].str.lower().str.contains(sales_record_search, na=False)
                        | filtered_sales_df["item_code"].str.lower().str.contains(sales_record_search, na=False)
                        | filtered_sales_df["location"].str.lower().str.contains(sales_record_search, na=False)
                    ]

                if filtered_sales_df.empty:
                    st.info("No sales records match the search text. Try a different user or item code.")
                else:
                    records_df = filtered_sales_df[
                        ["id", "username", "location", "item_code", "quantity_before", "quantity_used", "quantity_after", "transaction_time"]
                    ].copy()
                    st.dataframe(
                        records_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "id": "ID",
                            "username": "Sales User",
                            "location": "Location",
                            "item_code": "Item Code",
                            "quantity_before": "Qty Before Sale",
                            "quantity_used": "Quantity Sold",
                            "quantity_after": "Qty After Sale",
                            "transaction_time": "Sale Time",
                        }
                    )


