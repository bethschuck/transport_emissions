import dash
import dash_core_components as dcc
import dash_bootstrap_components as dbc
import dash_html_components as html
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from dash.dependencies import Input, Output, State
from pathlib import Path



# INPUTS
def data_load():
    '''
    This function reads data from csv files into dataframes for:
        pt_details - the information about each PT project, included frequency, distance, and mode type
        emission_factors - the emissions factors for each mode (how much CO2-e is emitted for each km travelled)
        base_numbers - the pkt and vkt for 2018 and 2030 baseline, and the unchanges vkt and pkt for the 2030 scenario
    This function also calculates the emissions for each year, from the emission factors and base_numbers
    '''

    # Read data from csv into dataframes
    pt_details = pd.read_csv('pt_details.csv', index_col = 0)
    base_numbers = pd.read_csv('base_numbers.csv', index_col = 0) # Has placeholders for emissions info
    emission_factors = pd.read_csv('emission_factors.csv', index_col = 0) # Emission factors have units kg CO2-e/km

    base_numbers.loc['emissions_2018'] = emission_factors.loc['values_2018'] * base_numbers.loc['vkt_2018']
    base_numbers.loc['emissions_2030_baseline'] = emission_factors.loc['values_2030_baseline'] * base_numbers.loc['vkt_2030_baseline']
    base_numbers.loc['emissions_2030_scenario'] = emission_factors.loc['values_2030_scenario'] * base_numbers.loc['vkt_2030_scenario']
    
    return pt_details, base_numbers, emission_factors
    
    
def data_initialisation(base_numbers):
    '''
    This function produces the basic input values for future calculations
    
    Inputs:
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        
    Outputs:
        numbers - dictionary with key values for calculations
    '''
    
    # Finding the total pkt by private (and active) modes
    private_modes =['passenger_light', 'electric_light', 'walking', 'cycling'] 
    pt_modes = ['diesel_bus', 'electric_bus', 'heavy_rail', 'light_rail'] 
    all_modes = ['passenger_light', 'electric_light', 'walking', 'cycling', 'diesel_bus', 'electric_bus', 'heavy_rail', 'light_rail'] 
    
    # What proportion of pkt are from each mode (for 2030 baseline)
    mode_sum_pkt = 0
    mode_pkt_no_bike = 0
    for mode in private_modes:
        mode_sum_pkt += base_numbers.loc['pkt_2030_baseline'][mode]
        if mode != 'cycling':
            mode_pkt_no_bike +=base_numbers.loc['pkt_2030_baseline'][mode]
    
    
    # Dictionary of values to pass into all functions
    numbers ={
        'pkt_annualisation':2250.0, # Annualisation factor: one peak hour to annual ridership distances
        'vkt_annualisation':332.0,  # Annualisation factor: one weekday to annual vehicle distances
        'car_occupancy':1.58, # Average number of pkt per vkt for light fleet in NZ
        'mode_sum_pkt': mode_sum_pkt,
        'mode_pkt_no_bike': mode_pkt_no_bike,
        'bus_lifespan': 15,
        'private_modes': private_modes,
        'pt_modes': pt_modes,
        '2018_car_ownership': 1261016,
        'all_modes': all_modes
    }
    
    return numbers

def pt_proj_effects(numbers, base_numbers, pt_details):
    '''
    This function returns dataframes which have the effect of different PT projects on the vkt 
    and pkt of different modes.
    
    INPUTS:
    numbers - dictionary containing key numbers
    pt_details - dataframe: containing frequency, capacity and distance data for various PT projects 
    base_numbers - dataframe: containing the PKT and VKT data for 2018, and for the 2030 baseline
    
    OUTPUTS:
    pt_effects_vkt - dataframe with the effect of each project on the pkt and vkt for each mode
    pt_effects_pkt - dataframe with the effect of each project on the pkt and vkt for each mode
    '''
    
    # Creating a new datafram for pkt and vkt by mode
    pt_effects_pkt = pd.DataFrame(index = pt_details.index, columns = base_numbers.keys())
    pt_effects_vkt = pd.DataFrame(index = pt_details.index, columns = base_numbers.keys())
    
    
    # For each PT project
    for project in pt_details.index:
        
        # Calculating the PKT by primary mode for each project
        pt_effects_pkt.loc[project][pt_details.primary_mode[project]] = (
            (60 / pt_details.peak_freq[project]) # Number of buses per hour in peak
            * pt_details.distance[project] # Distance covered by this PT project 
            * numbers['pkt_annualisation'] # Passenger annualisation factor: am peak to annual
            * pt_details.vehicle_capacity[project] # Peak vehicle capacity
            * 2 # Both directions
            * 2 # For both AM peak hours
        )
        
        # Calculating the VKT by primary mode for each project
        pt_effects_vkt.loc[project][pt_details.primary_mode[project]] = (
            ((60/pt_details.peak_freq[project]) # Number of buses per hour in peak
            * pt_details.num_peak_hrs[project] # Number of hours considered peak
            + (60/pt_details.off_peak_freq[project]) # Number of buses per hour in off-peak times
            * (pt_details.num_hours[project]-pt_details.num_peak_hrs[project])) # Number of hours considered off-peak
            * pt_details.distance[project] #  Distance covered by this PT project
            * numbers['vkt_annualisation'] # Vehicle annualisation factor: day to year
            * 2 # For both directions
        )
        
        for mode in numbers['private_modes']:
            # Calculating the effect on PKT for private/non-primary modes
            #mode_prop = base_numbers.loc['pkt_2030_baseline'][mode] / numbers['mode_sum_pkt']
            pt_effects_pkt.loc[project][mode] = (
                - base_numbers.loc['pkt_2030_baseline'][mode] / numbers['mode_sum_pkt'] # Proportion of pkt by this mode in 2030 
                * pt_effects_pkt.loc[project][pt_details.primary_mode[project]] # pkt by primary mode
            )
            
            # Calculating the effect on VKT for private/non-primary modes
            if mode in ['passenger_light', 'electric_light']:
                pt_effects_vkt.loc[project][mode] = pt_effects_pkt.loc[project][mode]/numbers['car_occupancy']
            elif mode in ['walking', 'cycling']:
                pt_effects_vkt.loc[project][mode] = pt_effects_pkt.loc[project][mode]
        
        # No change in PT pkt or vkt (except primary mode)
        for mode in numbers['pt_modes']:
            if mode != pt_details.primary_mode[project]:
                pt_effects_vkt.loc[project][mode] = 0 
                pt_effects_pkt.loc[project][mode] = 0
    
    return pt_effects_vkt, pt_effects_pkt

