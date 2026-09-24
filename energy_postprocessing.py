'''
Analyzes table results for each simulation run, and compiles energy
consumption summaries into bar charts. Can include filters for
sensing logic, HVAC control strategies and occupancy profiles.
'''
import os
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import itertools as it
import argparse

class Filter:
    '''
    Object to carry filters for data analysis.
    '''
    def __init__(self,sensing_logic:list=None,control_strategy:list=None,occupancy_profile:list=None,end_uses:list=None):
        '''        
        :param sensing_logic: Can be one of "ALL" or "ANY"
        :type sensing_logic: str
        :param control_strategy: Can be one of "1", "2", "3", "4", or "baseline"
        :type control_strategy: str
        :param occupancy_profile: Can be one of "TYPI", "HAHM", "HALM" or "HBLM"
        :type occupancy_profile: str
        :param values: List of valid combinations of end use and fuel type from end uses summary
        table. e.g., ["Heating Electricity", "Heating Natural Gas"].
        :type values: list
        '''

        allowed_sensing_logic = ["ALL", "ANY"]
        self.sensing_logic = allowed_sensing_logic if ((sensing_logic is None) or any([sensing_logic_type not in allowed_sensing_logic for sensing_logic_type in sensing_logic])) else sensing_logic
        allowed_control_strategy = ['baseline'] + [f'strategy{i}' for i in range(1, 5)]
        add_baseline_flag = False
        if control_strategy is not None:
            if 'baseline' in control_strategy:
                control_strategy.remove('baseline')
                add_baseline_flag = True
        self.control_strategy = allowed_control_strategy if ((control_strategy is None) or any([int(strategy) not in range(1,5) for strategy in control_strategy])) else [f'strategy{strategy}' for strategy in control_strategy]
        if add_baseline_flag:
            self.control_strategy = ['baseline'] + self.control_strategy
        allowed_occupancy_profiles = ["TYPI", "HAHM", "HALM", "HBLM"]
        self.occupancy_profile = allowed_occupancy_profiles if ((occupancy_profile is None) or any([occupancy_profile_type not in allowed_occupancy_profiles for occupancy_profile_type in occupancy_profile])) else occupancy_profile
        allowed_end_uses = ["Heating Electricity", "Heating Natural Gas", "Cooling Electricity",
                            "Interior Lighting Electricity", "Fans Electricity",
                            'Exterior Lighting Electricity', 'Interior Equipment Electricity',
                            'Heating Comfort Not Met', 'Cooling Comfort Not Met']
        self.end_uses = allowed_end_uses if ((end_uses is None) or any([end_use not in allowed_end_uses for end_use in end_uses])) else end_uses

def get_relevant_results_files(folder:str, filters:Filter):
    '''
    Get list of relevant results files based on filters.
    
    :param results_folder: Path to folder with simulation results.
    :type results_folder: str
    :param filters: Filter object with filtering criteria.
    :type filters: Filter
    :return: List of relevant results file paths.
    :rtype: list
    '''
    relevant_files = []
    for root, _, files in os.walk(folder):
        for file in files:
            if file.endswith('.csv'):
                for logic in filters.sensing_logic:
                    for strategy in filters.control_strategy:
                        for profile in filters.occupancy_profile:
                            if (logic in file) and (strategy in file) and (profile in file):
                                relevant_files.append(os.path.join(root, file))

    return relevant_files

