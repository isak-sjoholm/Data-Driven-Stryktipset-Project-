"""
email_sender.py
---------------
Builds and sends the results email: filtering summary, probability
breakdown (individual priors -> consensus -> odds-implied -> Bayesian
update), then one section per ranking method (agreement, payout, value)
with explanatory text, stats, a distribution table, an agreement table,
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


def _probability_table_to_html(df, prob_cols):
    """
    Renders a probability table (per-match 1/X/2 probabilities) as HTML,
    with columns Match, Hemmalag, Bortalag, 1, X, 2 - probabilities shown
    as whole-number percentages.

    Args:
        df: DataFrame with columns match_nr, home, away, plus the three
            probability columns named in prob_cols
        prob_cols: tuple of 3 column names in the df, in order (p1, pX, p2)

    Returns:
        str: HTML table
    """
    p1_col, pX_col, p2_col = prob_cols
    rows_html = []
    for _, row in df.iterrows():
        rows_html.append(
            f"<tr>"
            f"<td style='padding:6px; border:1px solid #ddd;'>{int(row['match_nr'])}</td>"
            f"<td style='padding:6px; border:1px solid #ddd;'>{row['home']}</td>"
            f"<td style='padding:6px; border:1px solid #ddd;'>{row['away']}</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{round(row[p1_col]*100)}%</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{round(row[pX_col]*100)}%</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:center;'>{round(row[p2_col]*100)}%</td>"
            f"</tr>"
        )
    return (
        "<table style='border-collapse:collapse; width:100%;'>"
        "<tr>"
        "<th style='padding:6px; border:1px solid #ddd;'>Match</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>Hemmalag</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>Bortalag</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>1</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>X</th>"
        "<th style='padding:6px; border:1px solid #ddd;'>2</th>"
        "</tr>"
        + "".join(rows_html) +
        "</table>"
    )


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


def _agreement_table_to_html(agreement_table, dropout_explanations=None):
    """
    Converts a compute_agreement_with_experts_table() DataFrame to an HTML
    table, with an optional explanatory line under each expert's row
    describing why their rows didn't make the top-N (not shown for
    Svenska Folket, which has no dropout breakdown).

    Args:
        agreement_table: DataFrame with columns name, agreement_pct
        dropout_explanations: dict {player_name: explanation string},
            from compute_expert_dropout_breakdown() - optional
    """
    rows_html = []
    for _, row in agreement_table.iterrows():
        name = row["name"]
        rows_html.append(
            f"<tr>"
            f"<td style='padding:6px; border:1px solid #ddd; font-weight:bold;'>{name}</td>"
            f"<td style='padding:6px; border:1px solid #ddd; text-align:right;'>{row['agreement_pct']}%</td>"
            f"</tr>"
        )
        if dropout_explanations and name in dropout_explanations and dropout_explanations[name]:
            rows_html.append(
                f"<tr>"
                f"<td colspan='2' style='padding:4px 6px 12px 6px; border-left:1px solid #ddd; border-right:1px solid #ddd; font-size:12px; color:#777; font-style:italic;'>"
                f"{dropout_explanations[name]}"
                f"</td>"
                f"</tr>"
            )

    return "<table style='border-collapse:collapse; width:100%;'>" + "".join(rows_html) + "</table>"

def _stats_to_html(stats):
    """Renders the P(13 rätt) / mean payout / payout range stats as an HTML list."""
    return (
        "<ul>"
        f"<li>Sannolikhet för 13 rätt: {stats['prob_13']*100:.3f}%</li>"
        f"<li>Snitt utdelning vid 13 rätt: {stats['mean_payout']:,.0f} kr</li>"
        f"<li>Intervall utdelning vid 13 rätt: {stats['min_payout']:,.0f} - {stats['max_payout']:,.0f} kr</li>"
        "</ul>"
    )


def build_email_html(
    game_type,
    total_combos_before,
    filter_descriptions,
    total_combos_after,
    expert_counts_after_filter,
    prior_tables,
    consensus_df,
    odds_implied_df,
    bayesian_df,
    method1,
    method2,
    method3,
):
    """
    Assembles the full HTML email body.

    Args:
        game_type: e.g. "Stryktipset"
        total_combos_before: int, combos before historical filtering
        filter_descriptions: list of str, from describe_applied_filters()
        total_combos_after: int, combos after historical filtering
        expert_counts_after_filter: dict {player_name: count}
        prior_tables: dict {player_name: DataFrame} (match_nr, home, away, p1, pX, p2)
        consensus_df: DataFrame (match_nr, home, away, prior1, priorX, prior2)
        odds_implied_df: DataFrame (match_nr, home, away, imp1, impx, imp2)
        bayesian_df: DataFrame (match_nr, home, away, imp1, impx, imp2)
        method1: dict with keys: row_count, distribution_df, agreement_df, stats
        method2: dict with keys: min_payout, remaining_count, row_count,
            distribution_df, agreement_df, stats
        method3: dict with keys: min_probability, remaining_count, row_count,
            distribution_df, agreement_df, stats

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
        f"<p>Startade med alla möjliga {total_combos_before:,} enkelrader.</p>",
        "<ul>" + "".join(f"<li>{desc}</li>" for desc in filter_descriptions) + "</ul>",
        f"<p>Efter filtreringen fanns {total_combos_after:,} enkelrader kvar.</p>",
        "<p>Bland dessa fanns:</p>",
        "<ul>" + "".join(
            f"<li>{count:,} av {name}s enkelrader kvar</li>"
            for name, count in expert_counts_after_filter.items()
        ) + "</ul>",

        "<h3>Räkna ut sannolikheter</h3>",
        "<p>För Isak, Ludde och Fredde räknades deras implied sannolikheter ut för varje match baserat på deras val:</p>",
    ]

    for name, df in prior_tables.items():
        parts.append(f"<h4>{name}:</h4>")
        parts.append(_probability_table_to_html(df, ("p1", "pX", "p2")))

    parts.append("<p>Sedan kombineras dessa till gemensamma sannolikheter baserat på hur mycket de håller med varandra, vem som är mest säker (spikar), osv:</p>")
    parts.append("<h4>Gemensamma sannolikheter:</h4>")
    parts.append(_probability_table_to_html(consensus_df, ("prior1", "priorX", "prior2")))

    parts.append('<p>Givet matchernas odds räknades dessa "objektiva" sannolikheter ut för varje match:</p>')
    parts.append("<h4>Sannolikheter enligt oddsmarknaden:</h4>")
    parts.append(_probability_table_to_html(odds_implied_df, ("imp1", "impx", "imp2")))

    parts.append("<p>Med Isak, Ludde, och Freddes input justerades dessa sannolikheter för varje match till:</p>")
    parts.append("<h4>Sannolikheter enligt oddsmarknaden + Ludde/Fredde/Isak:</h4>")
    parts.append(_probability_table_to_html(bayesian_df, ("imp1", "impx", "imp2")))

    # METHOD 1
    parts.append("<h3>Metod 1: Agreement</h3>")
    parts.append(f"<p>Av de {total_combos_after:,} enkelraderna som blev kvar efter filtreringen rankas dom efter:</p>")
    parts.append(
        "<ol>"
        "<li>Hur många av enkelradens tecken som Isak, Ludde, och Fredde har med på sina kuponger</li>"
        "<li>Om lika, hur säkra Isak, Ludde, och Fredde var (mer spikad & mindre garderad = mer säkra = rankas högre)</li>"
        "<li>Om lika, störst sannolikhet enligt odds</li>"
        "</ol>"
    )
    parts.append("<p>Dvs, denna metod bortser från sannolikheter, odds, och spelvärde och väljer bara för att det ska bli så jämnt som möjligt mellan Isak, Ludde, och Fredde.</p>")
    parts.append(_stats_to_html(method1["stats"]))
    parts.append("<p>Det resulterade i:</p>")
    parts.append(_distribution_table_to_html(method1["distribution_df"]))
    parts.append("<h4>Agreement</h4>")
    parts.append(_agreement_table_to_html(method1["agreement_df"], method1.get("dropout_explanations")))
    
    # METHOD 2
    parts.append("<h3>Metod 2: Förväntad utdelning</h3>")
    parts.append(
        f"<p>Av de {total_combos_after:,} enkelraderna som blev kvar efter filtreringen så räknades förväntade "
        f"utdelningen ut för varje rad, givet att den får 13 rätt. Alla rader som förväntas ge mindre än "
        f"{method2['min_payout']:,.0f} kr plockades bort. Då fanns {method2['remaining_count']:,} enkelrader kvar.</p>"
    )
    parts.append("<p>De enkelraderna rankades efter:</p>")
    parts.append(
        "<ol>"
        "<li>Sannolikhet enligt den kombinerade sannolikheten mellan \"objektiva\" sannolikheter och sannolikheterna enligt Isak, Ludde och Freddes kuponger.</li>"
        "</ol>"
    )
    parts.append(
        f"<p>Dvs, denna metod tar hänsyn till sannolikheter givet oddsmarknaden och Isak, Ludde, och Freddes val "
        f"för att maximera chansen på 13 rätt om 13 rätt ger &gt; {method2['min_payout']:,.0f} kr.</p>"
    )
    parts.append(_stats_to_html(method2["stats"]))
    parts.append("<p>Det resulterade i:</p>")
    parts.append(_distribution_table_to_html(method2["distribution_df"]))
    parts.append("<h4>Agreement</h4>")
    parts.append(_agreement_table_to_html(method2["agreement_df"], method2.get("dropout_explanations")))    
    
    
    # METHOD 3
    parts.append("<h3>Metod 3: Spelvärde</h3>")
    parts.append(
        f"<p>Av de {total_combos_after:,} enkelraderna som blev kvar efter filtreringen så räknades spelvärdet ut "
        f"för varje rad som: Förväntad vinst = (sannolikhet för 13 rätt × förväntad vinst vid 13 rätt) − "
        f"(sannolikhet för mindre än 13 rätt × förlora). Alla enkelrader som förväntas få 13 rätt mer sällan än "
        f"{method3['min_probability']*100:.3f}% av gångerna plockades bort. Då fanns {method3['remaining_count']:,} enkelrader kvar.</p>"
    )
    parts.append("<p>De enkelraderna rankades efter den förväntade vinsten.</p>")
    parts.append(
        "<p>Dvs, denna metod tar hänsyn till sannolikheter givet oddsmarknaden och Isak, Ludde, och Freddes val "
        "OCH spelvärde för att maximera chansen att vinna mycket pengar.</p>"
    )
    parts.append(_stats_to_html(method3["stats"]))
    parts.append("<p>Det resulterade i:</p>")
    parts.append(_distribution_table_to_html(method3["distribution_df"]))
    parts.append("<h4>Agreement</h4>")
    parts.append(_agreement_table_to_html(method3["agreement_df"], method3.get("dropout_explanations")))
    
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



