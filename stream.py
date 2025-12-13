import streamlit as st
import json
import math
import os # Keep os for potential other uses, but not directly for fixed file path

def poisson_probability(actual, mean):
    """Calculates P(x; μ) = (e^-μ * μ^x) / x!"""
    if actual < 0:
        return 0.0
    return math.exp(-mean) * (mean**actual) / math.factorial(actual)

def calculate_xg(home_stats, away_stats, league_avg_goals):
    """
    Returns (Home Expected Goals, Away Expected Goals)
    Uses the specific league average to calculate relative strengths.
    """
    avg_home_goals_league = league_avg_goals * 0.55
    avg_away_goals_league = league_avg_goals * 0.45

    # Protection against division by zero
    if avg_home_goals_league == 0: avg_home_goals_league = 1.0 # Sensible default
    if avg_away_goals_league == 0: avg_away_goals_league = 1.0 # Sensible default

    # Use .get() with a default value to prevent KeyError if a stat is missing
    h_attack = home_stats.get('goals_scored_home_avg', 0) / avg_home_goals_league
    h_defense = home_stats.get('goals_conceded_home_avg', 0) / avg_away_goals_league
    
    a_attack = away_stats.get('goals_scored_away_avg', 0) / avg_away_goals_league
    a_defense = away_stats.get('goals_conceded_away_avg', 0) / avg_home_goals_league

    home_xg = h_attack * a_defense * avg_home_goals_league
    away_xg = a_attack * h_defense * avg_away_goals_league

    return home_xg, away_xg

def process_match_for_streamlit(match):
    """Runs the prediction logic for a single match object and returns results."""
    h_team = match['home_team']
    a_team = match['away_team']
    league_code = match.get('league', 'Unknown')
    
    league_avg = match.get('league_avg_goals', 2.5) # Default to 2.5 if missing
    
    h_xg, a_xg = calculate_xg(match['home_stats'], match['away_stats'], league_avg)

    outcomes = {'home_win': 0, 'draw': 0, 'away_win': 0}
    most_likely_score = ("N/A", 0)

    # Consider goals from 0 to 5 for probability distribution
    # You can increase this range if higher scores are common in your data
    for i in range(6): 
        for j in range(6):
            prob = poisson_probability(i, h_xg) * poisson_probability(j, a_xg)
            
            if i > j: outcomes['home_win'] += prob
            elif i == j: outcomes['draw'] += prob
            else: outcomes['away_win'] += prob

            if prob > most_likely_score[1]:
                most_likely_score = (f"{i}-{j}", prob)
    
    return {
        'league': league_code,
        'home_team': h_team,
        'away_team': a_team,
        'home_xg': h_xg,
        'away_xg': a_xg,
        'home_win_prob': outcomes['home_win'],
        'draw_prob': outcomes['draw'],
        'away_win_prob': outcomes['away_win'],
        'most_likely_score': most_likely_score[0],
        'most_likely_score_prob': most_likely_score[1]
    }

def main_streamlit():
    st.set_page_config(page_title="Football Match Predictor", layout="wide")
    st.title("⚽ Football Match Predictor")
    st.markdown("---")

    st.sidebar.header("Upload Fixtures JSON")
    uploaded_file = st.sidebar.file_uploader(
        "Choose a JSON file",
        type="json",
        help="Upload a JSON file containing your match fixtures data."
    )

    fixtures = []
    if uploaded_file is not None:
        try:
            # Read the uploaded file as a string and then parse it as JSON
            file_contents = uploaded_file.read().decode("utf-8")
            data = json.loads(file_contents)
            
            fixtures = data.get('fixtures', [])
            if fixtures:
                st.sidebar.success(f"Loaded {len(fixtures)} fixtures from '{uploaded_file.name}'.")
            else:
                st.sidebar.warning(f"No 'fixtures' key found or it's empty in '{uploaded_file.name}'. Please check the JSON structure.")
        except json.JSONDecodeError:
            st.sidebar.error("Error: Failed to decode JSON. Please ensure the file is valid JSON.")
        except Exception as e:
            st.sidebar.error(f"An unexpected error occurred while reading the file: {e}")
            st.sidebar.exception(e) # Display the full traceback for debugging

    if not fixtures:
        st.info("Please upload a `fixtures.json` file in the sidebar to get started.")
        st.markdown("---")
        st.write("### Example `fixtures.json` structure:")
        st.code("""
{
  "fixtures": [
    {
      "home_team": "Team A",
      "away_team": "Team B",
      "league": "Premier League",
      "league_avg_goals": 2.7,
      "home_stats": {
        "goals_scored_home_avg": 1.8,
        "goals_conceded_home_avg": 0.9
      },
      "away_stats": {
        "goals_scored_away_avg": 1.2,
        "goals_conceded_away_avg": 1.5
      }
    }
  ]
}
        """)
        return # Stop execution if no fixtures are loaded

    st.sidebar.markdown("---")
    st.sidebar.header("Select a Match")
    
    # Create a dictionary for easy lookup and display
    # Using a unique key for each match in the selectbox, useful if team names repeat
    match_options = {
        f"{match['home_team']} vs {match['away_team']} ({match.get('league', 'Unknown')})": match 
        for i, match in enumerate(fixtures)
    }
    
    selected_match_key = st.sidebar.selectbox(
        "Choose a match to predict:",
        options=list(match_options.keys())
    )

    if selected_match_key:
        selected_match = match_options[selected_match_key]
        st.header(f"Prediction for: {selected_match['home_team']} vs {selected_match['away_team']}")
        st.subheader(f"League: {selected_match.get('league', 'Unknown')} (Avg Goals: {selected_match.get('league_avg_goals', 2.5):.2f})")

        results = process_match_for_streamlit(selected_match)

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Home Expected Goals (xG)", f"{results['home_xg']:.2f}")
        with col2:
            st.metric("Away Expected Goals (xG)", f"{results['away_xg']:.2f}")
        with col3:
            st.metric("Most Likely Score", f"{results['most_likely_score']} ({results['most_likely_score_prob']*100:.1f}%)")

        st.subheader("Match Outcome Probabilities")
        
        prob_col1, prob_col2, prob_col3 = st.columns(3)
        with prob_col1:
            st.info(f"**{results['home_team']} Win:** {results['home_win_prob']*100:.1f}%")
        with prob_col2:
            st.warning(f"**Draw:** {results['draw_prob']*100:.1f}%")
        with prob_col3:
            st.info(f"**{results['away_team']} Win:** {results['away_win_prob']*100:.1f}%")

        st.markdown("---")
        st.write("### Raw Match Data")
        st.json(selected_match)

if __name__ == "__main__":
    main_streamlit()