def get_reqd_summary_data(files:list, filters:Filter, fill_baseline_and_strat_1:bool=False) -> pd.DataFrame:
    '''
    Compile summary data from relevant results files in a nested dataframe
    that has nested indices for each filter in the filters object. Order
    of nesting is as follows, if each of the below exists in the filters object:
    occupancy_profile > sensing_logic > control_strategy.
    
    :param files: List of relevant results file paths.
    :type files: list
    :param filters: Filter object with filtering criteria.
    :type filters: Filter
    :return: DataFrame with compiled summary data.
    :rtype: pd.DataFrame
    '''
    array_1 = []
    array_2 = []
    array_3 = []
    array_4 = []
    for profile in filters.occupancy_profile:
        for logic in filters.sensing_logic:
            for strategy in filters.control_strategy:
                for end_use in filters.end_uses:
                    array_1.append(profile)
                    array_2.append(logic)
                    array_3.append(strategy)
                    array_4.append(end_use)
    summary_data_index = pd.MultiIndex.from_arrays([array_1,array_2,array_3,array_4], names=["occupancy_profile", "sensing_logic", "control_strategy", "end_uses"])
    summary_data=pd.DataFrame(index=summary_data_index, columns=['values'])
    for row in summary_data.index:
        for file in files:
            if all([row[0].lower() in file.lower(), row[1].lower() in file.lower(), row[2].lower() in file.lower()]):
                print(file)
                data = pd.read_csv(file,skiprows=48,index_col=1,nrows=14)
                if 'electricity' in row[3].lower():
                    fuel = 'electricity'
                else:
                    fuel = 'natural gas'
                end_use = row[3].lower().replace(fuel, '').strip()
                for index in data.index:
                    # print(end_use,index.lower())
                    if end_use in index.lower():
                        for column in data.columns:
                            # print(fuel, column.lower())
                            if fuel in column.lower():
                                print(index.lower(), column.lower(), row[3].lower())
                                summary_data.loc[row, 'values'] = data.loc[index, column]

                if 'heating comfort' in row[3].lower() or 'cooling comfort' in row[3].lower():
                    thermal_comfort_data = pd.read_csv(file,skiprows=187,index_col=1,nrows=3)
                    for index in thermal_comfort_data.index:
                        if ('occupied heating' in index.lower()) and ('heating comfort' in row[3].lower()):
                            summary_data.loc[row, 'values'] = thermal_comfort_data.loc[index, 'Facility [Hours]']
                        elif ('occupied cooling' in index.lower()) and ('cooling comfort' in row[3].lower()):
                            summary_data.loc[row, 'values'] = thermal_comfort_data.loc[index, 'Facility [Hours]']

    if fill_baseline_and_strat_1:
        # Set strategy-1 and baseline equal for both ANY and ALL for each occupancy profile
        for profile in filters.occupancy_profile:
            baseline_end_use_values = []
            strategy1_end_use_values = []
            for logic in filters.sensing_logic:
                if 'ALL' in logic:
                    for end_use in filters.end_uses:
                        idx_baseline = (profile, logic, 'baseline', end_use)
                        idx_strategy1 = (profile, logic, 'strategy1', end_use)
                        baseline_end_use_values.append(summary_data.loc[idx_baseline, 'values'])
                        strategy1_end_use_values.append(summary_data.loc[idx_strategy1, 'values'])
                if 'ANY' in logic:
                    for index,end_use in enumerate(filters.end_uses):
                        idx_baseline = (profile, logic, 'baseline', end_use)
                        idx_strategy1 = (profile, logic, 'strategy1', end_use)
                        summary_data.loc[idx_baseline, 'values'] = baseline_end_use_values[index]
                        summary_data.loc[idx_strategy1, 'values'] = strategy1_end_use_values[index]

        summary_data.to_excel(os.path.join(os.getcwd(), "energy_summary_data.xlsx"))

    return summary_data