def pt_projects_apply(base_numbers, pt_effects_vkt, pt_effects_pkt, pt_included):
    '''
    This function updates the 2030 scenario pkt and vkt based on the inclusion of different PT projects
    
    Inputs:
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        pt_effects_vkt - dataframe with the effect of each project on the pkt and vkt for each mode
        pt_effects_pkt - dataframe with the effect of each project on the pkt and vkt for each mode
        pt_included - list of included PT projects
        
    Outputs:
        updated base_numbers
    '''
    
    if pt_included != []:
        base_numbers.loc['vkt_2030_scenario'] += pt_effects_vkt.loc[pt_included].sum()
        base_numbers.loc['pkt_2030_scenario'] += pt_effects_pkt.loc[pt_included].sum()
    
    return base_numbers

def bus_ridership_changes(numbers, base_numbers, bus_prop_increase):
    '''
    This function updates the 2030 scenario pkt and vkt based on an increase in bus ridership
    
    Inputs:
        numbers - dictionary with key values for calculations
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        bus_prop_increase - the % increase in pkt by bus from the 2030 baseline (0.4 would mean a 40% increase in pkt)
        
    Outputs:
        updated base_numbers
    '''
    if bus_prop_increase > 0:

        # Work out how many pkt will be shifted to bus
        bus_change = base_numbers.loc['pkt_2030_baseline']['diesel_bus'] * bus_prop_increase

        # Apply change
        base_numbers.loc['pkt_2030_scenario']['diesel_bus'] += bus_change

        for mode in numbers['private_modes']:
            effect = (
                - base_numbers.loc['pkt_2030_baseline'][mode] 
                / numbers['mode_sum_pkt'] # Proportion of pkt by this mode in 2030 baseline
                * bus_change
            )

            base_numbers.loc['pkt_2030_scenario'][mode] += effect

            if mode in ['passenger_light', 'electric_light']:
                base_numbers.loc['vkt_2030_scenario'][mode] += effect/numbers['car_occupancy']

            elif mode in ['walking', 'cycling']:
                base_numbers.loc['vkt_2030_scenario'][mode] += effect  

    return base_numbers


def cycling_changes(numbers, base_numbers, cycling_included):
    '''
    This function updates the 2030 scenario pkt and vkt based on an increase in cycling mode share
    
    Inputs:
        numbers - dictionary with key values for calculations
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        cycling_included - the final % mode share by bike 
        
    Outputs:
        updated base_numbers
    '''
    if cycling_included > 0:
        # Calculate how much pkt will change based on increase
        cycling_included = cycling_included - 1
        cycling_change = base_numbers.loc['pkt_2030_baseline']['cycling'] * cycling_included

        # Apply change
        base_numbers.loc['pkt_2030_scenario']['cycling'] += cycling_change

        for mode in numbers['private_modes']:
            if mode != 'cycling':
                effect = (
                    - base_numbers.loc['pkt_2030_baseline'][mode] 
                    / numbers['mode_pkt_no_bike'] # Proportion of pkt by this mode in 2030 baseline
                    * cycling_change
                )

                base_numbers.loc['pkt_2030_scenario'][mode] += effect

            if mode in ['passenger_light', 'electric_light']:
                base_numbers.loc['vkt_2030_scenario'][mode] += effect/numbers['car_occupancy']

            elif mode in ['walking', 'cycling']:
                base_numbers.loc['vkt_2030_scenario'][mode] += effect
    return base_numbers



def bus_electric(numbers, base_numbers, bus_electrification_included):
    '''
    This function updates the 2030 scenario pkt and vkt based on partial electrification of the bus fleet
    
    Inputs:
        numbers - dictionary with key values for calculations
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        bus_electrification_included - the year bus electrification will begin (should be 0 for no electrification)
        
    Outputs:
        updated base_numbers
    '''
    if bus_electrification_included > 2019:
        # Calculate what % of the bus lifespan will be covered
        prop = (2030-bus_electrification_included)/numbers['bus_lifespan']
        # Replace that % of buses with electric buses for pkt and vkt
        bus_vkt_shift = base_numbers.loc['vkt_2030_scenario']['diesel_bus']*prop
        base_numbers.loc['vkt_2030_scenario','diesel_bus'] += - bus_vkt_shift
        base_numbers.loc['vkt_2030_scenario','electric_bus'] += bus_vkt_shift

        bus_pkt_shift = base_numbers.loc['pkt_2030_scenario']['diesel_bus']*prop
        base_numbers.loc['pkt_2030_scenario','diesel_bus'] += - bus_pkt_shift 
        base_numbers.loc['pkt_2030_scenario','electric_bus'] += bus_pkt_shift 
    
    return base_numbers

def car_electric(base_numbers, car_electrification_included):
    '''
    This function updates the 2030 scenario pkt and vkt based on partial electrification of the light fleet
    
    Inputs:
        numbers - dictionary with key values for calculations
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        car_electrification_included - the proportion of the fleet to electrify
        
    Outputs:
        updated base_numbers
    '''
    if car_electrification_included > 0:
        # Replace that % of cars with electric cars for pkt and vkt
        car_vkt_shift = base_numbers.loc['vkt_2030_scenario']['passenger_light']*car_electrification_included
        base_numbers.loc['vkt_2030_scenario','passenger_light'] += - car_vkt_shift
        base_numbers.loc['vkt_2030_scenario','electric_light'] += car_vkt_shift

        car_pkt_shift = base_numbers.loc['pkt_2030_scenario']['passenger_light']*car_electrification_included
        base_numbers.loc['pkt_2030_scenario','passenger_light'] += - car_pkt_shift 
        base_numbers.loc['pkt_2030_scenario','electric_light'] += car_pkt_shift 

    return base_numbers