def send_reminder_email(recipient_emails, config_file=None):
    """
    Sends a reminder email asking experts to fill in their Stryktipset
    coupon, with a link to the Lovable input app.

    Args:
        recipient_emails: list of str (or single str)
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
    msg["Subject"] = f"Påminnelse: Fyll i din Stryktipset-kupong - {datetime.now().strftime('%Y-%m-%d')}"

    html_body = f"""
    <html>
    <head>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                line-height: 1.6;
                color: #2c3e50;
                margin: 0;
                padding: 0;
                background-color: #f5f5f5;
            }}
            .container {{
                max-width: 600px;
                margin: 40px auto;
                background-color: #ffffff;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px 20px;
                text-align: center;
            }}
            .header h1 {{
                margin: 0;
                font-size: 24px;
                font-weight: 600;
            }}
            .content {{
                padding: 40px 30px;
            }}
            .game-type {{
                text-align: center;
                font-size: 20px;
                font-weight: 600;
                color: #667eea;
                margin: 0 0 30px 0;
                padding-bottom: 20px;
                border-bottom: 2px solid #e8e8e8;
            }}
            .text {{
                color: #555;
                font-size: 16px;
                margin: 20px 0;
            }}
            .button-container {{
                text-align: center;
                margin: 30px 0;
            }}
            .button {{
                display: inline-block;
                padding: 14px 32px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 600;
                font-size: 16px;
                box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);
            }}
            .reminder {{
                background-color: #f8f9fa;
                border-left: 4px solid #667eea;
                padding: 20px;
                margin: 30px 0;
                border-radius: 4px;
            }}
            .reminder strong {{
                color: #667eea;
                display: block;
                margin-bottom: 12px;
                font-size: 15px;
            }}
            .reminder ul {{
                margin: 10px 0 0 0;
                padding-left: 20px;
                color: #555;
            }}
            .reminder li {{
                margin: 8px 0;
            }}
            .footer {{
                margin-top: 40px;
                padding-top: 20px;
                border-top: 1px solid #e8e8e8;
                text-align: center;
                color: #999;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Påminnelse</h1>
            </div>
            <div class="content">
                <div class="game-type">Stryktipset</div>

                <p class="text">Hej!</p>
                <p class="text">Det är dags att fylla i din Stryktipset-kupong för denna vecka.</p>

                <div class="button-container">
                    <a href="https://striktips-prior-probes.lovable.app" class="button">
                        Fyll i din kupong här
                    </a>
                </div>

                <div class="reminder">
                    <strong>Viktigt att komma ihåg:</strong>
                    <ul>
                        <li><strong>5 halvgarderingar</strong> (t.ex. 1X, X2, 12)</li>
                        <li><strong>2 helgardering</strong> (t.ex. 1, X, 2)</li>
                    </ul>
                </div>

                <p class="text" style="text-align: center; margin-top: 30px;">Lycka till!</p>

                <div class="footer">
                    Automatiskt påminnelsemail
                </div>
            </div>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP(config["smtp_server"], config["smtp_port"])
        server.starttls()
        server.login(config["sender_email"], config["sender_password"])
        server.send_message(msg, to_addrs=recipient_emails)
        server.quit()
        print(f"[INFO] Reminder email sent to {', '.join(recipient_emails)}")
        return True
    except Exception as e:
        print(f"[ERROR] Could not send reminder email: {e}")
        return False