def make_bar_chart(data:pd.DataFrame, title:str, legend_labels_variable:str=None, y_label:str=None, style:str='individual', plot_filters:Filter=None):
    '''
    Create bar chart from summary data.
    
    :param data: DataFrame with summary data.
    :type data: pd.DataFrame
    :param title: Title of the bar chart.
    :type title: str
    :param x_tick_labels_variables: Variable from filter that will provide the labels for the x-axis ticks.
    :type x_tick_labels_variables: str
    :param legend_labels_variable: Variable from filter that will provide the labels for the legends.
    :type legend_labels_variable: str
    :param y_label: Label for the y-axis.
    :type y_label: str
    :type style: str
    :param style: Style of plot. Can be one of the following.
    - 'grouped' (Grouped bar charts)
    - 'stacked' (Stacked bar charts)
    - 'individual' (Individual bars)
    '''

    if style == 'stacked':
        fig, ax = plt.subplots()
        layers = ['occupancy_profile', 'control_strategy', 'sensing_logic']

        filter_labels = []
        added_keys = []
        # for key in plot_filters.__dict__.keys():
        for key in layers:
            if key not in [legend_labels_variable,'values']:
                added_keys.append(key)
                filter_labels.append(plot_filters.__dict__[key])
        for key in plot_filters.__dict__.keys():
            if key not in added_keys and key not in [legend_labels_variable, 'values']:
                filter_labels.append(plot_filters.__dict__[key])

        plot_data_index_mapping = {}
        data_layers = data.index.names
        for data_layer in data_layers:
            if data_layer in layers:
                reqd_index = layers.index(data_layer)
                plot_data_index_mapping[data_layer] = reqd_index

        x_label_combos = list(it.product(*filter_labels))
        bottom_values = []
        for label in plot_filters.__dict__[legend_labels_variable]:
            value_list = []
            for x_label in x_label_combos:
                idx=tuple()
                for index_column_name in data_layers:
                    if index_column_name in layers:
                        reqd_index = plot_data_index_mapping[index_column_name]
                        reqd_filter = x_label[reqd_index]
                        idx += (reqd_filter,)
                idx += (label,)
                value=data.loc[idx,'values']
                if value>0:
                    value_list.append(value)
            if len(bottom_values) < 1:
                bottom_values = np.zeros(len(value_list))
            bar_bottoms = bottom_values.copy()
            # bar_separation = (10/13)*len(value_list)
            bar_separation = 10
            x_positions = (np.arange(len(value_list))+1)*bar_separation
            # bar_width = (7.5/13)*len(value_list)
            if len(x_positions) ==13:
                bar_width = 7.5
            else:
                bar_width = 5
            ax.bar(x_positions, value_list, bottom=bottom_values, label=label, width=bar_width)
            bottom_values += value_list
            bar_tops = bottom_values.copy()

            for index, bar_coords in enumerate(zip(x_positions, bar_bottoms, bar_tops)):
                ax.text(bar_coords[0], (bar_coords[1] + (bar_coords[2]-bar_coords[1])/2), f"{value_list[index]:,.0f}", ha='center', va='center', fontsize=8, color='black')
        if len(x_positions) ==13:
            legend_font_size = 10
        else:
            legend_font_size = 6.75
        ax.legend(loc='lower center', bbox_to_anchor=(0.5,1),ncol=len(plot_filters.__dict__[legend_labels_variable]),fontsize=legend_font_size)
        for label in ax.get_legend().get_texts():
            if 'heating' not in label.get_text().lower():
                label.set_text(label.get_text().replace(' Electricity',''))
            else:
                label.set_text(label.get_text())
        ax.set_ylabel(y_label)
        print(ax.get_legend().get_texts()[0].get_fontsize())

        # Create custom x-tick labels (TODO: Generalize for multiple layers)
        # x_labels = ['','','ALL','ANY','','ALL','ANY','','ALL','ANY','','ALL','ANY']
        # ax.set_xticks(x_positions,x_labels)
        # layer_2_groupings = [[0],[1],[2,3],[4],[5,6],[7],[8,9],[10],[11,12]]
        # layer_2_labels = ['','Strategy #1','Strategy #4','Strategy #1','Strategy #4','Strategy #1','Strategy #4','Strategy #1','Strategy #4']
        # for index,grouping in enumerate(layer_2_groupings):
        #     ax_temp = ax.twinx()
        #     left_edge = x_positions[grouping[0]] - 5
        #     right_edge = x_positions[grouping[-1]] + 5
        #     center = (left_edge + right_edge) / 2
        #     # ax.annotate(xy=(center, -20),xytext=(center, -20),text=layer_2_labels[index],ha='center',va='center',fontsize=10)
        #     ax_temp.text(center,-15000,layer_2_labels[index],ha='center',va='center',fontsize=8)
        #     ax_temp.vlines(x=right_edge, ymin=-20000, ymax=0, color='black', linestyle='--', linewidth=0.5)
        #     ax_temp.vlines(x=left_edge, ymin=-20000, ymax=0, color='black', linestyle='--', linewidth=0.5)
        # fig.set_size_inches(12.8,4.8)
        # fig.tight_layout()
        # End TODO
        if len(x_positions) ==13:
            figure_width = 12.8
        else:
            figure_width = 6.4
        # fig.set_size_inches(figure_width,4.8)
        fig.set_size_inches(figure_width,2.4)
        fig.tight_layout()

    elif style == 'grouped':
        fig, ax = plt.subplots()
        layers = ['end_uses']

        filter_labels = []
        added_keys = []
        # for key in plot_filters.__dict__.keys():
        for key in layers:
            if key not in [legend_labels_variable, 'values']:
                added_keys.append(key)
                filter_labels.append(plot_filters.__dict__[key])
        for key in plot_filters.__dict__.keys():
            if key not in added_keys and key not in [legend_labels_variable, 'values']:
                filter_labels.append(plot_filters.__dict__[key])
                added_keys.append(key)
        filter_labels.append(plot_filters.__dict__[legend_labels_variable])
        added_keys.append(legend_labels_variable)

        # Record mapping between index headers in data source and the order of
        # labels in the filter combos generated downstream
        plot_data_index_mapping = {}
        data_layers = data.index.names
        for data_layer in data_layers:
            if data_layer in added_keys:
                reqd_index = added_keys.index(data_layer)
                plot_data_index_mapping[data_layer] = reqd_index

        x_label_combos = list(it.product(*filter_labels))
        major_x_values = [20*item for item in list(range(len(plot_filters.__dict__[layers[0]])))]
        bar_width = 2.5
        for label in plot_filters.__dict__[legend_labels_variable]:
            value_list = []
            for x_label in x_label_combos:
                if label == x_label[-1]:
                    idx=tuple()
                    for index_column_name in data_layers:
                        if index_column_name in added_keys:
                            reqd_index = plot_data_index_mapping[index_column_name]
                            reqd_filter = x_label[reqd_index]
                            idx += (reqd_filter,)
                    value=data.loc[idx,'values']
                    if value>0:
                        value_list.append(value)
            offset = ((plot_filters.__dict__[legend_labels_variable].index(label)) - ((len(plot_filters.__dict__[legend_labels_variable])-1)/2))*(bar_width+1)
            bar_x_values = [value + offset for value in major_x_values]
            ax.bar(bar_x_values, value_list, label=label, width=bar_width)

        if len(major_x_values) ==13:
            legend_font_size = 10
        else:
            legend_font_size = 6.75
        ax.legend(loc='lower center', bbox_to_anchor=(0.5,1),ncol=len(plot_filters.__dict__[legend_labels_variable]),fontsize=legend_font_size)
        if 'end_uses' in legend_labels_variable:
            for label in ax.get_legend().get_texts():
                if 'heating' not in label.get_text().lower():
                    label.set_text(label.get_text().replace(' Electricity',''))
                else:
                    label.set_text(label.get_text())
        elif 'control_strategy' in legend_labels_variable:
            for label in ax.get_legend().get_texts():
                if 'strategy' in label.get_text().lower():
                    label.set_text(label.get_text().replace('strategy','Strategy #'))
                elif 'baseline' in label.get_text().lower():
                    label.set_text('Baseline')

        if len(layers) == 1:
            if 'end_uses' in layers:
                labels = [end_use.replace(' Electricity','') if 'heating' not in end_use.lower() else end_use for end_use in plot_filters.__dict__[layers[0]]]
                ax.set_xticks(major_x_values, labels)
                ax.tick_params(axis='x', labelsize=6.5)
                ax.tick_params(axis='y', labelsize=6.5)

        ax.set_ylabel(y_label,fontsize=6.5)
        ax.grid(axis='y',alpha=0.5)
        ax.set_axisbelow(True)

        # Create custom x-tick labels (TODO: Generalize for multiple layers)
        # x_labels = ['','','ALL','ANY','','ALL','ANY','','ALL','ANY','','ALL','ANY']
        # ax.set_xticks(x_positions,x_labels)
        # layer_2_groupings = [[0],[1],[2,3],[4],[5,6],[7],[8,9],[10],[11,12]]
        # layer_2_labels = ['','Strategy #1','Strategy #4','Strategy #1','Strategy #4','Strategy #1','Strategy #4','Strategy #1','Strategy #4']
        # for index,grouping in enumerate(layer_2_groupings):
        #     ax_temp = ax.twinx()
        #     left_edge = x_positions[grouping[0]] - 5
        #     right_edge = x_positions[grouping[-1]] + 5
        #     center = (left_edge + right_edge) / 2
        #     # ax.annotate(xy=(center, -20),xytext=(center, -20),text=layer_2_labels[index],ha='center',va='center',fontsize=10)
        #     ax_temp.text(center,-15000,layer_2_labels[index],ha='center',va='center',fontsize=8)
        #     ax_temp.vlines(x=right_edge, ymin=-20000, ymax=0, color='black', linestyle='--', linewidth=0.5)
        #     ax_temp.vlines(x=left_edge, ymin=-20000, ymax=0, color='black', linestyle='--', linewidth=0.5)
        # fig.set_size_inches(12.8,4.8)
        # fig.tight_layout()
        # End TODO

        if len(major_x_values) ==13:
            figure_width = 12.8
        else:
            figure_width = 6.4
        fig.set_size_inches(figure_width,2.4)
        fig.tight_layout()

    # print(fig.get_size_inches())
    fig.savefig(os.path.join(os.getcwd(), f"{title.replace(' ','_')}.png"), dpi=300)
    plt.close(fig)

