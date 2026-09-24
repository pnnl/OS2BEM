# OS2BEM Occupancy and Building Energy Model Workflow

This directory contains the tracked tools and inputs for converting occupancy
simulation data into EnergyPlus schedules, applying those schedules to an IDF,
running an EnergyPlus simulation, and summarizing the results.

## Requirements

- Python 3.9 or newer
- `pandas`
- `eppy` for IDF editing and EnergyPlus execution
- `matplotlib` and `numpy` for result postprocessing
- A local EnergyPlus installation with a compatible IDD, currently configured as
  `C:\EnergyPlusV24-2-0\Energy+.idd` in `occ_hvac.py`

## Directory Layout

```text
OS2BEM/
	generate_schedule_files.py
	occ_hvac.py
	energy_postprocessing.py
	idfs/
	weather/
	Occ sim inputs-Presets/
	HVAC and lighting schedules/
	gbxml_zone_space_mapping.json
	gbxml_spaces_cd_hvac.csv
	gbxml_inputs/
		gbxml_spaces_hvac.py
		gbxml_cd_hvac.xml
```

`generate_schedule_files.py` converts room-level occupancy data into:

- A binary lighting schedule with one column per input space.
- A binary HVAC schedule with one column per mapped thermal zone.

`gbxml_spaces_hvac.py` is an optional preprocessing utility for refreshing the
OS2BEM space and zone mappings after a new Revit/System Analysis gbXML export.
It reads `gbxml_inputs/gbxml_cd_hvac.xml` and writes
`gbxml_spaces_cd_hvac.csv` and `gbxml_zone_space_mapping.json` into OS2BEM.
Run it from the repository root when the gbXML source changes:

```powershell
python .\OS2BEM\gbxml_inputs\gbxml_spaces_hvac.py
```

During this process, `gbxml_spaces_hvac.py` parses the `Zone` and `Space`
elements in `gbxml_inputs/gbxml_cd_hvac.xml`. It first maps each gbXML zone ID
to its zone name, then uses each space's `zoneIdRef` and space name to build a
JSON object whose keys are thermal-zone names and whose values are lists of
spaces assigned to those zones. The script writes that object to
`OS2BEM/gbxml_zone_space_mapping.json`, overwriting the existing file so the
schedule generator can use the refreshed mapping. It also writes the space ID
and name table to `OS2BEM/gbxml_spaces_cd_hvac.csv`.

## Input Files

The occupancy CSV must contain one column per space. The script ignores the
case-insensitive metadata columns `Step`, `Time`, and `Whole building`, along with
columns whose names contain `Unnamed`. All other columns must contain numeric
occupancy values.

The zone-space mapping must be a JSON object whose keys are zone names and whose
values are lists of space names. An occupancy column is matched to either an
identical space name or the identifier at the start of a descriptive space name.
For example, column `110A` matches `110A Open Office`.

```json
{
	"CORE_BOT": [
		"110A Open Office",
		"110B Open Office"
	],
	"PERIMETER_BOT_ZN_1": [
		"127 Private Office"
	]
}
```

Every occupancy column must map to exactly one zone.

## Python API

All input and output locations are supplied to `generate_files`; they may be
strings or `pathlib.Path` objects.

```python
from pathlib import Path

from OS2BEM.generate_schedule_files import generate_files

base_path = Path("OS2BEM")
output_path = base_path / "generated_schedules"

lighting_path, hvac_path = generate_files(
		occupancy_schedule="TYPI",
		sensing_logic="ANY",
		occupancy_file_path=base_path / "Occ sim inputs-Presets" / "occSim_TYPI.csv",
		mapping_file_path=base_path / "gbxml_zone_space_mapping.json",
		lighting_file_path=output_path / "lighting_schedule_TYPI.csv",
		hvac_file_path=output_path / "hvac_schedule_TYPI_ANY.csv",
)
```

The function creates missing output directories, overwrites existing destination
files, and returns the two resolved output paths as `(lighting_path, hvac_path)`.

`occupancy_schedule` must be one of `TYPI`, `HAHM`, `HALM`, or `HBLM`.
`sensing_logic` must be one of:

- `ANY`: HVAC is ON when any occupancy-input space mapped to the zone is occupied.
- `ALL`: HVAC is ON when every occupancy-input space mapped to the zone is occupied.
- `OCC_FRACTION`: HVAC is ON when the zone's summed occupancy exceeds the selected
	fraction of its peak summed occupancy over the full input schedule.

For `OCC_FRACTION`, pass an `occupancy_fraction` from `0` through `1`:

