'''Note: This script is compatible with EnergyPlus version v22.1 and v24.1.
The script was not checked for other EnergyPlus versions,
be aware the syntax may vary in other versions.'''

### Import libraries
import os
import shutil
import logging
import argparse
from timeit import default_timer as timer
import pandas as pd
from eppy.modeleditor import IDF

force_simulation = True
t = timer()

########   Simulation Configuration Parameters ########
### Assign the design phase - Currently this script is designed to work for "CD" design phase
#design_phase = "CD"
city = 'portland'                                   # Defines the simulation location (tampa, portland, denver, rochester)
approach = "ANY"                                    # Control strategy approach ("ALL" or "ANY")
occ_config = "TYPI"                                 # Occupant profile configuration options ("TYPI", "HBLM", "HALM", "HAHM")
update_people_schedule = True                       # True will update the "People" object schedule in the IDF file using Occsim-generated occupancy profiles.
apply_light_controls = True                         # Temporary to check the impact of lighting controls
apply_setpoint_controls = True                      # True enables HVAC setpoint controls based on occupancy profiles
apply_ventilation_controls = True                   # True enables ventilation control modifications
input_occsim_sch_timestep = 5                       # Timestep (in mins) of the occupancy profiles and corresponding HVAc status inputs
reporting_frequency = "Timestep"                    # Output variable reporting frequency ("Hourly" or "Timestep")
occupied_hours_start = 8                            # Start of building occupied hours - typical operating hours
occupied_hours_end = 17                             # End of occupied building hours (17 is 6pm) - typical operating hours (may want to consider following prototype idf setpint schedule i.e., until 10pm)
setback_occ_standby = 0.555555556                   # Setback widening temperature (in °C) during occupied standby mode, which is 1°F below/above typical heating/cooling setpoint
simulation_start = [1,1]
simulation_end = [12,31]

input_occsim_sch = f'occSim_{occ_config}.csv'                     #Specify occsim schedule, ensure consistent formatting "occsim_T10". The suffix following the underscore "_" is used to identify the file and helps differentiate the output files across various simulation scenarios.
schedule_suffix = "new"
input_hvac_status_sch = f"hvac_schedule_{occ_config}_{approach}_{schedule_suffix}.csv"  #Specify the file with hvac status schedules.
simulation_timestep = 60/input_occsim_sch_timestep                #Simulation Timestep (1 = 60mins, 4 = 15mins, 12 = 5mins)

def get_control_string():
    """Return the highest cumulative control strategy enabled by the flags."""
    strategy_1 = update_people_schedule
    strategy_2 = apply_light_controls and strategy_1
    strategy_3 = apply_setpoint_controls and strategy_2
    strategy_4 = apply_ventilation_controls and strategy_3

    if strategy_1 and not(strategy_2 or strategy_3 or strategy_4):
        return "strategy1"
    if strategy_2 and not(strategy_3 or strategy_4):
        return "strategy2"
    if strategy_3 and not(strategy_4):
        return "strategy3"
    if strategy_4:
        return "strategy4"
    return "baseline"


control_string = get_control_string()

########  Setup Directories and Folders ########
iddfile = "C:\\EnergyPlusV24-2-0\\Energy+.idd"
file_path = os.path.dirname(os.path.abspath(__file__))
idf_filename = f"cd_v3_hvac_{city}_original.idf"
os2bem_dir = file_path
schedule_dir = os.path.join(os2bem_dir, "HVAC and lighting schedules")
occupancy_dir = os.path.join(os2bem_dir, "Occ sim inputs-Presets")
space_mapping_path = os.path.join(os2bem_dir, "gbxml_spaces_cd_hvac.csv")
experiment_dir = os.path.join(file_path, "experiments", f"{os.path.splitext(idf_filename)[0]}_{occ_config}_{approach}")
eplus_outdir = os.path.join(file_path, "idfs", f"eplus_{approach}_{occ_config}_{control_string}_110525")
weather = {'tampa': 'USA_FL_Tampa.Intl.AP.722110_TMY3.epw',
       'portland': 'USA_OR_Portland.Intl.AP.726980_TMY3.epw',
       'rochester': 'USA_MN_Rochester.Intl.AP.726440_TMY3.epw'}
epw = os.path.join(file_path, "weather", f"{weather[city]}")

input_hvac_status_sch_path = os.path.join(schedule_dir, input_hvac_status_sch)
input_occsim_sch_path = os.path.join(occupancy_dir, input_occsim_sch)
## Add Output folders
output_dir = os.path.join(file_path, "output_110525")
outdir_folders = [os.path.join(output_dir, 'Additional Results'), os.path.join(output_dir, 'Annual Results'), os.path.join(output_dir, 'Hourly Results'), os.path.join(file_path, 'debug')]
for folder in outdir_folders:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Configure logging to write print messages to a log file
logging.basicConfig(filename=os.path.join(file_path, "debug", f"logfile_{approach}_{occ_config}.log"), level=logging.INFO, format="%(asctime)s - %(message)s", filemode="w")
logging.info(f'Processing {input_hvac_status_sch}, with {input_occsim_sch_timestep}min timestep input and simulation timestep of {simulation_timestep}')

def get_terminal_for_zone(idf: IDF, zone: str):
    '''
    Return the VAV terminal name serving a given thermal zone.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - zone (str): Zone name to match against ZoneHVAC:EquipmentConnections.

    Output:
    - str: Air terminal name from ZoneHVAC:AirDistributionUnit.

    Key parameters and behavior:
    - Matching is case-insensitive and uses substring containment for zone names.
    - Assumes one matching equipment connection and one primary terminal path.
    '''
    zone_equipment_connections = idf.idfobjects['ZoneHVAC:EquipmentConnections'.upper()]
    for connection in zone_equipment_connections:
        if zone.upper() in connection.Zone_Name.upper():
            reqd_equip_list = connection.Zone_Conditioning_Equipment_List_Name
            break

    equip_list_object = idf.getobject('ZoneHVAC:EquipmentList'.upper(), reqd_equip_list)
    reqd_equip_name = equip_list_object.Zone_Equipment_1_Name
    equip_object = idf.getobject('ZoneHVAC:AirDistributionUnit'.upper(), reqd_equip_name)
    terminal_name = equip_object.Air_Terminal_Name

    return terminal_name

def generate_lighting_schedule(input_occsim: pd.DataFrame, light_schedule_path: str, source_path: str = None)-> pd.DataFrame:
    '''
    Build binary lighting schedules from occupancy-schedule data.

    Inputs:
    - input_occsim (pd.DataFrame): Occupancy schedule table. The function uses
        columns from index 2 to -2 as room schedules.
    - light_schedule_path (str): Output CSV path for generated lighting schedules.

    Output:
    - pd.DataFrame: Lighting schedule DataFrame with values mapped to 0 or 1.

    Key parameters and behavior:
    - Any value >= 1 is mapped to 1; all other values are mapped to 0.
    - Writes the generated schedule CSV to light_schedule_path.
    '''
    if source_path:
        shutil.copy2(source_path, light_schedule_path)
        return pd.read_csv(source_path)

    ### Convert occupancy sch values to lighting fractional schedule (0 or 1)
    ### If the original schedule value is equal or greater than 1, replace with 1, otherwise replace with 0.
    df_lights = input_occsim.iloc[:, 2:-2]
    df_lights = df_lights.applymap(lambda x: 1 if x >= 1 else 0)  # May need to update in future if there are fractional values.
    df_lights.to_csv(light_schedule_path, index=False)
    return df_lights