def analyze_experiment_results(experiments_folder: str, output_folder: str) -> pd.DataFrame:
    """Aggregate the generated experiment meter files and save comparison outputs."""
    rows = []
    for experiment_dir in sorted(os.scandir(experiments_folder), key=lambda entry: entry.name):
        if not experiment_dir.is_dir() or not experiment_dir.name.endswith('_090926'):
            continue
        meter_files = [entry for entry in os.scandir(os.path.join(experiment_dir.path, 'results', 'Hourly Results'))
                       if entry.name.startswith('Timestep_HVAC_Meter_') and entry.name.endswith('.csv')]
        if len(meter_files) != 1:
            continue
        meter = pd.read_csv(meter_files[0].path)
        name_parts = experiment_dir.name.split('_TYPI_hvac_schedule_TYPI_', 1)
        if len(name_parts) != 2:
            continue
        model, schedule = name_parts
        energy = {
            'Cooling Electricity (kWh)': meter['Cooling Electricity (kWh)'].sum(),
            'Heating Electricity (kWh)': meter['Heating Electricity (kWh)'].sum(),
            'Heating NaturalGas (kWh)': meter['Heating NaturalGas (kWh)'].sum(),
            'Total Heating Energy (kWh)': meter['Total Heating Energy (kWh)'].sum(),
            'Lighting Electricity (kWh)': meter['Lighting Electricity (kWh)'].sum(),
        }
        rows.append({'model': model, 'schedule': schedule, **energy})

    summary = pd.DataFrame(rows).sort_values(['model', 'schedule'])
    os.makedirs(output_folder, exist_ok=True)
    summary.to_csv(os.path.join(output_folder, 'experiment_energy_summary.csv'), index=False)
    chart_data = summary.pivot(index='schedule', columns='model', values='Total Heating Energy (kWh)')
    chart_data['Cooling Electricity (kWh)'] = summary.groupby('schedule')['Cooling Electricity (kWh)'].mean()
    chart_data['Lighting Electricity (kWh)'] = summary.groupby('schedule')['Lighting Electricity (kWh)'].mean()
    chart_data['Total Reported Energy (kWh)'] = (
        chart_data['Cooling Electricity (kWh)']
        + chart_data['Lighting Electricity (kWh)']
        + summary.groupby('schedule')['Total Heating Energy (kWh)'].mean()
    )

    schedules = list(chart_data.index)
    x_positions = np.arange(len(schedules))
    bar_width = 0.36
    fig, ax = plt.subplots(figsize=(14, 7))
    original = summary[summary['model'] == 'original'].set_index('schedule').loc[schedules]
    rezoned = summary[summary['model'] == 'rezoned'].set_index('schedule').loc[schedules]
    original_totals = original['Cooling Electricity (kWh)'] + original['Total Heating Energy (kWh)'] + original['Lighting Electricity (kWh)']
    rezoned_totals = rezoned['Cooling Electricity (kWh)'] + rezoned['Total Heating Energy (kWh)'] + rezoned['Lighting Electricity (kWh)']
    original_bars = ax.bar(x_positions - bar_width / 2, original_totals, bar_width, label='Original', color='#2f6690')
    rezoned_bars = ax.bar(x_positions + bar_width / 2, rezoned_totals, bar_width, label='Rezoned', color='#d97941')

    for bars, values in [(original_bars, original_totals), (rezoned_bars, rezoned_totals)]:
        for bar, value in zip(bars, values):
            ax.annotate(f'{value:,.0f}', (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 5), textcoords='offset points', ha='center', va='bottom', fontsize=8)

    for index, (original_value, rezoned_value) in enumerate(zip(original_totals, rezoned_totals)):
        difference = rezoned_value - original_value
        percent = difference / original_value * 100
        ax.annotate(f'{difference:+,.0f} ({percent:+.1f}%)',
                    (x_positions[index], max(original_value, rezoned_value)),
                    xytext=(0, 25), textcoords='offset points', ha='center', va='bottom', fontsize=8,
                    color='#4a4a4a')

    labels = [schedule.replace('_090926', '').replace('OCC_FRACTION_', 'Fraction ') for schedule in schedules]
    ax.set_xticks(x_positions, labels)
    ax.set_ylabel('Annual energy use (kWh)')
    ax.set_title('Strategy-4 TYPI Energy Use by HVAC Occupancy Logic', pad=28, fontsize=14, weight='bold')
    ax.text(0.5, 1.01, 'Labels above bars show totals; centered labels show rezoned minus original',
            transform=ax.transAxes, ha='center', va='bottom', fontsize=9, color='#666666')
    ax.grid(axis='y', alpha=0.25)
    ax.set_axisbelow(True)
    ax.spines[['top', 'right']].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc='upper left')
    ax.set_ylim(0, max(rezoned_totals.max(), original_totals.max()) * 1.14)
    fig.tight_layout()
    fig.savefig(os.path.join(output_folder, 'experiment_energy_summary.png'), dpi=250, bbox_inches='tight')
    plt.close(fig)
    return summary

