import streamlit as st
import pdfplumber
import re
import math

# ==========================================
# 1. CALCULATION LOGIC (YOUR EXACT MATH)
# ==========================================

def poisson_probability(actual, mean):
    """Calculates P(x; μ) = (e^-μ * μ^x) / x!"""
    return math.exp(-mean) * (mean**actual) / math.factorial(actual)

def calculate_xg(home_stats, away_stats, league_stats):
    """
    Returns (Home Expected Goals, Away Expected Goals)
    Uses the EXACT league averages extracted from the PDF.
    """
    # 1. Get League Averages (Fallback to 1.5/1.2 if missing)
    avg_home_goals_league = league_stats.get('avg_home_goals', 1.50)
    avg_away_goals_league = league_stats.get('avg_away_goals', 1.20)

    # Protection against zero division
    if avg_home_goals_league == 0: avg_home_goals_league = 1.50
    if avg_away_goals_league == 0: avg_away_goals_league = 1.20

    # 2. Calculate Strengths (Team Avg / League Avg)
    h_attack = home_stats['goals_scored_home_avg'] / avg_home_goals_league
    h_defense = home_stats['goals_conceded_home_avg'] / avg_away_goals_league
    
    a_attack = away_stats['goals_scored_away_avg'] / avg_away_goals_league
    a_defense = away_stats['goals_conceded_away_avg'] / avg_home_goals_league

    # 3. Calculate Lambda (Expected Goals)
    home_xg = h_attack * a_defense * avg_home_goals_league
    away_xg = a_attack * h_defense * avg_away_goals_league

    return home_xg, away_xg

def analyze_match(match, league_stats):
    """
    Runs the prediction logic for a single match object.
    Returns a dictionary of results.
    """
    # Calculate xG using the parent league's stats
    h_xg, a_xg = calculate_xg(match['home_stats'], match['away_stats'], league_stats)

    # Calculate Outcome Probabilities
    outcomes = {'home_win': 0, 'draw': 0, 'away_win': 0}
    most_likely_score = (None, 0) # (Score String, Probability)

    # Iterate through potential scores (0-0 up to 5-5)
    for i in range(6): # Home goals
        for j in range(6): # Away goals
            prob = poisson_probability(i, h_xg) * poisson_probability(j, a_xg)
            
            if i > j: outcomes['home_win'] += prob
            elif i == j: outcomes['draw'] += prob
            else: outcomes['away_win'] += prob

            if prob > most_likely_score[1]:
                most_likely_score = (f"{i}-{j}", prob)

    return {
        "league": match.get('league'),
        "home_team": match['home_team'],
        "away_team": match['away_team'],
        "home_xg": h_xg,
        "away_xg": a_xg,
        "home_prob": outcomes['home_win'] * 100,
        "draw_prob": outcomes['draw'] * 100,
        "away_prob": outcomes['away_win'] * 100,
        "top_score": most_likely_score[0],
        "top_score_pct": most_likely_score[1] * 100
    }

# ==========================================
# 2. PDF PARSING LOGIC
# ==========================================

def parse_league_header(line):
    # Pattern: Goals per match: 2.59 (1.39 at home, 1.20 away)
    stats_pattern = r"Goals per match:\s*([\d\.]+)\s*\(([\d\.]+)\s*at home,\s*([\d\.]+)\s*away\)"
    match = re.search(stats_pattern, line)
    league_name = line.split("stats")[0].strip()
    
    if match:
        return league_name, float(match.group(2)), float(match.group(3))
    return league_name, 1.50, 1.20 # Defaults

def clean_team_name(raw_name):
    # Removes time (e.g. "Blackburn 20:45" -> "Blackburn")
    return re.sub(r'\s*\d{1,2}:\d{2}$', '', raw_name).strip()

def extract_data_from_pdf(pdf_file):
    """
    Reads PDF and returns structure:
    [ { "league_stats": {...}, "fixtures": [...] }, ... ]
    """
    structured_data = []
    current_league_obj = None
    pending_home = None # Stores home team data while waiting for away line
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text: continue
            
            for line in text.split('\n'):
                line = line.strip()
                
                # 1. Detect League Header
                if "Goals per match:" in line:
                    l_name, l_home, l_away = parse_league_header(line)
                    current_league_obj = {
                        "league": l_name,
                        "league_stats": {"avg_home_goals": l_home, "avg_away_goals": l_away},
                        "fixtures": []
                    }
                    structured_data.append(current_league_obj)
                    pending_home = None
                    continue

                # 2. Detect Match Data (Look for "last [number]")
                if current_league_obj and re.search(r"\s+last\s+\d+", line):
                    parts = re.split(r"\s+last\s+\d+\s+\d+\s+", line, maxsplit=1)
                    if len(parts) < 2: continue
                    
                    team_name_raw = parts[0]
                    stats_str = parts[1].replace('%', '')
                    tokens = stats_str.split()
                    
                    if len(tokens) >= 7:
                        gf = float(tokens[5]) # Goals For
                        ga = float(tokens[6]) # Goals Against
                        
                        if pending_home is None:
                            # This is the Home Team
                            pending_home = {
                                "name": clean_team_name(team_name_raw),
                                "stats": {"goals_scored_home_avg": gf, "goals_conceded_home_avg": ga}
                            }
                        else:
                            # This is the Away Team
                            away_name = clean_team_name(team_name_raw)
                            fixture = {
                                "league": current_league_obj["league"],
                                "home_team": pending_home["name"],
                                "away_team": away_name,
                                "home_stats": pending_home["stats"],
                                "away_stats": {"goals_scored_away_avg": gf, "goals_conceded_away_avg": ga}
                            }
                            current_league_obj["fixtures"].append(fixture)
                            pending_home = None # Reset
                            
    return structured_data

