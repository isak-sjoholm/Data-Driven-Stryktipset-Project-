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



def build_email_html(
    game_type,
    total_combos_before,
    total_combos_after,
    expert_counts_after_filter,
    prior_tables_html,
    consensus_table_html,
    odds_implied_table_html,
    bayesian_table_html,
    method_sections,
):
    """
    Assembles the full HTML email body.

    Args:
        game_type: e.g. "Stryktipset"
        total_combos_before: int, combos before historical filtering (~1.6M)
        total_combos_after: int, combos after historical filtering
        expert_counts_after_filter: dict {player_name: count} - how many of
            each expert's expanded rows survived the historical filter
        prior_tables_html: dict {player_name: html_table_string}
        consensus_table_html: str
        odds_implied_table_html: str
        bayesian_table_html: str
        method_sections: list of dicts, each with:
            {"title": str, "stats_html": str (optional), "distribution_html": str,
             "agreement_html": str, "row_count": int}

    Returns:
        str: full HTML document
    """
    parts = [
        "<html><head><style>",
        "body { font-family: Arial, sans-serif; }",
        "h2 { color: #333; }",
        "h3 { color: #555; margin-top: 30px; border-bottom: 2px solid #ddd; padding-bottom: 5px; }",
        "h4 { color: #666; margin-top: 20px; }",
        "p { color: #444; }",
        "</style></head><body>",
        f"<h2>{game_type} - Resultat</h2>",
        f"<p>Genererat: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        "<hr>",

        "<h3>Första filtrering</h3>",
        f"<p>Startade med ca {total_combos_before:,} enkelrader.</p>",
        f"<p>Efter historisk filtrering fanns {total_combos_after:,} enkelrader kvar.</p>",
        "<p>Bland dessa fanns:</p>",
        "<ul>" + "".join(
            f"<li>{count:,} av {name}s expanderade rader kvar</li>"
            for name, count in expert_counts_after_filter.items()
        ) + "</ul>",

        "<h3>Räkna ut sannolikheter</h3>",
    ]

    for name, table_html in prior_tables_html.items():
        parts.append(f"<h4>{name}s prior</h4>")
        parts.append(table_html)

    parts.append("<h4>Konsensus-prior</h4>")
    parts.append(consensus_table_html)
    parts.append("<h4>Odds-implied sannolikheter</h4>")
    parts.append(odds_implied_table_html)
    parts.append("<h4>Bayesian-uppdaterade sannolikheter</h4>")
    parts.append(bayesian_table_html)

    for section in method_sections:
        parts.append(f"<h3>{section['title']}</h3>")
        if section.get("stats_html"):
            parts.append(section["stats_html"])
        parts.append(f"<p>{section['row_count']} rader valda.</p>")
        parts.append("<h4>Fördelning per match</h4>")
        parts.append(section["distribution_html"])
        parts.append("<h4>Agreement</h4>")
        parts.append(section["agreement_html"])

    parts.append("<hr>")
    parts.append("<p><strong>Txt-filer med enkelrader är bifogade.</strong></p>")
    parts.append("</body></html>")

    return "\n".join(parts)


def send_combined_results_email(recipient_emails, html_body, txt_attachments, subject, config_file=None):
    """
    Sends the results email via SMTP.

    Args:
        recipient_emails: str or list of str
        html_body: str, full HTML document (from build_email_html())
        txt_attachments: dict {filename: txt_content_string}
        subject: email subject line
        config_file: path to email_config.txt (default: project root)

    Returns:
        bool: True if sent successfully
    """
    config = _read_email_config(config_file)

    if isinstance(recipient_emails, str):
        recipient_emails = [recipient_emails]

    msg = MIMEMultipart()
    msg["From"] = config["sender_email"]
    msg["To"] = ", ".join(recipient_emails)
    msg["Subject"] = subject

    msg.attach(MIMEText(html_body, "html"))

    for filename, content in txt_attachments.items():
        part = MIMEBase("application", "octet-stream")
        part.set_payload(content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    try:
        server = smtplib.SMTP(config["smtp_server"], config["smtp_port"])
        server.starttls()
        server.login(config["sender_email"], config["sender_password"])
        server.send_message(msg, to_addrs=recipient_emails)
        server.quit()
        print(f"[INFO] Email sent to {', '.join(recipient_emails)} with {len(txt_attachments)} attachments")
        return True
    except Exception as e:
        print(f"[ERROR] Could not send email: {e}")
        return False