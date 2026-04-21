#!/usr/bin/env python3
import itertools
import json
import math
import os
import random
from flask import Flask, render_template_string, request

app = Flask(__name__)
DATA_FILE = os.path.join(os.path.dirname(__file__), "golf_data.json")
MAX_PLAYERS = 20
BRUTE_FORCE_LIMIT = 500_000


# ── Data ──────────────────────────────────────────────────────────────────────

def default_data():
    return {
        "settings": {
            "num_players": 8, "num_teams": 2,
            "course_name": "", "par": 72,
            "course_rating": 72.0, "slope": 113,
        },
        "players": [{"name": f"Player {i+1}", "handicap_index": 0.0} for i in range(MAX_PLAYERS)],
    }


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                d = json.load(f)
            while len(d["players"]) < MAX_PLAYERS:
                n = len(d["players"])
                d["players"].append({"name": f"Player {n+1}", "handicap_index": 0.0})
            for k, v in default_data()["settings"].items():
                d["settings"].setdefault(k, v)
            return d
        except Exception:
            pass
    return default_data()


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def calc_course_hcp(index, slope, rating, par):
    return index * (slope / 113.0) + (rating - par)


def fmt_num(v):
    if isinstance(v, (int, float)) and v == int(v):
        return str(int(v))
    return f"{v:.1f}"


app.jinja_env.filters["fmt_num"] = fmt_num


# ── Algorithms ────────────────────────────────────────────────────────────────

def partition_diff(partition, hcps):
    totals = [sum(hcps[i] for i in t) for t in partition]
    return max(totals) - min(totals)


def iter_partitions(indices, ts, k):
    if k == 1:
        yield (tuple(indices),)
        return
    anchor, rest = indices[0], indices[1:]
    for combo in itertools.combinations(rest, ts - 1):
        combo_set = set(combo)
        team = (anchor,) + combo
        remaining = [x for x in rest if x not in combo_set]
        for sub in iter_partitions(remaining, ts, k - 1):
            yield (team,) + sub


def est_partitions(n, k, ts):
    if k <= 1:
        return 1
    return math.comb(n - 1, ts - 1) * est_partitions(n - ts, k - 1, ts)


def brute_force(hcps, k):
    ts = len(hcps) // k
    best, best_d = None, float("inf")
    for part in iter_partitions(list(range(len(hcps))), ts, k):
        d = partition_diff(part, hcps)
        if d < best_d:
            best_d, best = d, part
    return best, best_d


def local_search(teams, hcps, k):
    teams = [list(t) for t in teams]
    cur = partition_diff(teams, hcps)
    improved = True
    while improved:
        improved = False
        for i in range(k):
            for j in range(i + 1, k):
                for a in range(len(teams[i])):
                    for b in range(len(teams[j])):
                        teams[i][a], teams[j][b] = teams[j][b], teams[i][a]
                        d = partition_diff(teams, hcps)
                        if d < cur:
                            cur = d
                            improved = True
                        else:
                            teams[i][a], teams[j][b] = teams[j][b], teams[i][a]
    return [tuple(t) for t in teams], cur


def snake_draft(hcps, k):
    order = sorted(range(len(hcps)), key=lambda i: hcps[i], reverse=True)
    teams = [[] for _ in range(k)]
    direction, t = 1, 0
    for idx in order:
        teams[t].append(idx)
        t += direction
        if t == k:
            t, direction = k - 1, -1
        elif t == -1:
            t, direction = 0, 1
    return teams


def heuristic(hcps, k, restarts=300):
    n, ts = len(hcps), len(hcps) // k
    best_teams, best_d = None, float("inf")
    teams, d = local_search(snake_draft(hcps, k), hcps, k)
    if d < best_d:
        best_d, best_teams = d, teams
    indices = list(range(n))
    for _ in range(restarts):
        if best_d == 0:
            break
        random.shuffle(indices)
        init = [indices[i * ts:(i + 1) * ts] for i in range(k)]
        teams, d = local_search(init, hcps, k)
        if d < best_d:
            best_d, best_teams = d, teams
    return best_teams, best_d


def find_best_split(hcps, k):
    n, ts = len(hcps), len(hcps) // k
    est = est_partitions(n, k, ts)
    if est <= BRUTE_FORCE_LIMIT:
        part, diff = brute_force(hcps, k)
        method = "exact"
    else:
        part, diff = heuristic(hcps, k)
        method = "heuristic"
    return part, diff, method