def edit_simulation_run_period(idf: IDF, run_period_name: str, simulation_start: list, simulation_end: list):
    '''
    Update the IDF RunPeriod object with simulation start and end dates.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - run_period_name (str): Name of the RunPeriod object to edit.
    - simulation_start (list): [month, day] start date.
    - simulation_end (list): [month, day] end date.

    Output:
    - None.

    Key parameters and behavior:
    - Expects simulation_start and simulation_end to be two-item lists.
    - Mutates the IDF object in place.
    '''
    # Edit simulation run period
    run_period_object = idf.getobject('RunPeriod'.upper(), run_period_name)
    run_period_object.Begin_Month = simulation_start[0]
    run_period_object.Begin_Day_of_Month = simulation_start[1]
    run_period_object.End_Month = simulation_end[0]
    run_period_object.End_Day_of_Month = simulation_end[1]

def extract_zone_hvac_status_mapping(idf: IDF, df_hvac_status: pd.DataFrame)->tuple[dict[str, int], list[str]]:
    '''
    Map IDF thermal zones to HVAC status schedule column numbers.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - df_hvac_status (pd.DataFrame): HVAC status schedules loaded from CSV.

    Output:
    - tuple[dict[str, int], list[str]]:
      1) Dictionary mapping zone name to 1-based CSV column index.
      2) List of non-plenum zone names from the IDF.

    Key parameters and behavior:
    - Excludes zones containing "plenum" in the zone name.
    - Applies temporary renaming CORE_BOTTOM -> CORE_BOT for consistency.
    '''
    # Extract Zone names from the IDF file
    hvac_zones = [zone.Name for zone in idf.idfobjects['ZONE'] if "plenum" not in zone.Name.lower()]
    # Read the column numbers correponding to each thermal zone to use in th next step
    if "CORE_BOTTOM" in df_hvac_status.columns: # This is temporary and should be deleted later. The thermal zone name was changed to (Core_Bot) in Revit for consistency (Occsim files need to be updated)
        df_hvac_status.rename(columns={"CORE_BOTTOM": "CORE_BOT"}, inplace=True)
    #df.head()
    zone_occupancy_columns = {zone: df_hvac_status.columns.get_loc(zone) + 1 for zone in hvac_zones if zone in df_hvac_status.columns}
    return zone_occupancy_columns, hvac_zones

def add_zone_people_schedule(idf:IDF, id_space_value:str, sch_column_number:int, input_occsim_sch_file:str, sch_type="Any Number"):
    '''
    Add a Schedule:File object for People schedules for a single space.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - id_space_value (str): Space identifier used to name the schedule.
    - sch_column_number (int): 1-based CSV column containing the schedule.
    - input_occsim_sch_file (str): Absolute path to occupancy schedule CSV.
    - sch_type (str): Schedule type limits name (default: "Any Number").

    Output:
    - None.

    Key parameters and behavior:
    - Creates a schedule named "<space_id>_people".
    - Uses global input_occsim_sch_timestep for Minutes_per_Item.
    - Mutates the IDF object in place.
    '''
    occ_sch = idf.newidfobject("Schedule:File")
    ## Update object attributes. Name the schedule based on the space ID and add the suffix "_people"
    occ_sch.Name = f"{id_space_value}_people"
    occ_sch.Schedule_Type_Limits_Name = sch_type
    occ_sch.File_Name = input_occsim_sch_file
    occ_sch.Column_Number = sch_column_number
    occ_sch.Rows_to_Skip_at_Top = "1"
    occ_sch.Number_of_Hours_of_Data = "8760" # Assume standard year (not a leap year)
    occ_sch.Column_Separator = "Comma"
    occ_sch.Interpolate_to_Timestep = "No"
    occ_sch.Minutes_per_Item = str(int(input_occsim_sch_timestep))

def modify_people_object(ppl_obj, sch_file_people:dict, off_sch_name:str = "Always_Off")->tuple[bool, object]:
    '''
    Assign a matching occupancy schedule to a People object, or fallback schedule.

    Inputs:
    - ppl_obj: EnergyPlus People object from idf.idfobjects["PEOPLE"].
    - sch_file_people (dict): Mapping of schedule name -> Schedule:File object.
    - off_sch_name (str): Fallback schedule name when no match exists.

    Output:
    - tuple[bool, object]:
    1) True when matched schedule is assigned, else False.
    2) Assigned schedule object when matched, else None.

    Key parameters and behavior:
    - Forces Number_of_People_Calculation_Method to "People" and Number_of_People to 1.
    - Matching is based on exact People object name lookup in sch_file_people.
    '''
    # Override the number of people to be 1 for all light objects
    ppl_obj.Number_of_People_Calculation_Method = "People"
    ppl_obj.Number_of_People = 1

    # Check if a corresponding People object with the same name exist
    # Match People object name to its corresponding schedule
    if ppl_obj.Name in sch_file_people:
        sch = sch_file_people[ppl_obj.Name]
        ppl_obj.Number_of_People_Schedule_Name = sch.Name
        return True, sch
    else:
        # If no matching People object was found, it means no occsim schedule for that space, and hence assign an always off schedule
        ppl_obj.Number_of_People_Schedule_Name = off_sch_name
        return False, None

def add_lighting_sch_object(idf, id_space_value:str, sch_column_number:int, light_schedule_path:str):
    '''
    Add a Schedule:File object for lighting schedule control for one space.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - id_space_value (str): Space identifier used to name the schedule.
    - sch_column_number (int): 1-based CSV column containing the light schedule.
    - light_schedule_path (str): Absolute path to generated light schedule CSV.

    Output:
    - None.

    Key parameters and behavior:
    - Creates a schedule named "<space_id>_lights".
    - Uses global input_occsim_sch_timestep for Minutes_per_Item.
    - Mutates the IDF object in place.
    '''
    light_sch = idf.newidfobject("Schedule:File")
    # Update object attributes. Name the schedule based on the space ID and add the suffix "_lights"
    light_sch.Name = f"{id_space_value}_lights"
    light_sch.Schedule_Type_Limits_Name = "Fractional"
    light_sch.File_Name = light_schedule_path
    light_sch.Column_Number = sch_column_number
    light_sch.Rows_to_Skip_at_Top = "1"
    light_sch.Number_of_Hours_of_Data = "8760"
    light_sch.Column_Separator = "Comma"
    light_sch.Interpolate_to_Timestep = "No"
    light_sch.Minutes_per_Item = str(int(input_occsim_sch_timestep))

