import json
import time



def create_placeholder_kupong(game_type="Stryktipset"):
    """
    Creates a placeholder kupong with NA values, used when no active
    matches are found for this game type (e.g. between rounds).

    Args:
        game_type: which game type this placeholder is for

    Returns:
        str: placeholder kupong string with NA values
    """
    num_matches = 13 if game_type in ["Stryktipset", "Europatipset"] else 8

    parts = []
    for i in range(1, num_matches + 1):
        part = f"Game {i}, NA, NA, 33.33, 33.33, 33.34, 3.0, 3.0, 3.0"
        parts.append(part)

    return "; ".join(parts)


def parse_extracted_data_to_kupong(extracted_data, game_type="Stryktipset"):
    """
    Parses data extracted via JavaScript (from fetch_from_svenskaspel) into
    kupong string format.

    Args:
        extracted_data: dict with matchData, teamElements, oddsElements, etc.
        game_type: which game type this data is for

    Returns:
        str or None: kupong string, or None if parsing failed
    """
    import re

    # First: try using matchData if available (preferred, structured format)
    match_data = extracted_data.get("matchData", [])

    if match_data and len(match_data) > 0:
        print(f"[INFO] Using matchData structure with {len(match_data)} matches")
        kupong_parts = []

        for i, match in enumerate(match_data):
            match_num = i + 1
            home = match.get("home", "").strip()
            away = match.get("away", "").strip()

            if not home or not away:
                continue

            odds = match.get("odds")
            if odds and len(odds) >= 3:
                o1 = odds[0].replace(",", ".")
                ox = odds[1].replace(",", ".")
                o2 = odds[2].replace(",", ".")
            else:
                o1, ox, o2 = "2.0", "3.0", "3.0"
                print(f"[WARN] No odds for match {match_num} ({home} vs {away}), using placeholder")

            sv = match.get("svenskaFolket")
            if sv and len(sv) >= 3:
                sv1 = float(sv[0])
                svx = float(sv[1])
                sv2 = float(sv[2])
            else:
                sv1, svx, sv2 = 33.0, 33.0, 34.0
                print(f"[WARN] No crowd % for match {match_num} ({home} vs {away}), using placeholder")

            part = f"Game {match_num}, {home}, {away}, {sv1}, {svx}, {sv2}, {o1}, {ox}, {o2}"
            kupong_parts.append(part)

        if kupong_parts:
            return "; ".join(kupong_parts)

    # Fallback: use the older team-pairing method if matchData isn't available
    print("[WARN] Using fallback method (matchData missing)")

    team_elements = extracted_data.get("teamElements", [])
    odds_elements = extracted_data.get("oddsElements", [])

    teams = []
    for team in team_elements:
        text = team.get("text", "").strip()
        if text and len(text) > 2:
            classes = " ".join(team.get("classes", [])).lower()
            is_home = "home" in classes
            is_away = "away" in classes
            if is_home or is_away:
                teams.append({"name": text, "is_home": is_home, "is_away": is_away})

    matches = []
    i = 0
    while i < len(teams) - 1:
        if teams[i]["is_home"]:
            j = i + 1
            while j < len(teams) and not teams[j]["is_away"]:
                j += 1
            if j < len(teams) and teams[j]["is_away"]:
                matches.append({"home": teams[i]["name"], "away": teams[j]["name"]})
                i = j + 1
                continue
            i += 1

    if not matches:
        print("[ERROR] Could not find home/away team pairs")
        return None

    print(f"[INFO] Found {len(matches)} matches (team pairs)")

    odds_sv_pairs = []
    for odds_elem in odds_elements:
        odds = None
        sv = None

        if "odds" in odds_elem and odds_elem["odds"]:
            odds = odds_elem["odds"]
        else:
            text = odds_elem.get("text", "").strip()
            odds_match = re.search(r"(\d+[,.]\d+)[\t\s\n]+(\d+[,.]\d+)[\t\s\n]+(\d+[,.]\d+)", text)
            if odds_match:
                odds = [odds_match.group(1), odds_match.group(2), odds_match.group(3)]

        if "svenskaFolket" in odds_elem and odds_elem["svenskaFolket"]:
            sv = odds_elem["svenskaFolket"]
        else:
            text = odds_elem.get("text", "").strip()
            game_type_lower = game_type.lower()
            if game_type_lower in text.lower() or "stryktipset" in text.lower():
                percents = re.findall(r"(\d+)%", text)
                if len(percents) >= 3:
                    sv = percents[:3]

        if odds and sv:
            odds_str = ",".join(odds)
            sv_str = ",".join(sv)
            if not any(p["odds_str"] == odds_str and p["sv_str"] == sv_str for p in odds_sv_pairs):
                odds_sv_pairs.append({"odds": odds, "sv": sv, "odds_str": odds_str, "sv_str": sv_str})

    print(f"[INFO] Found {len(odds_sv_pairs)} unique odds/crowd combinations")

    kupong_parts = []
    for i, match in enumerate(matches):
        match_num = i + 1

        if i < len(odds_sv_pairs):
            pair = odds_sv_pairs[i]
            odds = pair["odds"]
            sv = pair["sv"]
        elif odds_sv_pairs:
            pair = odds_sv_pairs[0]
            odds = pair["odds"]
            sv = pair["sv"]
            print(f"[WARN] Match {match_num} using first odds/crowd data (same as match 1)")
        else:
            odds = ["2.0", "3.0", "3.0"]
            sv = ["33.0", "33.0", "34.0"]
            print(f"[WARN] No odds/crowd data for match {match_num}, using placeholder")

        o1 = odds[0].replace(",", ".")
        ox = odds[1].replace(",", ".")
        o2 = odds[2].replace(",", ".")
        sv1 = float(sv[0])
        svx = float(sv[1])
        sv2 = float(sv[2])

        part = f"Game {match_num}, {match['home']}, {match['away']}, {sv1}, {svx}, {sv2}, {o1}, {ox}, {o2}"
        kupong_parts.append(part)

    return "; ".join(kupong_parts) if kupong_parts else None




