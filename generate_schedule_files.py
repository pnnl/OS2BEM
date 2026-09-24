import json
from pathlib import Path
from typing import Dict, List, Tuple, Union

import pandas as pd


PathLike = Union[str, Path]
VALID_OCCUPANCY_SCHEDULES = {"TYPI", "HAHM", "HALM", "HBLM"}
VALID_SENSING_LOGIC = {"ANY", "ALL", "OCC_FRACTION"}


def generate_files(
    occupancy_schedule: str,
    sensing_logic: str,
    occupancy_file_path: PathLike,
    mapping_file_path: PathLike,
    lighting_file_path: PathLike,
    hvac_file_path: PathLike,
    occupancy_fraction: float = 0,
) -> Tuple[Path, Path]:
    """Generate binary HVAC and lighting schedule CSV files.

    Lighting is ON for a space whenever its occupancy is greater than zero.
    HVAC is aggregated by zone according to ``sensing_logic``. ``ANY`` turns
    HVAC on when any input space in the zone is occupied, while ``ALL`` requires
    every input space in the zone to be occupied. ``OCC_FRACTION`` turns HVAC on
    when a zone's summed occupancy exceeds ``occupancy_fraction`` times that
    zone's peak summed occupancy over the input schedule.

    Args:
        occupancy_schedule: Schedule label. Must be TYPI, HAHM, HALM, or HBLM.
        sensing_logic: Zone HVAC aggregation mode: ANY, ALL, or OCC_FRACTION.
        occupancy_file_path: Input occupancy CSV path.
        mapping_file_path: Input zone-to-space mapping JSON path.
        lighting_file_path: Destination lighting schedule CSV path.
        hvac_file_path: Destination HVAC schedule CSV path.
        occupancy_fraction: OCC_FRACTION threshold in the inclusive range 0 to 1.

    Returns:
        Resolved lighting and HVAC output paths, in that order.

    Raises:
        FileNotFoundError: An input file does not exist.
        ValueError: An option, threshold, mapping structure, or space mapping is invalid.
    """
    print(f"Generating schedule files for occupancy schedule: {occupancy_schedule} with sensing logic: {sensing_logic}")
    if occupancy_schedule not in VALID_OCCUPANCY_SCHEDULES:
        raise ValueError("Invalid occupancy schedule type. Choose from 'TYPI', 'HAHM', 'HALM', 'HBLM'.")
    if sensing_logic not in VALID_SENSING_LOGIC:
        raise ValueError("Invalid sensing logic. Choose from 'ANY', 'ALL', or 'OCC_FRACTION'.")
    if not 0 <= occupancy_fraction <= 1:
        raise ValueError("occupancy_fraction must be between 0 and 1.")

    occupancy_file_path = Path(occupancy_file_path).expanduser().resolve()
    mapping_file_path = Path(mapping_file_path).expanduser().resolve()
    lighting_file_path = Path(lighting_file_path).expanduser().resolve()
    hvac_file_path = Path(hvac_file_path).expanduser().resolve()

    if not occupancy_file_path.is_file():
        raise FileNotFoundError(f"Occupancy schedule file not found: {occupancy_file_path}")
    occupancy_data = pd.read_csv(occupancy_file_path)

    if not mapping_file_path.is_file():
        raise FileNotFoundError(f"Zone-space mapping file not found: {mapping_file_path}")
    with mapping_file_path.open("r", encoding="utf-8") as f:
        zone_space_mapping = json.load(f)
    if not isinstance(zone_space_mapping, dict) or not all(
        isinstance(zone, str)
        and isinstance(spaces, list)
        and all(isinstance(space, str) for space in spaces)
        for zone, spaces in zone_space_mapping.items()
    ):
        raise ValueError("Zone-space mapping must be a JSON object whose values are lists of space names.")

    hvac_schedule_data = pd.DataFrame()
    metadata_columns = {"step", "time", "whole building"}
    occupancy_columns: List[str] = [
        column
        for column in occupancy_data.columns
        if str(column).strip().lower() not in metadata_columns
        and "unnamed" not in str(column).lower()
    ]
    column_to_zone: Dict[str, str] = {}
    for column in occupancy_columns:
        identifier = str(column).strip()
        matching_zones = {
            zone
            for zone, spaces in zone_space_mapping.items()
            if any(space == identifier or space.startswith(f"{identifier} ") for space in spaces)
        }
        if not matching_zones:
            raise ValueError(f"Space identifier '{column}' not found in zone-space mapping.")
        if len(matching_zones) > 1:
            raise ValueError(f"Space identifier '{column}' is mapped to multiple zones.")
        column_to_zone[identifier] = matching_zones.pop()
    lighting_schedule_data = occupancy_data[occupancy_columns].gt(0).astype(int)

    if sensing_logic in ["ANY", "ALL"]:
        for column in occupancy_columns:
            occupancy_signal = occupancy_data[column].gt(0).astype(int)
            zone_name = column_to_zone[str(column).strip()]

            if zone_name not in hvac_schedule_data.columns:
                hvac_schedule_data[zone_name] = occupancy_signal
            elif sensing_logic == "ANY":
                hvac_schedule_data[zone_name] = hvac_schedule_data[zone_name] | occupancy_signal
            else:
                hvac_schedule_data[zone_name] = hvac_schedule_data[zone_name] & occupancy_signal
    else:
        for zone in zone_space_mapping:
            total_occupancy = pd.Series(0, index=occupancy_data.index)
            for column in occupancy_columns:
                if column_to_zone[str(column).strip()] == zone:
                    total_occupancy += occupancy_data[column]
            hvac_schedule_data[zone] = total_occupancy.gt(
                occupancy_fraction * total_occupancy.max()
            ).astype(int)

    lighting_file_path.parent.mkdir(parents=True, exist_ok=True)
    lighting_schedule_data.to_csv(lighting_file_path, index=False)

    hvac_file_path.parent.mkdir(parents=True, exist_ok=True)
    hvac_schedule_data.to_csv(hvac_file_path, index=False)
    return lighting_file_path, hvac_file_path


if __name__ == "__main__":
    base_path = Path(__file__).resolve().parent
    occ_data_folder = base_path / "Occ sim inputs-Presets"
    mapping_file_path = base_path / "gbxml_zone_space_mapping.json"
    output_folder = base_path / "HVAC and lighting schedules"
    if not occ_data_folder.is_dir():
        raise FileNotFoundError(f"Occupancy data folder not found: {occ_data_folder}")

    for occupancy_file_path in occ_data_folder.glob("occSim_*.csv"):
        occupancy_schedule = occupancy_file_path.stem.removeprefix("occSim_")
        for sensing_logic in ["ANY", "ALL"]:
            generate_files(
                occupancy_schedule,
                sensing_logic,
                occupancy_file_path,
                mapping_file_path,
                output_folder / f"lighting_schedule_{occupancy_schedule}_new.csv",
                output_folder / f"hvac_schedule_{occupancy_schedule}_{sensing_logic}_new.csv",
            )
        for fraction in [0.25, 0.5, 0.75]:
            generate_files(
                occupancy_schedule,
                sensing_logic="OCC_FRACTION",
                occupancy_file_path=occupancy_file_path,
                mapping_file_path=mapping_file_path,
                lighting_file_path=output_folder / f"lighting_schedule_{occupancy_schedule}_new.csv",
                hvac_file_path=output_folder
                / f"hvac_schedule_{occupancy_schedule}_OCC_FRACTION_{fraction}_new.csv",
                occupancy_fraction=fraction,
            )