def add_hvac_status_sch(idf:IDF, zone:str, column:int, input_hvac_status_sch_file:str, input_occsim_sch_timestep:int, setpoint_sch_names:dict)->tuple[bool, bool]:
    '''
    Add HVAC status schedule and cloned setpoint schedules for one zone.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - zone (str): Zone name used for schedule naming.
    - column (int): 1-based CSV column for zone HVAC status schedule.
    - input_hvac_status_sch_file (str): Absolute path to HVAC status CSV.
    - input_occsim_sch_timestep (int): Minutes per schedule item.
    - setpoint_sch_names (dict): Mapping with keys "Heating" and "Cooling"
      pointing to existing common Schedule:Compact names.

    Output:
    - tuple[bool, bool]:
      1) heating_not_found flag.
      2) cooling_not_found flag.

    Key parameters and behavior:
    - Creates "<zone>_HVACStatus_Sch" Schedule:File object.
    - Copies common heating/cooling setpoint schedules into zone-specific schedules.
    - Returns flags instead of raising, so caller can decide failure handling.
    '''
    hvac_status_sch = idf.newidfobject("SCHEDULE:FILE")
    hvac_status_sch.Name = f"{zone}_HVACStatus_Sch"
    hvac_status_sch.Schedule_Type_Limits_Name = "Fractional"
    hvac_status_sch.File_Name = input_hvac_status_sch_file
    hvac_status_sch.Column_Number = f"{column}"
    hvac_status_sch.Rows_to_Skip_at_Top = "1"
    hvac_status_sch.Number_of_Hours_of_Data = "8760"
    hvac_status_sch.Column_Separator = "Comma"
    hvac_status_sch.Interpolate_to_Timestep = "No"
    hvac_status_sch.Minutes_per_Item = str(int(input_occsim_sch_timestep))
    # Copy the existing common heating/cooling setpoint schedules and create seperate setpoint schedules for each zone
    common_htgsp = next((obj for obj in idf.idfobjects['SCHEDULE:COMPACT'] if obj.Name == setpoint_sch_names['Heating']), None)
    common_clgsp = next((obj for obj in idf.idfobjects['SCHEDULE:COMPACT'] if obj.Name == setpoint_sch_names['Cooling']), None)
    if common_htgsp:
        heating_schedule = idf.copyidfobject(common_htgsp)
        heating_schedule.Name = f"{zone}_HTGSP_Sch"
        heating_not_found = False
    else:
        heating_not_found = True
    if common_clgsp:
        cooling_schedule = idf.copyidfobject(common_clgsp)
        cooling_schedule.Name = f"{zone}_CLGSP_Sch"
        cooling_not_found = False
    else:
        cooling_not_found = True

    return heating_not_found, cooling_not_found

def add_zone_temp_setback_control(idf, zone, occupied_hours_start, occupied_hours_end, setback_occ_standby, reporting_frequency):
    '''
    Create EMS objects to apply occupancy-based temperature setback for a zone.

    Inputs:
    - idf (IDF): Parsed EnergyPlus model object.
    - zone (str): Zone name used for EMS object naming.
    - occupied_hours_start (int): Occupied-hour start (24h clock).
    - occupied_hours_end (int): Occupied-hour end (24h clock).
    - setback_occ_standby (float): Setback magnitude in degC for standby mode.
    - reporting_frequency (str): Output reporting frequency for added variables.

    Output:
    - None.

    Key parameters and behavior:
    - Adds EMS sensors, actuators, program, and program-calling manager.
    - Applies setback only on weekdays and non-holidays during occupied-hour window.
    - Adds output variables for zone-specific heating and cooling setpoint schedules.
    '''
    ems_zone = zone.replace(" ", "_")
    # Create Sensor objects
    sensor = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:SENSOR")
    sensor.Name = f"{ems_zone}_Occupancy"
    sensor.OutputVariable_or_OutputMeter_Index_Key_Name = f"{zone}_HVACStatus_Sch"
    sensor.OutputVariable_or_OutputMeter_Name = "Schedule Value"
    heating_sensor = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:SENSOR")
    heating_sensor.Name = f"{ems_zone}_HTGSP_Sch_Sens"
    heating_sensor.OutputVariable_or_OutputMeter_Index_Key_Name = f"{zone}_HTGSP_Sch"
    heating_sensor.OutputVariable_or_OutputMeter_Name = "Schedule Value"
    cooling_sensor = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:SENSOR")
    cooling_sensor.Name = f"{ems_zone}_CLGSP_Sch_Sens"
    cooling_sensor.OutputVariable_or_OutputMeter_Index_Key_Name = f"{zone}_CLGSP_Sch"
    cooling_sensor.OutputVariable_or_OutputMeter_Name = "Schedule Value"
    # Create Actuator objects
    heating_actuator = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:ACTUATOR")
    heating_actuator.Name = f"{ems_zone}_HeatSP_Act"
    heating_actuator.Actuated_Component_Unique_Name = f"{zone}"
    heating_actuator.Actuated_Component_Type = "Zone Temperature Control"
    heating_actuator.Actuated_Component_Control_Type = "Heating Setpoint"
    cooling_actuator = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:ACTUATOR")
    cooling_actuator.Name = f"{ems_zone}_CoolSP_Act"
    cooling_actuator.Actuated_Component_Unique_Name = f"{zone}"
    cooling_actuator.Actuated_Component_Type = "Zone Temperature Control"
    cooling_actuator.Actuated_Component_Control_Type = "Cooling Setpoint"
    # Create Programs to override the default setpoint schedules based on hvac status
    program = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAM")
    #print(program.fieldnames)
    program.Name = f"{ems_zone}_Setpoint_Control"
    program.Program_Line_1 = f"IF (DayOfWeek >= 2 && DayOfWeek <= 6) && (Holiday ==0)"
    program.Program_Line_2 =    f"IF ((DaylightSavings==0 && Hour >= {occupied_hours_start} &&  Hour <= {occupied_hours_end}) || (DaylightSavings==1 && Hour >= {occupied_hours_start-1} &&  Hour <= {occupied_hours_end-1}))"
    program.Program_Line_3 =        f"IF ({ems_zone}_Occupancy == 1)"
    program.Program_Line_4 =            f"SET {ems_zone}_HeatSP_Act = NULL"
    program.Program_Line_5 =            f"SET {ems_zone}_CoolSP_Act = NULL"
    program.Program_Line_6 =        f"ELSEIF ({ems_zone}_Occupancy == 0)"
    program.Program_Line_7 =            f"SET {ems_zone}_HeatSP_Act = {ems_zone}_HTGSP_Sch_Sens - {setback_occ_standby}"
    program.Program_Line_8 =            f"SET {ems_zone}_CoolSP_Act = {ems_zone}_CLGSP_Sch_Sens + {setback_occ_standby}"
    program.Program_Line_9 =        f"ENDIF"
    program.Program_Line_10 =   f"ELSE"
    program.Program_Line_11 =       f"SET {ems_zone}_HeatSP_Act = NULL"
    program.Program_Line_12 =       f"SET {ems_zone}_CoolSP_Act = NULL"
    program.Program_Line_13 =   f"ENDIF"
    program.Program_Line_14 = f"ELSE"
    program.Program_Line_15 =   f"SET {ems_zone}_HeatSP_Act = NULL"
    program.Program_Line_16 =   f"SET {ems_zone}_CoolSP_Act = NULL"
    program.Program_Line_17 = f"ENDIF"
    # Create Program Calling Manager objects
    prog_calling_manager = idf.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAMCALLINGMANAGER")
    #print(prog_calling_manager.fieldnames)
    prog_calling_manager.Name = f"{ems_zone}_Setpoint_Manager"
    prog_calling_manager.EnergyPlus_Model_Calling_Point = "BeginTimestepBeforePredictor"
    prog_calling_manager.Program_Name_1 = program.Name
    # Create Output:Variable objects to report and check the schedules
    # Heating Setpoint Sch
    output_variable_heat = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_heat.Key_Value = f"{zone}_HTGSP_Sch"
    output_variable_heat.Variable_Name = "Schedule Value"
    output_variable_heat.Reporting_Frequency = reporting_frequency
    # Cooling Setpoint Sch
    output_var_cooling = idf.newidfobject("OUTPUT:VARIABLE")
    output_var_cooling.Key_Value = f"{zone}_CLGSP_Sch"
    output_var_cooling.Variable_Name = "Schedule Value"
    output_var_cooling.Reporting_Frequency = reporting_frequency