def car_occupancy(base_numbers, occupancy_included):
    '''
    This function updates the 2030 scenario pkt and vkt based on changed car occupancy 
    
    Inputs:
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        occupancy_included - the average occupancy of a car (0 if no change from initial)
        
    Outputs:
        updated base_numbers
    '''
    
    if occupancy_included > 0:
        base_numbers.loc['vkt_2030_scenario']['passenger_light'] = base_numbers.loc['pkt_2030_scenario']['passenger_light']/occupancy_included
        base_numbers.loc['vkt_2030_scenario']['electric_light'] = base_numbers.loc['pkt_2030_scenario']['electric_light']/occupancy_included
    
    return base_numbers

def calculate_emissions(base_numbers, emission_factors, car_emission_change):
    '''
    This function updates the 2030 scenario emissions based on the 2030 scenario vkt and emission_factors
    
    Inputs:
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        emission_factors - the emissions factors for each mode (how much CO2-e is emitted for each km travelled)
        car_emission_change - the % reduction in car emissions per km travelled from 2018 levels
        
    Outputs:
        updated base_numbers
    '''
    
    
    base_numbers.loc['emissions_2030_scenario'] = emission_factors.loc['values_2030_scenario'] * base_numbers.loc['vkt_2030_scenario']
    base_numbers.loc['emissions_2030_scenario', 'passenger_light'] = base_numbers.loc['emissions_2030_scenario', 'passenger_light'] * (1-car_emission_change)
    
    return base_numbers


def covid_trips(base_numbers, covid, numbers):
    '''
    This function updates the 2030 scenario pkt and vkt based on trips not taken
    
    Inputs:
        base_numbers - dataframe with pkt, vkt and emissions data for 2018, 2030 baseline and 2030 scenario
        numbers - dictionary with key values for calculations
        covid - the % reduction in trips taken 
        
    Outputs:
        updated base_numbers
    '''
    
    for mode in numbers['all_modes']:
        base_numbers.loc['pkt_2030_scenario', mode] = (1-(covid/100))*base_numbers.loc['pkt_2030_scenario', mode]
        if mode in ['cycling', 'walking']:
            base_numbers.loc['vkt_2030_scenario', mode] = base_numbers.loc['pkt_2030_scenario', mode]
        elif mode in ['light_fleet', 'electric_light']:
            base_numbers.loc['vkt_2030_scenario', mode] = base_numbers.loc['pkt_2030_scenario', mode]/numbers['car_occupancy']
    return base_numbers


# Initialisation
pt_details, master_base_numbers, emission_factors = data_load()
numbers = data_initialisation(master_base_numbers)
pt_effects_vkt, pt_effects_pkt = pt_proj_effects(numbers, master_base_numbers, pt_details)











body_text = {
    'header_intro': 'It can be daunting to consider the emissions produced every year, and very challenging to work out what we can do to reduce them. In the Auckland Region in 2016, nearly 40% of greenhouse gas emissions were from road transport. This tool is designed to show the effect of changes and improvements to our transport network, and work out what changes can be made to reduce our emissions.',
    'changes_text': 'Below are several different options for changes and improvements to Auckland Region\'s transport network. Make some changes, and see how they affect the emissions per year, and the distance people travel by each mode.',
    'cars_text': 'Although knowing emissions can be good for gauging the environmental impact of our transport system, they do not provide a full view of the transport environment. ',
    'cars_text2': 'Below are approximate numbers of cars travelling on Auckland region roads under the different scenarios. This should help to gauge traffic levels and general state of transport under each scenario.',
    'instruction_text': 'This tool is intended to show how changes and improvements to Auckland\'s transport network will change the emissions from the Auckland region. Above are several projects and hypothetical changes to the network. Try including different combinations, and seeing how it affects the total emissions.',
    'instruction_text1': 'In the graphs and other outputs, 2030 baseline shows what we expect to see in 2030 without any of the changes and improvements being included (and accounting for the population increase from 2018). 2030 scenario shows what we expect to see in 2030 given the changes you have selected. 2018 is the values observed and calculated for 2018.',
    'instruction_text2': 'We are only looking at road transport and rail here, and only including passenger travel. Sea and air travel have been excluded, as has freight transport.',
    'pt_projects_info': 'Some of the PT projects listed are currently in construction, while others are still in the conceptual phase. When the projects are marked as included, it is assumed that they are fully completed and in frequent use by 2030. We do not suppose that these projects would be full all the time, but we would assume that they are close to being at capacity during the peak periods.',
    'bus_ridership_info': 'Regular improvements and updates to the bus network in Auckland means that ridership increases at a relatively steady rate each year. This increase has not been accounted for in the baseline figures for 2030. The options available to select include increasing at the current trend, or at some higher rate. A higher rate of increase would come from increased investment in the bus network, for things like frequency increases.',
    'cycling_projects_info': 'An investment programme was proposed for cycling improvements between 2018 and 2028. The programme targets practical trips and journeys where mode shift to cycling would benefit the wider transport system. It is about targeting congestion and improving access to jobs and study across Auckland. The choices you can select include this invetment programme, and several other versions on higher scales. As a final option, you can see what would happen if Auckland reached that same proportion of mode share from cycling as Copenhagen.',
    'bus_electrification_info': 'The buses in Auckland are mostly diesel currently. Auckland Transport announced they plan to have all new buses from 2025 be fully electric and have an entirely electric fleet by 2040. By bringing forwards the start year of this process, a higher proportion of the buses would be electric by 2030.',
    'improved_car_emissions_info': 'New Zealand cars have higher emissions per km than many other countries. As older cars are gradually replaced me new cars, the average emissions per km will decrease. Adding more regulations for imported vehicles will accelerate this improvement too. We can expect a decrease in average car emissions of about 10% by 2030 through the cycling out of old cars for newer cars. If we imposed new regulations in an effort to catch up with the rest of the world, we would see a more significant decrease in emissions per km.',
    'car_electrification_info': 'Currently electric cars make up a very small proportion of our car fleet. We expect this proportion to increase over time, and some projections expect our fleet to be roughly 10% elecric by 2030. If the purchace of electric cars is incentivised, then the proportion of electric cars by 2030 could be much higher than 10%.',
    'car_occupancy_info': 'Currently, the average car occupancy in New Zealand is 1.58 people per car. By increasing this, so there are more people in each car on average, the number of vehicle km will decrease relative to the number of passenger km. This increase in occupancy could be acheived through incentives to ride-share, such as an increase T2 or T3 lanes.',
    'northwest': 'The Auckland Transport Alignment Project (ATAP) has committed to providing light rail between the City Centre and Auckland’s northwest within the next ten years (2018-2028).',
    'a2c': 'The Auckland Transport Alignment Project (ATAP) has committed to providing light rail between the City Centre and Māngere within the next ten years (2018-2028).',
    'ameti': 'AMETI (Auckland Manukau Eastern Transport Initiative) Eastern busway will create a dedicated, congestion-free busway between Panmure, Pakuranga, and Botany town centres.',
    'a2b': 'The Airport to Botany Rapid Transit project will deliver a new rapid public transport link between the airport, Manukau and Botany, which will improve accessibility in the southern and eastern areas of Auckland and provide an important link in the rapid transit network, with connections to the rail network at Puhinui and Manukau stations, the Eastern Busway at Botany Interchange and light rail at the Airport.',
    'isthmus': 'The Cross Isthmus corridor is currently relatively undeveloped but connects a number of major growth areas across the southern isthmus: New Lynn, Avondale, Mt Roskill, Three Kings, Royal Oak and Onehunga. There are plans to develop this corridor further, with a particular focus on how it can support growth and integrate with the City-Airport corridor.',
    'crl': 'The CRL is a 3.45km twin-tunnel underground rail link up to 42 metres below the city centre transforming the downtown Britomart Transport Centre into a two-way through-station that better connects the Auckland rail network. It is due to be completed in 2024.',
    'covid_text': 'COVID-19 has brought some unexpected changes, including the sginificantly reduced numbers of people leaving their homes. What if people just stopped making trips? See what the emissions look like with reduced trips taken.',
    'covid_text2': 'An 80% reduction is roughly what we are seeing in our stage four lockdown.',
}










