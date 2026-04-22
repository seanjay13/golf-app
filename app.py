#!/usr/bin/env python3
import itertools
import json
import math
import os
import random
from flask import Flask, render_template_string, request, redirect, url_for

app = Flask(__name__)
DATA_FILE    = os.path.join(os.path.dirname(__file__), "golf_data.json")
COURSES_FILE = os.path.join(os.path.dirname(__file__), "courses.json")
MAX_PLAYERS       = 20
BRUTE_FORCE_LIMIT = 500_000
TEE_NAMES         = ["Blue", "White", "Gold", "Red"]


# ── Courses ───────────────────────────────────────────────────────────────────

def load_courses():
    if os.path.exists(COURSES_FILE):
        try:
            with open(COURSES_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_courses(courses):
    with open(COURSES_FILE, "w") as f:
        json.dump(courses, f, indent=2)


# ── Player data ───────────────────────────────────────────────────────────────

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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    data = load_data()
    courses = load_courses()
    error = None
    results = None

    if request.method == "POST":
        s = data["settings"]
        s["course_name"] = request.form.get("course_name", "").strip()
        try:
            s["num_players"]   = max(2, min(MAX_PLAYERS, int(request.form.get("num_players", 8))))
            s["num_teams"]     = max(2, min(10, int(request.form.get("num_teams", 2))))
            s["par"]           = int(request.form.get("par", 72))
            s["course_rating"] = float(request.form.get("course_rating", 72.0))
            s["slope"]         = int(request.form.get("slope", 113))
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
                    f"Choose a player count divisible by {nt} "
                    f"(e.g. {nt * (np_ // nt)} or {nt * (np_ // nt + 1)})."
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

            min_chcp = min(course_hcps)
            shot_alloc = sorted(
                [
                    {
                        "name": active[i]["name"],
                        "hcp_index": active[i]["handicap_index"],
                        "course_hcp": course_hcps[i],
                        "shots": round(course_hcps[i] - min_chcp),
                    }
                    for i in range(len(active))
                ],
                key=lambda p: p["course_hcp"],
            )

            results = {
                "teams": teams_out,
                "diff": diff,
                "method": method,
                "shot_alloc": shot_alloc,
            }

    return render_template_string(
        HTML,
        data=data,
        results=results,
        error=error,
        max_players=MAX_PLAYERS,
        courses_json=json.dumps(courses),
    )


@app.route("/courses")
def courses_page():
    courses = load_courses()
    msg  = request.args.get("msg", "")
    edit = request.args.get("edit", "")
    prefill = None
    if edit.isdigit() and 0 <= int(edit) < len(courses):
        prefill = {"idx": int(edit), "course": courses[int(edit)]}
    return render_template_string(
        COURSES_HTML,
        courses=courses,
        tee_names=TEE_NAMES,
        msg=msg,
        prefill=prefill,
    )


@app.route("/courses/save", methods=["POST"])
def courses_save():
    courses = load_courses()
    edit_idx = request.form.get("edit_idx", "").strip()
    name     = request.form.get("name", "").strip()
    city     = request.form.get("city", "").strip()

    if not name:
        return redirect(url_for("courses_page", msg="Course name is required."))

    tees = {}
    for tee in TEE_NAMES:
        p = request.form.get(f"tee_{tee}_par", "").strip()
        r = request.form.get(f"tee_{tee}_rating", "").strip()
        s = request.form.get(f"tee_{tee}_slope", "").strip()
        if p and r and s:
            try:
                tees[tee] = {"par": int(p), "rating": float(r), "slope": int(s)}
            except ValueError:
                pass

    if not tees:
        return redirect(url_for("courses_page", msg="At least one complete tee set (par, rating, slope) is required."))

    course = {"name": name, "city": city, "tees": tees}
    if edit_idx.isdigit() and 0 <= int(edit_idx) < len(courses):
        courses[int(edit_idx)] = course
    else:
        courses.append(course)

    courses.sort(key=lambda c: c["name"].lower())
    save_courses(courses)
    return redirect(url_for("courses_page", msg=f"'{name}' saved."))


@app.route("/courses/delete/<int:idx>", methods=["POST"])
def courses_delete(idx):
    courses = load_courses()
    if 0 <= idx < len(courses):
        name = courses[idx]["name"]
        courses.pop(idx)
        save_courses(courses)
        return redirect(url_for("courses_page", msg=f"'{name}' deleted."))
    return redirect(url_for("courses_page"))


# ── Templates ─────────────────────────────────────────────────────────────────

_SHARED_CSS = """
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
.subtitle a { color: #4a8a3e; text-decoration: none; }
.subtitle a:hover { text-decoration: underline; }

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
input:disabled, select:disabled { background: #f4f7f2; color: #a0b89a; cursor: not-allowed; }

.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.75rem;
}
.span-full { grid-column: 1 / -1; }
.span-2 { grid-column: span 2; }

.warn-text { font-size: 0.78rem; color: #a05000; padding: 0.15rem 0; }

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
  background: #fff4f4; border: 1.5px solid #dfa0a0; border-radius: 10px;
  padding: 0.75rem 1rem; color: #8b2020;
  max-width: 620px; margin: 0 auto 1.25rem; font-size: 0.88rem;
}
.info-box {
  background: #f0faf0; border: 1.5px solid #90c890; border-radius: 10px;
  padding: 0.75rem 1rem; color: #2d5a27;
  max-width: 620px; margin: 0 auto 1.25rem; font-size: 0.88rem;
}

.results { max-width: 620px; margin: 0 auto; }
.course-meta {
  text-align: center; font-size: 0.75rem; color: #9ab892;
  text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 1rem;
}
.teams-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem; margin-bottom: 1rem;
}
.team-card { background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); overflow: hidden; }
.team-header {
  padding: 0.6rem 1rem; font-weight: 700; font-size: 0.82rem;
  letter-spacing: 0.06em; text-transform: uppercase;
  display: flex; justify-content: space-between; align-items: center; color: white;
}
.team-header .team-ttl { font-weight: 400; font-size: 0.78rem; opacity: 0.85; }
.result-row {
  display: grid; grid-template-columns: 1fr 44px 44px;
  gap: 0.25rem; padding: 0.28rem 1rem;
  font-size: 0.86rem; border-bottom: 1px solid #f0f4f0; align-items: center;
}
.result-row:last-child { border-bottom: none; }
.result-row .idx  { color: #b0c8a8; font-size: 0.75rem; text-align: right; }
.result-row .chcp { font-weight: 600; color: #2d5a27; text-align: right; }
.col-labels {
  display: grid; grid-template-columns: 1fr 44px 44px;
  gap: 0.25rem; padding: 0.2rem 1rem 0;
  font-size: 0.67rem; color: #b0c8a8; text-transform: uppercase; letter-spacing: 0.06em;
}
.col-labels span { text-align: right; }
.col-labels span:first-child { text-align: left; }
.team-footer {
  background: #f0f4f0; padding: 0.45rem 1rem;
  display: flex; justify-content: space-between;
  font-weight: 700; font-size: 0.85rem; border-top: 2px solid #d8e8d0; color: #2d5a27;
}
.diff-card {
  background: white; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.07);
  padding: 1rem 1.5rem; text-align: center; margin-bottom: 1rem;
}
.diff-label { font-size: 0.72rem; color: #9ab892; text-transform: uppercase; letter-spacing: 0.09em; }
.diff-value { font-size: 2.4rem; font-weight: 800; color: #2d5a27; line-height: 1.2; }
.diff-sub { font-size: 0.78rem; color: #9ab892; margin-top: 0.15rem; }

.shot-table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
.shot-table th {
  font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em;
  color: #9ab892; font-weight: 600; padding: 0 0.5rem 0.5rem; text-align: left;
}
.shot-table th.right { text-align: right; }
.shot-table td { padding: 0.3rem 0.5rem; font-size: 0.88rem; border-bottom: 1px solid #f0f4f0; }
.shot-table tr:last-child td { border-bottom: none; }
.shots-zero { color: #b0c8a8; font-weight: 500; }
.shots-pos  { color: #1a2e1a; font-weight: 700; font-size: 1rem; }
"""

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Golf Team Splitter</title>
  <style>""" + _SHARED_CSS + """
    .course-select-row {
      display: grid; grid-template-columns: 1fr 130px; gap: 0.5rem;
    }
    .tee-badge {
      display: inline-block; padding: 0.1rem 0.45rem; border-radius: 20px;
      font-size: 0.72rem; font-weight: 600; margin-right: 0.2rem;
    }
    .tee-Blue  { background: #d0e8ff; color: #1a4a8a; }
    .tee-White { background: #f0f0f0; color: #505050; }
    .tee-Gold  { background: #fff0c0; color: #7a5800; }
    .tee-Red   { background: #ffd8d8; color: #8a1a1a; }
  </style>
</head>
<body>
  <h1>⛳ Golf Team Splitter</h1>
  <p class="subtitle">
    Calculates course handicaps and finds the fairest team split
    &nbsp;&mdash;&nbsp; <a href="/courses">Manage Courses</a>
  </p>

  <form method="POST" action="/">

    <div class="card">
      <p class="card-title">Course &amp; Game Settings</p>
      <div class="settings-grid">

        <!-- Course database quick-fill -->
        <div class="span-full">
          <label>Select from Course Database</label>
          <div class="course-select-row">
            <select id="db_course" onchange="onDbCourseChange()">
              <option value="">— choose to auto-fill fields below —</option>
            </select>
            <select id="db_tee" onchange="onDbTeeChange()" disabled>
              <option value="">Tee</option>
            </select>
          </div>
        </div>

        <div class="span-full">
          <label for="course_name">Course Name</label>
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
        {%- if results.diff == 0 -%}perfectly balanced
        {%- else -%}strokes &mdash; {{ results.method }} solution{%- endif -%}
      </div>
    </div>

    <!-- Shot Allocation -->
    <div class="card" style="max-width:620px;margin:0 auto 1rem">
      <p class="card-title">Shot Allocation</p>
      <p style="font-size:0.8rem;color:#6b8c63;margin-bottom:0.75rem">
        Shots each player receives relative to
        <strong>{{ results.shot_alloc[0].name }}</strong>
        (lowest course HCP: {{ results.shot_alloc[0].course_hcp | fmt_num }})
      </p>
      <table class="shot-table">
        <thead>
          <tr>
            <th>Player</th>
            <th class="right">Index</th>
            <th class="right">Course HCP</th>
            <th class="right">Shots Received</th>
          </tr>
        </thead>
        <tbody>
          {% for p in results.shot_alloc %}
          <tr>
            <td>{{ p.name }}</td>
            <td style="text-align:right;color:#6b8c63">{{ p.hcp_index | fmt_num }}</td>
            <td style="text-align:right;color:#2d5a27;font-weight:600">{{ p.course_hcp | fmt_num }}</td>
            <td style="text-align:right">
              {% if p.shots == 0 %}
                <span class="shots-zero">— scratch</span>
              {% else %}
                <span class="shots-pos">+{{ p.shots }}</span>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

  </div>
  {% endif %}

  <script>
    const MAX = {{ max_players }};
    const COURSES_DB = {{ courses_json | safe }};

    // Populate course dropdown
    (function() {
      const sel = document.getElementById('db_course');
      COURSES_DB.forEach(function(c) {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = c.name + (c.city ? '  (' + c.city + ')' : '');
        sel.appendChild(opt);
      });
    })();

    function onDbCourseChange() {
      const courseName = document.getElementById('db_course').value;
      const teeSel = document.getElementById('db_tee');
      teeSel.innerHTML = '<option value="">— select tee —</option>';
      teeSel.disabled = true;

      if (!courseName) return;
      const course = COURSES_DB.find(function(c) { return c.name === courseName; });
      if (!course) return;

      const teeOrder = ['Blue', 'White', 'Gold', 'Red'];
      teeOrder.forEach(function(tee) {
        if (course.tees[tee]) {
          const opt = document.createElement('option');
          opt.value = tee;
          opt.textContent = tee;
          teeSel.appendChild(opt);
        }
      });
      teeSel.disabled = false;

      document.getElementById('course_name').value = courseName;
    }

    function onDbTeeChange() {
      const courseName = document.getElementById('db_course').value;
      const tee = document.getElementById('db_tee').value;
      if (!courseName || !tee) return;

      const course = COURSES_DB.find(function(c) { return c.name === courseName; });
      if (!course || !course.tees[tee]) return;

      const t = course.tees[tee];
      document.getElementById('par').value           = t.par;
      document.getElementById('course_rating').value = t.rating;
      document.getElementById('slope').value          = t.slope;
    }

    function onSettingsChange() {
      const np = parseInt(document.getElementById('num_players').value) || 0;
      const nt = parseInt(document.getElementById('num_teams').value)   || 0;
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


COURSES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Course Manager — Golf Team Splitter</title>
  <style>""" + _SHARED_CSS + """
    .card-wide {
      background: white; border-radius: 12px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.07);
      padding: 1.25rem 1.5rem;
      max-width: 820px; margin: 0 auto 1.25rem;
    }
    .tee-grid { display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem; }
    .tee-row  { display: grid; grid-template-columns: 56px 1fr 1fr 1fr; gap: 0.5rem; align-items: center; }
    .tee-row .tee-lbl {
      font-size: 0.82rem; font-weight: 700; color: #2d5a27;
      padding: 0.45rem 0; text-align: center;
      border-radius: 6px;
    }
    .tee-lbl-Blue  { background: #d0e8ff; color: #1a4a8a; }
    .tee-lbl-White { background: #f0f0f0; color: #505050; }
    .tee-lbl-Gold  { background: #fff0c0; color: #7a5800; }
    .tee-lbl-Red   { background: #ffd8d8; color: #8a1a1a; }
    .tee-header-row {
      display: grid; grid-template-columns: 56px 1fr 1fr 1fr; gap: 0.5rem;
      margin-bottom: 0.25rem;
    }
    .tee-header-row span {
      font-size: 0.67rem; text-transform: uppercase; letter-spacing: 0.07em;
      color: #9ab892; font-weight: 600; text-align: center;
    }
    .form-row  { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 0.75rem; }
    .form-actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
    .btn-primary {
      flex: 1; padding: 0.65rem; background: #2d5a27; color: white;
      border: none; border-radius: 8px; font-size: 0.9rem; font-weight: 600;
      cursor: pointer; transition: background 0.15s;
    }
    .btn-primary:hover { background: #3d7835; }
    .btn-secondary {
      padding: 0.65rem 1rem; background: white; color: #6b8c63;
      border: 1.5px solid #d0ddc8; border-radius: 8px; font-size: 0.9rem;
      font-weight: 600; cursor: pointer; transition: background 0.15s;
    }
    .btn-secondary:hover { background: #f0f4f0; }

    .courses-table { width: 100%; border-collapse: collapse; }
    .courses-table th {
      font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.07em;
      color: #9ab892; font-weight: 600; padding: 0 0.5rem 0.6rem; text-align: left;
    }
    .courses-table td {
      padding: 0.4rem 0.5rem; font-size: 0.88rem;
      border-bottom: 1px solid #f0f4f0; vertical-align: middle;
    }
    .courses-table tr:last-child td { border-bottom: none; }
    .courses-table tr:hover td { background: #fafffe; }
    .tee-pip {
      display: inline-block; width: 10px; height: 10px; border-radius: 50%;
      margin-right: 3px; vertical-align: middle;
    }
    .pip-Blue  { background: #5a9adf; }
    .pip-White { background: #c8c8c8; border: 1px solid #aaa; }
    .pip-Gold  { background: #e8c040; }
    .pip-Red   { background: #df5a5a; }
    .btn-edit {
      padding: 0.25rem 0.6rem; background: #f0f4f0; color: #2d5a27;
      border: 1.5px solid #c8dcc0; border-radius: 6px; font-size: 0.78rem;
      font-weight: 600; cursor: pointer; transition: background 0.15s; margin-right: 0.3rem;
    }
    .btn-edit:hover { background: #d8ecd0; }
    .btn-del {
      padding: 0.25rem 0.6rem; background: #fff4f4; color: #8b2020;
      border: 1.5px solid #dfa0a0; border-radius: 6px; font-size: 0.78rem;
      font-weight: 600; cursor: pointer; transition: background 0.15s;
    }
    .btn-del:hover { background: #fde8e8; }
    .editing-banner {
      background: #fffbe8; border: 1.5px solid #e8d870; border-radius: 8px;
      padding: 0.5rem 0.75rem; font-size: 0.82rem; color: #7a6000;
      margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: center;
    }
  </style>
</head>
<body>
  <h1>⛳ Course Manager</h1>
  <p class="subtitle"><a href="/">← Back to Team Splitter</a></p>

  {% if msg %}
  <div class="info-box" style="max-width:820px">{{ msg }}</div>
  {% endif %}

  <!-- Add / Edit Form -->
  <div class="card-wide">
    <p class="card-title" id="form-title">Add New Course</p>

    <div class="editing-banner" id="editing-banner" style="display:none">
      <span id="editing-label">Editing: </span>
      <button type="button" class="btn-secondary" onclick="resetForm()" style="padding:0.2rem 0.6rem;font-size:0.78rem">
        Cancel Edit
      </button>
    </div>

    <form method="POST" action="/courses/save" id="course-form">
      <input type="hidden" name="edit_idx" id="edit_idx" value="">

      <div class="form-row">
        <div>
          <label for="name">Course Name *</label>
          <input type="text" id="name" name="name" placeholder="e.g. Cog Hill Course 4" required>
        </div>
        <div>
          <label for="city">City / State</label>
          <input type="text" id="city" name="city" placeholder="e.g. Lemont, IL">
        </div>
      </div>

      <label style="margin-bottom:0.4rem">Tee Data (fill any tees that apply)</label>
      <div class="tee-header-row">
        <span></span><span>Par</span><span>Rating</span><span>Slope</span>
      </div>
      <div class="tee-grid">
        {% for tee in tee_names %}
        <div class="tee-row">
          <span class="tee-lbl tee-lbl-{{ tee }}">{{ tee }}</span>
          <input type="number" id="tee_{{ tee }}_par"    name="tee_{{ tee }}_par"
                 placeholder="72" min="60" max="80" step="1">
          <input type="number" id="tee_{{ tee }}_rating" name="tee_{{ tee }}_rating"
                 placeholder="72.0" min="50" max="90" step="0.1">
          <input type="number" id="tee_{{ tee }}_slope"  name="tee_{{ tee }}_slope"
                 placeholder="113" min="55" max="155" step="1">
        </div>
        {% endfor %}
      </div>

      <div class="form-actions">
        <button type="submit" class="btn-primary">Save Course</button>
      </div>
    </form>
  </div>

  <!-- Course List -->
  <div class="card-wide">
    <p class="card-title">Course Database ({{ courses|length }} courses)</p>
    {% if courses %}
    <table class="courses-table">
      <thead>
        <tr>
          <th>Course</th>
          <th>City</th>
          <th>Tees</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for course in courses %}
        <tr>
          <td style="font-weight:500">{{ course.name }}</td>
          <td style="color:#6b8c63">{{ course.city }}</td>
          <td>
            {% for tee in tee_names %}{% if tee in course.tees %}
              <span class="tee-pip pip-{{ tee }}"></span>
            {% endif %}{% endfor %}
            <span style="font-size:0.78rem;color:#9ab892">
              {% for tee in tee_names %}{% if tee in course.tees %}{{ tee }} {% endif %}{% endfor %}
            </span>
          </td>
          <td style="white-space:nowrap">
            <button type="button" class="btn-edit"
                    onclick="editCourse({{ loop.index0 }}, {{ course | tojson }})">
              Edit
            </button>
            <form method="POST" action="/courses/delete/{{ loop.index0 }}"
                  style="display:inline"
                  onsubmit="return confirm('Delete {{ course.name }}?')">
              <button type="submit" class="btn-del">Delete</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p style="color:#9ab892;font-size:0.88rem">No courses yet. Add one above.</p>
    {% endif %}
  </div>

  <script>
    const TEE_NAMES = {{ tee_names | tojson }};

    {% if prefill %}
    editCourse({{ prefill.idx }}, {{ prefill.course | tojson }});
    {% endif %}

    function editCourse(idx, course) {
      document.getElementById('edit_idx').value = idx;
      document.getElementById('form-title').textContent = 'Edit Course';
      document.getElementById('name').value = course.name || '';
      document.getElementById('city').value = course.city || '';

      TEE_NAMES.forEach(function(tee) {
        const data = (course.tees && course.tees[tee]) || {};
        document.getElementById('tee_' + tee + '_par').value    = data.par    || '';
        document.getElementById('tee_' + tee + '_rating').value = data.rating || '';
        document.getElementById('tee_' + tee + '_slope').value  = data.slope  || '';
      });

      const banner = document.getElementById('editing-banner');
      banner.style.display = 'flex';
      document.getElementById('editing-label').textContent = 'Editing: ' + course.name;
      document.getElementById('course-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function resetForm() {
      document.getElementById('edit_idx').value = '';
      document.getElementById('form-title').textContent = 'Add New Course';
      document.getElementById('course-form').reset();
      document.getElementById('editing-banner').style.display = 'none';
    }
  </script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(debug=True, port=5001)