def analyze_control_setbacks(experiments_folder: str, output_folder: str) -> pd.DataFrame:
    """Quantify reduced HVAC setpoints, ventilation, and lighting operation."""
    rows = []
    for experiment_dir in sorted(os.scandir(experiments_folder), key=lambda entry: entry.name):
        if not experiment_dir.is_dir() or not experiment_dir.name.endswith('_090926'):
            continue
        hourly_dir = os.path.join(experiment_dir.path, 'results', 'Hourly Results')
        var_files = [entry for entry in os.scandir(hourly_dir)
                     if entry.name.startswith('Timestep_HVAC_Var_') and entry.name.endswith('.csv')]
        if len(var_files) != 1:
            continue
        data = pd.read_csv(var_files[0].path)
        schedule_parts = experiment_dir.name.split('_TYPI_hvac_schedule_TYPI_', 1)
        if len(schedule_parts) != 2:
            continue
        model, schedule = schedule_parts

        heating = data[[c for c in data.columns if 'ZONE THERMOSTAT HEATING SETPOINT TEMPERATURE' in c.upper()]]
        cooling = data[[c for c in data.columns if 'ZONE THERMOSTAT COOLING SETPOINT TEMPERATURE' in c.upper()]]
        hvac_status = data[[c for c in data.columns if '_HVACSTATUS_SCH:' in c.upper()]]
        ventilation = data[[c for c in data.columns if 'ZONE MECHANICAL VENTILATION MASS FLOW RATE' in c.upper()]]
        limiting = data[[c for c in data.columns if 'AIR SYSTEM OUTDOOR AIR LIMITING FACTOR' in c.upper()]]
        lighting = data[[c for c in data.columns if 'ZONE LIGHTS ELECTRICITY ENERGY' in c.upper()]]

        occupied = pd.Series(True, index=data.index)
        if 'Date/Time' in data.columns:
            hour_text = data['Date/Time'].astype(str).str.extract(r'\s(\d{1,2}):')[0]
            occupied = pd.to_numeric(hour_text, errors='coerce').between(8, 16)

        def fraction(condition, mask=None):
            values = condition.astype(float)
            if mask is not None:
                values = values.loc[mask]
            return float(values.stack().mean()) if not values.empty else np.nan

        heating_active = heating.where(heating.gt(0))
        cooling_active = cooling.where(cooling.gt(0))
        heating_setback = fraction(heating_active.lt(19.0), occupied)
        cooling_setback = fraction(cooling_active.gt(25.5), occupied)
        hvac_off = fraction(hvac_status.lt(0.5), occupied)
        ventilation_setback = fraction(limiting.lt(0.999), occupied)
        lighting_off = fraction(lighting.le(0.0), occupied)
        rows.append({
            'model': model,
            'schedule': schedule,
            'heating_setpoint_setback_pct': heating_setback * 100,
            'cooling_setpoint_setback_pct': cooling_setback * 100,
            'hvac_status_off_pct': hvac_off * 100,
            'ventilation_reduced_pct': ventilation_setback * 100,
            'lighting_off_pct': lighting_off * 100,
            'mean_ventilation_limiting_factor': float(limiting.clip(lower=0, upper=1).mean().mean()) if not limiting.empty else np.nan,
        })

    metrics = pd.DataFrame(rows).sort_values(['model', 'schedule'])
    os.makedirs(output_folder, exist_ok=True)
    metrics.to_csv(os.path.join(output_folder, 'experiment_control_setback_summary.csv'), index=False)

    plot_metrics = ['hvac_status_off_pct', 'ventilation_reduced_pct', 'lighting_off_pct']
    labels = ['HVAC off', 'Ventilation setback', 'Lighting off']
    schedules = list(metrics['schedule'].drop_duplicates())
    x_positions = np.arange(len(schedules))
    bar_width = 0.36
    fig, axes = plt.subplots(len(plot_metrics), 1, figsize=(14, 9), sharex=True)
    for axis, metric, label in zip(axes, plot_metrics, labels):
        original = metrics[metrics['model'] == 'original'].set_index('schedule').reindex(schedules)[metric]
        rezoned = metrics[metrics['model'] == 'rezoned'].set_index('schedule').reindex(schedules)[metric]
        axis.bar(x_positions - bar_width / 2, original, bar_width, label='Original', color='#2f6690')
        axis.bar(x_positions + bar_width / 2, rezoned, bar_width, label='Rezoned', color='#d97941')
        for index, value in enumerate(original):
            axis.text(x_positions[index] - bar_width / 2, value + 1, f'{value:.1f}%', ha='center', fontsize=7)
        for index, value in enumerate(rezoned):
            axis.text(x_positions[index] + bar_width / 2, value + 1, f'{value:.1f}%', ha='center', fontsize=7)
        axis.set_ylabel('% of occupied\ntime steps', fontsize=8)
        axis.set_title(label, loc='left', fontsize=10, weight='bold')
        axis.set_ylim(0, 105)
        axis.grid(axis='y', alpha=0.25)
        axis.spines[['top', 'right']].set_visible(False)
    axes[0].legend(frameon=False, ncol=2, loc='upper right')
    axes[-1].set_xticks(x_positions, [s.replace('_090926', '').replace('OCC_FRACTION_', 'Fraction ') for s in schedules])
    fig.suptitle('Strategy-4 TYPI Control Reduction Frequency', fontsize=15, weight='bold')
    fig.tight_layout()
    fig.savefig(os.path.join(output_folder, 'experiment_control_setback_summary.png'), dpi=250, bbox_inches='tight')
    plt.close(fig)
    return metrics

