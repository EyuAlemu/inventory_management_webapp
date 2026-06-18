import hashlib
import hmac
import os

import streamlit as st

from db import get_connection


PASSWORD_HASH_ITERATIONS = 260000
SUPER_ADMIN_USERNAME = "Ruth"
VALID_ROLES = {"super_admin", "admin", "sales", "user"}


def hash_password(password):
    salt = os.urandom(16).hex()
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        PASSWORD_HASH_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${password_hash}"


def verify_password(password, stored_password):
    if not stored_password:
        return False, False

    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt, expected_hash = stored_password.split("$", 3)
            password_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                int(iterations)
            ).hex()
        except (ValueError, TypeError):
            return False, False

        return hmac.compare_digest(password_hash, expected_hash), False

    password_matches = hmac.compare_digest(password, stored_password)
    return password_matches, password_matches


def get_initial_admin_password():
    password = os.getenv("INVENTORY_ADMIN_PASSWORD")
    if password:
        return password

    try:
        return st.secrets.get("INITIAL_ADMIN_PASSWORD")
    except Exception:
        return None


def get_initial_super_admin_password():
    password = os.getenv("INVENTORY_SUPER_ADMIN_PASSWORD") or os.getenv("INVENTORY_RUTH_PASSWORD")
    if password:
        return password

    try:
        return st.secrets.get("INITIAL_SUPER_ADMIN_PASSWORD") or st.secrets.get("RUTH_PASSWORD")
    except Exception:
        return None


def normalize_role(username, role):
    if role not in VALID_ROLES:
        return "user"

    if role == "super_admin" and username.strip().lower() != SUPER_ADMIN_USERNAME.lower():
        return "admin"

    return role


def add_default_admin():
    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        initial_admin_password = get_initial_admin_password()
        if not initial_admin_password:
            conn.close()
            return

        c.execute(
            "INSERT INTO users (username,password,role) VALUES (?,?,?)",
            ("admin", hash_password(initial_admin_password), "admin")
        )

    initial_super_admin_password = get_initial_super_admin_password()
    c.execute("SELECT id, role FROM users WHERE lower(username)=lower(?)", (SUPER_ADMIN_USERNAME,))
    ruth_user = c.fetchone()

    if ruth_user:
        if ruth_user[1] != "super_admin":
            c.execute(
                "UPDATE users SET role=? WHERE id=?",
                ("super_admin", ruth_user[0])
            )
    elif initial_super_admin_password:
        c.execute(
            "INSERT INTO users (username,password,role) VALUES (?,?,?)",
            (SUPER_ADMIN_USERNAME, hash_password(initial_super_admin_password), "super_admin")
        )

    c.execute(
        "UPDATE users SET role='admin' WHERE role='super_admin' AND lower(username) != lower(?)",
        (SUPER_ADMIN_USERNAME,)
    )

    conn.commit()
    conn.close()


def login(username, password):
    conn = get_connection()
    c = conn.cursor()

    c.execute(
        "SELECT * FROM users WHERE username=?",
        (username,)
    )

    user = c.fetchone()
    if not user:
        conn.close()
        return None

    password_matches, should_upgrade_hash = verify_password(password, user[2])

    if password_matches and should_upgrade_hash:
        c.execute(
            "UPDATE users SET password=? WHERE id=?",
            (hash_password(password), user[0])
        )
        conn.commit()

    conn.close()

    if not password_matches:
        return None

    normalized_role = normalize_role(user[1], user[3])
    if normalized_role != user[3]:
        return (user[0], user[1], user[2], normalized_role)

    return user
