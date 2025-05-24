import argparse
import json
import pandas as pd
from awpy import Demo
from awpy import plot as awplot
import matplotlib.pyplot as plt
import os
from collections import Counter

# SECTION: ANALYZE DEMO FUNCTION
# analyze_demo now takes parsed data instead of demo_path to avoid re-parsing
def analyze_demo(demo_obj, ticks_df, rounds_df, player_name_to_heatmap, demo_path_for_outputs):
    """
    Uses pre-parsed CS2 demo data, extracts player positions at specified times before round end,
    generates separate heatmaps for different round ranges and times,
    and outputs a JSON summary.
    """    # SECTION: INITIAL SETUP AND DATA PREPARATION
    # ============================================

    # SUB-SECTION: Tickrate Initialization and Validation
    tickrate = demo_obj.tickrate
    if tickrate is None: # Should have been caught in main, but as a safeguard
        print("Warning: Tickrate not found in demo_obj. Assuming 128.")
        tickrate = 128

    # SUB-SECTION: Time Marker Configuration
    # Define specific timestamps to analyze (seconds from round start)
    time_markers_config = [
        {"label": "1m48s", "seconds_from_start": 7, "display_time": "1:48", "color": "red"},
        {"label": "1m47s", "seconds_from_start": 8, "display_time": "1:47", "color": "red"},
        {"label": "1m46s", "seconds_from_start": 9, "display_time": "1:46", "color": "red"},
    ]

    if rounds_df.empty:
        print("No rounds data found (passed to analyze_demo).")
        return
    if ticks_df.empty:
        print("No ticks data found (passed to analyze_demo).")
        return

    # SUB-SECTION: Define Round Ranges (Halves, Overtime)
    total_rounds = len(rounds_df)
    round_ranges = []
    if total_rounds >= 1:
        first_half_end_idx = min(12, total_rounds)
        round_ranges.append({
            "name": "first_half",
            "rounds": rounds_df.iloc[0:first_half_end_idx],
            "label": f"Rounds 1-{first_half_end_idx} (First Half)"
        })

    if total_rounds >= 13:
        second_half_start_idx = 12
        second_half_end_idx = min(24, total_rounds)
        if second_half_end_idx > second_half_start_idx:
            round_ranges.append({
                "name": "second_half",
                "rounds": rounds_df.iloc[second_half_start_idx:second_half_end_idx],
                "label": f"Rounds {second_half_start_idx + 1}-{second_half_end_idx} (Second Half)"
            })

    if total_rounds >= 25:
        overtime_start_idx = 24
        if total_rounds > overtime_start_idx:
            round_ranges.append({
                "name": "overtime",
                "rounds": rounds_df.iloc[overtime_start_idx:],
                "label": f"Rounds {overtime_start_idx + 1}+ (Overtime)"
            })

    # SUB-SECTION: Extract Player Positions for Each Time Marker and Round Range
    all_heatmap_data = []

    for range_info in round_ranges:
        range_name = range_info["name"]
        rounds_to_process_for_range = range_info["rounds"]
        range_label = range_info["label"]

        if rounds_to_process_for_range.empty:
            continue

        for time_config in time_markers_config:
            time_label_for_file = time_config["label"]
            seconds_from_start = time_config["seconds_from_start"] # Corrected
            display_time_for_title = time_config["display_time"]
            # Note: The logic for target_tick uses 'current_round_end_tick - offset'.
            # If 'seconds_from_start' truly means from the *round's actual start* (e.g. freeze_end),
            # then target_tick calculation should be 'actual_round_start_tick + offset'.
            # However, the existing target_tick logic (current_round_end_tick - offset) was kept
            # as per previous iterations where it was producing desired heatmaps based on time *before round end*.
            # If this interpretation is wrong, the target_tick calculation below is the primary place to change.
            current_offset_ticks = int(seconds_from_start * tickrate) # Renamed for clarity based on usage

            positions_by_player_for_timestamp = {}

            for _, round_row in rounds_to_process_for_range.iterrows():
                round_num = round_row['round_num']

                actual_round_start_tick = None
                if 'freeze_end' in round_row and not pd.isna(round_row['freeze_end']):
                    actual_round_start_tick = round_row['freeze_end']
                elif 'start' in round_row and not pd.isna(round_row['start']):
                    actual_round_start_tick = round_row['start']

                if actual_round_start_tick is None:
                    continue

                current_round_end_tick = None
                if 'end' in round_row and not pd.isna(round_row['end']):
                    current_round_end_tick = round_row['end']
                elif 'end_official_tick' in round_row and not pd.isna(round_row['end_official_tick']):
                    current_round_end_tick = round_row['end_official_tick']

                if current_round_end_tick is None:
                    continue

                # This is where the interpretation of 'seconds_from_start' matters most.
                # If it's from actual round start:
                # target_tick = actual_round_start_tick + current_offset_ticks
                # If it's 'seconds_before_end' (as the original '1m48s left' implies):
                target_tick = current_round_end_tick - current_offset_ticks # Kept existing logic

                if target_tick < actual_round_start_tick:
                    target_tick = actual_round_start_tick

                required_cols = ['name', 'X', 'Y', 'Z', 'round_num', 'tick', 'side']
                if not all(col in ticks_df.columns for col in required_cols):
                    print(f"Critical Error in analyze_demo: Ticks DataFrame is missing required columns. Needed: {required_cols}. Aborting.")
                    return

                mask = (ticks_df['round_num'] == round_num) & (ticks_df['tick'] == target_tick)
                tick_positions = ticks_df[mask]

                for _, player_state in tick_positions.iterrows():
                    name = player_state['name']
                    if pd.isna(player_state['X']) or pd.isna(player_state['Y']) or pd.isna(player_state['Z']):
                        continue
                    x, y, z = player_state['X'], player_state['Y'], player_state['Z']
                    side = player_state['side']
                    positions_by_player_for_timestamp.setdefault(name, []).append((x, y, z, round_num, side))

            all_heatmap_data.append({
                "range_name": range_name,
                "range_label": range_label,
                "time_label_for_file": time_label_for_file,
                "display_time_for_title": display_time_for_title,
                "seconds_from_start": seconds_from_start,
                "positions_by_player": positions_by_player_for_timestamp,
                "color": time_config["color"]            })

    # SECTION: INDIVIDUAL HEATMAP GENERATION
    # ======================================
    # SUB-SECTION: Process Each Time/Range Combination for Individual Heatmaps
    generated_heatmap_count = 0
    for heatmap_data_item in all_heatmap_data:
        range_name = heatmap_data_item["range_name"]
        range_label = heatmap_data_item["range_label"]
        time_label_for_file = heatmap_data_item["time_label_for_file"]
        display_time_for_title = heatmap_data_item["display_time_for_title"]
        seconds_from_start = heatmap_data_item["seconds_from_start"]
        positions_by_player = heatmap_data_item["positions_by_player"]

        if not positions_by_player:
            continue

        if player_name_to_heatmap in positions_by_player:
            map_name = demo_obj.header.get('map_name', 'de_unknown')
            if not map_name: map_name = 'de_unknown'

            points_with_side_info = positions_by_player.get(player_name_to_heatmap, [])
            if not points_with_side_info:
                continue

            # SUB-SECTION: Prepare Data for Individual Heatmap
            # Determine the starting round number for this specific heatmap's range
            # to adjust round numbers for display (1-based per segment)
            current_range_info_for_individual_heatmap = next((r_info for r_info in round_ranges if r_info["name"] == range_name), None)
            first_round_in_range_individual = 1 # Default
            if current_range_info_for_individual_heatmap and not current_range_info_for_individual_heatmap["rounds"].empty:
                first_round_in_range_individual = int(current_range_info_for_individual_heatmap["rounds"]["round_num"].iloc[0])

            player_sides_for_this_heatmap = [p[4] for p in points_with_side_info if len(p) > 4 and p[4]]
            most_common_side = Counter(player_sides_for_this_heatmap).most_common(1)[0][0] if player_sides_for_this_heatmap else "Unknown"

            formatted_points_for_heatmap = [(p[0], p[1], p[2]) for p in points_with_side_info]

            current_heatmap_point_frequencies = {}
            for p_data in points_with_side_info:
                pos_tuple_xyz = (float(p_data[0]), float(p_data[1]), float(p_data[2]))
                current_heatmap_point_frequencies[pos_tuple_xyz] = current_heatmap_point_frequencies.get(pos_tuple_xyz, 0) + 1

            if formatted_points_for_heatmap:
                print(f"Generating heatmap for player: {player_name_to_heatmap} ({range_label} - {display_time_for_title} - {most_common_side} Side)")
                generated_heatmap_count +=1
                try:
                    # SUB-SECTION: Generate Hexagon Heatmap with Side-based Colors
                    cmap_choice = "Blues" if most_common_side == "ct" else "Reds"
                    fig, ax = awplot.heatmap(map_name=map_name, points=formatted_points_for_heatmap, method="hex", size=16, cmap=cmap_choice, alpha=0.7)
                    info_text = (f"Player: {player_name_to_heatmap} ({most_common_side.upper()}-Side)\n"
                                 f"Timestamp: {display_time_for_title} ({seconds_from_start}s from start)\n"
                                 f"{range_label} ({len(formatted_points_for_heatmap)} positions)")
                    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=6, fontweight='bold',
                           verticalalignment='center', bbox=dict(facecolor='white', alpha=0.6, pad=5))
                    # SUB-SECTION: Process Round Numbers for Position Annotations
                    # Store round numbers for each position to show on annotations
                    round_numbers_by_position = {}
                    for p_data in points_with_side_info:
                        pos_tuple_xyz = (float(p_data[0]), float(p_data[1]), float(p_data[2]))
                        original_round_num = p_data[3] if len(p_data) > 3 else 0

                        # Adjust round number to be 1-based for the current half/overtime for individual heatmaps
                        adjusted_round_num_individual = original_round_num - first_round_in_range_individual + 1 if original_round_num >= first_round_in_range_individual else "?"
                        # Ensure round numbers for first and second half do not exceed 12
                        if range_name in ["first_half", "second_half"] and isinstance(adjusted_round_num_individual, int):
                            if adjusted_round_num_individual > 12:
                                adjusted_round_num_individual = (adjusted_round_num_individual - 1) % 12 + 1

                        xy_key = (pos_tuple_xyz[0], pos_tuple_xyz[1])
                        if xy_key not in round_numbers_by_position:
                            round_numbers_by_position[xy_key] = []
                        round_numbers_by_position[xy_key].append(str(adjusted_round_num_individual))

                    # SUB-SECTION: Apply Round Number Annotations to Hexagon Centers
                    # Add annotations with round numbers
                    for (x, y), round_nums in round_numbers_by_position.items():
                        original_z_for_xy = next((p[2] for p in formatted_points_for_heatmap if p[0] == x and p[1] == y), None)
                        should_annotate = not (map_name == "de_nuke" and original_z_for_xy is not None and original_z_for_xy < -300)
                        if should_annotate:
                            # Convert game coordinates to pixel coordinates for annotation
                            x_pixel = awplot.utils.game_to_pixel_axis(map_name, x, "x")
                            y_pixel = awplot.utils.game_to_pixel_axis(map_name, y, "y")


                            # Check if the pixel coordinates are within bounds
                            if 0 <= x_pixel <= 1024 and 0 <= y_pixel <= 1024:
                                rounds_text = ",".join(round_nums) if len(round_nums) <= 3 else f"{round_nums[0]},+{len(round_nums)-1}"
                                ax.text(x_pixel, y_pixel, rounds_text, color="white", fontsize=4, ha='center', va='center', fontweight='bold')                    # SUB-SECTION: Save Individual Heatmap File
                    heatmap_filename = f"example_outputs/heatmap_{player_name_to_heatmap.replace(' ', '_')}_{range_name}_{time_label_for_file}_{most_common_side}.png"
                    fig.savefig(heatmap_filename)
                    plt.close(fig)
                except Exception as e:
                    print(f"Error generating heatmap for {player_name_to_heatmap} ({map_name}, {range_label}, {display_time_for_title}): {e}")    
    
    # SECTION: COMBINED HEATMAP GENERATION
    # ====================================
    # SUB-SECTION: Setup for Combined Heatmaps
    map_name = demo_obj.header.get('map_name', 'de_unknown') # Corrected quotes
    if not map_name: map_name = 'de_unknown'

    for range_info in round_ranges:
        range_name = range_info["name"]
        range_label = range_info["label"]

        # SUB-SECTION: Collect All Position Data for This Range
        player_positions_for_range_all_times = []
        sides_for_range_all_times = []

        # Determine the starting round number for this range
        rounds_slice = range_info["rounds"]
        if not rounds_slice.empty:
            first_round_in_range = int(rounds_slice["round_num"].iloc[0])
        else:
            first_round_in_range = 1

        for heatmap_data_item in all_heatmap_data:
            if heatmap_data_item["range_name"] == range_name:
                positions_by_player = heatmap_data_item["positions_by_player"]
                if player_name_to_heatmap in positions_by_player:
                    points_with_side_info = positions_by_player.get(player_name_to_heatmap, [])
                    if points_with_side_info:
                        for p_data in points_with_side_info:
                            original_round_num = p_data[3] if len(p_data) > 3 else 0
                            # Adjust round number to be 1-based for the current half/overtime
                            adjusted_round_num = original_round_num - first_round_in_range + 1 if original_round_num >= first_round_in_range else "?"
                            # Ensure round numbers for first and second half do not exceed 12 for combined heatmaps
                            if range_name in ["first_half", "second_half"] and isinstance(adjusted_round_num, int):
                                if adjusted_round_num > 12:
                                     adjusted_round_num = (adjusted_round_num - 1) % 12 + 1

                            player_positions_for_range_all_times.append({
                                "point": (float(p_data[0]), float(p_data[1]), float(p_data[2])),
                                "time_label": heatmap_data_item["time_label_for_file"],
                                "color": heatmap_data_item["color"],
                                "side": p_data[4] if len(p_data) > 4 else "Unknown",
                                "round": adjusted_round_num # Use adjusted round number
                            })
                            if len(p_data) > 4 and p_data[4]:
                                sides_for_range_all_times.append(p_data[4])

        if not player_positions_for_range_all_times:
            print(f"No data for combined heatmap for player {player_name_to_heatmap} in range {range_label}")
            continue

        most_common_side_combined = Counter(sides_for_range_all_times).most_common(1)[0][0] if sides_for_range_all_times else "Unknown"
          # SUB-SECTION: Generate Combined Heatmap Plot
        print(f"Generating combined heatmap for player: {player_name_to_heatmap} ({range_label} - Combined Times - {most_common_side_combined} Side)")

        try:
            # SUB-SECTION: Create Base Map and Setup
            # Create a base map plot using awpy.plot.plot()
            fig, ax = awplot.plot(map_name=map_name)  # awplot.plot returns fig, ax
            ax.set_title(f"Combined Positions: {player_name_to_heatmap} ({most_common_side_combined.upper()}-Side)\n{range_label}", fontsize=12, fontweight='bold')

            legend_elements = []

            # SUB-SECTION: Layer Scatter Plots for Each Time Marker with Side-based Coloring
            # Layer scatter plots for each time marker using side-based coloring (blue for CT, red for T)
            for time_config in time_markers_config:
                time_label = time_config["label"]
                display_time = time_config["display_time"]

                points_for_this_time = [
                    item for item in player_positions_for_range_all_times if item["time_label"] == time_label
                ]

                if points_for_this_time:
                    # Convert game coordinates to pixel coordinates for plotting
                    valid_points_with_rounds = []
                    for item in points_for_this_time:
                        p = item["point"]
                        x_coord = awplot.utils.game_to_pixel_axis(map_name, p[0], "x")
                        y_coord = awplot.utils.game_to_pixel_axis(map_name, p[1], "y")                        # Filter out points outside map bounds
                        if 0 <= x_coord <= 1024 and 0 <= y_coord <= 1024:
                            valid_points_with_rounds.append({
                                "x": x_coord,
                                "y": y_coord,
                                "round": item["round"],
                                "side": item["side"]
                            })

                    if valid_points_with_rounds:
                        # Use side-based coloring: blue for CT, red for T
                        side_color = "#4472C4" if most_common_side_combined.lower() == "ct" else "#C5504B"
                        
                        # Progressive transparency: 1:48 most transparent, 1:46 least transparent
                        timestamp_alpha_map = {
                            "1:48": 0.2,  # Most transparent (latest timestamp)
                            "1:47": 0.4, # Medium transparency
                            "1:46": 0.8   # Least transparent (earliest timestamp)
                        }
                        alpha_value = timestamp_alpha_map.get(display_time, 0.7)
                        
                        # Scatter plot for this timestamp's points with progressive transparency
                        x_coords_valid = [p["x"] for p in valid_points_with_rounds]
                        y_coords_valid = [p["y"] for p in valid_points_with_rounds]
                        ax.scatter(x_coords_valid, y_coords_valid, color=side_color, label=f"{display_time}", alpha=alpha_value, s=50)

                        # Add round numbers as text annotations on each point
                        for point_data in valid_points_with_rounds:
                            ax.annotate(str(point_data["round"]),
                                       (point_data["x"], point_data["y"]),
                                       xytext=(0, 0), textcoords='offset points',
                                       ha='center', va='center',
                                       fontsize=4, fontweight='bold',
                                       color='white')
                            
            # Position legend inside the plot area
            ax.legend(title="Timestamps", loc="upper left", framealpha=0.8, fontsize=8)
            ax.axis('off')  # Turn off axis numbers and ticks

            combined_heatmap_filename = f"example_outputs/heatmap_{player_name_to_heatmap.replace(' ', '_')}_{range_name}_combined_{most_common_side_combined}.png"
            fig.savefig(combined_heatmap_filename, bbox_inches='tight', dpi=150, facecolor='black')
            plt.close(fig)
            generated_heatmap_count += 1
            print(f"Saved combined heatmap: {combined_heatmap_filename}")

        except Exception as e:
            print(f"Error generating combined heatmap for {player_name_to_heatmap} ({map_name}, {range_label}): {e}")
    print(f"Generated {generated_heatmap_count} heatmaps for {player_name_to_heatmap} (including combined).")

    # SECTION: JSON OUTPUT GENERATION
    # ===============================
    # SUB-SECTION: Data Aggregation and Processing
    print("Generating JSON summary (aggregating all processed timestamps)...")
    json_output = []
    combined_positions_frequency = {}
    combined_positions_details = {}

    # SUB-SECTION: Process Position Data from All Heatmap Items
    for heatmap_data_item in all_heatmap_data:
        positions_by_player_for_item = heatmap_data_item["positions_by_player"]
        time_label = heatmap_data_item["time_label_for_file"]
        range_label_json = heatmap_data_item["range_label"]

        for player, pos_list_with_side in positions_by_player_for_item.items():
            if player not in combined_positions_frequency:
                combined_positions_frequency[player] = {}
                combined_positions_details[player] = {}

            for pos_data_with_side in pos_list_with_side:
                x_val, y_val, z_val, round_num, side_val = pos_data_with_side # Corrected variable name
                pos_tuple_xyz = (float(x_val), float(y_val), float(z_val))

                combined_positions_frequency[player][pos_tuple_xyz] = combined_positions_frequency[player].get(pos_tuple_xyz, 0) + 1
                occurrence_detail = {
                    "round": round_num,
                    "side": side_val,
                    "time_label": time_label,
                    "range_label": range_label_json
                }
                if pos_tuple_xyz not in combined_positions_details[player]:
                    combined_positions_details[player][pos_tuple_xyz] = []
                combined_positions_details[player][pos_tuple_xyz].append(occurrence_detail)

    # SUB-SECTION: Generate Final JSON Structure
    for player, freq_dict in combined_positions_frequency.items():
        player_data = {"player": player, "positions": []}
        details_for_player = combined_positions_details.get(player, {})
        for pos_xyz, count in freq_dict.items():
            occurrence_list = details_for_player.get(pos_xyz, [])
            sorted_occurrences = sorted(occurrence_list, key=lambda k: (k['round'], k['time_label']))

            position_info = {
                "position": list(pos_xyz),
                "count": count,
                "occurrences": sorted_occurrences
            }
            player_data["positions"].append(position_info)
        json_output.append(player_data)

    # SUB-SECTION: Write JSON Files to Disk
    if not os.path.exists("example_outputs"):
        os.makedirs("example_outputs")
        print(f"Created directory: example_outputs")

    json_filename = f"example_outputs/positions_{player_name_to_heatmap.replace(' ', '_')}.json"
    with open(json_filename, "w") as fp:
        json.dump(json_output, fp, indent=2)
    print(f"JSON summary saved to {json_filename}")

    target_player_data = [entry for entry in json_output if entry["player"] == player_name_to_heatmap]
    target_json_filename = f"example_outputs/positions_{player_name_to_heatmap.replace(' ', '_')}_target.json"
    with open(target_json_filename, "w") as fp:
        json.dump(target_player_data, fp, indent=2)
    print(f"Target player JSON saved to {target_json_filename}")

    # SECTION: ORGANIZE OUTPUT FILES INTO DEMO-SPECIFIC DIRECTORY
    # ===========================================================
    # SUB-SECTION: Create Demo-Specific Output Directory
    demo_dir = os.path.dirname(demo_path_for_outputs)
    demo_name_base = os.path.basename(demo_path_for_outputs).replace('.dem', '') # Corrected quotes
    demo_output_dir = os.path.join(demo_name_base)

    if not os.path.exists(demo_output_dir):
        os.makedirs(demo_output_dir)
        print(f"Created directory: {demo_output_dir}")

    # Change dest_path to demo_lib directory
    # out out should be in demo_lib/<demo_name_base>
    demo_output_dir = os.path.join(demo_dir, demo_name_base)
    if not os.path.exists(demo_output_dir):
        os.makedirs(demo_output_dir)
        print(f"Created directory: {demo_output_dir}")

    # SUB-SECTION: Move Generated Files to Demo Directory
    files_to_move = [f for f in os.listdir("example_outputs") if (f.endswith(".json") or f.endswith(".png")) and player_name_to_heatmap.replace(' ', '_') in f]



    for file_to_move in files_to_move:
        src_path = os.path.join("example_outputs", file_to_move)
        dest_path = os.path.join(demo_output_dir, file_to_move)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(src_path, dest_path)
    print(f"Moved generated files for {player_name_to_heatmap} to {demo_output_dir}")