def generate_idf_and_simulate(file_path: str):
    '''
    Generate a scenario-specific IDF, run EnergyPlus, and export processed results.

    Key input:
    - file_path (str): Project root path. Expected to contain folders such as
        idfs/, input/, weather/, gbxml/, and debug/.

    Required global configuration (set near top of file before calling):
    - city: Must exist in the weather mapping (e.g., portland, tampa, rochester).
    - approach: HVAC strategy selector used in file names ("ALL" or "ANY").
    - occ_config: Occupancy profile label used in schedule file names
        (e.g., "TYPI", "HBLM", "HALM", "HAHM").
    - update_people_schedule, apply_light_controls, apply_setpoint_controls,
        apply_ventilation_controls: Control which IDF modifications are applied.
    - input_occsim_sch_timestep: Minutes per item in input schedules (commonly 5).
        Must match the source CSV cadence used to build Schedule:File objects.
    - reporting_frequency: "Hourly" or "Timestep" for output variables/meters.
    - simulation_start / simulation_end: [month, day] run-period bounds.
    - iddfile: Absolute path to EnergyPlus IDD compatible with the installed version.

    Required input files and dependencies:
    - Base IDF: idfs/cd_v3_hvac_{city}_071425.idf
    - Weather file: weather/<mapped_epw_for_city>
    - Occupancy schedules CSV: OS2BEM/Occ sim inputs-Presets/{input_occsim_sch}
    - HVAC status CSV: OS2BEM/HVAC and lighting schedules/{input_hvac_status_sch}
    - GBXML space mapping CSV: OS2BEM/gbxml_spaces_cd_hvac.csv

    Notes for correct operation:
    - Room/zone names across IDF, query_results.csv, and schedule CSV headers must be
        aligned. Mismatches can trigger SystemExit or incorrect schedule assignment.
    - input_occsim_sch_timestep must be consistent with CSV data resolution to avoid
        schedule misalignment.
    - This function writes debug artifacts and may overwrite
        input/gbxml_spaces_cd_hvac.csv after filtering non-conditioned spaces.

    Outputs:
    - Saves modified IDF to idfs/*_sch_{occ_config}_{approach}_{control_string}.idf.
    - Runs EnergyPlus and copies html/csv/err/edd/sql outputs into
        output_110525/{Additional Results, Annual Results, Hourly Results}.
    - Produces a post-processed meter CSV with additional kWh columns.
    '''
    # Method-level configurable parameters
    idf_template_filename = idf_filename
    debug_folder_name = "debug"
    light_schedule_filename = f"lighting_schedule_{occ_config}_{schedule_suffix}.csv"
    non_occsim_space_types = ["Hallway", "Stairwell", "Elevator", "Plenum", "Shaft"]
    run_period_name = "Run Period 1"
    heating_setpoint_schedule_name = "Heating Setpoint Schedule"
    cooling_setpoint_schedule_name = "Cooling Setpoint Schedule"

    ### Setup directories and folders for mapping space names
    #idf_template_filename = "ASHRAE901_OfficeMedium_STD2022_Portland.idf"
    debug_dir = os.path.join(experiment_dir, debug_folder_name)
    input_occsim_sch_file = os.path.join(occupancy_dir, input_occsim_sch)
    input_hvac_status_sch_file = os.path.join(schedule_dir, input_hvac_status_sch)
    source_light_schedule_path = os.path.join(schedule_dir, light_schedule_filename)
    light_schedule_path = os.path.join(experiment_dir, light_schedule_filename)
    space_mapping_gbxml = space_mapping_path
    idf_file = os.path.join(file_path, "idfs", idf_template_filename)
    local_eplus_outdir = os.path.join(experiment_dir, "energyplus")
    local_output_dir = os.path.join(experiment_dir, "results")
    for folder in [debug_dir, local_eplus_outdir, os.path.join(local_output_dir, "Additional Results"), os.path.join(local_output_dir, "Annual Results"), os.path.join(local_output_dir, "Hourly Results")]:
        os.makedirs(folder, exist_ok=True)

    input_occsim = pd.read_csv(input_occsim_sch_file)
    df_gbxml_spaces = pd.read_csv(space_mapping_gbxml)
    df_hvac_status = pd.read_csv(input_hvac_status_sch_file) # Load hvac status schedule from Occsim output file into a dataframe considering 5-mins timestep.
    input_occsim.to_csv(os.path.join(debug_dir, "input_occsim_df.csv"), index=False)
    df_gbxml_spaces_dict_before_filter = dict(zip(df_gbxml_spaces["id"], df_gbxml_spaces["space"]))
    pd.DataFrame(list(df_gbxml_spaces_dict_before_filter.items()), columns= ['id', 'space']).to_csv(os.path.join(debug_dir, "gbxml_spaces_cd_hvac_before_filter.csv"), index=False)
    # Filter out space types that are not included in the occsim
    filtered_df_gbxml_spaces = df_gbxml_spaces[~df_gbxml_spaces.apply(lambda row: row.astype(str).str.contains('|'.join(non_occsim_space_types), case=False).any(), axis=1)]

    ######## Preparing for mapping ########
    ### Read and store the column headers from input file "occsim.csv" while Skipping the firs 3 columns from the dataframe (index, Step and Time)...
    ### ... as well as the last 2 headers (whole building and unnamed columns).
    input_occsim_headers = input_occsim.columns.tolist()[2:-2]
    ## Split the space names from the gbXML file to extract room numbers and space types
    filtered_df_gbxml_spaces[['id_subroom', 'space_type']] = filtered_df_gbxml_spaces['space'].str.split(' ', n=1, expand=True)
    ## Split id_room to show room numbers only to be able to map IDs to df_gbxml_spaces
    filtered_df_gbxml_spaces['id_room'] = filtered_df_gbxml_spaces['id_subroom'].str.split('-', n = 1).str[0]
    ## Sort and save the modified df_gbxml_spaces DataFrame
    filtered_df_gbxml_spaces_sorted = filtered_df_gbxml_spaces.sort_values(by="space", ascending=True, inplace=False)
    filtered_df_gbxml_spaces_sorted.to_csv(os.path.join(file_path, "debug", "modified_gbxml_spaces_filtered_hvac.csv"), index=False)
    df_gbxml_spaces_dict = pd.Series(filtered_df_gbxml_spaces_sorted.set_index('id')[['space', 'id_room', 'space_type']].apply(tuple, axis=1)).to_dict()

    ## Initialize an empty dictionary to store the mapping
    dict_gbxml_spaces = {}
    ## Iterate over each row in the gbxml DataFrame and store some parameters
    for _, gbxml_row in filtered_df_gbxml_spaces_sorted.iterrows():
        id_space_value = gbxml_row['space']
        id_room_value = gbxml_row['id_room']
        space_type = gbxml_row['space_type']
        ## Find matching rows in query_df where "?number" matches id_room_value
        # matching_rows = query_df[query_df['?number'] == id_room_value]
        ## Check if there are any matching rows
        if id_room_value in input_occsim_headers:
            occsim_sch_value = gbxml_row['id_room']   # Assuming there is at least one match, take the "occsim" value
        else:
            ## Handle cases with no matches based on 'space type'
            occsim_sch_value = "OFF_24_7"
        ## Map the "id" from filtered_df_gbxml_spaces_sorted to the "occsim" value from query_df in the dictionary
        dict_gbxml_spaces[id_space_value] = occsim_sch_value
    ## save dictionary as csv
    filtered_df_gbxml_spaces = pd.DataFrame.from_dict(dict_gbxml_spaces, orient='index').to_csv(os.path.join(debug_dir, "dict_mapping.csv"), index=True)

    df_lights = generate_lighting_schedule(input_occsim, light_schedule_path, source_light_schedule_path)

    ## Prepare the EnergyPlus Environment for editing content
    ## Read template idf
    IDF.setiddname(iddfile)
    idf = IDF(idf_file, epw)
    ## Removing existing Output:Meter, Output:Variable and Output:Meter:MeterFileOnly, to make sure this script controls the reported variables.
    var_class  = ["Output:Meter","Output:Variable","Output:Meter:MeterFileOnly"]
    for var in var_class:
        var_class_list = list(idf.idfobjects[var])
        for object_var in var_class_list:
            idf.removeidfobject(object_var)
    # Orignal Heating and Cooling Setpoint Schedule names from the IDF
    setpoint_sch_names = {
        'Heating': heating_setpoint_schedule_name,
        'Cooling': cooling_setpoint_schedule_name,
    }

    edit_simulation_run_period(idf, run_period_name, simulation_start, simulation_end)

    zone_occupancy_columns, hvac_zones = extract_zone_hvac_status_mapping(idf, df_hvac_status)

    # Create zero fraction schedule to be used in the next block of code
    sch_off = idf.newidfobject("Schedule:Constant")
    sch_off.Name = "Always_Off"
    sch_off.Schedule_Type_Limits_Name = "Fractional"
    sch_off.Hourly_Value = 0

    ######## Updating People ########
    # If update_people_schedule is True, creates schedules of type Schedule:File based on Occsim output and assigns them to the "People" objects in the IDF
    if update_people_schedule:
        # Create a ScheduleTypeLimits object for People Schedule:File objects
        sch_type_anynumber = idf.newidfobject("ScheduleTypeLimits")
        sch_type_anynumber.Name = "Any Number"
        sch_type_anynumber.Lower_Limit_Value = 0
        sch_type_anynumber.Upper_Limit_Value = ""
        sch_type_anynumber.Numeric_Type = "Discrete"

        #### Creating Shedule:File objects ####
        # Loop through all spaces and create corresponding Schedule:File objects based on Occsim profiles (e.g., occsim_TYPI.csv) file
        # These schedules will later be assigned to the People objects
        for id_space_value, occsim_sch_value in dict_gbxml_spaces.items():
            sch_type = sch_type_anynumber.Name
            if occsim_sch_value in input_occsim:
                sch_column_number = input_occsim.columns.get_loc(occsim_sch_value) +1
            else:
                error_sch_input = f'Error: {occsim_sch_value} not in input occsim file'
                logging.info(error_sch_input)
                raise SystemExit(error_sch_input)
            add_zone_people_schedule(idf, id_space_value, sch_column_number, input_occsim_sch_file, sch_type)

        #### Assigning People Schedules to People Objects ####
        # This block overrides the number of people and links each People object to the corresponding schedule
        # We need to map the space names between occsim, Revit and EnergyPlus
        logging.info("-----------------------")
        logging.info("Processing People")
         # Collect all Schedule:File objects that were created for People schedules
        sch_file_people = {sch.Name: sch for sch in idf.idfobjects["SCHEDULE:FILE"] if "_people" in sch.Name}
        # keeping track of assigned schedules for debugging
        assigned_ppl_schedules = set()
        not_assigned_ppl_schedules = set()
        # Loop through each People object in the IDF
        for ppl_obj in idf.idfobjects["PEOPLE"]:
            off_sch_name = sch_off.Name
            result, sch = modify_people_object(ppl_obj, sch_file_people, off_sch_name)
            if result:
                assigned_ppl_schedules.add(ppl_obj.Number_of_People_Schedule_Name)
                logging.info(f"People object name has a matching Schedule:File name, assigned schedule: {sch.Name} to object: {ppl_obj.Name}")
            else:
                not_assigned_ppl_schedules.add(ppl_obj.Number_of_People_Schedule_Name)
                logging.info(f"No matching people schedule for object: {ppl_obj.Name} (space: {df_gbxml_spaces_dict_before_filter.get(ppl_obj.Name.split('_')[0], 'Unknown')}), space doesn't have occsim schedule, hence assigned schedule: {sch_off.Name}")
        for sch_name, sch in sch_file_people.items():
            if sch_name not in assigned_ppl_schedules:
                error_sch_ppl_obj = f"Error: a schedule:file object {sch_name} has no matching people object"
                logging.info(error_sch_ppl_obj)
                raise SystemExit(error_sch_ppl_obj)
        # save to csv for debugging purposes        
        assigned_ppl_sch_df = pd.concat([pd.DataFrame(sorted(list(assigned_ppl_schedules)), columns = ['assigned_ppl_sch']), pd.DataFrame(sorted(list(not_assigned_ppl_schedules)), columns = ['not assigned_ppl_sch'])], axis=1)
        assigned_ppl_sch_df.to_csv(os.path.join(debug_dir, "assigned_ppl_schedules.csv"), index = False)
        control = "PeopleOnly" #flag

    ######## Updating Lighting ########
    # If apply_occupancy_controls is True, creates schedules of type Schedule:File based on Occsim output converted to on/off schedules and assigns them to the "light" objects in the IDF
    #if apply_occupancy_controls:
    if apply_light_controls:
        control = "NoSetback" #flag
        #### Creating Shecule:File objects ####
        # Loop through all spaces and create corresponding Schedule:File objects based on on/off occsim profiles (i.e., light_sch_rooms.csv) file
        # These schedules will later be assigned to the light objects
        for id_space_value, occsim_sch_value in dict_gbxml_spaces.items():
            # Get the correct column number from the CSV for this room/space schedule
            if occsim_sch_value in df_lights:
                sch_column_number = df_lights.columns.get_loc(occsim_sch_value) +1
                add_lighting_sch_object(idf, id_space_value, sch_column_number, light_schedule_path)
            else:
                error_sch_input = f'Error: {occsim_sch_value} not in input occsim file'
                logging.info(error_sch_input)
                raise SystemExit(error_sch_input)

        #### Assigning light Schedules to light Objects ####
        logging.info("-----------------------")
        logging.info("Processing Lighting")
        # Collect all Schedule:File objects that were created for light schedules
        sch_file_lights = {sch_ltg.Name: sch_ltg for sch_ltg in idf.idfobjects["SCHEDULE:FILE"] if "_lights" in sch_ltg.Name}
        # keeping track of assigned schedules for debugging
        assigned_ltg_schedules = set()
        not_assigned_ltg_schedules = set()
        # Loop through each light object in the IDF
        for light_obj in idf.idfobjects["LIGHTS"]:
            # Check if a corresponding light object with the same name exist
            # Match light object name to its corresponding schedule
            if light_obj.Name in sch_file_lights:
                sch_ltg = sch_file_lights[light_obj.Name]
                # Check if the light object name has a matching Schedule:File name
                # Assign the Schedule:File object to the light object as a schedule
                light_obj.Schedule_Name = sch_ltg.Name
                logging.info(f"Light object name has a matching Schedule:File name, assigned schedule: {sch_ltg.Name} to object: {light_obj.Name}")
                assigned_ltg_schedules.add(sch_ltg.Name)
            else:
                # If no matching People object was found, it means no occsim schedule for that space, and hence assign an always off schedule
                light_obj.Schedule_Name = sch_off.Name
                not_assigned_ltg_schedules.add(light_obj.Name.split('_')[0])
                logging.info(f"No matching light schedule for object: {light_obj.Name} (space: {df_gbxml_spaces_dict_before_filter.get(light_obj.Name.split('_')[0], 'Unknown')}), space doesn't have occsim schedule, hence assigned schedule: {sch_off.Name}")    
                # Check orphaned schedule:file objects that might be in the IDF file but have no corresponding light object.
        for sch_ltg_name, sch_ltg in sch_file_lights.items():
            if sch_ltg_name not in assigned_ltg_schedules:
                error_sch_ltg_obj = f"Error: a schedule:file object {sch_ltg_name} has no matching light object"
                logging.info(error_sch_ltg_obj)
                raise SystemExit(error_sch_ltg_obj)
        assigned_ltg_schedules_df = pd.concat([pd.DataFrame(sorted(list(assigned_ltg_schedules)), columns = ['assigned_light_sch']), pd.DataFrame(sorted(list(not_assigned_ltg_schedules)), columns = ['not assigned_light_sch'])], axis=1)
        assigned_ltg_schedules_df.to_csv(os.path.join(debug_dir, "assigned_light_schedules.csv"), index = False)

    ######## Updating HVAC ########
    #if apply_occupancy_controls:
    if apply_setpoint_controls:
        control = "WithTempSetback"
        #### Creating Shecule:File objects for hvac status to be used as sensors for EMS setpoint control ####
        # Create Schedule:File for each zone
        for zone, column in zone_occupancy_columns.items():
            heating_not_found, cooling_not_found = add_hvac_status_sch(idf, zone, column, input_hvac_status_sch_file, input_occsim_sch_timestep, setpoint_sch_names)

            if heating_not_found:
                error_heatsp = 'Error: No Heating Setpoint Schedule found!!!'
                logging.info(error_heatsp)
                raise SystemExit(error_heatsp)
            if cooling_not_found:
                error_coolsp = 'Error: No Cooling Setpoint Schedule found!!!'
                logging.info(error_coolsp)
                raise SystemExit(error_coolsp)

        # Create a dictionary to map zone names to thermostat control names from ZoneControl:Thermostat
        zone_to_control = {}
        for zone_control in idf.idfobjects['ZONECONTROL:THERMOSTAT']:
            zone_to_control[zone_control.Zone_or_ZoneList_Name] = zone_control.Control_1_Name
        # Create a dictionary to map thermostat names to thermostat objects for easy access
        thermostat_name_to_object = {}
        for thermostat in idf.idfobjects['THERMOSTATSETPOINT:DUALSETPOINT']:
            thermostat_name_to_object[thermostat.Name] = thermostat
        # Iterate through the zone names and update the ThermostatSetpoint:DualSetpoint objects
        for zone_name, control_name in zone_to_control.items():
            if control_name in thermostat_name_to_object:
                # Get the thermostat object
                thermostat = thermostat_name_to_object[control_name]
                # Find the corresponding heating and cooling schedules
                heating_schedule_name = f"{zone_name}_HTGSP_Sch"
                cooling_schedule_name = f"{zone_name}_CLGSP_Sch"
                # Assuming the schedule names exist and correct
                # Assign the schedules to the thermostat
                thermostat.Heating_Setpoint_Temperature_Schedule_Name = heating_schedule_name
                thermostat.Cooling_Setpoint_Temperature_Schedule_Name = cooling_schedule_name

        # Create EMS objects for each zone
        for zone in hvac_zones:
            add_zone_temp_setback_control(idf, zone, occupied_hours_start, occupied_hours_end, setback_occ_standby, reporting_frequency)
    if apply_ventilation_controls:
        control = "WithVentilation"
        idf = modify_ventilation_control_objects_for_DCV(idf)

    ######## Updating Simulation Parameters and Reporting Variables ########
    ### Note: This is compatible with the currently used version of EnergyPlus (v22.1), be aware the syntax may vary in other versions
    ## Change time step to match the input timestep
    timestep = idf.idfobjects["Timestep"][0]                # Read first object in this class
    timestep.Number_of_Timesteps_per_Hour = str(int(simulation_timestep))
    ## Disable Run Simulation for Sizing Periods since we are not interested in it for now
    simulcont = idf.idfobjects["SimulationControl"][0]
    simulcont.Run_Simulation_for_Sizing_Periods = "No"
    ## Delete unnecessary sizing files in "SizingPeriod:DesignDay"
    #idf.popidfobject('SizingPeriod:DesignDay',-1) # This is done manually now
    ## Update Run Period so the first day of the year is a Sunday
    runperiod = idf.idfobjects["RunPeriod"][0]
    runperiod.Begin_Year = "2006"
    runperiod.End_Year = "2006"
    runperiod.Day_of_Week_for_Start_Day = "Sunday"
    ## Chaneg reporting style of the typical EnergyPlus html summary report and units to kWh
    output_cont = idf.idfobjects["OutputControl:Table:Style"][0]
    output_cont.Column_Separator = "CommaAndHTML"           # Reports output in both csv and html files
    output_cont.Unit_Conversion = "JtoKWH"
    ## Add Output:EnergyManagementSystem object to generate .edd file with Actuator availability and EMS Debugging
    output_ems = idf.newidfobject("Output:EnergyManagementSystem")
    output_ems.Actuator_Availability_Dictionary_Reporting = "verbose"
    output_ems.Internal_Variable_Availability_Dictionary_Reporting = "verbose"
    output_ems.EMS_Runtime_Language_Debug_Output_Level = "errorsonly"


    # Add Output:Variable object to report Occupancy Schedule
    output_variable_occ = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_occ.Key_Value = ".*_HVACStatus_Sch$"
    output_variable_occ.Variable_Name = "Schedule Value"
    output_variable_occ.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report Original People schedule
    output_variable_occ_orig = idf.newidfobject("OUTPUT:VARIABLE")
    people = idf.idfobjects["People"][5]
    people_sch = people.Number_of_People_Schedule_Name
    output_variable_occ_orig .Key_Value = people_sch
    output_variable_occ_orig .Variable_Name = "Schedule Value"
    output_variable_occ_orig .Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report Occupancy count at the thermal zone level
    output_variable_occ_count = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_occ_count.Key_Value = "*"
    output_variable_occ_count.Variable_Name = "Zone People Occupant Count"
    output_variable_occ_count.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report lighting energy use at the thermal zone level
    output_variable_light_energy = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_light_energy.Key_Value = "*"
    output_variable_light_energy.Variable_Name = "Zone Lights Electricity Energy"
    output_variable_light_energy.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report Zone Thermostat Heating Setpoint Temperature
    output_variable_occ = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_occ.Key_Value = "*"
    output_variable_occ.Variable_Name = "Zone Thermostat Heating Setpoint Temperature"
    output_variable_occ.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report Zone Thermostat Cooling Setpoint Temperature
    output_variable_occ = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_occ.Key_Value = "*"
    output_variable_occ.Variable_Name = "Zone Thermostat Cooling Setpoint Temperature"
    output_variable_occ.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report zone air Temperature
    output_variable_zone_temp = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_zone_temp.Key_Value = "*"
    output_variable_zone_temp.Variable_Name = "Zone Air Temperature"
    output_variable_zone_temp.Reporting_Frequency = reporting_frequency
    # Add Output:Variable object to report zone predicted sensible load
    output_variable_zone_load = idf.newidfobject("OUTPUT:VARIABLE")
    output_variable_zone_load.Key_Value = "*"
    output_variable_zone_load.Variable_Name = "Zone Predicted Sensible Load to Setpoint Heat Transfer Rate"
    output_variable_zone_load.Reporting_Frequency = reporting_frequency
    ## Add Output:Variable object to report hourly cooling energy use and update object attributes
    output_variable_cool= idf.newidfobject("Output:Variable")
    output_variable_cool.Key_Value = "*"                              # For all available Coil objects
    output_variable_cool.Variable_Name = "Cooling Coil Electricity Energy"
    output_variable_cool.Reporting_Frequency = reporting_frequency
    ## Add Output:Variable object to report hourly Heating energy use and update object attributes
    output_variable_heat_elec = idf.newidfobject("Output:Variable")
    output_variable_heat_elec.Key_Value = "*"                         # For all available Coil objects
    output_variable_heat_elec.Variable_Name = "Heating Coil Electricity Energy"
    output_variable_heat_elec.Reporting_Frequency = reporting_frequency
    output_variable_heat_gas = idf.newidfobject("Output:Variable")
    output_variable_heat_gas.Key_Value = "*"                          # For all available Coil objects
    output_variable_heat_gas.Variable_Name = "Heating Coil NaturalGas Energy"
    output_variable_heat_gas.Reporting_Frequency = reporting_frequency
    ## Add output variable for type of day, daylightsaving status, outdoor air and zone air temperatures  
    site_vars = ["Site Outdoor Air Drybulb Temperature", "Site Day Type Index", "Site Daylight Saving Time Status"]
    for site_var in site_vars:
        output_variable_site = idf.newidfobject("OUTPUT:VARIABLE")
        output_variable_site.Key_Value = "*"
        output_variable_site.Variable_Name = site_var
        output_variable_site.Reporting_Frequency = reporting_frequency
    for tz in ["CORE_BOT", "PERIMETER_BOT_ZN_1", "PERIMETER_BOT_ZN_2"]:
        output_variable_vent = idf.newidfobject("OUTPUT:VARIABLE")
        output_variable_vent.Key_Value = tz
        output_variable_vent.Variable_Name = "Zone Mechanical Ventilation Mass Flow Rate"
        output_variable_vent.Reporting_Frequency = reporting_frequency
    for vent_var in ["Air System Outdoor Air Mass Flow Rate", "Air System Outdoor Air Mechanical Ventilation Requested Mass Flow Rate", 'Air System Outdoor Air Limiting Factor']:
        output_variable_request_vent = idf.newidfobject("OUTPUT:VARIABLE")
        output_variable_request_vent.Key_Value = "*"
        output_variable_request_vent.Variable_Name = vent_var
        output_variable_request_vent.Reporting_Frequency = reporting_frequency
    ## Update the reporting frequency of the existing Output:Meter:MeterFileOnly
    # output_mtr_only = list(idf.idfobjects["Output:Meter:MeterFileOnly"])
    # for meter in output_mtr_only:
    #     meter.Reporting_Frequency = reporting_frequency
    ## Add new Output:Meter:MeterFileOnly to report Facility Natural Gas and Electricity energy use
    for meter in ["NaturalGas:Facility","Electricity:Facility","Cooling:Electricity","Heating:Electricity","Heating:NaturalGas", "InteriorLights:Electricity"]:
        output_mtr_only = idf.newidfobject("Output:Meter:MeterFileOnly")
        output_mtr_only.Key_Name = meter
        output_mtr_only.Reporting_Frequency = reporting_frequency

    ######## Save IDF and Run Simulation ########
    new_idf = os.path.join(experiment_dir, f"{os.path.splitext(idf_template_filename)[0]}_sch_{occ_config}_{approach}_{control_string}.idf")
    idf.saveas(new_idf)
    idf = IDF(new_idf, epw)
    idf.run(output_directory=local_eplus_outdir, readvars=True)
    ## Get results and clone to eplus_outdir
    outfile_html = os.path.join(local_output_dir, 'Additional Results', f'eplustbl_HVAC_{city}_{approach}_{control_string}_{occ_config}.html')
    outfile_edd = os.path.join(local_output_dir, 'Additional Results', f'eplustbl_HVAC_{city}_{approach}_{control_string}_{occ_config}.edd')
    outfile_err = os.path.join(local_output_dir, 'Additional Results', f'eplustbl_HVAC_{city}_{approach}_{control_string}_{occ_config}.err')
    outfile_tbl_csv = os.path.join(local_output_dir, 'Annual Results', f'eplustbl_HVAC_{city}_{approach}_{control_string}_{occ_config}.csv')
    outfile_var_csv = os.path.join(local_output_dir, 'Hourly Results', f'{reporting_frequency}_HVAC_Var_{city}_{approach}_{control_string}_{occ_config}.csv')
    outfile_Meter_csv = os.path.join(local_output_dir, 'Hourly Results', f'{reporting_frequency}_HVAC_Meter_{city}_{approach}_{control_string}_{occ_config}.csv')
    outfile_sql = os.path.join(local_output_dir, 'Hourly Results', f'{reporting_frequency}_HVAC_Meter_{city}_{approach}_{control_string}_{occ_config}.sql')
    shutil.copy(os.path.join(local_eplus_outdir, 'eplustbl.htm'), outfile_html)
    shutil.copy(os.path.join(local_eplus_outdir, "eplustbl.csv"), outfile_tbl_csv)
    shutil.copy(os.path.join(local_eplus_outdir, "eplusout.csv"), outfile_var_csv)
    shutil.copy(os.path.join(local_eplus_outdir, 'eplusout.edd'), outfile_edd)
    shutil.copy(os.path.join(local_eplus_outdir, 'eplusout.err'), outfile_err)
    shutil.copy(os.path.join(local_eplus_outdir, 'eplusout.sql'), outfile_sql)
    #shutil.copy(f"{eplus_outdir}eplusmtr.csv", outfile_Meter_csv)

    # Add new columns after converting output energy results in the meter file to kWh
    # This is considering the energyplus meter outputs will be reported in the units of "J". The code then converts the values to kWh and append to the output file
    df_meter = pd.read_csv(os.path.join(local_eplus_outdir, "eplusmtr.csv"))
    df_meter.columns = [df_meter.columns[0]] + [col.lower().strip() for col in df_meter.columns[1:]]
    df_meter['Cooling Electricity (kWh)'] = df_meter[f'Cooling:Electricity [J]({reporting_frequency})'.lower()] * 2.77778e-7
    df_meter['Heating Electricity (kWh)'] = df_meter[f'Heating:Electricity [J]({reporting_frequency})'.lower()] * 2.77778e-7
    df_meter['Heating NaturalGas (kWh)'] = df_meter[f'Heating:NaturalGas [J]({reporting_frequency})'.lower()] * 2.77778e-7
    df_meter['Total Heating Energy (kWh)'] = df_meter['Heating Electricity (kWh)'] + df_meter['Heating NaturalGas (kWh)']
    df_meter['Lighting Electricity (kWh)'] = df_meter[f'InteriorLights:Electricity [J]({reporting_frequency})'.lower()] * 2.77778e-7
    df_meter.to_csv(outfile_Meter_csv, index=False)

    endt = timer()
    elapsed = (endt-t)/60
    print(f"Simulation Completed - Elapsed Time is {elapsed} Mins")

    ### The output files to check are "eplustbl_HVAC_xxx.csv" (xxx refers to the input file name after the underscore used as identifier) for the default annual EnergyPlus summary report under output\Annual Analysis
    ## and "Hourly_HVAC_var_xxx.csv" and "Hourly_HVAC_Meter_xxx.csv"under \output\Hourly Results. Additional outputs can be found under output\Additional Results

