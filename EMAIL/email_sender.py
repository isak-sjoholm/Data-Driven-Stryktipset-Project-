"""
email_sender.py
---------------
Builds and sends the results email: one section per ranking method
(agreement, payout), each with a distribution table, an agreement table,
and a txt attachment of the top rows.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_email_config(config_file=None):
    """
    Reads sender_email, sender_password, smtp_server, smtp_port from a
    config file (default: email_config.txt in the project root).

    Returns:
        dict with keys: sender_email, sender_password, smtp_server, smtp_port
    """
    if config_file is None:
        config_file = os.path.join(ROOT_DIR, "email_config.txt")

    config = {"sender_email": None, "sender_password": None, "smtp_server": "smtp.gmail.com", "smtp_port": 587}

    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Email config file not found: {config_file}")

    with open(config_file, "r") as f:
        for line in f:
            line = line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key == "sender_email":
                config["sender_email"] = value
            elif key == "sender_password":
                config["sender_password"] = value
            elif key == "smtp_server":
                config["smtp_server"] = value
            elif key == "smtp_port":
                config["smtp_port"] = int(value)

    if not config["sender_email"] or not config["sender_password"]:
        raise ValueError("Incomplete email config (sender_email or sender_password missing)")

    return config


def _distribution_table_to_html(dist_table):
    """Converts a compute_distribution_table() DataFrame to an HTML table."""
    rows_html = []
    for _, row in dist_table.iterrows():
        rows_html.append(
            f"<tr>"
            f"<td style='padding:6px; border:1px solid #ddd;'>{row['home']}</td>"
            f"<td style='padding:6px; border:1px solid #ddd;'>{row['away']}</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{row['pct_1']}%</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{row['pct_X']}%</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{row['pct_2']}%</td>"
            f"</tr>"
        )
    return (
        "<table style='border-collapse:collapse; width:100%;'>"
        "<tr>"
        "<th style='padding:6px; border:1px solid #ddd;'>Hemmalag</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>Bortalag</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>1</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>X</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>2</th>"
        "</tr>"
        + "".join(rows_html) +
        "</table>"
    )


def _agreement_table_to_html(agreement_table):
    """Converts a compute_agreement_with_experts_table() DataFrame to an HTML table."""
    rows_html = []
    for _, row in agreement_table.iterrows():
        rows_html.append(
            f"<tr>"
            f"<td style='padding:6px; border:1px solid #ddd; font-weight:bold;'>{row['name']}</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:right;'>{row['agreement_pct']}%</td>"
            f"</tr>"
        )
    return "<table style='border-collapse:collapse;'>" + "".join(rows_html) + "</table>"