# ── Route ─────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    data = load_data()
    error = None
    results = None

    if request.method == "POST":
        s = data["settings"]
        s["course_name"] = request.form.get("course_name", "").strip()
        try:
            s["num_players"] = max(2, min(MAX_PLAYERS, int(request.form.get("num_players", 8))))
            s["num_teams"] = max(2, min(10, int(request.form.get("num_teams", 2))))
            s["par"] = int(request.form.get("par", 72))
            s["course_rating"] = float(request.form.get("course_rating", 72.0))
            s["slope"] = int(request.form.get("slope", 113))
        except ValueError:
            error = "Please enter valid numbers for all course settings."

        for i in range(MAX_PLAYERS):
            data["players"][i]["name"] = (
                request.form.get(f"name_{i}", f"Player {i+1}").strip() or f"Player {i+1}"
            )
            try:
                data["players"][i]["handicap_index"] = float(request.form.get(f"hcp_{i}", 0))
            except ValueError:
                data["players"][i]["handicap_index"] = 0.0

        if not error:
            np_, nt = s["num_players"], s["num_teams"]
            if np_ % nt != 0:
                error = (
                    f"{np_} players can't be evenly split into {nt} teams. "
                    f"Choose a player count divisible by {nt} (e.g. {nt * (np_ // nt)} or {nt * (np_ // nt + 1)})."
                )

        if not error:
            save_data(data)
            active = data["players"][:s["num_players"]]
            course_hcps = [
                calc_course_hcp(p["handicap_index"], s["slope"], s["course_rating"], s["par"])
                for p in active
            ]
            partition, diff, method = find_best_split(course_hcps, s["num_teams"])
            teams_out = []
            for team_indices in partition:
                players_out = sorted(
                    [
                        {
                            "name": active[i]["name"],
                            "hcp_index": active[i]["handicap_index"],
                            "course_hcp": course_hcps[i],
                        }
                        for i in team_indices
                    ],
                    key=lambda p: p["course_hcp"],
                    reverse=True,
                )
                teams_out.append({
                    "players": players_out,
                    "total": sum(course_hcps[i] for i in team_indices),
                })
            teams_out.sort(key=lambda t: t["total"], reverse=True)
            for n_i, t in enumerate(teams_out):
                t["label"] = f"Team {n_i + 1}"
            results = {"teams": teams_out, "diff": diff, "method": method}

    return render_template_string(
        HTML, data=data, results=results, error=error, max_players=MAX_PLAYERS
    )


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Golf Team Splitter</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f0f4f0;
      color: #1a2e1a;
      min-height: 100vh;
      padding: 2rem 1rem 3rem;
    }
    h1 { text-align: center; font-size: 1.8rem; color: #2d5a27; margin-bottom: 0.25rem; }
    .subtitle { text-align: center; color: #6b8c63; margin-bottom: 2rem; font-size: 0.9rem; }

    .card {
      background: white;
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.07);
      padding: 1.25rem 1.5rem;
      max-width: 620px;
      margin: 0 auto 1.25rem;
    }
    .card-title {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: #9ab892;
      font-weight: 600;
      margin-bottom: 1rem;
    }

    label { display: block; font-size: 0.75rem; color: #6b8c63; margin-bottom: 0.2rem; font-weight: 500; }
    input[type="text"], input[type="number"], select {
      width: 100%;
      padding: 0.45rem 0.65rem;
      border: 1.5px solid #d0ddc8;
      border-radius: 8px;
      font-size: 0.9rem;
      color: #1a2e1a;
      background: #fafffe;
      transition: border-color 0.15s;
    }
    input:focus, select:focus { outline: none; border-color: #4a8a3e; }

    .settings-grid {
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 0.75rem;
    }
    .span-full { grid-column: 1 / -1; }
    .span-2 { grid-column: span 2; }

    .warn-text {
      font-size: 0.78rem;
      color: #a05000;
      padding: 0.15rem 0;
    }

    .player-table { width: 100%; border-collapse: collapse; }
    .player-table th {
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: #9ab892;
      font-weight: 600;
      padding: 0 0.4rem 0.5rem;
      text-align: left;
    }
    .player-table th.right { text-align: right; }
    .player-table td { padding: 0.15rem 0.25rem; }
    .num-col { width: 26px; color: #b0c8a8; font-size: 0.78rem; padding-top: 0.5rem !important; text-align: right; padding-right: 0.5rem !important; }
    .hcp-col { width: 88px; }
    .hcp-col input { text-align: center; }

    .submit-btn {
      display: block;
      width: 100%;
      max-width: 620px;
      margin: 0 auto 1.5rem;
      padding: 0.8rem;
      background: #2d5a27;
      color: white;
      border: none;
      border-radius: 10px;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }
    .submit-btn:hover { background: #3d7835; }

    .error-box {
      background: #fff4f4;
      border: 1.5px solid #dfa0a0;
      border-radius: 10px;
      padding: 0.75rem 1rem;
      color: #8b2020;
      max-width: 620px;
      margin: 0 auto 1.25rem;
      font-size: 0.88rem;
    }

    /* Results */
    .results { max-width: 620px; margin: 0 auto; }
    .course-meta {
      text-align: center;
      font-size: 0.75rem;
      color: #9ab892;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      margin-bottom: 1rem;
    }
    .teams-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .team-card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); overflow: hidden; }
    .team-header {
      padding: 0.6rem 1rem;
      font-weight: 700;
      font-size: 0.82rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: white;
    }
    .team-header .team-ttl { font-weight: 400; font-size: 0.78rem; opacity: 0.85; }

    .result-row {
      display: grid;
      grid-template-columns: 1fr 44px 44px;
      gap: 0.25rem;
      padding: 0.28rem 1rem;
      font-size: 0.86rem;
      border-bottom: 1px solid #f0f4f0;
      align-items: center;
    }
    .result-row:last-child { border-bottom: none; }
    .result-row .idx { color: #b0c8a8; font-size: 0.75rem; text-align: right; }
    .result-row .chcp { font-weight: 600; color: #2d5a27; text-align: right; }

    .col-labels {
      display: grid;
      grid-template-columns: 1fr 44px 44px;
      gap: 0.25rem;
      padding: 0.2rem 1rem 0;
      font-size: 0.67rem;
      color: #b0c8a8;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .col-labels span { text-align: right; }
    .col-labels span:first-child { text-align: left; }

    .team-footer {
      background: #f0f4f0;
      padding: 0.45rem 1rem;
      display: flex;
      justify-content: space-between;
      font-weight: 700;
      font-size: 0.85rem;
      border-top: 2px solid #d8e8d0;
      color: #2d5a27;
    }

    .diff-card {
      background: white;
      border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.07);
      padding: 1rem 1.5rem;
      text-align: center;
    }
    .diff-label { font-size: 0.72rem; color: #9ab892; text-transform: uppercase; letter-spacing: 0.09em; }
    .diff-value { font-size: 2.4rem; font-weight: 800; color: #2d5a27; line-height: 1.2; }
    .diff-sub { font-size: 0.78rem; color: #9ab892; margin-top: 0.15rem; }
  </style>
</head>
<body>
  <h1>⛳ Golf Team Splitter</h1>
  <p class="subtitle">Calculates course handicaps and finds the fairest team split</p>

  <form method="POST" action="/">

    <div class="card">
      <p class="card-title">Course &amp; Game Settings</p>
      <div class="settings-grid">

        <div class="span-full">
          <label for="course_name">Course Name (optional)</label>
          <input type="text" id="course_name" name="course_name"
                 value="{{ data.settings.course_name }}" placeholder="e.g. Pebble Beach">
        </div>

        <div>
          <label for="par">Par</label>
          <input type="number" id="par" name="par"
                 value="{{ data.settings.par }}" min="60" max="80" step="1" required>
        </div>
        <div>
          <label for="course_rating">Course Rating</label>
          <input type="number" id="course_rating" name="course_rating"
                 value="{{ data.settings.course_rating }}" min="50" max="90" step="0.1" required>
        </div>
        <div>
          <label for="slope">Slope Rating</label>
          <input type="number" id="slope" name="slope"
                 value="{{ data.settings.slope }}" min="55" max="155" step="1" required>
        </div>

        <div>
          <label for="num_players">Players</label>
          <select id="num_players" name="num_players" onchange="onSettingsChange()">
            {% for n in range(2, max_players + 1) %}
            <option value="{{ n }}"{{ ' selected' if data.settings.num_players == n }}>{{ n }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label for="num_teams">Teams</label>
          <input type="number" id="num_teams" name="num_teams"
                 value="{{ data.settings.num_teams }}" min="2" max="10" step="1"
                 required oninput="onSettingsChange()">
        </div>
        <div style="display:flex;align-items:flex-end">
          <p id="div-warn" class="warn-text" style="display:none">
            Players must divide evenly into teams.
          </p>
        </div>

      </div>
      <p style="font-size:0.72rem;color:#b0c8a8;margin-top:0.9rem">
        Course Handicap = Handicap Index &times; (Slope &divide; 113) + (Course Rating &minus; Par)
      </p>
    </div>

    <div class="card">
      <p class="card-title">Players &amp; Handicap Indexes</p>
      <table class="player-table">
        <thead>
          <tr>
            <th></th>
            <th>Name</th>
            <th class="right" style="padding-right:0.65rem">HCP Index</th>
          </tr>
        </thead>
        <tbody>
          {% for i in range(max_players) %}
          <tr id="row-{{ i }}"{{ ' style="display:none"' if i >= data.settings.num_players }}>
            <td class="num-col">{{ i + 1 }}</td>
            <td>
              <input type="text" name="name_{{ i }}"
                     value="{{ data.players[i].name }}" placeholder="Player {{ i+1 }}">
            </td>
            <td class="hcp-col">
              <input type="number" name="hcp_{{ i }}"
                     value="{{ data.players[i].handicap_index }}"
                     step="0.1" min="-10" max="54">
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <button type="submit" class="submit-btn">Calculate Fairest Teams</button>
  </form>

  {% if error %}
  <div class="error-box">{{ error }}</div>
  {% endif %}

  {% if results %}
  {% set team_colors = ['#2d5a27','#1a4a6b','#7a4010','#4a1a6b','#6b1a3a','#1a6b5a','#3a5a1a','#5a1a1a'] %}
  <div class="results">
    {% if data.settings.course_name %}
    <p class="course-meta">
      {{ data.settings.course_name }}
      &nbsp;&mdash;&nbsp; Par {{ data.settings.par }}
      &nbsp;&mdash;&nbsp; Rating {{ data.settings.course_rating | fmt_num }}
      &nbsp;&mdash;&nbsp; Slope {{ data.settings.slope }}
    </p>
    {% endif %}
    <div class="teams-grid">
      {% for team in results.teams %}
      <div class="team-card">
        <div class="team-header" style="background:{{ team_colors[loop.index0 % team_colors|length] }}">
          <span>{{ team.label }}</span>
          <span class="team-ttl">Total: {{ team.total | fmt_num }}</span>
        </div>
        <div class="col-labels">
          <span>Name</span><span>Index</span><span>C.HCP</span>
        </div>
        <div>
          {% for p in team.players %}
          <div class="result-row">
            <span>{{ p.name }}</span>
            <span class="idx">{{ p.hcp_index | fmt_num }}</span>
            <span class="chcp">{{ p.course_hcp | fmt_num }}</span>
          </div>
          {% endfor %}
        </div>
        <div class="team-footer">
          <span>Course HCP Total</span>
          <span>{{ team.total | fmt_num }}</span>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="diff-card">
      <div class="diff-label">Handicap Difference Between Teams</div>
      <div class="diff-value">{{ results.diff | fmt_num }}</div>
      <div class="diff-sub">
        {%- if results.diff == 0 -%}
          perfectly balanced
        {%- else -%}
          strokes &mdash; {{ results.method }} solution
        {%- endif -%}
      </div>
    </div>
  </div>
  {% endif %}

  <script>
    const MAX = {{ max_players }};

    function onSettingsChange() {
      const np = parseInt(document.getElementById('num_players').value) || 0;
      const nt = parseInt(document.getElementById('num_teams').value) || 0;
      for (let i = 0; i < MAX; i++) {
        document.getElementById('row-' + i).style.display = i < np ? '' : 'none';
      }
      const warn = document.getElementById('div-warn');
      warn.style.display = (nt > 0 && np % nt !== 0) ? 'block' : 'none';
    }

    onSettingsChange();
  </script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(debug=True)
