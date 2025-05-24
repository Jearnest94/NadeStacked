Proof-of-Concept: CS2 Demo Position Analysis at 1:33
Overview

This proof-of-concept (PoC) repository provides a minimal Python script to parse Counter-Strike 2 (CS2) demo files (e.g. from Faceit matches) and extract player positions. Specifically, for each round in a demo, it finds each player's (X, Y, Z) coordinates at the 1:33 timestamp (or as close as possible, if the round ended earlier). The script then:

    Aggregates positions across all rounds for each player at that time point.

    Generates a heatmap image highlighting the density of a specified player's positions on the map at 1:33.

    Outputs a JSON summary listing each player and the frequency of their positions at that time.

The emphasis is on clarity and speed of implementation rather than polish. The code is kept simple and modular, making it easy to adjust the time marker or extend output logic later. There are no complex frameworks (no CI/CD or linting setup) – just a straightforward script that can be run locally on a demo file.
Repository Structure

cs2-position-poc/
├── main.py             # Entry-point script for parsing and analysis
├── requirements.txt    # Python dependencies for the project
├── example_outputs/    # Example output files from running the script on a test demo
│   ├── positions_summary.json   # JSON with player position frequencies at 1:33
│   └── heatmap_PlayerName.png   # Heatmap image for a specific player's positions
└── README.md           # Usage instructions and project overview

    main.py: Contains the core logic – parsing the demo, extracting positions, generating the heatmap, and saving outputs.

    requirements.txt: Lists required Python packages (Awpy, matplotlib, etc.).

    example_outputs/: Includes sample outputs (a JSON and a heatmap image) produced using a test .dem file. In a real scenario, you would replace the test demo with an actual Faceit CS2 demo.

Dependencies and Installation

The project uses Python 3.11+ and the following libraries (listed in requirements.txt):

    Awpy – A Python library for parsing CS:GO/CS2 demos
    github.com
    . Awpy wraps a high-performance Go parser, allowing us to get structured data (events, player positions, etc.) from demo files in Python
    file-w9tbt4qjggsim8cb31glfj
    file-w9tbt4qjggsim8cb31glfj
    .

    matplotlib – For plotting the heatmap.

    pandas – For simple data manipulation (optional, used here for clarity).

    (Awpy will internally use Polars for DataFrames and includes any other needed dependencies.)

You can install the requirements with pip:

pip install -r requirements.txt

Parsing CS2 Demo Files with Awpy

We use Awpy to parse the .dem file and extract relevant data. In main.py, the Awpy Demo class is used to load and parse the demo:

from awpy import Demo

demo_path = "path/to/test.dem"  # Path to your CS2 demo file
demo = Demo(demo_path)
# Parse demo for player tick data, including positions (X, Y, Z coordinates)
demo.parse(player_props=["X", "Y", "Z"])  # include position data for each player tick:contentReference[oaicite:3]{index=3}

When demo.parse() is called with player_props=["X","Y","Z"], Awpy will produce a demo.ticks DataFrame containing per-player, per-tick information, including the X/Y/Z world coordinates of each player at each tick
awpy.readthedocs.io
. We rely on Awpy's parsing backend to handle all the heavy lifting (reading the binary demo format and extracting structured data). The parse may take a few seconds per demo, but it is optimized in Awpy (wrapping the fast Go parser) to handle full match demos efficiently
file-w9tbt4qjggsim8cb31glfj
file-w9tbt4qjggsim8cb31glfj
.

After parsing, we have access to:

    demo.rounds – a table of round timings (start, freeze time end, round end, etc.).

    demo.ticks – a table of player states at each tick during active play (excluding warmups or timeouts)
    awpy.readthedocs.io
    .

    Other info like demo.kills, demo.grenades, etc., though we only need rounds and ticks for this task.

Note: The default competitive round time is 1:55 (115 seconds) in CS2
bo3.gg
. The timestamp 1:33 means there are 93 seconds left, which is 22 seconds into the round (115 - 93 = 22). We will use this to calculate the target tick offset.
Extracting Player Positions at 1:33 of Each Round

To find player positions at the 1:33 mark, the script iterates through each round and computes the tick corresponding to 22 seconds after round start. In a Faceit 128-tick demo, 22 seconds corresponds to 22 * 128 = 2816 ticks. We use the round’s freeze_end tick (the tick when the freeze time ended and the round’s clock started) as a reference:

import pandas as pd

rounds_df = demo.rounds.to_pandas()
ticks_df = demo.ticks.to_pandas()