colors = {
    'white': '#FFFFFF',
    'black': '#111111',
    'light_blue': '#daecf2',
    'light_orange': '#f2e0da',
    'blue': '#2fabe1',
    'dark_blue': '#1320ae',
    'grey_blue': '#4b4f7b',
    'orange': '#e58a69',
    'orange_red': '#ae2513',
    'grey_red': '#7b514b',

    'far_background': '#364161',
    'covid_background': '#8d4951',
    'med_background': '#364161',
    'near_background': '#445174',
    'option_text': '#e2e0f1',
    'option_text_dark': '#1320ae',
    'contrast_option_text': '#f2e0da',
    'text': '#FFFFFF',
    'info_text': '#FFFFFF',
    'header_text': '#e2e0f1',
    'header2_text': '#e2e0f1',
    'header3_text': '#e2e0f1',
    'header4_text': '#e2e0f1',
    'header5_text': '#e2e0f1',
    'header6_text': '#e2e0f1',

    'passenger_light': '#f75263',
    'electric_light': '#d52b00',
    'diesel_bus': '#f7f53e',
    'electric_bus': '#eeac00',
    'heavy_rail': '#469ae2',
    'light_rail': '#004786',
    'walking': '#65d799',
    'cycling': '#1f9e65',

    'car_text': '#f75263',

}

font_size = {
    'text_size': 18,
    'large_text': 25,
    'graph_text_size': 18,
    'legend_text_size': 16,
    'cars': 30,
    'emissions': 30,
    'H1': 70,
    'H2': 55,
    'H3': 45,
    'H4': 40,
    'H5': 30,
    'H6': 25,

}
pad = 40



colorway_colours = [colors['passenger_light'], colors['electric_light'], colors['diesel_bus'], colors['electric_bus'], colors['heavy_rail'], colors['light_rail'], colors['walking'], colors['cycling']]
text_size = 18

external_stylesheets = ['https://codepen.io/chriddyp/pen/bWLwgP.css']
app = dash.Dash(__name__, external_stylesheets=external_stylesheets)




