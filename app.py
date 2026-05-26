
import streamlit as st
import streamlit.components.v1 as components
import sqlite3
import pandas as pd
from datetime import datetime

from auth import add_default_admin, hash_password, login
from db import get_connection, init_db
from utils import decode_qr_from_image, generate_qr, image_to_base64, safe_html

init_db()
add_default_admin()

st.set_page_config(page_title="Inventory Management", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.12), transparent 32rem),
                linear-gradient(135deg, #f8fafc 0%, #eef2f7 100%);
        }

        [data-testid="stMain"] {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }

        .block-container {
            max-width: 420px !important;
            margin: 0 auto !important;
            padding: 2rem 1rem !important;
        }

        [data-testid="stMainBlockContainer"] {
            width: 100%;
            max-width: 420px;
        }

        [data-testid="stForm"] {
            width: 100%;
            background: #ffffff;
            border: 1px solid #d8e0ea;
            border-radius: 16px;
            padding: 1.5rem 1.75rem 1.65rem;
            box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
        }

        .login-logo {
            width: 84px;
            height: 84px;
            margin: 0 auto 1rem;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2563eb, #22c55e);
            color: #ffffff;
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: 0;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
            margin-bottom: 0.65rem;
        }

        [data-testid="stForm"] h1 {
            text-align: center;
            color: #111827;
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.1rem;
            padding-bottom: 0;
        }

        [data-testid="stForm"] p {
            text-align: center;
            color: #64748b;
            margin-top: 0;
            margin-bottom: 0.85rem;
        }

        [data-testid="stForm"] label {
            color: #334155;
            font-weight: 600;
        }

        [data-testid="stForm"] label p {
            margin: 0;
            line-height: 1.2;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] {
            margin-bottom: 0.55rem;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] > label {
            margin-bottom: 0.25rem;
        }

        [data-testid="stForm"] [data-testid="stTextInput"] > div {
            margin-top: 0;
        }

        [data-testid="stForm"] input {
            border-radius: 10px;
        }

        [data-testid="stFormSubmitButton"] button {
            width: 100%;
            border: 0;
            border-radius: 10px;
            background: #2563eb;
            color: #ffffff;
            min-height: 2.5rem;
            height: 2.5rem;
            padding: 0 1rem;
            transition: background 0.15s ease, transform 0.15s ease;
        }

        [data-testid="stFormSubmitButton"] button p {
            color: #ffffff;
            font-weight: 700;
            line-height: 1;
            margin: 0;
            padding: 0;
        }

        [data-testid="stFormSubmitButton"] button:hover {
            background: #1d4ed8;
            color: #ffffff;
            transform: translateY(-1px);
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.form("login_form"):
        st.markdown('<div class="login-logo">IM</div>', unsafe_allow_html=True)
        st.title("Inventory Login")
        st.caption("Sign in to manage stock and usage logs.")

        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        login_submitted = st.form_submit_button("Login")

    if login_submitted:
        user = login(username, password)

        if user:
            st.session_state.logged_in = True
            st.session_state.username = user[1]
            st.session_state.role = user[3]
            st.session_state.menu = "Dashboard"
            st.success("Login successful")
            st.rerun()
        else:
            st.error("Invalid credentials")

else:

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(111, 132, 23, 0.12), transparent 28rem),
                linear-gradient(135deg, #f8faf7 0%, #eef3f0 100%);
        }

        [data-testid="stMainBlockContainer"] {
            padding-top: 5rem;
        }

        [data-testid="stSidebar"] {
            background: #d9e4f2;
        }

        [data-testid="stSidebar"] > div:first-child {
            background: transparent;
            padding-top: 1.25rem;
        }

        .sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            margin-bottom: 0.85rem;
        }

        .sidebar-brand-mark {
            width: 42px;
            height: 42px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            font-size: 0.85rem;
            font-weight: 800;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.28);
        }

        .sidebar-brand-title {
            color: #0f172a;
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.1;
        }

        .sidebar-brand-subtitle {
            color: #475569;
            font-size: 0.78rem;
            font-weight: 500;
            line-height: 1.2;
            margin-top: 0.15rem;
        }

        .sidebar-section-label {
            color: #334155;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0;
            margin: 0.55rem 0 0.25rem;
            text-transform: uppercase;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] hr {
            margin-top: 0.25rem;
            margin-bottom: 0.25rem;
            border-color: rgba(15, 23, 42, 0.16);
        }

        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(hr) {
            margin: 0 !important;
            padding: 0 !important;
        }

        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
            justify-content: flex-start;
            text-align: left;
            border-radius: 10px;
            border: 0;
            background: rgba(255, 255, 255, 0.56);
            color: #0f172a;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
            font-size: 0.92rem;
            font-weight: 650;
            min-height: 2rem;
            padding: 0.25rem 0.65rem;
        }

        [data-testid="stSidebar"] .stButton > button div {
            justify-content: flex-start;
            text-align: left;
            width: 100%;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(255, 255, 255, 0.84);
            color: #0f172a;
            box-shadow: inset 3px 0 0 #2563eb, 0 4px 14px rgba(15, 23, 42, 0.12);
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: #ffffff;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.3);
        }

        [data-testid="stSidebar"] .stButton > button p {
            color: inherit;
        }

        [data-testid="stSidebar"] .stButton > button p {
            margin: 0;
            line-height: 1.1;
            text-align: left;
            width: 100%;
        }

        [data-testid="stSidebar"] .stButton > button[kind="primary"] p {
            color: #ffffff;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] {
            margin-bottom: 0 !important;
            padding-bottom: 0 !important;
        }

        .page-header {
            margin-top: 0.25rem;
            margin-bottom: 1.25rem;
        }

        .page-eyebrow {
            color: #667d16;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }

        .page-title {
            color: #31333f;
            font-size: 2rem;
            font-weight: 800;
            line-height: 1.15;
            margin-bottom: 0.25rem;
        }

        .page-subtitle {
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.98rem;
            margin-bottom: 0;
        }

        .dashboard-card {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            min-height: 118px;
        }

        .dashboard-card-label {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 0.45rem;
        }

        .dashboard-card-value {
            color: #31333f;
            font-size: 1.85rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.45rem;
        }

        .dashboard-card-note {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.8rem;
        }

        .dashboard-section-title {
            color: #31333f;
            font-size: 1.05rem;
            font-weight: 800;
            margin: 1.35rem 0 0.4rem;
        }

        .content-panel {
            background: #ffffff;
            border: 1px solid rgba(49, 51, 63, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(49, 51, 63, 0.07);
            padding: 1.1rem;
        }

        .workflow-panel {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.1), transparent 10rem),
                #ffffff;
            border: 1px solid rgba(14, 165, 233, 0.16);
            border-radius: 12px;
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.06);
            padding: 1rem;
            margin-bottom: 0.85rem;
        }

        .workflow-kicker {
            color: #0e7490;
            font-size: 0.76rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: 0.25rem;
        }

        .workflow-title {
            color: #0f172a;
            font-size: 1.08rem;
            font-weight: 850;
            margin-bottom: 0.25rem;
        }

        .workflow-text {
            color: #64748b;
            font-size: 0.88rem;
            line-height: 1.4;
            margin-bottom: 0.7rem;
        }

        .action-summary-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.7rem;
            margin-top: 0.8rem;
        }

        .action-summary-card {
            background: #f8fafc;
            border: 1px solid rgba(14, 165, 233, 0.12);
            border-radius: 12px;
            padding: 0.85rem;
        }

        .action-summary-label {
            color: #64748b;
            font-size: 0.72rem;
            font-weight: 850;
            text-transform: uppercase;
            margin-bottom: 0.3rem;
        }

        .action-summary-value {
            color: #0f172a;
            font-size: 1.25rem;
            font-weight: 850;
            line-height: 1;
        }

        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input {
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid rgba(37, 99, 235, 0.22) !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stTextArea"] textarea::placeholder,
        [data-testid="stNumberInput"] input::placeholder,
        [data-testid="stDateInput"] input::placeholder {
            color: #64748b !important;
            opacity: 1 !important;
        }

        [data-testid="stTextInput"] input:focus,
        [data-testid="stTextArea"] textarea:focus,
        [data-testid="stNumberInput"] input:focus,
        [data-testid="stDateInput"] input:focus {
            border-color: #2563eb !important;
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14), 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            background: #ffffff !important;
            color: #0f172a !important;
            border: 1px solid rgba(37, 99, 235, 0.22) !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06) !important;
        }

        [data-testid="stTextInput"] label p,
        [data-testid="stTextArea"] label p,
        [data-testid="stNumberInput"] label p,
        [data-testid="stDateInput"] label p,
        [data-testid="stSelectbox"] label p {
            color: #0f172a !important;
            font-weight: 700 !important;
        }

        .item-card {
            background: #ffffff;
            border: 1px solid rgba(49, 51, 63, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(49, 51, 63, 0.07);
            padding: 1.15rem;
        }

        .item-status {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.2rem 0.55rem;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.75rem;
        }

        .item-status.ok {
            background: rgba(34, 197, 94, 0.12);
            color: #15803d;
        }

        .item-status.low {
            background: rgba(255, 75, 75, 0.12);
            color: rgb(211, 47, 47);
        }

        .item-name {
            color: #31333f;
            font-size: 1.35rem;
            font-weight: 850;
            line-height: 1.15;
            margin-bottom: 0.3rem;
        }

        .item-meta {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.9rem;
            margin-bottom: 0.85rem;
        }

        .quantity-pill {
            background: var(--secondary-background-color);
            border-radius: 12px;
            padding: 0.8rem;
        }

        .quantity-pill-label {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.76rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }

        .quantity-pill-value {
            color: #31333f;
            font-size: 1.65rem;
            font-weight: 850;
            line-height: 1;
        }

        .preview-list {
            display: grid;
            gap: 0.65rem;
        }

        .preview-row {
            background: var(--secondary-background-color);
            border-radius: 10px;
            padding: 0.7rem 0.8rem;
        }

        .preview-label {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.72rem;
            font-weight: 800;
            margin-bottom: 0.2rem;
            text-transform: uppercase;
        }

        .preview-value {
            color: #31333f;
            font-size: 0.95rem;
            font-weight: 700;
            word-break: break-word;
        }

        .user-flow-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.8rem;
            margin-top: 0.75rem;
        }

        .user-dashboard-hero {
            background:
                linear-gradient(135deg, rgba(18, 36, 23, 0.96), rgba(86, 107, 22, 0.88)),
                radial-gradient(circle at top right, rgba(255, 255, 255, 0.2), transparent 18rem);
            border-radius: 18px;
            box-shadow: 0 18px 42px rgba(18, 36, 23, 0.18);
            padding: 1.35rem;
            color: #ffffff;
        }

        .user-dashboard-hero-grid {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 1rem;
            align-items: end;
        }

        .user-hero-stat {
            background: rgba(255, 255, 255, 0.12);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 14px;
            min-width: 130px;
            padding: 0.8rem;
        }

        .user-hero-stat-value {
            color: #ffffff;
            font-size: 1.6rem;
            font-weight: 850;
            line-height: 1;
        }

        .user-hero-stat-label {
            color: rgba(255, 255, 255, 0.68);
            font-size: 0.75rem;
            font-weight: 750;
            margin-top: 0.35rem;
        }

        .user-dashboard-hero .dashboard-card-label,
        .user-dashboard-hero .item-meta {
            color: rgba(255, 255, 255, 0.72);
        }

        .user-dashboard-hero .item-name {
            color: #ffffff;
            font-size: 1.55rem;
        }

        .user-metric-card {
            background:
                radial-gradient(circle at top right, rgba(14, 165, 233, 0.14), transparent 8rem),
                linear-gradient(145deg, #ffffff 0%, #f4fbff 100%);
            border: 1px solid rgba(14, 165, 233, 0.16);
            border-radius: 8px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
            padding: 1rem;
            min-height: 118px;
            position: relative;
        }

        .user-metric-card::after {
            content: "";
            position: absolute;
            left: 1rem;
            right: 1rem;
            bottom: 0.7rem;
            height: 3px;
            border-radius: 999px;
            background: linear-gradient(90deg, #0ea5e9, #14b8a6);
        }

        .user-metric-label {
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 800;
            margin-bottom: 0.5rem;
        }

        .user-metric-value {
            color: #0f172a;
            font-size: 1.85rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.5rem;
        }

        .user-metric-note {
            color: #64748b;
            font-size: 0.8rem;
            padding-bottom: 0.55rem;
        }

        .user-chart-card {
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
            border: 1px solid rgba(14, 165, 233, 0.14);
            border-radius: 8px;
            box-shadow: 0 16px 32px rgba(15, 23, 42, 0.07);
            padding: 1.05rem;
            min-height: 320px;
        }

        .user-chart-title {
            color: #0f172a;
            font-size: 1.02rem;
            font-weight: 850;
            margin-bottom: 0.7rem;
        }

        .user-chart-badge {
            background: #ecfeff;
            border-radius: 999px;
            color: #0e7490;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.25rem 0.55rem;
            white-space: nowrap;
        }

        .user-stock-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.68rem 0;
            border-bottom: 1px solid rgba(14, 165, 233, 0.12);
        }

        .user-stock-row:last-child {
            border-bottom: 0;
        }

        .user-stock-name {
            color: #0f172a;
            font-size: 0.88rem;
            font-weight: 850;
        }

        .user-stock-meta {
            color: #64748b;
            font-size: 0.76rem;
            margin-top: 0.15rem;
        }

        .user-stock-qty {
            color: #0e7490;
            font-size: 0.95rem;
            font-weight: 850;
        }

        .user-stock-track {
            height: 8px;
            background: #e0f2fe;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 0.45rem;
        }

        .user-stock-fill {
            height: 100%;
            border-radius: inherit;
            background: linear-gradient(90deg, #0ea5e9, #14b8a6);
        }

        .quick-action-panel {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
        }

        .user-dashboard-grid {
            display: grid;
            grid-template-columns: 1.15fr 0.85fr;
            gap: 1rem;
            margin-top: 1rem;
        }

        .lookup-preview-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.1rem;
        }

        .scanner-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.1rem;
            margin-top: 1rem;
        }

        .scanner-icon {
            width: 42px;
            height: 42px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #eef3dc;
            color: #5f7414;
            font-size: 1.25rem;
            margin-bottom: 0.7rem;
        }

        .lookup-preview-field {
            background: var(--secondary-background-color);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 12px;
            padding: 0.75rem 0.85rem;
            margin-top: 0.75rem;
        }

        .lookup-preview-label {
            color: rgba(49, 51, 63, 0.58);
            font-size: 0.75rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
        }

        .lookup-preview-value {
            color: rgba(49, 51, 63, 0.72);
            font-size: 0.92rem;
            font-weight: 650;
        }

        .user-action-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 1rem;
        }

        .user-action-chip {
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 10px 24px rgba(32, 48, 24, 0.07);
            padding: 0.85rem;
        }

        .user-action-chip-title {
            color: #203018;
            font-size: 0.9rem;
            font-weight: 850;
            margin-bottom: 0.2rem;
        }

        .user-action-chip-text {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.78rem;
            line-height: 1.35;
        }

        .user-action-card {
            display: none;
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 16px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1.35rem;
            min-height: 170px;
        }

        .user-action-icon {
            width: 40px;
            height: 40px;
            border-radius: 13px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #eef3dc;
            color: #5f7414;
            font-size: 1.15rem;
            margin-bottom: 0.85rem;
        }

        .user-dashboard-actions .stButton > button {
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #8fa82b, #667d16);
            color: #ffffff;
            font-weight: 750;
            box-shadow: 0 12px 24px rgba(102, 125, 22, 0.22);
        }

        .user-dashboard-actions .stButton > button:hover {
            background: linear-gradient(135deg, #7f9822, #566b12);
            color: #ffffff;
            box-shadow: 0 14px 28px rgba(102, 125, 22, 0.28);
        }

        .user-dashboard-actions .stButton > button p {
            color: #ffffff;
            font-weight: 750;
        }

        .user-flow-card {
            background: rgba(255, 255, 255, 0.94);
            border: 1px solid rgba(32, 48, 24, 0.08);
            border-radius: 14px;
            box-shadow: 0 14px 34px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            min-height: 128px;
        }

        .user-flow-number {
            width: 30px;
            height: 30px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(102, 125, 22, 0.12);
            color: #667d16;
            font-size: 0.8rem;
            font-weight: 850;
            margin-bottom: 0.55rem;
        }

        .user-flow-title {
            color: #31333f;
            font-size: 0.95rem;
            font-weight: 850;
            line-height: 1.2;
            margin-bottom: 0.3rem;
        }

        .user-flow-text {
            color: rgba(49, 51, 63, 0.64);
            font-size: 0.82rem;
            line-height: 1.35;
        }

        .admin-dashboard-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin-bottom: 1.4rem;
            background:
                radial-gradient(circle at 88% 20%, rgba(37, 99, 235, 0.16), transparent 15rem),
                radial-gradient(circle at 18% 0%, rgba(14, 165, 233, 0.12), transparent 14rem),
                linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(244, 248, 252, 0.98));
            border: 1px solid rgba(30, 64, 175, 0.1);
            border-radius: 18px;
            box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08);
            padding: 1.25rem;
        }

        .admin-dashboard-title {
            color: #0f172a;
            font-size: 2.25rem;
            font-weight: 850;
            line-height: 1.1;
            margin-bottom: 0.35rem;
        }

        .admin-dashboard-subtitle {
            color: #64748b;
            font-size: 0.98rem;
        }

        .admin-profile-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.65rem;
            background: #ffffff;
            border: 1px solid rgba(37, 99, 235, 0.12);
            border-radius: 999px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
            padding: 0.55rem 0.85rem;
            white-space: nowrap;
        }

        .admin-profile-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #dbeafe;
            color: #1d4ed8;
            font-weight: 850;
        }

        .admin-profile-name {
            color: #0f172a;
            font-size: 0.9rem;
            font-weight: 800;
            line-height: 1.1;
        }

        .admin-profile-role {
            color: #64748b;
            font-size: 0.76rem;
        }

        .admin-stat-card {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 16px;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.07);
            min-height: 138px;
            padding: 1rem;
            position: relative;
            overflow: hidden;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }

        .admin-stat-card::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--stat-accent, #2563eb);
        }

        .admin-stat-card:hover,
        .dashboard-card:hover,
        .user-flow-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 20px 42px rgba(15, 23, 42, 0.12);
        }

        .stat-blue {
            --stat-accent: #2563eb;
            --stat-soft: #dbeafe;
            --stat-ink: #1d4ed8;
        }

        .stat-cyan {
            --stat-accent: #0891b2;
            --stat-soft: #cffafe;
            --stat-ink: #0e7490;
        }

        .stat-amber {
            --stat-accent: #f59e0b;
            --stat-soft: #fef3c7;
            --stat-ink: #b45309;
        }

        .stat-violet {
            --stat-accent: #7c3aed;
            --stat-soft: #ede9fe;
            --stat-ink: #6d28d9;
        }

        .stat-emerald {
            --stat-accent: #059669;
            --stat-soft: #d1fae5;
            --stat-ink: #047857;
        }

        .admin-stat-icon {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: var(--stat-soft, #dbeafe);
            color: var(--stat-ink, #1d4ed8);
            font-size: 1.15rem;
            margin-bottom: 0.7rem;
        }

        .admin-stat-label {
            color: #64748b;
            font-size: 0.82rem;
            font-weight: 750;
            margin-bottom: 0.3rem;
        }

        .admin-stat-value {
            color: #0f172a;
            font-size: 1.75rem;
            font-weight: 850;
            line-height: 1;
            margin-bottom: 0.55rem;
        }

        .admin-stat-note {
            color: var(--stat-ink, #1d4ed8);
            font-size: 0.78rem;
            font-weight: 700;
        }

        .admin-panel {
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            box-shadow: 0 14px 30px rgba(15, 23, 42, 0.07);
            padding: 1rem;
        }

        .admin-panel-title {
            color: #0f172a;
            font-size: 1.02rem;
            font-weight: 850;
            margin-bottom: 0.7rem;
        }

        .analytics-card {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 16px;
            box-shadow: 0 16px 34px rgba(15, 23, 42, 0.07);
            padding: 1.05rem;
            min-height: 320px;
        }

        .analytics-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            margin-bottom: 0.9rem;
        }

        .analytics-badge {
            background: #eff6ff;
            border-radius: 999px;
            color: #1d4ed8;
            font-size: 0.72rem;
            font-weight: 850;
            padding: 0.25rem 0.55rem;
            white-space: nowrap;
        }

        .analytics-bar-chart {
            display: grid;
            grid-template-columns: 42px 1fr;
            gap: 0.75rem;
            align-items: end;
            min-height: 190px;
            padding: 0.35rem 0.15rem 0;
        }

        .analytics-y-axis {
            display: grid;
            grid-template-rows: repeat(4, 1fr);
            height: 138px;
            padding-bottom: 1.8rem;
            color: #94a3b8;
            font-size: 0.7rem;
            font-weight: 750;
            text-align: right;
        }

        .analytics-plot {
            position: relative;
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.72rem;
            align-items: end;
            min-height: 170px;
            padding: 0 0.1rem;
        }

        .analytics-plot::before {
            content: "";
            position: absolute;
            left: 0;
            right: 0;
            top: 0;
            height: 138px;
            background:
                linear-gradient(to bottom,
                    rgba(148, 163, 184, 0.16) 0,
                    rgba(148, 163, 184, 0.16) 1px,
                    transparent 1px,
                    transparent 33.33%,
                    rgba(148, 163, 184, 0.16) 33.33%,
                    rgba(148, 163, 184, 0.16) calc(33.33% + 1px),
                    transparent calc(33.33% + 1px),
                    transparent 66.66%,
                    rgba(148, 163, 184, 0.16) 66.66%,
                    rgba(148, 163, 184, 0.16) calc(66.66% + 1px),
                    transparent calc(66.66% + 1px),
                    transparent calc(100% - 1px),
                    rgba(15, 23, 42, 0.28) calc(100% - 1px),
                    rgba(15, 23, 42, 0.28) 100%);
            pointer-events: none;
        }

        .analytics-bar-item {
            position: relative;
            z-index: 1;
            display: grid;
            grid-template-rows: auto 1fr auto;
            gap: 0.4rem;
            min-height: 170px;
            align-items: end;
        }

        .analytics-bar-value {
            color: #0f172a;
            font-size: 0.74rem;
            font-weight: 850;
            line-height: 1;
            text-align: center;
        }

        .analytics-bar-track {
            position: relative;
            width: 100%;
            height: 154px;
            border-radius: 8px 8px 0 0;
            background: transparent;
            overflow: hidden;
        }

        .analytics-bar-fill {
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            min-height: 8px;
            border-radius: 8px 8px 0 0;
            background: linear-gradient(180deg, #2563eb, #06b6d4);
            box-shadow: 0 10px 20px rgba(37, 99, 235, 0.22);
        }

        .analytics-bar-label {
            color: #64748b;
            font-size: 0.7rem;
            font-weight: 800;
            text-align: center;
            white-space: nowrap;
        }

        .analytics-empty {
            background: #f8fafc;
            border-radius: 14px;
            color: #64748b;
            font-size: 0.9rem;
            font-weight: 650;
            padding: 1rem;
        }

        .donut-layout {
            display: grid;
            grid-template-columns: 150px 1fr;
            gap: 1rem;
            align-items: center;
            min-height: 220px;
        }

        .donut-chart {
            width: 150px;
            height: 150px;
            border-radius: 50%;
            position: relative;
            box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.18), 0 12px 26px rgba(15, 23, 42, 0.08);
        }

        .donut-chart::after {
            content: "";
            position: absolute;
            width: 70px;
            height: 70px;
            border-radius: 50%;
            background: #ffffff;
            top: 40px;
            left: 40px;
            box-shadow: 0 0 0 1px rgba(148, 163, 184, 0.12);
        }

        .donut-legend {
            display: grid;
            gap: 0.7rem;
        }

        .donut-legend-row {
            display: grid;
            grid-template-columns: 12px 1fr auto;
            gap: 0.55rem;
            align-items: center;
            color: #334155;
            font-size: 0.84rem;
            font-weight: 700;
        }

        .donut-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .donut-percent {
            color: #0f172a;
            font-weight: 850;
        }

        .inventory-action-buttons .stButton > button {
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #2563eb, #06b6d4);
            color: #ffffff;
            font-weight: 800;
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.18);
        }

        .inventory-action-buttons .stButton > button:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2);
            color: #ffffff;
            box-shadow: 0 10px 22px rgba(37, 99, 235, 0.24);
        }

        .inventory-action-buttons .stButton > button p {
            color: inherit;
            font-weight: 800;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"],
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 8px 18px rgba(37, 99, 235, 0.2) !important;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"]:hover,
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            box-shadow: 0 10px 22px rgba(37, 99, 235, 0.26) !important;
        }

        [data-testid="stMain"] [data-testid="stButton"] button[kind="primary"] p,
        [data-testid="stMain"] [data-testid="stButton"] [data-testid="stBaseButton-primary"] p {
            color: #ffffff !important;
            font-weight: 800;
        }

        .inventory-action-buttons [data-testid="stHorizontalBlock"] {
            gap: 0 !important;
        }

        .inventory-action-buttons [data-testid="column"] {
            padding: 0 !important;
        }

        .inventory-action-buttons [data-testid="stElementContainer"] {
            margin: 0 !important;
        }

        .inventory-stream-cell {
            min-height: 50px;
            display: flex;
            align-items: center;
            padding: 0.75rem 0.9rem;
            background: #ffffff;
            border-right: 1px solid rgba(148, 163, 184, 0.18);
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
            color: #334155;
            font-size: 0.9rem;
            font-weight: 650;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .inventory-stream-cell.strong {
            color: #0f172a;
            font-weight: 800;
        }

        .inventory-stream-cell.header {
            min-height: 42px;
            background: #f8fafc;
            color: #64748b;
            font-size: 0.78rem;
            font-weight: 800;
            text-transform: uppercase;
        }

        .inventory-action-buttons [data-testid="stButton"] {
            margin: 0 !important;
            padding: 0.42rem 0.65rem !important;
            min-height: 50px;
            display: flex;
            align-items: center;
            background: #ffffff;
            border-bottom: 1px solid rgba(148, 163, 184, 0.2);
        }

        .inventory-action-buttons [data-testid="stButton"] button {
            margin: 0 !important;
        }

        .qr-print-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }

        .qr-label-card {
            background: #ffffff;
            border: 1px solid rgba(32, 48, 24, 0.1);
            border-radius: 14px;
            box-shadow: 0 12px 28px rgba(32, 48, 24, 0.08);
            padding: 1rem;
            text-align: center;
        }

        .qr-label-title {
            color: #203018;
            font-size: 1rem;
            font-weight: 850;
            margin-top: 0.65rem;
        }

        .qr-label-meta {
            color: rgba(49, 51, 63, 0.62);
            font-size: 0.82rem;
            font-weight: 650;
            margin-top: 0.2rem;
        }

        .qr-print-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border: 0;
            border-radius: 10px;
            background: linear-gradient(135deg, #8fa82b, #667d16);
            color: #ffffff !important;
            font-weight: 800;
            padding: 0.65rem 1rem;
            text-decoration: none !important;
            cursor: pointer;
            box-shadow: 0 12px 24px rgba(102, 125, 22, 0.22);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3);
        }

        .add-inventory-form [data-testid="stFormSubmitButton"] button p {
            color: #ffffff !important;
        }

        [data-testid="stFormSubmitButton"] button,
        [data-testid="stFormSubmitButton"] button[kind="primary"],
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"] {
            background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 12px 24px rgba(37, 99, 235, 0.24) !important;
        }

        [data-testid="stFormSubmitButton"] button:hover,
        [data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"]:hover {
            background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
            color: #ffffff !important;
            border: 0 !important;
            box-shadow: 0 14px 28px rgba(37, 99, 235, 0.3) !important;
        }

        [data-testid="stFormSubmitButton"] button p,
        [data-testid="stFormSubmitButton"] [data-testid="stBaseButton-primary"] p {
            color: #ffffff !important;
            font-weight: 750;
        }

        @media print {
            [data-testid="stSidebar"],
            [data-testid="stToolbar"],
            [data-testid="stHeader"],
            .stButton,
            .page-header,
            .dashboard-section-title,
            .qr-print-controls {
                display: none !important;
            }

            .qr-print-grid {
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 12px;
            }

            .qr-label-card {
                box-shadow: none;
                break-inside: avoid;
                border: 1px solid #222;
            }
        }

        .admin-status-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 0.75rem;
            align-items: center;
            padding: 0.6rem 0;
            border-bottom: 1px solid rgba(32, 48, 24, 0.08);
        }

        .admin-status-row:last-child {
            border-bottom: 0;
        }

        .admin-status-name {
            color: #203018;
            font-size: 0.86rem;
            font-weight: 750;
        }

        .admin-status-meta {
            color: rgba(32, 48, 24, 0.58);
            font-size: 0.76rem;
            margin-top: 0.15rem;
        }

        .admin-status-qty {
            color: #203018;
            font-size: 0.9rem;
            font-weight: 850;
            text-align: right;
        }

        .admin-progress {
            height: 7px;
            background: #eef1e6;
            border-radius: 999px;
            overflow: hidden;
            margin-top: 0.45rem;
        }

        .admin-progress-fill {
            height: 100%;
            border-radius: inherit;
            background: #6f8417;
        }

        .admin-progress-fill.low {
            background: #f0a51a;
        }

        .admin-progress-fill.empty {
            background: #e54b4b;
        }

        @media (max-width: 900px) {
            .user-flow-grid {
                grid-template-columns: 1fr;
            }

            .user-dashboard-grid,
            .user-action-strip {
                grid-template-columns: 1fr;
            }

            .admin-dashboard-header {
                display: block;
            }
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.sidebar.markdown(
        """
        <div class="sidebar-brand">
            <div class="sidebar-brand-mark">TE</div>
            <div>
                <div class="sidebar-brand-title">Tarakji Enterprise<div>
                <div class="sidebar-brand-subtitle">Stock control panel</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    st.sidebar.markdown("---")

    if "menu" not in st.session_state:
        st.session_state.menu = "Dashboard"

    menu_icons = {
        "Dashboard": "📊",
        "Scan Inventory": "🔎",
        "Scan QR / Barcode": "▣",
        "Transaction Logs": "🧾",
        "Add Inventory": "➕",
        "View Inventory": "📦",
        "Print QR Codes": "▣",
        "User Management": "👤",
        "Logout": "↩",
    }

    menu_icons["Manage Sales"] = "$"
    menu_icons["Sell Item"] = "$"

    if st.session_state.role == "admin":
        main_items = ["Dashboard", "Transaction Logs"]
    else:
        main_items = ["Dashboard", "Scan Inventory", "Scan QR / Barcode", "Sell Item", "Transaction Logs"]

    admin_items = ["Add Inventory", "View Inventory", "Print QR Codes", "Manage Sales", "User Management"] if st.session_state.role == "admin" else []

    allowed_items = main_items + admin_items + ["Logout"]

    if st.session_state.menu not in allowed_items:
        st.session_state.menu = "Dashboard" if st.session_state.role == "admin" else "Scan Inventory"

    st.sidebar.markdown(
        '<div class="sidebar-section-label">Main</div>',
        unsafe_allow_html=True
    )

    for item in main_items:
        if st.sidebar.button(
            f"{menu_icons.get(item, '•')}  {item}",
            key=f"menu_{item}",
            type="primary" if st.session_state.menu == item else "secondary",
            width="stretch"
        ):
            st.session_state.menu = item
            st.rerun()

    if admin_items:
        st.sidebar.markdown("---")
        st.sidebar.markdown(
            '<div class="sidebar-section-label">Admin</div>',
            unsafe_allow_html=True
        )

        for item in admin_items:
            if st.sidebar.button(
                f"{menu_icons.get(item, '•')}  {item}",
                key=f"menu_{item}",
                type="primary" if st.session_state.menu == item else "secondary",
                width="stretch"
            ):
                st.session_state.menu = item
                st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        '<div class="sidebar-section-label">Account</div>',
        unsafe_allow_html=True
    )

    if st.sidebar.button(
        f"{menu_icons['Logout']}  Logout",
        key="menu_Logout",
        type="primary" if st.session_state.menu == "Logout" else "secondary",
        width="stretch"
    ):
        st.session_state.menu = "Logout"
        st.rerun()

    menu = st.session_state.menu

    if menu == "Dashboard" and st.session_state.role != "admin":
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
                    st.info("No items assigned yet.")
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
                    st.info("No activity yet.")
                else:
                    recent_user_df = user_transactions_df.head(5)[
                        ["item_code", "transaction_type", "quantity_used", "quantity_after", "transaction_time"]
                    ].copy()
                    recent_user_df["transaction_type"] = recent_user_df["transaction_type"].replace({
                        "allocation": "Added to My Stock",
                        "sale": "Sold Item",
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

    if menu == "Dashboard" and st.session_state.role == "admin":

        conn = get_connection()

        inventory_df = pd.read_sql_query(
            "SELECT * FROM inventory",
            conn
        )

        trans_df = pd.read_sql_query(
            "SELECT * FROM transactions",
            conn
        )

        users_df = pd.read_sql_query(
            "SELECT id, username, role FROM users",
            conn
        )

        conn.close()

        total_items = len(inventory_df)
        total_stock = int(inventory_df["quantity"].sum()) if not inventory_df.empty else 0
        low_stock = int((inventory_df["quantity"] <= 5).sum()) if not inventory_df.empty else 0
        total_transactions = len(trans_df)
        total_users = len(users_df)
        total_used = int(trans_df["quantity_used"].sum()) if not trans_df.empty else 0
        username_safe = safe_html(st.session_state.username)

        st.markdown(
            f"""
            <div class="admin-dashboard-header">
                <div>
                    <div class="admin-dashboard-title">Dashboard</div>
                    <div class="admin-dashboard-subtitle">Welcome back, {username_safe}. Here's what's happening with your Tarakji Enterprise<.</div>
                </div>
                <div class="admin-profile-pill">
                    <div class="admin-profile-avatar">A</div>
                    <div>
                        <div class="admin-profile-name">Admin</div>
                        <div class="admin-profile-role">Super Admin</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        card1, card2, card3, card4, card5 = st.columns(5)

        with card1:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-blue">
                    <div class="admin-stat-icon">📦</div>
                    <div class="admin-stat-label">Products</div>
                    <div class="admin-stat-value">{total_items}</div>
                    <div class="admin-stat-note">Active inventory items</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card2:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-cyan">
                    <div class="admin-stat-icon">🏷</div>
                    <div class="admin-stat-label">Stock Units</div>
                    <div class="admin-stat-value">{total_stock}</div>
                    <div class="admin-stat-note">Units available now</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card3:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-amber">
                    <div class="admin-stat-icon">⚠</div>
                    <div class="admin-stat-label">Low Stock Items</div>
                    <div class="admin-stat-value">{low_stock}</div>
                    <div class="admin-stat-note">Need attention</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card4:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-violet">
                    <div class="admin-stat-icon">🧾</div>
                    <div class="admin-stat-label">Transactions</div>
                    <div class="admin-stat-value">{total_transactions}</div>
                    <div class="admin-stat-note">Usage records saved</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        with card5:
            st.markdown(
                f"""
                <div class="admin-stat-card stat-emerald">
                    <div class="admin-stat-icon">👥</div>
                    <div class="admin-stat-label">Users</div>
                    <div class="admin-stat-value">{total_users}</div>
                    <div class="admin-stat-note">System accounts</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown(
            """
            <div class="dashboard-section-title">Reports & Analytics</div>
            <div class="content-panel" style="margin-bottom: 0.9rem;">
                <div class="dashboard-card-label">Operational insight</div>
                <div class="dashboard-card-note">Monitor usage trends, item movement, recent transactions, and low-stock risk from one admin view.</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        report_col1, report_col2 = st.columns([1.35, 0.85])

        with report_col1:
            usage_overview_html = '<div class="analytics-empty">No transaction data available yet.</div>'

            if not trans_df.empty:
                usage_chart_df = trans_df.copy()
                usage_chart_df["transaction_date"] = pd.to_datetime(
                    usage_chart_df["transaction_time"],
                    errors="coerce"
                ).dt.strftime("%b %d")
                usage_chart_df = usage_chart_df.dropna(subset=["transaction_date"])

                if not usage_chart_df.empty:
                    usage_by_date = usage_chart_df.groupby("transaction_date")[
                        "quantity_used"
                    ].sum().tail(7)
                    max_usage = max(int(usage_by_date.max()), 1)
                    y_axis_values = [max_usage, round(max_usage * 0.67), round(max_usage * 0.33), 0]
                    y_axis_html = "".join(
                        f'<div>{value}</div>'
                        for value in y_axis_values
                    )
                    usage_rows = []

                    for date_label, quantity_used in usage_by_date.items():
                        percent = min(int((int(quantity_used) / max_usage) * 100), 100)
                        usage_rows.append(
                            f'<div class="analytics-bar-item">'
                            f'<div class="analytics-bar-value">{int(quantity_used)}</div>'
                            f'<div class="analytics-bar-track">'
                            f'<div class="analytics-bar-fill" style="height: {percent}%"></div>'
                            f'</div>'
                            f'<div class="analytics-bar-label">{date_label}</div>'
                            f'</div>'
                        )

                    usage_overview_html = (
                        f'<div class="analytics-bar-chart">'
                        f'<div class="analytics-y-axis">{y_axis_html}</div>'
                        f'<div class="analytics-plot">{"".join(usage_rows)}</div>'
                        f'</div>'
                    )

            st.html(
                f'<div class="analytics-card">'
                f'<div class="analytics-card-header">'
                f'<div class="admin-panel-title">Usage Overview</div>'
                f'<div class="analytics-badge">Last activity</div>'
                f'</div>'
                f'{usage_overview_html}'
                f'</div>'
            )

        with report_col2:
            usage_by_item_html = '<div class="analytics-empty">No item usage yet.</div>'

            if not trans_df.empty:
                usage_by_item_df = trans_df.groupby("item_code")[
                    "quantity_used"
                ].sum().sort_values(ascending=False).head(6)

                if not usage_by_item_df.empty:
                    donut_colors = ["#2563eb", "#06b6d4", "#7c3aed", "#f59e0b", "#059669", "#ef4444"]
                    total_item_usage = max(int(usage_by_item_df.sum()), 1)
                    current_percent = 0
                    donut_segments = []
                    legend_rows = []

                    for index, (item_code, quantity_used) in enumerate(usage_by_item_df.items()):
                        item_percent = round((int(quantity_used) / total_item_usage) * 100, 1)
                        next_percent = current_percent + item_percent
                        color = donut_colors[index % len(donut_colors)]
                        item_code_safe = safe_html(item_code)
                        donut_segments.append(f"{color} {current_percent}% {next_percent}%")
                        legend_rows.append(
                            f'<div class="donut-legend-row">'
                            f'<span class="donut-dot" style="background: {color};"></span>'
                            f'<span>{item_code_safe}</span>'
                            f'<span class="donut-percent">{item_percent}%</span>'
                            f'</div>'
                        )
                        current_percent = next_percent

                    usage_by_item_html = (
                        f'<div class="donut-layout">'
                        f'<div class="donut-chart" style="background: conic-gradient({", ".join(donut_segments)});"></div>'
                        f'<div class="donut-legend">{"".join(legend_rows)}</div>'
                        f'</div>'
                    )

            st.html(
                f'<div class="analytics-card">'
                f'<div class="analytics-card-header">'
                f'<div class="admin-panel-title">Usage by Item</div>'
                f'<div class="analytics-badge">Top items</div>'
                f'</div>'
                f'{usage_by_item_html}'
                f'</div>'
            )

        detail_col1, detail_col2, detail_col3 = st.columns([1.05, 1.05, 1.1])

        with detail_col1:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Low Stock Items</div>', unsafe_allow_html=True)

                if inventory_df.empty:
                    st.info("No inventory items yet.")
                else:
                    low_stock_df = inventory_df[inventory_df["quantity"] <= 5][
                        ["item_code", "item_name", "quantity"]
                    ].sort_values("quantity")

                    if low_stock_df.empty:
                        st.success("All items have healthy stock levels.")
                    else:
                        st.dataframe(low_stock_df, width="stretch", hide_index=True)

        with detail_col2:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Recent Transactions</div>', unsafe_allow_html=True)

                if trans_df.empty:
                    st.info("No transactions recorded yet.")
                else:
                    recent_trans_df = trans_df.sort_values("id", ascending=False).head(5)[
                        ["username", "item_code", "quantity_used", "transaction_time"]
                    ]
                    st.dataframe(recent_trans_df, width="stretch", hide_index=True)

        with detail_col3:
            with st.container(border=True):
                st.markdown('<div class="admin-panel-title">Inventory Status</div>', unsafe_allow_html=True)

                if inventory_df.empty:
                    st.info("No inventory items yet.")
                else:
                    max_quantity = max(int(inventory_df["quantity"].max()), 1)
                    status_rows = []

                    for _, row in inventory_df.sort_values("quantity").head(5).iterrows():
                        quantity = int(row["quantity"])
                        percent = min(int((quantity / max_quantity) * 100), 100)
                        progress_class = "empty" if quantity == 0 else "low" if quantity <= 5 else ""
                        status = "Out of Stock" if quantity == 0 else "Low Stock" if quantity <= 5 else "In Stock"
                        item_name_safe = safe_html(row["item_name"])
                        item_code_safe = safe_html(row["item_code"])

                        status_rows.append(
                            f"""
                            <div class="admin-status-row">
                                <div>
                                    <div class="admin-status-name">{item_name_safe}</div>
                                    <div class="admin-status-meta">{item_code_safe} · {status}</div>
                                    <div class="admin-progress">
                                        <div class="admin-progress-fill {progress_class}" style="width: {percent}%"></div>
                                    </div>
                                </div>
                                <div class="admin-status-qty">{quantity}</div>
                            </div>
                            """
                        )

                    st.markdown("".join(status_rows), unsafe_allow_html=True)

        most_used_item = (
            trans_df.groupby("item_code")["quantity_used"].sum().idxmax()
            if not trans_df.empty else "No usage yet"
        )
        most_used_item_safe = safe_html(most_used_item)

        st.markdown(
            f"""
            <div class="admin-panel" style="margin-top: 1rem;">
                <div class="admin-panel-title">Analytics Summary</div>
                <div class="preview-list">
                    <div class="preview-row">
                        <div class="preview-label">Total Quantity Used</div>
                        <div class="preview-value">{total_used}</div>
                    </div>
                    <div class="preview-row">
                        <div class="preview-label">Most Used Item</div>
                        <div class="preview-value">{most_used_item_safe}</div>
                    </div>
                    <div class="preview-row">
                        <div class="preview-label">Inventory Health</div>
                        <div class="preview-value">{
                            "Needs attention" if low_stock else "Healthy"
                        }</div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    if st.session_state.role == "admin":

        if menu == "Add Inventory":

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">Add Inventory</div>
                    <p class="page-subtitle">Create a new stock item and generate a QR code for quick lookup.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            form_col, preview_col = st.columns([1.05, 0.95])

            with form_col:
                st.markdown('<div class="dashboard-section-title">Item Information</div>', unsafe_allow_html=True)
                st.markdown('<div class="add-inventory-form">', unsafe_allow_html=True)

                with st.form("add_inventory_form"):
                    item_code = st.text_input("Item Code", key="admin_item_code")
                    item_name = st.text_input("Item Name")
                    description = st.text_area("Description")
                    quantity = st.number_input(
                        "Quantity",
                        min_value=1,
                        step=1
                    )

                    save_inventory = st.form_submit_button(
                        "Save Inventory",
                        type="primary",
                        width="stretch"
                    )

                st.markdown('</div>', unsafe_allow_html=True)

            with preview_col:
                st.markdown('<div class="dashboard-section-title">Preview</div>', unsafe_allow_html=True)
                st.markdown(
                    f"""
                    <div class="content-panel">
                        <div class="preview-list">
                            <div class="preview-row">
                                <div class="preview-label">Item Code</div>
                                <div class="preview-value">{item_code or "Not entered"}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Item Name</div>
                                <div class="preview-value">{item_name or "Not entered"}</div>
                            </div>
                            <div class="preview-row">
                                <div class="preview-label">Quantity</div>
                                <div class="preview-value">{quantity}</div>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            if save_inventory:

                if not item_code.strip() or not item_name.strip():
                    st.error("Item code and item name are required.")
                else:
                    conn = get_connection()
                    c = conn.cursor()

                    try:
                        c.execute(
                            '''
                            INSERT INTO inventory
                            (item_code,item_name,description,quantity)
                            VALUES (?,?,?,?)
                            ''',
                            (item_code.strip(), item_name.strip(), description.strip(), quantity)
                        )

                        conn.commit()
                        qr_path = generate_qr(item_code.strip())

                        st.success("Inventory added successfully.")
                        st.image(qr_path, caption=f"QR Code: {item_code.strip()}", width=180)

                    except sqlite3.IntegrityError:
                        st.error("An item with this code already exists.")

                    finally:
                        conn.close()

        if menu == "View Inventory":

            conn = get_connection()

            df = pd.read_sql_query(
                "SELECT * FROM inventory",
                conn
            )

            conn.close()

            st.markdown(
                """
                <div class="page-header">
                    <div class="page-eyebrow">Admin</div>
                    <div class="page-title">View Inventory</div>
                    <p class="page-subtitle">Browse current stock, search item records, and identify low inventory.</p>
                </div>
                """,
                unsafe_allow_html=True
            )

            total_items = len(df)
            total_quantity = int(df["quantity"].sum()) if not df.empty else 0
            low_stock = int((df["quantity"] <= 5).sum()) if not df.empty else 0

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
                        <div class="dashboard-card-label">Stock Units</div>
                        <div class="dashboard-card-value">{total_quantity}</div>
                        <div class="dashboard-card-note">Available quantity</div>
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
                        <div class="dashboard-card-note">Items at 5 units or less</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            st.markdown(
                '<div class="dashboard-section-title">Inventory Records</div>',
                unsafe_allow_html=True
            )

            if df.empty:
                st.info("No inventory items found.")
            else:
                search_term = st.text_input(
                    "Search inventory",
                    placeholder="Search by item code, name, or description",
                    label_visibility="collapsed"
                )

                display_df = df.copy()

                if search_term:
                    search_term = search_term.lower().strip()
                    display_df = display_df[
                        display_df["item_code"].str.lower().str.contains(search_term, na=False)
                        | display_df["item_name"].str.lower().str.contains(search_term, na=False)
                        | display_df["description"].str.lower().str.contains(search_term, na=False)
                    ]

                st.markdown(
                    '<div class="dashboard-section-title">Inventory Table</div>',
                    unsafe_allow_html=True
                )

                if "inventory_message" in st.session_state:
                    st.success(st.session_state.inventory_message)
                    del st.session_state.inventory_message

                st.markdown('<div class="inventory-action-buttons">', unsafe_allow_html=True)

                header_cols = st.columns([1, 1.4, 2, 0.7, 0.9], gap=None)
                for col, label in zip(header_cols, ["Item Code", "Item Name", "Description", "Qty", "Action"]):
                    with col:
                        st.markdown(
                            f'<div class="inventory-stream-cell header">{label}</div>',
                            unsafe_allow_html=True
                        )

                for _, row in display_df.iterrows():
                    row_cols = st.columns([1, 1.4, 2, 0.7, 0.9], gap=None)
                    item_code_safe = safe_html(row["item_code"])
                    item_name_safe = safe_html(row["item_name"])
                    description_safe = safe_html(row["description"])

                    with row_cols[0]:
                        st.markdown(
                            f'<div class="inventory-stream-cell strong">{item_code_safe}</div>',
                            unsafe_allow_html=True
                        )
                    with row_cols[1]:
                        st.markdown(
                            f'<div class="inventory-stream-cell strong">{item_name_safe}</div>',
                            unsafe_allow_html=True
                        )
                    with row_cols[2]:
                        st.markdown(
                            f'<div class="inventory-stream-cell">{description_safe}</div>',
                            unsafe_allow_html=True
                        )
                    with row_cols[3]:
                        st.markdown(
                            f'<div class="inventory-stream-cell strong">{row["quantity"]}</div>',
                            unsafe_allow_html=True
                        )
                    with row_cols[4]:
                        if st.button("Edit", key=f"manage_inventory_{row['id']}", type="primary", width="stretch"):
                            st.session_state.manage_inventory_id = int(row["id"])
                            st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

                selected_item = None

                if "manage_inventory_id" in st.session_state and st.session_state.manage_inventory_id:
                    selected_rows = df[df["id"] == st.session_state.manage_inventory_id]
                    if not selected_rows.empty:
                        selected_item = selected_rows.iloc[0]

                if selected_item is not None:
                    st.markdown('<div class="dashboard-section-title">Edit / Delete Item</div>', unsafe_allow_html=True)

                    edit_col, delete_col = st.columns([1.2, 0.8])

                    with edit_col:
                        selected_item_id = int(selected_item["id"])

                        with st.form(f"edit_inventory_form_{selected_item_id}"):
                            edit_item_code = st.text_input(
                                "Item Code",
                                value=str(selected_item["item_code"]),
                                key=f"edit_item_code_{selected_item_id}"
                            )
                            edit_item_name = st.text_input(
                                "Item Name",
                                value=str(selected_item["item_name"]),
                                key=f"edit_item_name_{selected_item_id}"
                            )
                            edit_description = st.text_area(
                                "Description",
                                value=str(selected_item["description"]),
                                key=f"edit_description_{selected_item_id}"
                            )
                            edit_quantity = st.number_input(
                                "Quantity",
                                min_value=0,
                                step=1,
                                value=int(selected_item["quantity"]),
                                key=f"edit_quantity_{selected_item_id}"
                            )

                            update_item = st.form_submit_button(
                                "Update Item",
                                type="primary",
                                width="stretch"
                            )

                        if update_item:
                            if not edit_item_code.strip() or not edit_item_name.strip():
                                st.error("Item code and item name are required.")
                            else:
                                old_item_code = str(selected_item["item_code"])
                                new_item_code = edit_item_code.strip()
                                conn = get_connection()
                                c = conn.cursor()

                                try:
                                    c.execute("BEGIN IMMEDIATE")
                                    c.execute(
                                        '''
                                        UPDATE inventory
                                        SET item_code=?, item_name=?, description=?, quantity=?
                                        WHERE id=?
                                        ''',
                                        (
                                            new_item_code,
                                            edit_item_name.strip(),
                                            edit_description.strip(),
                                            edit_quantity,
                                            selected_item_id
                                        )
                                    )

                                    if old_item_code != new_item_code:
                                        c.execute(
                                            '''
                                            SELECT username, quantity
                                            FROM user_inventory
                                            WHERE item_code=?
                                            ''',
                                            (old_item_code,)
                                        )
                                        old_user_stock_rows = c.fetchall()

                                        for stock_username, stock_quantity in old_user_stock_rows:
                                            c.execute(
                                                '''
                                                INSERT INTO user_inventory (username,item_code,quantity)
                                                VALUES (?,?,?)
                                                ON CONFLICT(username,item_code)
                                                DO UPDATE SET quantity=user_inventory.quantity + excluded.quantity
                                                ''',
                                                (stock_username, new_item_code, int(stock_quantity))
                                            )

                                        c.execute(
                                            "DELETE FROM user_inventory WHERE item_code=?",
                                            (old_item_code,)
                                        )
                                        c.execute(
                                            "UPDATE transactions SET item_code=? WHERE item_code=?",
                                            (new_item_code, old_item_code)
                                        )

                                    conn.commit()
                                    st.session_state.inventory_message = "Inventory updated successfully."
                                    st.session_state.manage_inventory_id = None
                                    st.rerun()

                                except sqlite3.IntegrityError:
                                    conn.rollback()
                                    st.error("Another item already uses this item code.")

                                finally:
                                    conn.close()

                    with delete_col:
                        selected_item_name_safe = safe_html(selected_item["item_name"])
                        st.markdown(
                            f"""
                            <div class="content-panel">
                                <div class="dashboard-card-label">Delete Item</div>
                                <div class="item-name" style="font-size: 1.05rem;">{selected_item_name_safe}</div>
                                <div class="item-meta">This removes the item from inventory. Existing transaction logs are not deleted.</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )

                        confirm_delete = st.checkbox(
                            "I understand this will delete the selected item.",
                            key="confirm_delete_inventory"
                        )

                        if st.button(
                            "Delete Item",
                            disabled=not confirm_delete,
                            width="stretch"
                        ):
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                "DELETE FROM user_inventory WHERE item_code=?",
                                (str(selected_item["item_code"]),)
                            )
                            c.execute(
                                "DELETE FROM inventory WHERE id=?",
                                (int(selected_item["id"]),)
                            )
                            conn.commit()
                            conn.close()
                            st.session_state.manage_inventory_id = None
                            st.session_state.inventory_message = "Inventory item deleted successfully."
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
                st.info("No inventory items found. Add inventory before printing QR labels.")
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
                    st.info("Select at least one inventory item to preview QR labels.")
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

        if menu == "User Management":

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

            total_users = len(users_df)
            admin_count = int((users_df["role"] == "admin").sum()) if not users_df.empty else 0
            staff_count = total_users - admin_count

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
                        <div class="dashboard-card-note">Full access accounts</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            with user_col3:
                st.markdown(
                    f"""
                    <div class="dashboard-card">
                        <div class="dashboard-card-label">Standard Users</div>
                        <div class="dashboard-card-value">{staff_count}</div>
                        <div class="dashboard-card-note">Inventory usage access</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

            create_col, manage_col = st.columns([0.95, 1.05])

            with create_col:
                st.markdown('<div class="dashboard-section-title">Create User</div>', unsafe_allow_html=True)

                with st.form("create_user_form"):
                    new_username = st.text_input("Username", key="new_username")
                    new_password = st.text_input("Password", type="password", key="new_password")
                    new_role = st.selectbox("Role", ["user", "admin"], key="new_role")

                    create_user = st.form_submit_button(
                        "Create User",
                        type="primary",
                        width="stretch"
                    )

                if create_user:
                    if not new_username.strip() or not new_password.strip():
                        st.error("Username and password are required.")
                    else:
                        conn = get_connection()
                        c = conn.cursor()

                        try:
                            c.execute(
                                "INSERT INTO users (username,password,role) VALUES (?,?,?)",
                                (new_username.strip(), hash_password(new_password.strip()), new_role)
                            )
                            conn.commit()
                            st.success("User created successfully.")
                            st.rerun()

                        except sqlite3.IntegrityError:
                            st.error("A user with this username already exists.")

                        finally:
                            conn.close()

            with manage_col:
                st.markdown('<div class="dashboard-section-title">Existing Users</div>', unsafe_allow_html=True)

                if users_df.empty:
                    st.info("No user accounts found.")
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
                        users_df["username"] != st.session_state.username
                    ]

                    if removable_users.empty:
                        st.info("You cannot delete the account you are currently using.")
                    else:
                        user_to_delete = st.selectbox(
                            "Delete User",
                            removable_users["username"].tolist(),
                            key="delete_user_select"
                        )

                        if st.button("Delete Selected User", type="secondary", width="stretch"):
                            conn = get_connection()
                            c = conn.cursor()
                            c.execute(
                                "DELETE FROM user_inventory WHERE username=?",
                                (user_to_delete,)
                            )
                            c.execute(
                                "DELETE FROM users WHERE username=?",
                                (user_to_delete,)
                            )
                            conn.commit()
                            conn.close()
                            st.success("User deleted successfully.")
                            st.rerun()

    if menu == "Manage Sales":

        conn = get_connection()
        sales_df = pd.read_sql_query(
            "SELECT * FROM transactions ORDER BY id DESC",
            conn
        )
        conn.close()

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Admin</div>
                <div class="page-title">Manage Sales</div>
                <p class="page-subtitle">Review user sales activity, item movement, and quantity sold from existing transaction records.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        if not sales_df.empty:
            sales_df = sales_df[sales_df["transaction_type"] == "sale"].copy()

        if sales_df.empty:
            st.info("No sales records found yet. User sales will appear here after inventory is scanned or submitted.")
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
            filter_col1, filter_col2, filter_col3 = st.columns([1, 1, 1.2])

            with filter_col1:
                user_options = ["All Users"] + sorted(sales_df["username"].dropna().unique().tolist())
                selected_user = st.selectbox("User", user_options, key="sales_user_filter")

            with filter_col2:
                item_options = ["All Items"] + sorted(sales_df["item_code"].dropna().unique().tolist())
                selected_item = st.selectbox("Item Code", item_options, key="sales_item_filter")

            with filter_col3:
                valid_dates = sales_df["sale_date"].dropna()
                if valid_dates.empty:
                    selected_dates = None
                    st.info("No valid sale dates available.")
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

            if selected_dates and len(selected_dates) == 2:
                start_date, end_date = selected_dates
                filtered_sales_df = filtered_sales_df[
                    filtered_sales_df["sale_date"].dt.date.between(start_date, end_date)
                ]

            summary_col1, summary_col2 = st.columns([1, 1])

            with summary_col1:
                st.markdown('<div class="dashboard-section-title">Sales by Item</div>', unsafe_allow_html=True)
                if filtered_sales_df.empty:
                    st.info("No item sales match the selected filters.")
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
                    st.info("No user sales match the selected filters.")
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

            st.markdown('<div class="dashboard-section-title">Sales Records</div>', unsafe_allow_html=True)

            if filtered_sales_df.empty:
                st.info("No sales records match the selected filters.")
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
                    ]

                if filtered_sales_df.empty:
                    st.info("No sales records match the search.")
                else:
                    records_df = filtered_sales_df[
                        ["id", "username", "item_code", "quantity_before", "quantity_used", "quantity_after", "transaction_time"]
                    ].copy()
                    st.dataframe(
                        records_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "id": "ID",
                            "username": "Sales User",
                            "item_code": "Item Code",
                            "quantity_before": "User Qty Before Sale",
                            "quantity_used": "Quantity Sold",
                            "quantity_after": "User Qty After Sale",
                            "transaction_time": "Sale Time",
                        }
                    )

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
                st.success(f"Code detected: {scanned_code}")
                st.rerun()
            elif scan_error:
                st.warning(scan_error)

    if menu == "Scan Inventory":

        if "scan_inventory_message" in st.session_state:
            st.success(st.session_state.scan_inventory_message)
            del st.session_state.scan_inventory_message

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">Inventory Lookup</div>
                <div class="page-title">Scan Inventory</div>
                <p class="page-subtitle">Enter an item code to review stock details before selling or checking inventory.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

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
                    <div class="workflow-title">Find Inventory Item</div>
                    <div class="workflow-text">Enter the item code from the QR label. After the item loads, choose how many units to add to your stock.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            with st.form("scan_inventory_lookup_form"):
                scan_lookup_code = st.text_input(
                    "Item Code",
                    key="scan_lookup_code",
                    placeholder="Enter item code, for example 123"
                )
                lookup_submitted = st.form_submit_button(
                    "View Item Details",
                    type="primary",
                    width="stretch"
                )

            if lookup_submitted:
                st.session_state.scan_selected_item_code = scan_lookup_code.strip()

            item_code = st.session_state.get("scan_selected_item_code", "").strip()

        with detail_col:
            st.markdown('<div class="dashboard-section-title">Receive Stock</div>', unsafe_allow_html=True)

            if not item_code:
                st.info("Enter an item code on the left to load the item and receive stock.")

        if item_code:

            conn = get_connection()
            c = conn.cursor()

            c.execute(
                "SELECT * FROM inventory WHERE item_code=?",
                (item_code,)
            )

            item = c.fetchone()

            if item:

                status_class = "low" if item[4] <= 5 else "ok"
                status_text = "Low stock" if item[4] <= 5 else "In stock"
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

                with detail_col:
                    st.markdown(
                        f"""
                        <div class="item-card">
                            <div class="item-status {status_class}">{status_text}</div>
                            <div class="item-name">{item_name_safe}</div>
                            <div class="item-meta">{item_description_safe}</div>
                            <div class="quantity-pill">
                                <div class="quantity-pill-label">SYSTEM AVAILABLE QUANTITY</div>
                                <div class="quantity-pill-value">{item[4]}</div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    transfer_qty = st.number_input(
                        "Quantity to Add to My Stock",
                        min_value=1,
                        step=1,
                        key="scan_transfer_quantity"
                    )

                    user_after_preview = user_quantity + int(transfer_qty)
                    system_after_preview = max(int(item[4]) - int(transfer_qty), 0)

                    st.markdown(
                        f"""
                        <div class="content-panel">
                            <div class="workflow-kicker">Stock Preview</div>
                            <div class="action-summary-grid">
                                <div class="action-summary-card">
                                    <div class="action-summary-label">My Current Qty</div>
                                    <div class="action-summary-value">{user_quantity}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">Adding</div>
                                    <div class="action-summary-value">{int(transfer_qty)}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">My Qty After</div>
                                    <div class="action-summary-value">{user_after_preview}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">System Qty After</div>
                                    <div class="action-summary-value">{system_after_preview}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    if st.button("Add to My Stock", type="primary", width="stretch"):
                        transfer_conn = get_connection()
                        transfer_c = transfer_conn.cursor()

                        try:
                            transfer_c.execute("BEGIN IMMEDIATE")
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

                            if not current_inventory:
                                transfer_conn.rollback()
                                st.error("Item not found. Check the item code and try again.")
                            else:
                                system_quantity_before = int(current_inventory[1])
                                user_quantity_before = int(current_user_inventory[0]) if current_user_inventory else 0
                                transfer_qty_int = int(transfer_qty)

                                if transfer_qty_int > system_quantity_before:
                                    transfer_conn.rollback()
                                    st.error("Not enough system stock available.")
                                else:
                                    system_quantity_after = system_quantity_before - transfer_qty_int
                                    user_quantity_after = user_quantity_before + transfer_qty_int

                                    transfer_c.execute(
                                        '''
                                        UPDATE inventory
                                        SET quantity=?
                                        WHERE id=?
                                        ''',
                                        (system_quantity_after, int(current_inventory[0]))
                                    )

                                    transfer_c.execute(
                                        '''
                                        INSERT INTO user_inventory (username,item_code,quantity)
                                        VALUES (?,?,?)
                                        ON CONFLICT(username,item_code)
                                        DO UPDATE SET quantity=excluded.quantity
                                        ''',
                                        (st.session_state.username, item_code, user_quantity_after)
                                    )

                                    transfer_c.execute(
                                        '''
                                        INSERT INTO transactions
                                        (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,transaction_time)
                                        VALUES (?,?,?,?,?,?,?)
                                        ''',
                                        (
                                            st.session_state.username,
                                            item_code,
                                            transfer_qty_int,
                                            user_quantity_before,
                                            user_quantity_after,
                                            "allocation",
                                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        )
                                    )

                                    transfer_conn.commit()
                                    st.session_state.scan_inventory_message = (
                                        f"{transfer_qty_int} unit(s) added to your stock. Your quantity is now {user_quantity_after}. System remaining quantity is {system_quantity_after}."
                                    )
                                    st.rerun()

                        finally:
                            transfer_conn.close()

                    if st.button("Go to Sell Item", width="stretch"):
                        st.session_state.prefill_sell_item_code = item_code
                        st.session_state.menu = "Sell Item"
                        st.rerun()

            else:
                with detail_col:
                    st.error("Item not found. Check the item code and try again.")

            conn.close()

    if menu == "Sell Item":

        if "sell_item_message" in st.session_state:
            st.success(st.session_state.sell_item_message)
            del st.session_state.sell_item_message

        st.markdown(
            """
            <div class="page-header">
                <div class="page-eyebrow">User Sale</div>
                <div class="page-title">Sell Item</div>
                <p class="page-subtitle">Enter an item code, choose quantity sold, and save the sale with remaining stock.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

        sell_lookup_col, sell_detail_col = st.columns([0.9, 1.1])

        with sell_lookup_col:
            if "prefill_sell_item_code" in st.session_state:
                st.session_state.sell_lookup_code = st.session_state.prefill_sell_item_code
                st.session_state.sell_selected_item_code = st.session_state.prefill_sell_item_code
                del st.session_state.prefill_sell_item_code

            st.markdown(
                """
                <div class="workflow-panel">
                    <div class="workflow-kicker">Step 1</div>
                    <div class="workflow-title">Find Item to Sell</div>
                    <div class="workflow-text">Enter the item code, then confirm how many units were sold from your available stock.</div>
                </div>
                """,
                unsafe_allow_html=True
            )

            with st.form("sell_item_lookup_form"):
                sell_lookup_code = st.text_input(
                    "Item Code",
                    key="sell_lookup_code",
                    placeholder="Enter item code, for example 123"
                )
                sell_lookup_submitted = st.form_submit_button(
                    "View Sale Details",
                    type="primary",
                    width="stretch"
                )

            if sell_lookup_submitted:
                st.session_state.sell_selected_item_code = sell_lookup_code.strip()

            sell_item_code = st.session_state.get("sell_selected_item_code", "").strip()

        with sell_detail_col:
            st.markdown('<div class="dashboard-section-title">Record Sale</div>', unsafe_allow_html=True)

            if not sell_item_code:
                st.info("Enter an item code on the left to load your available quantity.")

        if sell_item_code:
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT * FROM inventory WHERE item_code=?",
                (sell_item_code,)
            )
            item = c.fetchone()
            c.execute(
                '''
                SELECT quantity FROM user_inventory
                WHERE username=? AND item_code=?
                ''',
                (st.session_state.username, sell_item_code)
            )
            user_inventory_row = c.fetchone()
            conn.close()

            if item:
                system_quantity = int(item[4])
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
                        step=1,
                        key="sell_quantity_sold"
                    )

                    quantity_after_preview = max(user_quantity - int(quantity_sold), 0)

                    st.markdown(
                        f"""
                        <div class="content-panel">
                            <div class="workflow-kicker">Sale Preview</div>
                            <div class="action-summary-grid">
                                <div class="action-summary-card">
                                    <div class="action-summary-label">System Qty</div>
                                    <div class="action-summary-value">{system_quantity}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">My Qty Before</div>
                                    <div class="action-summary-value">{user_quantity}</div>
                                </div>
                                <div class="action-summary-card">
                                    <div class="action-summary-label">Sold</div>
                                    <div class="action-summary-value">{int(quantity_sold)}</div>
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

                    if st.button("Save Sale", type="primary", width="stretch"):
                        sale_conn = get_connection()
                        sale_c = sale_conn.cursor()

                        try:
                            sale_c.execute("BEGIN IMMEDIATE")
                            sale_c.execute(
                                '''
                                SELECT quantity FROM user_inventory
                                WHERE username=? AND item_code=?
                                ''',
                                (st.session_state.username, sell_item_code)
                            )
                            current_user_item = sale_c.fetchone()

                            sale_c.execute(
                                "SELECT id, item_name, quantity FROM inventory WHERE item_code=?",
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
                                    st.error("Not enough quantity in your stock. Add stock from Scan Inventory first.")
                                else:
                                    quantity_after = quantity_before - quantity_sold_int

                                    sale_c.execute(
                                        '''
                                        UPDATE user_inventory
                                        SET quantity=?
                                        WHERE username=? AND item_code=?
                                        ''',
                                        (quantity_after, st.session_state.username, sell_item_code)
                                    )

                                    sale_c.execute(
                                        '''
                                        INSERT INTO transactions
                                        (username,item_code,quantity_used,quantity_before,quantity_after,transaction_type,transaction_time)
                                        VALUES (?,?,?,?,?,?,?)
                                        ''',
                                        (
                                            st.session_state.username,
                                            sell_item_code,
                                            quantity_sold_int,
                                            quantity_before,
                                            quantity_after,
                                            "sale",
                                            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        )
                                    )

                                    sale_conn.commit()
                                    st.session_state.sell_item_message = (
                                        f"Sale saved successfully. Sold {quantity_sold_int} unit(s). Remaining quantity is {quantity_after}."
                                    )
                                    st.rerun()

                        finally:
                            sale_conn.close()

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

        if st.session_state.role != "admin" and not df.empty:
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
            df["quantity_before"] = df["quantity_before"].fillna(0).astype(int)
            df["quantity_after"] = df["quantity_after"].fillna(0).astype(int)

        total_logs = len(df)
        total_allocated = int(df.loc[df["transaction_type"] == "allocation", "quantity_used"].sum()) if not df.empty else 0
        total_sold = int(df.loc[df["transaction_type"] == "sale", "quantity_used"].sum()) if not df.empty else 0
        unique_items_used = df["item_code"].nunique() if not df.empty else 0
        active_users = df["username"].nunique() if not df.empty else 0

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
                    <div class="dashboard-card-note">Units sold from user stock</div>
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
                    <div class="dashboard-card-label">Users</div>
                    <div class="dashboard-card-value">{active_users}</div>
                    <div class="dashboard-card-note">People recording usage</div>
                </div>
                """,
                unsafe_allow_html=True
            )

        st.markdown(
            '<div class="dashboard-section-title">Usage History</div>',
            unsafe_allow_html=True
        )

        if df.empty:
            st.info("No transactions recorded yet.")
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
            display_df["transaction_type"] = display_df["transaction_type"].replace({
                "allocation": "Added to My Stock",
                "sale": "Sold Item",
                "legacy": "Legacy Record",
            })
            display_df = display_df[
                [
                    "id",
                    "username",
                    "item_code",
                    "transaction_type",
                    "quantity_before",
                    "quantity_used",
                    "quantity_after",
                    "transaction_time",
                ]
            ]

            st.dataframe(
                display_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "id": "ID",
                    "username": "User",
                    "item_code": "Item Code",
                    "transaction_type": "Action",
                    "quantity_before": "My Qty Before",
                    "quantity_used": "Quantity Changed",
                    "quantity_after": "My Qty After",
                    "transaction_time": "Transaction Time",
                }
            )

    if menu == "Logout":
        st.session_state.logged_in = False
        st.rerun()