tickrate = demo.tickrate  # typically 128 for Faceit 128-tick demos
time_marker_seconds = 22  # 1:33 into the round corresponds to 22 seconds elapsed
offset_ticks = int(time_marker_seconds * tickrate)

positions_by_player = {}  # will map player name -> list of positions (X, Y, Z)
for _, round_row in rounds_df.iterrows():
    round_num = round_row['round_num']
    start_tick = round_row['freeze_end']  # round clock starts after freeze time
    target_tick = start_tick + offset_ticks
    # If the round ended before reaching this timestamp, use the last tick of the round
    if target_tick > round_row['end']:
        target_tick = round_row['end']
    # Filter the tick dataframe for this round and the target tick
    mask = (ticks_df['round_num'] == round_num) & (ticks_df['tick'] == target_tick)
    tick_positions = ticks_df[mask]
    for _, player_state in tick_positions.iterrows():
        name = player_state['name']
        x, y, z = player_state['X'], player_state['Y'], player_state['Z']
        positions_by_player.setdefault(name, []).append((x, y, z))

How this works: For each round, we calculate target_tick. If the round lasted at least 22 seconds, this will be the tick closest to 1:33 remaining. If the round ended earlier than 1:33, we use the round’s end tick as the “closest” tick. We then filter demo.ticks for entries matching that round number and tick. The resulting rows (one per player alive at that time) give each surviving player's position at the chosen moment. We collect those positions in a dictionary (positions_by_player). Players who died before 1:33 in a round won’t have an entry for that round’s target tick.

After this loop, positions_by_player contains a list of positions (one per round, if the player was alive at that time) for each player.
Aggregating Positions and Frequency

Using the collected positions, we can also compute frequencies of repeated positions. In many cases, each position in the list will be unique per round. However, if a player tends to stand in exactly the same spot at 1:33 across multiple rounds, those coordinates will appear multiple times. We aggregate these into a frequency count per unique position:

positions_frequency = {}
for player, pos_list in positions_by_player.items():
    freq = {}
    for pos in pos_list:
        freq[pos] = freq.get(pos, 0) + 1
    positions_frequency[player] = freq

Now positions_frequency maps each player to a dictionary of {position: count}. For example, it might contain an entry like:

"PlayerA": {
    "(1000.0, -750.0, 128.0)": 3,
    "(1100.0, -800.0, 128.0)": 2
}

indicating PlayerA stood at coordinate (1000, -750, 128) in 3 different rounds at 1:33, and at (1100, -800, 128) in 2 rounds, etc. (Coordinates are in in-game units relative to the map.)
Generating a Heatmap for a Specific Player