def analyze_comfort_results(experiments_folder: str, output_folder: str) -> pd.DataFrame:
    """Extract annual unmet setpoint and occupant comfort hours from table reports."""
    rows = []
    for experiment_dir in sorted(os.scandir(experiments_folder), key=lambda entry: entry.name):
        if not experiment_dir.is_dir() or not experiment_dir.name.endswith('_090926'):
            continue
        annual_dir = os.path.join(experiment_dir.path, 'results', 'Annual Results')
        table_files = [entry for entry in os.scandir(annual_dir)
                       if entry.name.startswith('eplustbl_HVAC_') and entry.name.endswith('.csv')]
        if len(table_files) != 1:
            continue
        metrics = {}
        with open(table_files[0].path, encoding='utf-8-sig') as table:
            for line in table:
                fields = [field.strip() for field in line.rstrip('\n').split(',')]
                if len(fields) < 3:
                    continue
                label = fields[1].lower()
                try:
                    value = float(fields[2])
                except ValueError:
                    continue
                if label == 'time setpoint not met during occupied heating':
                    metrics['unmet_heating_setpoint_hours'] = value
                elif label == 'time setpoint not met during occupied cooling':
                    metrics['unmet_cooling_setpoint_hours'] = value
                elif label == 'time not comfortable based on simple ashrae 55-2004':
                    metrics['occupant_discomfort_hours'] = value
        name_parts = experiment_dir.name.split('_TYPI_hvac_schedule_TYPI_', 1)
        if len(name_parts) == 2 and metrics:
            rows.append({'model': name_parts[0], 'schedule': name_parts[1], **metrics})

    comfort = pd.DataFrame(rows).sort_values(['model', 'schedule'])
    os.makedirs(output_folder, exist_ok=True)
    comfort.to_csv(os.path.join(output_folder, 'experiment_comfort_summary.csv'), index=False)
    schedules = list(comfort['schedule'].drop_duplicates())
    x_positions = np.arange(len(schedules))
    bar_width = 0.36
    fig, axes = plt.subplots(3, 1, figsize=(14, 9), sharex=True)
    series = [
        ('unmet_heating_setpoint_hours', 'Occupied heating setpoint unmet hours'),
        ('unmet_cooling_setpoint_hours', 'Occupied cooling setpoint unmet hours'),
        ('occupant_discomfort_hours', 'Occupant discomfort hours (Simple ASHRAE 55-2004)'),
    ]
    for axis, (column, title) in zip(axes, series):
        original = comfort[comfort['model'] == 'original'].set_index('schedule').reindex(schedules)[column]
        rezoned = comfort[comfort['model'] == 'rezoned'].set_index('schedule').reindex(schedules)[column]
        bars_original = axis.bar(x_positions - bar_width / 2, original, bar_width, label='Original', color='#2f6690')
        bars_rezoned = axis.bar(x_positions + bar_width / 2, rezoned, bar_width, label='Rezoned', color='#d97941')
        for bars in [bars_original, bars_rezoned]:
            for bar in bars:
                axis.annotate(f'{bar.get_height():,.1f}', (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                              xytext=(0, 4), textcoords='offset points', ha='center', fontsize=7)
        axis.set_ylabel('Hours', fontsize=8)
        axis.set_title(title, loc='left', fontsize=10, weight='bold')
        axis.grid(axis='y', alpha=0.25)
        axis.spines[['top', 'right']].set_visible(False)
    axes[0].legend(frameon=False, ncol=2, loc='upper right')
    axes[-1].set_xticks(x_positions, [s.replace('_090926', '').replace('OCC_FRACTION_', 'Fraction ') for s in schedules])
    fig.suptitle('Strategy-4 TYPI Comfort and Setpoint Outcomes', fontsize=15, weight='bold')
    fig.tight_layout()
    fig.savefig(os.path.join(output_folder, 'experiment_comfort_summary.png'), dpi=250, bbox_inches='tight')
    plt.close(fig)
    return comfort

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiments-folder', help='Experiment root containing original_* and rezoned_* result folders.')
    parser.add_argument('--output-folder', default='postprocessing', help='Folder for generated summaries and charts.')
    args = parser.parse_args()
    if args.experiments_folder:
        summary = analyze_experiment_results(args.experiments_folder, args.output_folder)
        control_metrics = analyze_control_setbacks(args.experiments_folder, args.output_folder)
        comfort_metrics = analyze_comfort_results(args.experiments_folder, args.output_folder)
        print(summary.to_string(index=False))
        print(control_metrics.to_string(index=False))
        print(comfort_metrics.to_string(index=False))
        raise SystemExit(0)

    # Define paths
    results_folder = os.path.join(os.getcwd(),"output_110525","Annual Results")
    reqd_filters = Filter()
    relevant_results_files = get_relevant_results_files(results_folder, reqd_filters)
    summary_df = get_reqd_summary_data(relevant_results_files, reqd_filters)

    plot1_filters = Filter(control_strategy=['baseline','1','4'], end_uses=["Heating Electricity", "Heating Natural Gas", "Cooling Electricity", "Interior Lighting Electricity", "Fans Electricity"])
    make_bar_chart(summary_df, title="Energy Consumption Summary", legend_labels_variable='end_uses', y_label="Annual Energy Use (kWh)", style='stacked', plot_filters=plot1_filters)

    plot6_filters = Filter(control_strategy=['baseline','1','4'], end_uses=["Heating Comfort Not Met", "Cooling Comfort Not Met"])
    make_bar_chart(summary_df, title="Thermal Comfort Not Met", legend_labels_variable='end_uses', y_label="Thermal Comfort Not Met [Hours]", style='stacked', plot_filters=plot6_filters)

    summary_df = get_reqd_summary_data(relevant_results_files, reqd_filters, True)

    plot2_filters = Filter(control_strategy=['1','4'], end_uses=["Heating Electricity", "Heating Natural Gas", "Cooling Electricity", "Interior Lighting Electricity", "Fans Electricity"],occupancy_profile=['TYPI'],sensing_logic=['ALL','ANY'])
    make_bar_chart(summary_df, title="Energy Consumption by TYPI ALL and ANY", legend_labels_variable='end_uses', y_label="Annual Energy Use (kWh)", style='stacked', plot_filters=plot2_filters)

    plot3_filters = Filter(control_strategy=['1','4'], end_uses=["Heating Electricity", "Heating Natural Gas", "Cooling Electricity", "Interior Lighting Electricity", "Fans Electricity"],occupancy_profile=['HBLM'],sensing_logic=['ALL','ANY'])
    make_bar_chart(summary_df, title="Energy Consumption by HBLM ALL and ANY", legend_labels_variable='end_uses', y_label="Annual Energy Use (kWh)", style='stacked', plot_filters=plot3_filters)

    plot4_filters = Filter(control_strategy=['1','2','3','4'], end_uses=["Heating Electricity", "Heating Natural Gas", "Cooling Electricity", "Interior Lighting Electricity", "Fans Electricity"],occupancy_profile=['TYPI'],sensing_logic=['ALL'])
    make_bar_chart(summary_df, title="Energy Consumption by TYPI ALL across control strategies", legend_labels_variable='control_strategy', y_label="Annual Energy Use (kWh)", style='grouped', plot_filters=plot4_filters)

    plot5_filters = Filter(control_strategy=['1','2','3','4'], end_uses=["Heating Electricity", "Heating Natural Gas", "Cooling Electricity", "Interior Lighting Electricity", "Fans Electricity"],occupancy_profile=['TYPI'],sensing_logic=['ANY'])
    make_bar_chart(summary_df, title="Energy Consumption by TYPI ANY across control strategies", legend_labels_variable='control_strategy', y_label="Annual Energy Use (kWh)", style='grouped', plot_filters=plot5_filters)