app.layout = html.Div(
    # DIV 0
    style = {
        'backgroundColor': colors['far_background'], 
        'columnCount': 1,
        
    }, 
    children = [
    html.Div(
        # DIV 1A
        style = {
            'backgroundColor': colors['far_background'], 
            'columnCount': 1,
            'marginTop': 50,
            'marginBottom': 50,
            'marginLeft': 100,
            'marginRight': 100,
            #'border':'1px solid', 
            'border-radius': 0,
            'display': 'flex', 
            'flexWrap': 'wrap',
        }, 
        children = [
            html.Div(# DIV 2A - around heading
                style = {
                    'backgroundColor': colors['med_background'], 
                    'columnCount': 1,
                    'marginTop': 20,
                    'marginBottom': 20,
                    #'width': 1900,
                    'marginLeft': 'auto',
                    'marginRight': 'auto',
                }, 
                children = [
                    html.Div(# DIV 2A - inner around heading
                        style = {
                            'backgroundColor': colors['med_background'], 
                            'columnCount': 1,
                            'marginTop': 20,
                            'marginBottom': 20,
                            'width': 1900,
                            'marginLeft': 0,
                            'marginRight': 0,
                        }, 
                        children = [
                            html.H1(
                                children='Transport Emissions in the Auckland Region',
                                style={
                                    'textAlign': 'center',
                                    'color': colors['header_text'],
                                    'fontSize': font_size['H1'],
                                }
                            ),
                            html.P(
                                style={
                                    'textAlign': 'center',
                                    'color': colors['header_text'],
                                    'fontSize': font_size['large_text'],
                                },
                                children = body_text['header_intro']
                            )

                        ],
                    ),

                ],
            ),
            html.Div(# DIV 2B - everything
                style = {
                    'backgroundColor': colors['med_background'], 
                    'columnCount': 1,
                    'marginTop': 20,
                    'marginBottom': 20,
                    'marginLeft': 'auto',
                    'marginRight': 'auto',
                    'width': 2000,
                    #'vertical-align': 'centre',
                    #'display': 'inline-block',
                }, 
                #className='container',
                children = [
                    html.Div(# DIV 3A - all content box
                        style = {
                            'backgroundColor': colors['med_background'], 
                            'columnCount': 1,
                            'marginTop': 0,
                            'marginBottom': 0,
                            'marginLeft': 0,
                            'marginRight': 0,
                            'border-radius': 0,
                        }, 
                        children = [
                        
                        html.Div( # Border around left column box
                            style = {
                                    'backgroundColor': colors['near_background'], 
                                    'columnCount': 1,
                                    'marginTop': 0,
                                    'marginBottom': 0,
                                    'marginLeft': 0,
                                    'marginRight': 0,
                                    'width': 550,
                                    'border-radius': 10,
                                }, 
                            children = [
                                html.Div(# DIV 4A - left column content                                
                                    style = {
                                        'backgroundColor': colors['near_background'], 
                                        'columnCount': 1,
                                        'marginTop': pad,
                                        'marginBottom': pad,
                                        'marginLeft': pad,
                                        'marginRight': pad,
                                        'height': 1200,
                                    }, 
                                    children = [
                                        html.H4( # Changes and Choices
                                            children='Changes and Choices',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header2_text'],
                                                'fontSize': font_size['H4'],
                                            }
                                        ),

                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['changes_text']
                                        ),

                                        html.H5( # PT Projects
                                            children = 'PT Projects',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }
                                        ),
                                        
                                        dcc.Checklist( # pt_included
                                            id = 'pt_included',
                                            options=[
                                                {'label': 'City Rail Link', 'value': 'CRL'},
                                                {'label': 'Aiport to Botany', 'value': 'A2B'},
                                                {'label': 'Isthmus Crosstown', 'value': 'IsthmusCrosstown'},
                                                {'label': 'Northwestern Light Rail', 'value': 'NorthwesternLightRail'},
                                                {'label': 'City to Airport Light Rail', 'value': 'AirportLightRail'},
                                                {'label': 'Eastern Busway (AMETI)', 'value': 'AMETI'}
                                            ],
                                            labelStyle = {
                                                'fontSize': font_size['text_size'],
                                            },
                                            style={
                                                'color': colors['option_text'],
                                            },
                                            values = []
                                        ),


                                        html.H5( # Bus Ridership Increase
                                            children = 'Bus Ridership Increase',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }),

                                        dcc.RadioItems( # bus_prop_increase
                                            id = 'bus_prop_increase',
                                            options=[
                                                {'label': 'No Bus Ridership Change from 2018', 'value': 0},
                                                {'label': 'Bus Ridership Increases with Current Trends', 'value': 0.4},
                                                {'label': 'Bus Ridership Increases with Double Current Trends', 'value': 0.8},
                                                {'label': 'Bus Ridership Increases with Triple Current Trends', 'value': 1.2},
                                            ],
                                            value=0,
                                            style={
                                                'color': colors['option_text']
                                            },
                                            labelStyle = {
                                                'fontSize': font_size['text_size'],
                                            },
                                        ),


                                        html.H5( # Cycling Projects Included
                                            children = 'Cycling Projects Included',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }),

                                        dcc.RadioItems( # cycling_included
                                            id = 'cycling_included',
                                            options=[
                                                {'label': 'No Cycling Mode Share Increase', 'value': 0},
                                                {'label': 'Cycling Investment Plan', 'value': 5},
                                                {'label': 'Double Cycling Investment Plan', 'value': 10},
                                                {'label': 'Reach Cycling Levels of Copenhagen', 'value': 24},
                                            ],
                                            value=0,
                                            style={
                                                'color': colors['option_text']
                                            },
                                            labelStyle = {
                                                'fontSize': font_size['text_size'],
                                            },
                                        ),


                                        html.H5( # Bus Electrification Start Year
                                            children = 'Bus Electrification Start Year',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }),

                                        dcc.Dropdown( # bus_electrification_included
                                            id = 'bus_electrification_included',
                                            options=[
                                                {'label': 'No Bus Electrification', 'value': 0},
                                                {'label': '2020', 'value': 2020},
                                                {'label': '2021', 'value': 2021},
                                                {'label': '2022', 'value': 2022},
                                                {'label': '2023', 'value': 2023},
                                                {'label': '2024', 'value': 2024},
                                                {'label': '2025 (Current Plan)', 'value': 2025}
                                            ],
                                            value=0,
                                        ),


                                        html.H5( # Improved Car Emission Standards
                                            children = 'Improved Car Emission Standards',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }),

                                        dcc.Dropdown( # car_emission_change
                                            id = 'car_emission_change',
                                            options=[
                                                {'label': 'No Change From 2018', 'value': 0},
                                                {'label': '10% decrease in emissions per km', 'value': 0.1},
                                                {'label': '20% decrease in emissions per km', 'value': 0.2},
                                                {'label': '30% decrease in emissions per km', 'value': 0.3},
                                                {'label': '40% decrease in emissions per km', 'value': 0.4},
                                                {'label': '50% decrease in emissions per km', 'value': 0.5},
                                                {'label': '60% decrease in emissions per km', 'value': 0.6}
                                            ],
                                            value=0,
                                        ),


                                        html.H5( # Car Electrification Proportion
                                            children = 'Car Electrification Proportion',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                            }),

                                        dcc.Slider( # car_electrification_included
                                            id = 'car_electrification_included',
                                            min=0,
                                            max=100,
                                            marks={i: '{:.0f} %'.format(i) for i in range(0, 101, 10)},
                                            value=0,
                                        ),


                                        html.H5( # Average Car Occupancy
                                            children = 'Average Car Occupancy',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header3_text'],
                                                'fontSize': font_size['H5'],
                                                'marginTop': 30
                                            }),

                                        dcc.Slider(# occupancy_included
                                            id = 'occupancy_included',
                                            min=140,
                                            max=200,
                                            marks={
                                                140: {'label': '1.4', 'style': {'color': colors['option_text']}},
                                                150: {'label': '1.5', 'style': {'color': colors['option_text']}},
                                                158: {'label': '1.58', 'style': {'color': colors['contrast_option_text']}},
                                                170: {'label': '1.7', 'style': {'color': colors['option_text']}},
                                                180: {'label': '1.8', 'style': {'color': colors['option_text']}},
                                                190: {'label': '1.9', 'style': {'color': colors['option_text']}},
                                                200: {'label': '2.0', 'style': {'color': colors['option_text']}}
                                                },
                                            value=158,
                                        ),
                                    ],
                                ),

                        ], className="six columns"),

                        html.Div( # Border around middle column box
                            style = {
                                'backgroundColor': colors['near_background'], 
                                'columnCount': 1,
                                'marginTop': 0,
                                'marginBottom': 0,
                                'marginLeft': 50,
                                'marginRight': 0,
                                'width': 850,
                                'border-radius': 10,
                            }, 
                            children = [
                                html.Div(# DIV 4B - middle column content
                                    style = {
                                        'backgroundColor': colors['near_background'], 
                                        'columnCount': 1,
                                        'marginTop': pad,
                                        'marginBottom': pad,
                                        'marginLeft': pad,
                                        'marginRight': pad,
                                        'height': 1200,
                                    }, 
                                    children = [

                                        html.H4( # Auckland Transport Emissions
                                            children = 'Auckland Transport Emissions',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                                'marginTop': 0
                                            }),

                                        html.Div(
                                            style = {
                                                'backgroundColor': colors['near_background'],
                                                'columnCount': 3,
                                                'marginTop': pad,
                                                'marginBottom': pad,
                                            },
                                            children = [
                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2018:']
                                                ),
                                                html.P(
                                                    id = 'emissions_2018',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['electric_bus'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),
                                                
                                                html.P(
                                                    
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2030 Baseline:']
                                                ),
                                                html.P(
                                                    id = 'emissions_2030_baseline',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['passenger_light'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),

                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2030 Scenario:']
                                                ),
                                                html.P(
                                                    id = 'emissions_2030_scenario',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['passenger_light'],
                                                        'fontSize': font_size['emissions'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),
                                            ],
                                        ),
                                        
                                        
                                        dcc.Graph( # stacked_emissions
                                            id='stacked_emissions',
                                            config ={'displayModeBar': False},
                                        ),

                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['passenger_light'],
                                                'fontSize': font_size['emissions'],
                                                'marginBottom': 50,
                                            },
                                            children = ' '
                                        ),

                                        dcc.Graph( # stacked_emissions
                                            id='stacked_emissions1',
                                            config ={'displayModeBar': False},
                                        ),
                                    ],
                                ),
                        ], className="six columns"),


                        html.Div( # Border around right column boxes (both)
                            style = {
                                'backgroundColor': colors['far_background'], 
                                'columnCount': 1,
                                'marginTop': 0,
                                'marginBottom': 0,
                                'marginLeft': 0,
                                'marginRight': 0,
                                'width': 500,
                                'border-radius': 0,
                            }, 
                            children = [
                                html.Div( # Inner border around right column box (top)
                                    style = {
                                        'backgroundColor': colors['near_background'], 
                                        'columnCount': 1,
                                        'marginTop': 0,
                                        'marginBottom': 0,
                                        'marginLeft': 50,
                                        'marginRight': 0,
                                        'width': 500,
                                        'border-radius': 10,
                                    }, 
                                    children = [
                                        html.Div( # DIV 4C - top right column content
                                            style = {
                                                'backgroundColor': colors['near_background'], 
                                                'columnCount': 1,
                                                'marginTop': pad,
                                                'marginBottom': pad,
                                                'marginLeft': pad,
                                                'marginRight': pad,
                                                'height': 595,
                                            }, 
                                            children = [
                                                html.H4( # Cars
                                                    children='Cars on the Road',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['header2_text'],
                                                        'fontSize': font_size['H4'],
                                                    },
                                                ),

                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['info_text'],
                                                        'fontSize': font_size['text_size'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = body_text['cars_text2'],
                                                ),

                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2018:']
                                                ),
                                                html.P(
                                                    id = 'cars_2018',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['electric_bus'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),
                                                
                                                html.P(
                                                    
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2030 Baseline:']
                                                ),
                                                html.P(
                                                    id = 'cars_2030_baseline',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['passenger_light'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),

                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['text'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 0,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = ['2030 Scenario:']
                                                ),
                                                html.P(
                                                    id = 'cars_2030_scenario',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['passenger_light'],
                                                        'fontSize': font_size['cars'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                html.Div( # Inner border around right column box (bottom)
                                    style = {
                                        'backgroundColor': colors['covid_background'], 
                                        'columnCount': 1,
                                        'marginTop': 25,
                                        'marginBottom': 0,
                                        'marginLeft': 50,
                                        'marginRight': 0,
                                        'width': 500,
                                        'border-radius': 10,
                                    }, 
                                    children = [
                                        html.Div(# DIV 4C - bottom right column content
                                            style = {
                                                'backgroundColor': colors['covid_background'], 
                                                'columnCount': 1,
                                                'marginTop': pad,
                                                'marginBottom': pad,
                                                'marginLeft': pad,
                                                'marginRight': pad,
                                                'height': 500,
                                            }, 
                                            children = [
                                                html.H4( # Covid
                                                    children='COVID-19',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['header2_text'],
                                                        'fontSize': font_size['H4'],
                                                    }
                                                ),

                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['info_text'],
                                                        'fontSize': font_size['text_size'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = body_text['covid_text']
                                                ),
                                                html.P(
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['info_text'],
                                                        'fontSize': font_size['text_size'],
                                                        'marginBottom': 15,
                                                        'marginLeft': 5,
                                                        'marginRight': 5,
                                                    },
                                                    children = body_text['covid_text2']
                                                ),

                                                html.H5( # Reduction in Trips Taken
                                                    children = 'Reduction in Trips Taken',
                                                    style={
                                                        'textAlign': 'left',
                                                        'color': colors['header5_text'],
                                                        'fontSize': font_size['H5'],
                                                        'marginTop': 30
                                                    }),

                                                dcc.Slider(# covid
                                                    id = 'covid',
                                                    min=0,
                                                    max=100,
                                                    marks={i: '{}%'.format(i) for i in range(0, 101, 10)},
                                                    value=0,
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                        ], className="six columns"),
                    ], className="row"),
                    

                    html.Div(
                            style = {
                                'backgroundColor': colors['near_background'], 
                                'columnCount': 1,
                                'marginTop': 25,
                                'marginBottom': 0,
                                'marginLeft': 0,
                                'marginRight': 0,
                                'width': 2000,
                                'border-radius': 10,
                            }, 
                            children = [
                                html.Div(# Bottom box content, header
                                    style = {
                                        'backgroundColor': colors['near_background'], 
                                        'columnCount': 1,
                                        'marginTop': pad,
                                        'marginBottom': pad,
                                        'marginLeft': pad,
                                        'marginRight': pad,
                                        'width': 1700,
                                    }, 
                                    children = [
                                        html.H2( # Instructions
                                            children = 'Instructions and Information',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header2_text'],
                                                'fontSize': font_size['H2'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['large_text'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['instruction_text']
                                        ),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['large_text'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['instruction_text1']
                                        ),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['large_text'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['instruction_text2']
                                        ),
                                    ],
                                ),

                                html.Div(# Bottom box content, text
                                    style = {
                                        'backgroundColor': colors['near_background'], 
                                        'marginTop': 0,
                                        'marginBottom': pad,
                                        'marginLeft': pad,
                                        'marginRight': pad,
                                        #'height': 500,
                                        'columnCount': 2
                                    }, 
                                    children = [
                                        html.H4( # PT Projects info
                                            children = 'Public Transport Projects',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['pt_projects_info']
                                        ),


                                        html.H6( # City Rail Link
                                            children = 'City Rail Link',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['crl']
                                        ),

                                        html.H6( # Airport to Botany
                                            children = 'Airport to Botany',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['a2b']
                                        ),

                                        html.H6( # Isthmus Crosstown
                                            children = 'Isthmus Crosstown',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['isthmus']
                                        ),

                                        html.H6( # Northwestern Light Rail
                                            children = 'Northwestern Light Rail',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['northwest']
                                        ),

                                        html.H6( # City to Airport Light Rail
                                            children = 'City to Airport Light Rail',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['a2c']
                                        ),

                                        html.H6( # Eastern Busway (AMETI)
                                            children = 'Eastern Busway (AMETI)',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header6_text'],
                                                'fontSize': font_size['H6'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 50,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['ameti']
                                        ),

                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['near_background'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 500,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = 'Super secret hidden text ' 
                                        ),



                                        html.H4( # Bus ridership info
                                            children = 'Bus Ridership Levels',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['bus_ridership_info']
                                        ),

                                        html.H4( # Cycling Investment
                                            children = 'Cycling Projects',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['cycling_projects_info']
                                        ),

                                        html.H4( # Bus Electrification
                                            children = 'Bus Electrification',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['bus_electrification_info']
                                        ),

                                        html.H4( # Car Emissions
                                            children = 'Car Emission Standards',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['improved_car_emissions_info']
                                        ),

                                        html.H4( # Car Electrification
                                            children = 'Car Electrification',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['car_electrification_info']
                                        ),

                                        html.H4( # Car Occupancy
                                            children = 'Car Occupancy',
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['header4_text'],
                                                'fontSize': font_size['H4'],
                                            }),
                                        html.P(
                                            style={
                                                'textAlign': 'left',
                                                'color': colors['info_text'],
                                                'fontSize': font_size['text_size'],
                                                'marginBottom': 15,
                                                'marginLeft': 5,
                                                'marginRight': 5,
                                            },
                                            children = body_text['car_occupancy_info']
                                        ),
                                    ],
                                ),
                        ]),
                ],
            ),
            
        ],
    ),
])






@app.callback([
    Output('stacked_emissions', 'figure'),
    Output('stacked_emissions1', 'figure'),
    Output('cars_2018', 'children'),
    Output('cars_2030_baseline', 'children'),
    Output('cars_2030_scenario', 'style'),
    Output('cars_2030_scenario', 'children'),
    Output('emissions_2030_scenario', 'style'),
    Output('emissions_2018', 'children'),
    Output('emissions_2030_baseline', 'children'),
    Output('emissions_2030_scenario', 'children'),
    ],
    [Input('cycling_included', 'value'),
     Input('bus_prop_increase', 'value'),
     Input('bus_electrification_included', 'value'),
     Input('occupancy_included', 'value'),
     Input('car_electrification_included', 'value'),
     Input('pt_included', 'values'),
     Input('car_emission_change', 'value'),
     Input('covid', 'value'),
    ])
def update_graph(
    cycling_included, 
    bus_prop_increase, 
    bus_electrification_included, 
    occupancy_included, 
    car_electrification_included, 
    pt_included, 
    car_emission_change, 
    covid,
):
    occupancy_included = occupancy_included/100
    car_electrification_included = car_electrification_included/100
    

    base_numbers = master_base_numbers.copy()
    
    # Applying Selected Changes
    base_numbers = pt_projects_apply(base_numbers, pt_effects_vkt, pt_effects_pkt, pt_included)
    base_numbers = bus_ridership_changes(numbers, base_numbers, bus_prop_increase)
    base_numbers = cycling_changes(numbers, base_numbers, cycling_included)

    base_numbers = bus_electric(numbers, base_numbers, bus_electrification_included)
    base_numbers = car_electric(base_numbers, car_electrification_included)

    base_numbers = covid_trips(base_numbers, covid, numbers)

    base_numbers = car_occupancy(base_numbers, occupancy_included)
    base_numbers = calculate_emissions(base_numbers, emission_factors, car_emission_change)


    

    emissions_rows = ['emissions_2018', 'emissions_2030_baseline', 'emissions_2030_scenario']
    emissions_row_labels = ['2018', '2030 Baseline', '2030 Scenario', '2018x', '2030 Baselinex', '2030 Scenariox', 'x', 'xx']
    base_numbers_emissions = base_numbers.loc[emissions_rows]
    #base_numbers_emissions = base_numbers_emissions.transpose()

    pkt_rows = ['pkt_2018', 'pkt_2030_baseline', 'pkt_2030_scenario']
    #vkt_rows = ['vkt_2018', 'vkt_2030_baseline', 'vkt_2030_scenario']

    base_numbers_pkt = base_numbers.loc[pkt_rows]
    base_numbers_pkt = base_numbers_pkt.transpose()

    emissions_2018_num = base_numbers_emissions.loc['emissions_2018'].sum()/(10**9)
    emissions_2030_baseline_num = base_numbers_emissions.loc['emissions_2030_baseline'].sum()/(10**9)
    emissions_2030_scenario_num = base_numbers_emissions.loc['emissions_2030_scenario'].sum()/(10**9)

    emissions_2018 = '{:,.3f} Mt CO2-e'.format(emissions_2018_num)
    emissions_2030_baseline = '{:,.3f} Mt CO2-e'.format(emissions_2030_baseline_num)
    emissions_2030_scenario = '{:,.3f} Mt CO2-e'.format(emissions_2030_scenario_num)

    if emissions_2030_scenario_num > emissions_2030_baseline_num:
        emissions_colour = colors['electric_light']
    elif emissions_2030_scenario_num > (emissions_2018_num):
        emissions_colour = colors['passenger_light']
    elif emissions_2030_scenario_num > (emissions_2018_num/2):
        emissions_colour = colors['electric_bus'],
    else:
        emissions_colour = colors['walking'],

    emissions_style = {'textAlign': 'left', 'color': emissions_colour, 'fontSize': font_size['emissions'], 'marginBottom': 15, 'marginLeft': 5, 'marginRight': 5,}

    cars_2030_baseline_num = numbers['2018_car_ownership']/(base_numbers.loc['vkt_2018', 'passenger_light']+base_numbers.loc['vkt_2018','electric_light'])*(base_numbers.loc['vkt_2030_baseline', 'passenger_light']+base_numbers.loc['vkt_2030_baseline','electric_light'])
    cars_2030_scenario_num = numbers['2018_car_ownership']/(base_numbers.loc['vkt_2018', 'passenger_light']+base_numbers.loc['vkt_2018','electric_light'])*(base_numbers.loc['vkt_2030_scenario', 'passenger_light']+base_numbers.loc['vkt_2030_scenario','electric_light'])


    if cars_2030_scenario_num > cars_2030_baseline_num:
        car_colour = colors['electric_light']
    elif cars_2030_scenario_num > 1432825:
        car_colour = colors['passenger_light']
    elif cars_2030_scenario_num > 1089207:
        car_colour = colors['electric_bus'],
    else:
        car_colour = colors['walking'],
    cars_style = {'textAlign': 'left', 'color': car_colour, 'fontSize': font_size['cars'], 'marginBottom': 15, 'marginLeft': 5, 'marginRight': 5,}
    
    base_numbers_emissions = base_numbers_emissions.transpose()
    
    cars_2018 = '{:,.0f} cars'.format(numbers['2018_car_ownership'])
    cars_2030_baseline = '{:,.0f} cars '.format(cars_2030_baseline_num)
    cars_2030_scenario = '{:,.0f} cars '.format(cars_2030_scenario_num)

    trace1 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['passenger_light'], name='Petrol and Diesel Cars', hovertemplate = '%{y:,.2f} kg CO2-e') #<extra></extra>
    trace2 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['electric_light'], name='Electric Cars', hovertemplate = '%{y:,.2f} kg CO2-e')
    trace3 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['diesel_bus'], name='Diesel Buses', hovertemplate = '%{y:,.2f} kg CO2-e')
    trace4 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['electric_bus'], name='Electric Buses', hovertemplate = '%{y:,.2f} kg CO2-e')
    trace5 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['heavy_rail'], name='Heavy Rail', hoverinfo = 'none', showlegend = False)
    trace6 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['light_rail'], name='Light Rail', hoverinfo = 'none', showlegend = False)
    trace7 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['walking'], name='Walking', hoverinfo = 'none', showlegend = False)
    trace8 = go.Bar(x=emissions_row_labels, y=base_numbers_emissions.loc['cycling'], name='Cycling', hoverinfo = 'none', showlegend = False)

    trace9 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['passenger_light'], name='Petrol and Diesel Cars', hovertemplate = '%{y:,.2f} km') 
    trace10 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['electric_light'], name='Electric Cars', hovertemplate = '%{y:,.2f} km')
    trace11 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['diesel_bus'], name='Diesel Buses', hovertemplate = '%{y:,.2f} km')
    trace12 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['electric_bus'], name='Electric Buses', hovertemplate = '%{y:,.2f} km')
    trace13 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['heavy_rail'], name='Heavy Rail', hovertemplate = '%{y:,.2f} km')
    trace14 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['light_rail'], name='Light Rail', hovertemplate = '%{y:,.2f} km')
    trace15 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['walking'], name='Walking', hovertemplate = '%{y:,.2f} km')
    trace16 = go.Bar(x=emissions_row_labels, y=base_numbers_pkt.loc['cycling'], name='Cycling', hovertemplate = '%{y:,.2f} km')


    emissions_by_mode = {'data': [trace1, trace2, trace3, trace4, trace5, trace6, trace7, trace8],
        'layout':
            go.Layout(
                title='Auckland Transport Emissions by Mode', 
                barmode='stack', 
                font = {
                    'color': colors['option_text'],
                    'size': 16
                },
                legend={
                    'bgcolor': colors['near_background'],
                    'bordercolor': colors['far_background'],
                    'font': {
                        'color': colors['option_text'],
                        'size': 16,
                    }
                },
                margin={
                    'l': 80,
                    'b': 80,
                    't': 80,
                    #'pad': 20
                },
                #height = 400,
                #width = 600,
                autosize= True,
                separators = ".,",
                paper_bgcolor=colors['near_background'],
                plot_bgcolor=colors['near_background'],
                colorway = colorway_colours,
                xaxis = {
                    'visible': True,
                    'title': 'Year and Scenario',
                },
                yaxis = {
                    'visible': True,
                    'title': 'Emissions per year (kg CO2-equivalent)',
                },
            )}



    pkt_by_mode = {
        'data': [trace9, trace10, trace11, trace12, trace13, trace14, trace15, trace16],
        'layout':
            go.Layout(
                title='Passenger km Travelled by Mode', 
                barmode='stack', 
                font = {
                    'color': colors['option_text'],
                    'size': font_size['graph_text_size']
                },
                legend={
                    'bgcolor': colors['near_background'],
                    'bordercolor': colors['far_background'],
                    'font': {
                        'color': colors['option_text'],
                        'size': font_size['legend_text_size'],
                    }
                },
                margin={
                    'l': 80,
                    'b': 80,
                    't': 80,
                    #'pad': 20
                },
                #height = 400,
                #width = 600,
                autosize= True,
                separators = ".,",
                paper_bgcolor=colors['near_background'],
                plot_bgcolor=colors['near_background'],
                colorway = colorway_colours,
                xaxis = {
                    'visible': True,
                    'title': 'Year and Scenario',
                },
                yaxis = {
                    'visible': True,
                    'title': 'Distance travelled per year (km)',
                },
            )

    }
    return emissions_by_mode, pkt_by_mode, cars_2018, cars_2030_baseline, cars_style, cars_2030_scenario, emissions_style, emissions_2018, emissions_2030_baseline, emissions_2030_scenario






if __name__ == '__main__':
    app.run_server(debug=True)
    #app.config['suppress_callback_exceptions']=True