def modify_ventilation_control_objects_for_DCV(idf_data: str, output_path: str = None):
    '''
    Add and update objects to enable occupancy-driven DCV logic by zone.

    Inputs:
    - idf_data (IDF): Parsed EnergyPlus model object to modify.
    - output_path (str | None): Optional output file path to save modified IDF.

    Output:
    - IDF: Modified IDF object.

    Key parameters and behavior:
    - ventilation_per_area: Baseline outdoor-air design flow per floor area.
    - occupied_standby_ventilation_rate: Standby OA flow used to compute
        reqd_fraction_standby.
    - For each non-plenum zone, creates a schedule, actuator, EMS program,
        and calling manager to switch between standby and full OA fractions.
    - If output_path is provided, saves the modified IDF to disk.
    '''
    ventilation_per_area = 0.0004318 # m3/s-m2
    #ventilation_per_person = 0.0025 # m3/s-person
    occupied_standby_ventilation_rate = 0 # m3/s-m2
    reqd_fraction_standby = occupied_standby_ventilation_rate/ventilation_per_area # This variable can also be directly assigned a constant fraction

    #IDF.setiddname(iddfile)
    #idf_data = IDF(input_idf, epw)

    #Make modifications for each zone
    list_of_zones = [zone.Name for zone in idf_data.idfobjects['Zone'.upper()] if 'plenum' not in zone.Name.lower()]
    for zone in list_of_zones:
        ems_zone = zone.replace(" ", "_")
        # Add sensor variable for occupancy
        # sensor = idf_data.newidfobject("ENERGYMANAGEMENTSYSTEM:SENSOR")
        # sensor.Name = f"{zone}_Occupancy"
        # sensor.OutputVariable_or_OutputMeter_Index_Key_Name = f"{zone.upper()}"
        # sensor.OutputVariable_or_OutputMeter_Name = "Zone People Occupant Count"

        # Create occupied standby schedule
        schedule_object = idf_data.newidfobject('Schedule:Compact'.upper())
        schedule_object.Name = f'{zone} occupied standby schedule'
        schedule_object.Schedule_Type_Limits_Name = 'Fractional'
        schedule_object.Field_1 = 'Through: 12/31'
        schedule_object.Field_2 = 'For: AllDays'
        schedule_object.Field_3 = 'Until: 24:00'
        schedule_object.Field_4 = '1'

        # Change the space-level outdoor-air objects referenced by this zone's sizing object.
        sizing_object = idf_data.getobject('Sizing:Zone'.upper(), zone)
        if sizing_object is None:
            continue
        space_list = idf_data.getobject(
            'DesignSpecification:OutdoorAir:SpaceList'.upper(),
            sizing_object.Design_Specification_Outdoor_Air_Object_Name,
        )
        if space_list is None:
            continue
        dsoa_objects = []
        for field_name in space_list.fieldnames:
            if field_name.endswith('_Design_Specification_Outdoor_Air_Object_Name'):
                dsoa_name = getattr(space_list, field_name)
                if dsoa_name:
                    dsoa_object = idf_data.getobject('DesignSpecification:OutdoorAir'.upper(), dsoa_name)
                    if dsoa_object is not None:
                        dsoa_objects.append(dsoa_object)
        if not dsoa_objects:
            continue
        for dsoa_object in dsoa_objects:
            dsoa_object.Outdoor_Air_Schedule_Name = schedule_object.Name
        # dsoa_object.Outdoor_Air_Method = 'Sum'
        # dsoa_object.Outdoor_Air_Flow_per_Person = ventilation_per_person
        # dsoa_object.Outdoor_Air_Flow_per_Zone_Floor_Area = ventilation_per_area

        # EMS program and other required details: Modify schedule based on measured occupancy
        # Add schedule actuator
        actuator = idf_data.newidfobject('EnergyManagementSystem:Actuator'.upper())
        actuator.Name = f'{schedule_object.Name.replace(" ", "_")}_changer'
        actuator.Actuated_Component_Unique_Name = schedule_object.Name
        actuator.Actuated_Component_Type = 'Schedule:Compact'
        actuator.Actuated_Component_Control_Type = 'Schedule Value'

        # Add EMS program
        program = idf_data.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAM")
        program.Name = f"{ems_zone}_ventilation_control"
        program.Program_Line_1 = f"IF {ems_zone}_Occupancy == 0"
        program.Program_Line_2 = f"SET {actuator.Name} = {reqd_fraction_standby}"
        program.Program_Line_3 = "ELSE"
        program.Program_Line_4 = f"SET {actuator.Name} = 1"
        program.Program_Line_5 = "ENDIF"

        # Add Program Calling Manager
        prog_calling_manager = idf_data.newidfobject("ENERGYMANAGEMENTSYSTEM:PROGRAMCALLINGMANAGER")
        prog_calling_manager.Name = f"{ems_zone}_ventilation_control_calling_manager"
        prog_calling_manager.EnergyPlus_Model_Calling_Point = "BeginTimestepBeforePredictor"
        prog_calling_manager.Program_Name_1 = program.Name

    if not output_path is None:
        idf_data.saveas(output_path)

    return idf_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one occupancy/HVAC EnergyPlus experiment.")
    parser.add_argument("--idf", required=True, help="Input IDF filename in the OS2BEM idfs directory.")
    parser.add_argument("--schedule-dir", required=True, help="Directory containing the precomputed HVAC and lighting schedules.")
    parser.add_argument("--hvac-schedule", required=True, help="HVAC schedule filename to use.")
    parser.add_argument("--occupancy-file", required=True, help="Occupancy CSV filename in the occupancy schedule directory.")
    parser.add_argument("--occupancy-dir", required=True, help="Directory containing the occupancy CSV.")
    parser.add_argument("--output-dir", required=True, help="Dedicated output directory for this experiment.")
    parser.add_argument(
        "--update-people-schedule",
        action=argparse.BooleanOptionalAction,
        default=update_people_schedule,
        help="Enable or disable occupancy-driven People schedules (default: enabled).",
    )
    parser.add_argument(
        "--apply-light-controls",
        action=argparse.BooleanOptionalAction,
        default=apply_light_controls,
        help="Enable or disable occupancy-driven lighting controls (default: enabled).",
    )
    parser.add_argument(
        "--apply-setpoint-controls",
        action=argparse.BooleanOptionalAction,
        default=apply_setpoint_controls,
        help="Enable or disable occupancy-driven HVAC setpoint controls (default: enabled).",
    )
    parser.add_argument(
        "--apply-ventilation-controls",
        action=argparse.BooleanOptionalAction,
        default=apply_ventilation_controls,
        help="Enable or disable occupancy-driven ventilation controls (default: enabled).",
    )
    args = parser.parse_args()

    update_people_schedule = args.update_people_schedule
    apply_light_controls = args.apply_light_controls
    apply_setpoint_controls = args.apply_setpoint_controls
    apply_ventilation_controls = args.apply_ventilation_controls
    control_string = get_control_string()
    idf_filename = args.idf
    schedule_dir = os.path.abspath(args.schedule_dir)
    occupancy_dir = os.path.abspath(args.occupancy_dir)
    space_mapping_path = os.path.join(os2bem_dir, "gbxml_spaces_cd_hvac.csv")
    input_hvac_status_sch = args.hvac_schedule
    input_occsim_sch = args.occupancy_file
    experiment_dir = os.path.abspath(args.output_dir)
    eplus_outdir = os.path.join(file_path, "idfs", f"eplus_{approach}_{occ_config}_{control_string}_110525")
    occ_config = os.path.splitext(input_occsim_sch)[0].removeprefix("occSim_")
    approach = "OCC_FRACTION" if "OCC_FRACTION" in input_hvac_status_sch else "ANY" if "_ANY_" in input_hvac_status_sch else "ALL"
    generate_idf_and_simulate(file_path)