# ==========================================
# 3. STREAMLIT UI & FILTERING
# ==========================================

st.set_page_config(page_title="PDF Predictor & Filter", layout="wide")

st.title("⚽ PDF Predictor & Filter")

# --- SIDEBAR UI (Matching your screenshot) ---
st.sidebar.header("Filter Criteria")

# 1. Top Score Probability
min_score_pct = st.sidebar.slider(
    "Min. Top Score Probability (%)", 
    min_value=0.0, max_value=50.0, value=0.0, step=0.5,
    help="Filter out matches where the predicted scoreline has low confidence."
)

# 2. xG Filtering Section
st.sidebar.subheader("xG (Expected Goals)")
xg_mode = st.sidebar.radio(
    "xG Filtering Mode",
    options=["Any", "Both Teams High xG", "One Team High xG", "Total Match xG"],
    index=0
)

# Show threshold slider ONLY if we aren't selecting "Any"
xg_threshold = 2.0
if xg_mode != "Any":
    xg_threshold = st.sidebar.slider("xG Threshold", 1.0, 5.0, 2.0, 0.1)

# 3. Win Confidence
st.sidebar.subheader("Win Confidence")
min_win_prob = st.sidebar.slider(
    "Min. Win Probability for either team (%)", 
    min_value=0, max_value=100, value=0
)

# --- MAIN AREA ---

uploaded_file = st.file_uploader("Upload PDF File", type="pdf")

if uploaded_file is not None:
    with st.spinner("Processing PDF and Calculating..."):
        
        # 1. Extract
        raw_leagues_data = extract_data_from_pdf(uploaded_file)
        
        # 2. Predict (Calculate all matches first)
        all_matches = []
        for league_data in raw_leagues_data:
            l_stats = league_data['league_stats']
            for fixture in league_data['fixtures']:
                prediction = analyze_match(fixture, l_stats)
                all_matches.append(prediction)
        
        # 3. Filter (Apply Sidebar Logic)
        filtered_matches = []
        
        for m in all_matches:
            # A. Check Top Score %
            if m['top_score_pct'] < min_score_pct:
                continue
                
            # B. Check Win Probability
            # (We check if either Home Prob OR Away Prob meets the requirement)
            max_win_prob = max(m['home_prob'], m['away_prob'])
            if max_win_prob < min_win_prob:
                continue
            
            # C. Check xG Logic
            keep_xg = False
            
            if xg_mode == "Any":
                keep_xg = True
            
            elif xg_mode == "Both Teams High xG":
                # Strict: Both must be >= threshold
                if m['home_xg'] >= xg_threshold and m['away_xg'] >= xg_threshold:
                    keep_xg = True
                    
            elif xg_mode == "One Team High xG":
                # Loose: At least one must be >= threshold
                if m['home_xg'] >= xg_threshold or m['away_xg'] >= xg_threshold:
                    keep_xg = True
            
            elif xg_mode == "Total Match xG":
                # Combined: Sum must be >= threshold
                if (m['home_xg'] + m['away_xg']) >= xg_threshold:
                    keep_xg = True
            
            if keep_xg:
                filtered_matches.append(m)
        
        # 4. Display
        st.divider()
        st.subheader(f"Results: {len(filtered_matches)} matches found")
        
        if not filtered_matches:
            st.warning("No matches found with current filters.")
        
        for m in filtered_matches:
            # Visual styling
            with st.container():
                col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                
                with col1:
                    st.caption(m['league'])
                    st.markdown(f"#### {m['home_team']} vs {m['away_team']}")
                
                with col2:
                    st.markdown("**Expected Goals**")
                    # Highlight green if above threshold (if threshold is active), else just display
                    h_val = f"{m['home_xg']:.2f}"
                    a_val = f"{m['away_xg']:.2f}"
                    st.write(f" {h_val} -  {a_val}")
                    
                with col3:
                    st.markdown("**Win Prob**")
                    if m['home_prob'] > m['away_prob']:
                        st.write(f" **{m['home_team']}** {m['home_prob']:.0f}%")
                    else:
                        st.write(f" **{m['away_team']}** {m['away_prob']:.0f}%")
                    st.caption(f"Draw: {m['draw_prob']:.0f}%")
                
                with col4:
                    st.markdown("**Top Score**")
                    st.info(f"{m['top_score']} ({m['top_score_pct']:.1f}%)")
                
                st.markdown("---")