def fetch_from_svenskaspel(game_type="Stryktipset"):
    """
    Fetches kupong data from Svenska Spel's website using Playwright, since
    the page loads match data dynamically via JavaScript.

    Args:
        game_type: which game type to fetch (Stryktipset, Europatipset, Topptipset)

    Returns:
        str or None: kupong string, or None if fetching failed
    """
    print(f"[INFO] Fetching {game_type} kupong from Svenska Spel (via Playwright)...")

    base_urls = {
        "Stryktipset": "https://spela.svenskaspel.se/stryktipset",
        "Europatipset": "https://spela.svenskaspel.se/europatipset",
        "Topptipset": "https://spela.svenskaspel.se/topptipset"
    }

    if game_type not in base_urls:
        print(f"[ERROR] Unknown game_type: {game_type}")
        return None

    url = base_urls[game_type]

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            print(f"[INFO] Loading page: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            print("[INFO] Waiting for JavaScript to load data...")
            time.sleep(5)

            try:
                page.wait_for_selector('[class*="match"], [class*="game"], [class*="event"]', timeout=10000)
                print("[INFO] Match elements loaded")
            except Exception:
                print("[WARN] Could not find match elements, continuing anyway...")

            html = page.content()
            print(f"[INFO] Fetched HTML after JavaScript rendering ({len(html)} bytes)")

            js_code = """
            (() => {
                const gameType = """ + f'"{game_type}"' + """;
                const data = {};

                const mainContainers = Array.from(document.querySelectorAll('[id*="match"], [id*="game"], [id*="event"]'));
                const matchLists = Array.from(document.querySelectorAll('[class*="match-list"], [class*="game-list"], [class*="event-list"]'));
                const matches = Array.from(document.querySelectorAll('[class*="matches"], [class*="games"], [class*="events"]'));
                const articles = Array.from(document.querySelectorAll('article, section, main [role="main"]'));
                for (let i = 0; i < matchLists.length; i++) { mainContainers.push(matchLists[i]); }
                for (let i = 0; i < matches.length; i++) { mainContainers.push(matches[i]); }
                for (let i = 0; i < articles.length; i++) { mainContainers.push(articles[i]); }

                let actualMatches = [];

                const allPotentialMatches = document.querySelectorAll('div, li, tr, article');

                allPotentialMatches.forEach((elem) => {
                    const text = elem.innerText || '';
                    const html = elem.outerHTML || '';

                    if (text.length < 50) return;
                    if (text.length > 5000) return;

                    const hasTeamNames = /[A-Z][a-z]+.*[A-Z][a-z]+/.test(text);
                    const hasOdds = /\\d+[.,]\\d+/.test(text);
                    const hasTime = /\\d{1,2}:\\d{2}/.test(text);
                    const hasHomeAway = /hemma|borta|home|away/i.test(text);

                    const hasMatchStructure = elem.querySelector('[class*="team"], [class*="home"], [class*="away"], [class*="odd"], [class*="odds"]');

                    if ((hasTeamNames && hasOdds) || hasMatchStructure || (hasTeamNames && hasTime)) {
                        actualMatches.push({
                            index: actualMatches.length,
                            text: text.substring(0, 500),
                            html: html.substring(0, 1000),
                            classes: Array.from(elem.classList || []),
                            id: elem.id || '',
                            hasTeamNames,
                            hasOdds,
                            hasTime,
                            hasHomeAway,
                            hasMatchStructure: !!hasMatchStructure
                        });
                    }
                });

                data.actualMatches = actualMatches.slice(0, 20);
                data.matchCount = actualMatches.length;

                data.teamElements = [];
                data.matchData = [];
                data.oddsElements = [];

                const allElements = Array.from(document.querySelectorAll('div, section, article'));
                const matchContainers = [];
                const usedMatches = new Set();

                allElements.forEach((elem) => {
                    const homeParticipant = elem.querySelector('[class*="home-participant"]');
                    const awayParticipant = elem.querySelector('[class*="away-participant"]');

                    if (homeParticipant && awayParticipant) {
                        const homeName = homeParticipant.innerText?.trim() || '';
                        const awayName = awayParticipant.innerText?.trim() || '';

                        if (homeName && awayName && homeName.length > 2 && awayName.length > 2) {
                            const matchKey = homeName + '|' + awayName;

                            if (!usedMatches.has(matchKey)) {
                                usedMatches.add(matchKey);

                                const text = elem.innerText || '';

                                let matchNum = null;
                                for (let num = 1; num <= 13; num++) {
                                    if (text.includes('match nummer ' + num) ||
                                        text.includes('match ' + num + '\\n') ||
                                        (text.includes(num.toString()) && text.includes('Tipsinformation'))) {
                                        matchNum = num;
                                        break;
                                    }
                                }

                                if (!matchNum) {
                                    matchNum = matchContainers.length + 1;
                                }

                                let searchText = text;
                                let svFallback = null;
                                let oddsResult = null;

                                if (text.length < 200) {
                                    let parent = elem.parentElement;
                                    let searchCount = 0;
                                    while (parent && searchCount < 3) {
                                        const parentText = parent.innerText || '';
                                        if (parentText.length > text.length) {
                                            searchText = parentText;
                                            break;
                                        }
                                        parent = parent.parentElement;
                                        searchCount++;
                                    }
                                }

                                const svPattern = new RegExp('Svenska folket[\\\\s\\\\S]{0,500}?(\\\\d+)%[\\\\s\\\\S]{0,100}?(\\\\d+)%[\\\\s\\\\S]{0,100}?(\\\\d+)%');
                                const svMatch = searchText.match(svPattern);
                                if (svMatch && svMatch.length >= 4) {
                                    svFallback = [svMatch[1], svMatch[2], svMatch[3]];
                                }

                                const oddsPattern1 = new RegExp('Odds[\\\\s\\\\S]{0,500}?(\\\\d+[,.]\\\\d+)[\\\\s\\\\S]{0,100}?(\\\\d+[,.]\\\\d+)[\\\\s\\\\S]{0,100}?(\\\\d+[,.]\\\\d+)');
                                const oddsMatch1 = searchText.match(oddsPattern1);
                                if (oddsMatch1 && oddsMatch1.length >= 4) {
                                    oddsResult = [oddsMatch1[1], oddsMatch1[2], oddsMatch1[3]];
                                }

                                if (!oddsResult) {
                                    const oddsPattern2 = new RegExp('(\\\\d+[,.]\\\\d+)[\\\\s\\\\n]+(\\\\d+[,.]\\\\d+)[\\\\s\\\\n]+(\\\\d+[,.]\\\\d+)');
                                    const oddsMatch2 = searchText.match(oddsPattern2);
                                    if (oddsMatch2 && oddsMatch2.length >= 4) {
                                        const o1 = parseFloat(oddsMatch2[1].replace(',', '.'));
                                        const o2 = parseFloat(oddsMatch2[2].replace(',', '.'));
                                        const o3 = parseFloat(oddsMatch2[3].replace(',', '.'));
                                        if (o1 >= 1.0 && o1 <= 20.0 && o2 >= 1.0 && o2 <= 20.0 && o3 >= 1.0 && o3 <= 20.0) {
                                            oddsResult = [oddsMatch2[1], oddsMatch2[2], oddsMatch2[3]];
                                        }
                                    }
                                }

                                matchContainers.push({
                                    container: elem,
                                    home: homeName,
                                    away: awayName,
                                    homeElem: homeParticipant,
                                    awayElem: awayParticipant,
                                    matchNumber: matchNum,
                                    oddsText: oddsResult,
                                    svText: svFallback,
                                    index: matchContainers.length
                                });
                            }
                        }
                    }
                });

                matchContainers.sort((a, b) => {
                    if (a.matchNumber && b.matchNumber && a.matchNumber !== b.matchNumber) {
                        return a.matchNumber - b.matchNumber;
                    }
                    const rectA = a.homeElem.getBoundingClientRect();
                    const rectB = b.homeElem.getBoundingClientRect();
                    return rectA.top - rectB.top || rectA.left - rectB.left;
                });

                if (matchContainers.length === 0) {
                    const allContainers = Array.from(document.querySelectorAll('div, section, article, li'));
                    const usedMatches = new Set();

                    allContainers.forEach((container) => {
                        const homeParticipant = container.querySelector('[class*="home-participant"]');
                        const awayParticipant = container.querySelector('[class*="away-participant"]');

                        if (homeParticipant && awayParticipant) {
                            const homeName = homeParticipant.innerText?.trim() || '';
                            const awayName = awayParticipant.innerText?.trim() || '';

                            if (homeName && awayName && homeName.length > 2 && awayName.length > 2) {
                                const matchKey = homeName + '|' + awayName;

                                if (!usedMatches.has(matchKey)) {
                                    usedMatches.add(matchKey);

                                    let table = container.querySelector('[class*="match_info_table"], [class*="match-info-product-odds"]');

                                    if (!table) {
                                        let sibling = container.nextElementSibling;
                                        let searchCount = 0;
                                        while (sibling && searchCount < 3) {
                                            table = sibling.querySelector('[class*="match_info_table"], [class*="match-info-product-odds"]');
                                            if (table) break;
                                            sibling = sibling.nextElementSibling;
                                            searchCount++;
                                        }
                                    }

                                    if (!table) {
                                        let parent = container.parentElement;
                                        let parentSearchCount = 0;
                                        while (parent && parentSearchCount < 2) {
                                            table = parent.querySelector('[class*="match_info_table"], [class*="match-info-product-odds"]');
                                            if (table) break;
                                            parent = parent.parentElement;
                                            parentSearchCount++;
                                        }
                                    }

                                    matchContainers.push({
                                        container: container,
                                        home: homeName,
                                        away: awayName,
                                        homeElem: homeParticipant,
                                        awayElem: awayParticipant,
                                        matchNumber: matchContainers.length + 1,
                                        oddsText: null,
                                        svText: null,
                                        table: table,
                                        index: matchContainers.length
                                    });
                                }
                            }
                        }
                    });
                }

                matchContainers.sort((a, b) => {
                    if (a.matchNumber && b.matchNumber) {
                        return a.matchNumber - b.matchNumber;
                    }
                    const rectA = a.homeElem.getBoundingClientRect();
                    const rectB = b.homeElem.getBoundingClientRect();
                    return rectA.top - rectB.top || rectA.left - rectB.left;
                });

                const allTables = Array.from(document.querySelectorAll('[class*="match_info_table"], [class*="match-info-product-odds"], [class*="odds"], [class*="betting"]'));
                const usedTables = new Set();

                if (matchContainers.length === 0) {
                    const allParticipants = Array.from(document.querySelectorAll('[class*="participant"]'));
                    const participantMatches = [];

                    allParticipants.sort((a, b) => {
                        const rectA = a.getBoundingClientRect();
                        const rectB = b.getBoundingClientRect();
                        return rectA.top - rectB.top || rectA.left - rectB.left;
                    });

                    let i = 0;
                    while (i < allParticipants.length - 1) {
                        const elem = allParticipants[i];
                        const nextElem = allParticipants[i + 1];

                        const classes = Array.from(elem.classList || []).join(' ').toLowerCase();
                        const nextClasses = Array.from(nextElem.classList || []).join(' ').toLowerCase();

                        const text = elem.innerText?.trim() || '';
                        const nextText = nextElem.innerText?.trim() || '';

                        const isHome = (classes.includes('home-participant') || classes.includes('home')) && text.length > 2;
                        const isAway = (nextClasses.includes('away-participant') || nextClasses.includes('away')) && nextText.length > 2;

                        if (isHome && isAway) {
                            const rect1 = elem.getBoundingClientRect();
                            const rect2 = nextElem.getBoundingClientRect();
                            const distance = Math.abs(rect2.top - rect1.bottom);

                            if (distance < 100) {
                                participantMatches.push({
                                    home: text,
                                    away: nextText,
                                    homeElem: elem,
                                    awayElem: nextElem,
                                    index: participantMatches.length
                                });
                                i += 2;
                                continue;
                            }
                        }
                        i++;
                    }

                    participantMatches.forEach((match) => {
                        let commonParent = match.homeElem.parentElement;
                        while (commonParent && !commonParent.contains(match.awayElem)) {
                            commonParent = commonParent.parentElement;
                        }

                        if (commonParent) {
                            const table = commonParent.querySelector('[class*="match_info_table"], [class*="match-info-product-odds"]');

                            if (table) {
                                matchContainers.push({
                                    container: commonParent,
                                    home: match.home,
                                    away: match.away,
                                    homeElem: match.homeElem,
                                    awayElem: match.awayElem,
                                    table: table,
                                    index: matchContainers.length
                                });
                            }
                        }
                    });
                }

                matchContainers.forEach((matchContainer) => {
                    let matchOdds = null;
                    let matchSv = null;

                    if (matchContainer.oddsText) {
                        matchOdds = matchContainer.oddsText;
                    }
                    if (matchContainer.svText) {
                        matchSv = matchContainer.svText;
                    }

                    if ((!matchOdds || !matchSv) && matchContainer.table) {
                        const tableText = matchContainer.table.innerText || '';

                        if (!matchOdds) {
                            const oddsMatch = tableText.match(/(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)/);
                            if (oddsMatch && oddsMatch.length >= 4) {
                                matchOdds = [oddsMatch[1], oddsMatch[2], oddsMatch[3]];
                            }
                        }

                        if (!matchSv) {
                            const gameTypeLower = gameType.toLowerCase();
                            const svPatternStr = gameTypeLower + '.*?(\\d+)%.*?(\\d+)%.*?(\\d+)%';
                            const svPattern = new RegExp(svPatternStr, 'i');
                            const svMatch = tableText.match(svPattern);
                            if (!svMatch) {
                                const svFallback = tableText.match(/(\\d+)%[\\t\\s\\n]+(\\d+)%[\\t\\s\\n]+(\\d+)%/);
                                if (svFallback && svFallback.length >= 4) {
                                    matchSv = [svFallback[1], svFallback[2], svFallback[3]];
                                }
                            } else if (svMatch.length >= 4) {
                                matchSv = [svMatch[1], svMatch[2], svMatch[3]];
                            }
                        }
                    }

                    if ((!matchOdds || !matchSv) && !matchContainer.table) {
                        const homeRect = matchContainer.homeElem.getBoundingClientRect();
                        const awayRect = matchContainer.awayElem.getBoundingClientRect();

                        let closestTable = null;
                        let minTableDistance = Infinity;
                        let closestTableIdx = -1;

                        allTables.forEach((t, tIdx) => {
                            if (usedTables.has(tIdx)) return;

                            const tableRect = t.getBoundingClientRect();
                            if (tableRect.top >= homeRect.top - 100) {
                                const distanceFromAway = Math.abs(tableRect.top - awayRect.bottom);
                                const distanceFromHome = Math.abs(tableRect.top - homeRect.bottom);
                                const distance = Math.min(distanceFromAway, distanceFromHome);

                                if (distance < minTableDistance && distance < 800) {
                                    minTableDistance = distance;
                                    closestTable = t;
                                    closestTableIdx = tIdx;
                                }
                            }
                        });

                        if (closestTable) {
                            matchContainer.table = closestTable;
                            usedTables.add(closestTableIdx);

                            const tableText = closestTable.innerText || '';
                            if (!matchOdds) {
                                const oddsMatch = tableText.match(/(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)/);
                                if (oddsMatch && oddsMatch.length >= 4) {
                                    matchOdds = [oddsMatch[1], oddsMatch[2], oddsMatch[3]];
                                }
                            }
                            if (!matchSv) {
                                const gameTypeLower = gameType.toLowerCase();
                                const svPattern = new RegExp(gameTypeLower + '[\\\\s\\\\S]*?(\\\\d+)%[\\\\t\\\\s\\\\n]+(\\\\d+)%[\\\\t\\\\s\\\\n]+(\\\\d+)%', 'i');
                                const svMatch = tableText.match(svPattern);
                                if (!svMatch) {
                                    const svFallback = tableText.match(/(\\d+)%[\\t\\s\\n]+(\\d+)%[\\t\\s\\n]+(\\d+)%/);
                                    if (svFallback && svFallback.length >= 4) {
                                        matchSv = [svFallback[1], svFallback[2], svFallback[3]];
                                    }
                                } else if (svMatch.length >= 4) {
                                    matchSv = [svMatch[1], svMatch[2], svMatch[3]];
                                }
                            }
                        }
                    }

                    data.matchData.push({
                        home: matchContainer.home,
                        away: matchContainer.away,
                        odds: matchOdds,
                        svenskaFolket: matchSv,
                        index: matchContainer.index
                    });

                    if (matchOdds || matchSv) {
                        data.oddsElements.push({
                            odds: matchOdds,
                            svenskaFolket: matchSv,
                            text: matchContainer.home + ' vs ' + matchContainer.away,
                            classes: []
                        });
                    }

                    data.teamElements.push({text: matchContainer.home, classes: []});
                    data.teamElements.push({text: matchContainer.away, classes: []});
                });

                if (data.matchData.length === 0) {
                    const teamElements = document.querySelectorAll('[class*="participant"], [class*="home-participant"], [class*="away-participant"]');
                    const oddsTables = document.querySelectorAll('[class*="match-info-product-odds"], [class*="match_info_table"]');

                    teamElements.forEach((elem) => {
                        const text = elem.innerText?.trim();
                        if (text && text.length > 2) {
                            data.teamElements.push({
                                text: text.substring(0, 50),
                                classes: Array.from(elem.classList || [])
                            });
                        }
                    });

                    oddsTables.forEach((table) => {
                        const text = table.innerText || '';
                        const oddsMatch = text.match(/(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)[\\t\\s\\n]+(\\d+[,.]\\d+)/);
                        const svMatch = text.match(/(\\d+)%[\\t\\s\\n]+(\\d+)%[\\t\\s\\n]+(\\d+)%/);

                        const matchData = {
                            text: text.substring(0, 300),
                            classes: Array.from(table.classList || []),
                            odds: null,
                            svenskaFolket: null
                        };

                        if (oddsMatch && oddsMatch.length >= 4) {
                            matchData.odds = [oddsMatch[1], oddsMatch[2], oddsMatch[3]];
                        }

                        if (svMatch && svMatch.length >= 4) {
                            matchData.svenskaFolket = [svMatch[1], svMatch[2], svMatch[3]];
                            if (text.toLowerCase().includes('europatipset') || text.toLowerCase().includes('svensk')) {
                                matchData.isEuropatipset = true;
                            }
                        }

                        if (matchData.odds || matchData.svenskaFolket) {
                            data.oddsElements.push(matchData);
                        }
                    });
                }

                if (data.oddsElements.length === 0) {
                    const allOddsElements = document.querySelectorAll('[class*="odd"], [class*="odds"], [class*="price"], [class*="betting"]');
                    allOddsElements.forEach((elem, idx) => {
                        if (idx < 30) {
                            data.oddsElements.push({
                                text: elem.innerText?.trim().substring(0, 50),
                                classes: Array.from(elem.classList || [])
                            });
                        }
                    });
                }

                return data;
            })();
            """

            extracted_data = None
            try:
                extracted_data = page.evaluate(js_code)
                print(f"[INFO] Extracted data via JavaScript:")
                print(f"   - Match elements: {extracted_data.get('matchCount', 0)}")
                print(f"   - Odds elements: {len(extracted_data.get('oddsElements', []))}")
                print(f"   - Team elements: {len(extracted_data.get('teamElements', []))}")

                with open("match_debug_data.json", "w", encoding="utf-8") as f:
                    json.dump(extracted_data, f, indent=2, ensure_ascii=False)
                print(f"[INFO] Saved match data to 'match_debug_data.json'")

            except Exception as e:
                print(f"[WARN] Could not run JavaScript: {e}")

            browser.close()

            if extracted_data and (extracted_data.get("teamElements") or extracted_data.get("actualMatches")):
                print("[INFO] Attempting to build kupong from extracted data...")
                kupong = parse_extracted_data_to_kupong(extracted_data, game_type)
                if kupong:
                    print(f"[INFO] Built kupong with {len(kupong.split(';'))} matches!")
                    return kupong
                else:
                    print("[WARN] Could not build complete kupong from data")
                    team_count = len(extracted_data.get("teamElements", []))
                    if team_count == 0:
                        print("[INFO] No active matches found for this game type (likely closed or no matches now)")
                        return create_placeholder_kupong(game_type)

            print("[WARN] No match data could be extracted")
            return create_placeholder_kupong(game_type)

    except ImportError:
        print("[ERROR] Playwright not installed. Install with: pip install playwright && playwright install chromium")
        return None
    except Exception as e:
        print(f"[ERROR] Error fetching from Svenska Spel: {e}")
        import traceback
        traceback.print_exc()
        return None