if __name__ == "__main__":
    # SECTION: COMMAND LINE ARGUMENT PARSING AND SETUP
    # =================================================
    # SUB-SECTION: Parse Command Line Arguments
    parser = argparse.ArgumentParser(description="Analyze CS2 demo files for player positions at specific times.")
    parser.add_argument("--demo", type=str, required=False, help="Path to the .dem CS2 demo file.")
    parser.add_argument("--player", type=str, required=True, help="Name of the player or 1-based index to generate heatmaps for.")

    args = parser.parse_args()

    demo_file_path_arg = args.demo
    if not demo_file_path_arg:
        demo_file_path_arg = input("Please enter the path to the .dem CS2 demo file: ")

    # SUB-SECTION: Demo File Validation and Loading
    if not os.path.exists(demo_file_path_arg):
        print(f"Error: Demo file not found at '{demo_file_path_arg}'")
        exit()

    print(f"Loading and parsing demo: {demo_file_path_arg}...")
    try:
        demo_object_main = Demo(demo_file_path_arg)
        demo_object_main.parse(player_props=["X", "Y", "Z", "side"])
        print("Demo parsing complete.")
    except Exception as e:
        print(f"Error during initial demo.parse(): {e}")
        print("This could be due to a corrupt or incompatible demo file, or an issue within awpy.")
        exit()

    # SUB-SECTION: Validate Demo Data Integrity
    if not hasattr(demo_object_main, 'rounds') or demo_object_main.rounds is None or \
       not hasattr(demo_object_main, 'ticks') or demo_object_main.ticks is None:
        print("Demo parsing did not populate essential data (rounds or ticks). The demo may be empty, corrupt, or incompatible.")
        exit()

    main_ticks_df = demo_object_main.ticks.to_pandas()
    main_rounds_df = demo_object_main.rounds.to_pandas()

    # SUB-SECTION: Tickrate Validation
    if demo_object_main.tickrate is None:
        print("Warning: Tickrate not found in demo header. Assuming 128 for analysis.")
    else:
        print(f"Using tickrate: {demo_object_main.tickrate}")

    # SUB-SECTION: Player Data Validation and Selection Logic
    if main_ticks_df.empty or 'name' not in main_ticks_df.columns: # Corrected quotes
        print("No player tick data or 'name' column found in the demo.")
        exit()

    available_players = sorted(main_ticks_df['name'].dropna().unique())
    if not available_players:
        print("No players found in the demo tick data.")
        exit()

    player_name_to_analyze_main = None
    player_arg = args.player

    if player_arg.isdigit():
        try:
            player_idx = int(player_arg)
            if 1 <= player_idx <= len(available_players):
                player_name_to_analyze_main = available_players[player_idx - 1]
                print(f"Player argument '{player_arg}' interpreted as index. Analyzing player: {player_name_to_analyze_main}")
            else:
                print(f"Error: Player index '{player_idx}' is out of range (1-{len(available_players)}).")
        except ValueError:
            print(f"Error: Could not parse player index '{player_arg}'.")
    else:
        if player_arg in available_players:
            player_name_to_analyze_main = player_arg
            print(f"Analyzing player by name: {player_name_to_analyze_main}")
        else:
            print(f"Error: Player name '{player_arg}' not found in the demo.")

    if not player_name_to_analyze_main:
        print("No valid player selected for analysis.")
        print("Available players in this demo (use name or 1-based index for --player):")
        for i, name in enumerate(available_players, 1):
            print(f"  {i}. {name}")
        exit()
      # SECTION: EXECUTE ANALYSIS
    # =========================
    # SUB-SECTION: Create Output Directory
    if not os.path.exists("example_outputs"):
        os.makedirs("example_outputs")
        print("Created directory: example_outputs")

    # SUB-SECTION: Run Main Analysis Function
    analyze_demo(demo_object_main, main_ticks_df, main_rounds_df, player_name_to_analyze_main, demo_file_path_arg)

    # SUB-SECTION: Display Completion Message and Available Players
    print("\nAnalysis process complete.")
    # Change this to 3 players per line for better readability
    print("\nYou can re-run the script with --player <name or index> to generate heatmaps for a different player.")
    print("Available players in this demo (use name or 1-based index for --player):")
    for i, name in enumerate(available_players, 1):
        if i % 10 == 1:
            print()
        print(f"  {i}. {name}", end=' ')