We use matplotlib (with Awpy's plotting helper) to create a heatmap of a chosen player's positions. The heatmap will overlay the points on the map layout, visually highlighting areas where the player frequently stands at 1:33.

Awpy provides a convenient plotting function awpy.plot.heatmap to create heatmaps on map images
awpy.readthedocs.io
. We retrieve the map name from the demo header (e.g., "de_dust2" or "de_inferno") and pass the list of that player's points:

from awpy import plot as awplot

player_name = "PlayerA"  # (In practice, set this via an argument or config)
map_name = demo.header['map_name']  # e.g., "de_mirage"
points = positions_by_player.get(player_name, [])

# Generate heatmap using Awpy's plotting utility
fig, ax = awplot.heatmap(map_name=map_name, points=points, method="hex", size=10, cmap="Reds")
fig.savefig(f"heatmap_{player_name}.png")

This will produce a heatmap image (saved as heatmap_PlayerA.png for example). The map background is automatically handled by Awpy if the map data is available, and the points are overlaid with a density coloring (using hexagonal binning in this example). Areas where the player often appears will show up in hotter colors on the heatmap
awpy.readthedocs.io
.

(If Awpy’s map assets are not available or if a custom approach is preferred, one could manually plot the positions on a stored map image using matplotlib’s imshow and hexbin/hist2d. However, Awpy’s built-in heatmap simplifies this.)
Output: JSON Summary of Player Positions

Finally, we output a JSON file (positions_summary.json) listing each player's positions at 1:33 across rounds, along with occurrence counts:

    The JSON is structured per player. For each player, we provide a list of objects, each containing a position (XYZ coordinates) and a count of how many rounds the player was at that exact position at 1:33.

    If a player was not alive at 1:33 in some rounds, those rounds are simply not counted (so the total occurrences can be less than the total rounds).

For example, the JSON might look like:

{
  "PlayerA": [
    { "position": [1000.0, -750.0, 128.0], "count": 3 },
    { "position": [1100.0, -800.0, 128.0], "count": 2 }
  ],
  "PlayerB": [
    { "position": [ -250.0,  500.0, 128.0], "count": 5 }
  ]
}

This indicates PlayerA had two common spots (with frequencies 3 and 2), and PlayerB was at one spot in 5 rounds. In the script, we write this data with Python’s json module:

import json
with open("positions_summary.json", "w") as fp:
    json.dump(
        [
            { "player": player, "positions": [
                  {"position": list(pos), "count": count} for pos, count in freq_dict.items()
              ]
            }
            for player, freq_dict in positions_frequency.items()
        ],
        fp, indent=2
    )

(The structure above is one way to format the JSON. You could also use a dict of dicts, but using a list of position objects makes it easy to extend or add more info per position if needed.)
Usage Instructions (README Overview)

To run the analysis on a demo file, use the following steps:

    Place a CS2 demo file (.dem) in the repository directory (or note its path).

    Install dependencies with pip install -r requirements.txt (preferably in a Python 3.11+ environment).

    Run the script with the demo file path as an argument. For example:

    python main.py --demo path/to/yourmatch.dem --player "PlayerA"

    This will parse the demo and produce:

        positions_summary.json – a JSON file summarizing all players' positions at 1:33.

        heatmap_PlayerA.png – a heatmap image for the specified player (replace with a chosen name).

    Inspect the outputs: Open the JSON to see per-player position frequencies, and view the heatmap PNG to visually analyze PlayerA’s common positions at the 1:33 mark.

In a real scenario, you would replace "path/to/yourmatch.dem" with an actual Faceit match demo file. Large match demos (~30 rounds) parse in a few seconds
awpy.readthedocs.io
. The code is synchronous for simplicity, but since Awpy is efficient (leveraging a Go parser under the hood), it can handle full demos without additional optimization
file-w9tbt4qjggsim8cb31glfj
.
Extensibility and Modularity

This PoC is designed to be easily extendable:

    Changing the time marker: The timestamp (1:33) is defined in one place (time_marker_seconds = 22). Adjust this value or parse a new timestamp string to analyze a different round time (e.g., 0:45 or 1:00). The rest of the code will work with the new offset.

    Multiple time points: The position extraction logic can be refactored into a function (e.g., get_positions_at_time(demo, seconds)) to collect data at various time marks. You could call this function multiple times (for different timestamps) and output multiple heatmaps or combine data for deeper analysis.

    Extending output logic: The JSON structure can be modified or expanded (e.g., grouping positions into map regions or adding whether the player was alive/dead). The code is straightforward to adapt – since we prioritized clarity, the data processing steps are in plain Python/pandas.

    Plugging into a larger pipeline: This script can serve as a component in a bigger analytics pipeline. For instance, it could be called for multiple demo files (batch processing) or integrated with a web service that supplies a demo and player of interest, then returns the heatmap and JSON summary.

By focusing on core functionality (demo parsing, data extraction, and simple output), this repository provides a clear starting point for CS2 positional analysis. Awpy handles the complex parsing and even visualization, allowing us to deliver a working solution quickly
github.com
awpy.readthedocs.io
. Users can confidently take this minimal example and build upon it for more comprehensive tactical insights or different output formats as needed.
Citations
Favicon

GitHub - pnxenopoulos/awpy: Python library to parse, analyze and visualize Counter-Strike 2 data
https://github.com/pnxenopoulos/awpy

THE PRODUCT_ Technical & Architectural Blueprint-1-1.pdf
file://file-W9TBt4qJGgsim8Cb31gLfJ

THE PRODUCT_ Technical & Architectural Blueprint-1-1.pdf
file://file-W9TBt4qJGgsim8Cb31gLfJ
Favicon

Parsing a Counter-Strike 2 Demo — Awpy 2.0.2 documentation
https://awpy.readthedocs.io/en/latest/examples/parse_demo.html

THE PRODUCT_ Technical & Architectural Blueprint-1-1.pdf
file://file-W9TBt4qJGgsim8Cb31gLfJ
Favicon

Example Parser Output — Awpy 2.0.2 documentation
https://awpy.readthedocs.io/en/latest/modules/parser_output.html
Favicon

Bomb Defusal - CS2
https://bo3.gg/wiki/bomb-defusal
Favicon

Visualization & Plotting — Awpy 2.0.2 documentation
https://awpy.readthedocs.io/en/latest/modules/plot.html
Favicon

Parsing a Counter-Strike 2 Demo — Awpy 2.0.2 documentation
https://awpy.readthedocs.io/en/latest/examples/parse_demo.html
Favicon

GitHub - pnxenopoulos/awpy: Python library to parse, analyze and visualize Counter-Strike 2 data
https://github.com/pnxenopoulos/awpy