```python
generate_files(
		occupancy_schedule="TYPI",
		sensing_logic="OCC_FRACTION",
		occupancy_file_path=base_path / "Occ sim inputs-Presets" / "occSim_TYPI.csv",
		mapping_file_path=base_path / "gbxml_zone_space_mapping.json",
		lighting_file_path=output_path / "lighting_schedule_TYPI.csv",
		hvac_file_path=output_path / "hvac_schedule_TYPI_OCC_FRACTION_0.5.csv",
		occupancy_fraction=0.5,
)
```

## Batch Generation

Run the script from any working directory:

```powershell
python .\OS2BEM\generate_schedule_files.py
```

Batch mode resolves paths relative to `generate_schedule_files.py`. It reads
`occSim_*.csv` files from `Occ sim inputs-Presets` and writes schedules under
`HVAC and lighting schedules`.

For each input schedule, batch mode generates HVAC outputs for `ANY`, `ALL`, and
`OCC_FRACTION` thresholds `0.25`, `0.5`, and `0.75`. The lighting schedule is the
same for every HVAC mode and is written to one file per occupancy schedule.

## Run an EnergyPlus Experiment

`occ_hvac.py` applies occupancy-driven People, lighting, HVAC setpoint, and
ventilation controls to an IDF and runs EnergyPlus. It is compatible with
EnergyPlus syntax for versions 22.1 and 24.1.

Run it from the repository root after generating schedules:

```powershell
python .\OS2BEM\occ_hvac.py `
	--idf cd_v3_hvac_portland.idf `
	--schedule-dir ".\OS2BEM\HVAC and lighting schedules" `
	--hvac-schedule hvac_schedule_TYPI_ANY_new.csv `
	--occupancy-dir ".\OS2BEM\Occ sim inputs-Presets" `
	--occupancy-file occSim_TYPI.csv `
	--output-dir ".\OS2BEM\experiments\original_TYPI_ANY" `
	--update-people-schedule `
	--apply-light-controls `
	--apply-setpoint-controls `
	--apply-ventilation-controls
```

The IDF filename is resolved from `OS2BEM/idfs`, and weather files are resolved
from `OS2BEM/weather`. The command-line output directory is dedicated to that
experiment and receives the generated IDF, EnergyPlus files, debug artifacts,
and processed results under `results/`.

### Control Strategies

The control flags near the top of `occ_hvac.py` enable four cumulative strategy
levels. Each level includes the controls from the preceding levels:

| Strategy | Controls applied |
| --- | --- |
| Baseline | No occupancy-driven People, lighting, temperature, or ventilation controls. |
| Strategy 1 | Updates each EnergyPlus `People` object with its matching occupancy `Schedule:File`; unmatched spaces use the `Always_Off` schedule. People objects are normalized to one person so the schedule supplies the occupancy signal. |
| Strategy 2 | Strategy 1 plus occupancy-based lighting schedules. Lighting is on when the corresponding occupancy input is greater than zero and off otherwise. |
| Strategy 3 | Strategy 2 plus occupancy-driven HVAC temperature setback. Zone heating and cooling setpoint schedules are connected to HVAC status schedules, with EMS logic widening setpoints during unoccupied periods. |
| Strategy 4 | Strategy 3 plus occupancy-driven ventilation control. EMS logic reduces outdoor-air ventilation to the standby fraction when a zone has no occupants and restores full ventilation when occupied. |

The script derives the output label (`baseline`, `strategy1`, `strategy2`,
`strategy3`, or `strategy4`) from the highest enabled cumulative level. To select
a higher strategy, keep all preceding controls enabled as well; for example,
Strategy 3 requires `update_people_schedule`, `apply_light_controls`, and
`apply_setpoint_controls` to be enabled.

The four controls are boolean command-line options. They default to enabled to
preserve the full Strategy 4 behavior shown above. Use the corresponding
`--no-...` form to disable a control. For example, run Strategy 2 with:

```powershell
python .\OS2BEM\occ_hvac.py `
	--idf cd_v3_hvac_portland.idf `
	--schedule-dir ".\OS2BEM\HVAC and lighting schedules" `
	--hvac-schedule hvac_schedule_TYPI_ANY_new.csv `
	--occupancy-dir ".\OS2BEM\Occ sim inputs-Presets" `
	--occupancy-file occSim_TYPI.csv `
	--output-dir ".\OS2BEM\experiments\strategy2" `
	--no-apply-setpoint-controls `
	--no-apply-ventilation-controls
```

Use all four `--no-...` options for the baseline configuration. The selected
strategy is included in generated IDF and EnergyPlus output filenames.

## Postprocess Results

`energy_postprocessing.py` aggregates experiment meter files and creates energy,
control-setback, and comfort summaries with charts:

```powershell
python .\OS2BEM\energy_postprocessing.py `
	--experiments-folder ".\OS2BEM\experiments" `
	--output-folder ".\OS2BEM\postprocessing"
```

The postprocessor expects experiment folders containing `results/Annual Results`
and `results/Hourly Results` outputs from `occ_hvac.py`.