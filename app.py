import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import altair as alt
from streamlit_observable import observable

import numpy as np
import itertools as itertools

from config.config import TOP_N
from config.query import BigQueryClient

@st.cache_data
def load_token_distribution(_bq: BigQueryClient, token_name: str, granularity: str):
    """Load token distribution data from BigQuery with a percentage and granularity."""
    
    token_distribution_df = _bq.get_token_distribution(token_name, granularity)
    
    # Get unique IDs from the token_distribution_df
    unique_ids = token_distribution_df['id'].unique()

    # Retrieve rows from table A based on unique IDs
    table_a_df = _bq.get_table_rows('A', unique_ids)
    
    return token_distribution_df, table_a_df

@st.cache_resource
def plot_time_series(data, x_axis, y_axis, color_category):

    x_col = x_axis.split(':')[0]
    y_col = y_axis.split(':')[0]
    color_col = color_category.split(':')[0]

    # Calculate the total and normalized values for stacking
    y_total_col = f"total_{y_col}"
    data[y_total_col] = data.groupby(x_col)[y_col].transform('sum')
    data['normalized_y'] = (data[y_col] / data[y_total_col]) * 100

    # Rank Categories
    category_totals = data.groupby(color_col)[y_col].sum().reset_index()
    category_totals['rank'] = category_totals[y_col].rank(method='max', ascending=False)
    top_categories = category_totals[category_totals['rank'] <= TOP_N][color_col]

    # Modify Categories
    data['adjusted_category'] = data.apply(lambda row: row[color_col] if row[color_col] in top_categories.values else 'Other', axis=1)
    # Original Line Chart
    line_chart = alt.Chart(data).mark_line().encode(
        x=alt.X(x_axis, axis=alt.Axis(format="%Y-%m")),
        y=y_axis,
        color='adjusted_category:N'
    ).interactive()

    # Calculate Percentages for Stacked Area Chart
    y_total_col = f"total_{y_col}"
    data[y_total_col] = data.groupby(x_col)[y_col].transform('sum')
    data['normalized_y'] = (data[y_col] / data[y_total_col]) * 100

    # Stacked Area Chart
    area_chart = alt.Chart(data).mark_area().encode(
        x=alt.X(x_axis, axis=alt.Axis(format="%Y-%m")),
        y=alt.Y('normalized_y:Q', stack='normalize', axis=alt.Axis(format='%')),
        color='adjusted_category:N'
    ).interactive()

    # Combine the charts horizontally
    combined_charts = alt.vconcat(line_chart, area_chart).resolve_legend(
        color='independent'
    )

    return combined_charts

def main():
    """Execute the Streamlit app."""
    st.title("DeFi TVL: Token Distribution Analysis")
    
    bq = BigQueryClient()

    # Selection for the user to define the data granularity
    granularity = st.selectbox("Select data granularity:", options=['daily', 'weekly', 'monthly'], index=2)  # default to 'weekly'

    # User input for selecting a token
    token_name = st.text_input("Enter the token name for analysis (e.g., DAI):", 'USDC')

    if token_name:
        # Fetch data for the specified token name with the user-defined percentage and granularity
        token_distribution_df, table_a_df = load_token_distribution(bq, token_name, granularity)

        # token_distribution_df = token_distribution_df.sample(frac=0.1)

        token_distribution_df['aggregated_date'] = pd.to_datetime(token_distribution_df['aggregated_date'])
        token_distribution_df['aggregated_date'] = token_distribution_df['aggregated_date'].dt.strftime('%Y-%m-%d')

        # Convert DataFrame to JSON-serializable format (list of dictionaries)
        data_for_observable = token_distribution_df.to_dict(orient='records')

        # Pass this data to the Observable component
        observable("Tree", 
                notebook="@venvox-ws/defi-tvl-data-loading", 
                targets=["area"],
                redefine={"data": data_for_observable,})
        
        extracted_df = token_distribution_df[['aggregated_date', 'protocol_name', 'type', 'total_value_usd']]
        extracted_df.columns = ['date', 'name', 'category', 'value']
        extracted_df['value'] = (extracted_df['value'] / 1000000).astype(int)

        # Convert 'date' to datetime and filter out dates before 2021-01-01
        extracted_df['date'] = pd.to_datetime(extracted_df['date'])
        extracted_df = extracted_df[extracted_df['date'] >= '2021-01-01']

        # Adjust all dates to the first day of their respective months
        extracted_df['date'] = extracted_df['date'].apply(lambda x: x.replace(day=1))

        # Group by the new date, name, and category, and sum up the values
        # Adjust this step based on how you want to handle multiple entries
        extracted_df = extracted_df.groupby(['date', 'name', 'category'], as_index=False).sum()

        # Convert 'date' back to string
        extracted_df['date'] = extracted_df['date'].dt.strftime('%Y-%m-%d')

        # Convert the DataFrame to a dictionary
        extracted_df = extracted_df.to_dict(orient='records')

        # Pass this data to the Observable component
        observable("Race", 
                notebook="@venvox-ws/bar-chart-race", 
                targets=["chart"],
                redefine={"data2": extracted_df,})
        
        if token_distribution_df is not None and not token_distribution_df.empty:
            # Display the DataFrame and the time series plot for the token
            st.write(f"#### Retrieved data has {len(token_distribution_df)} rows")
            st.dataframe(token_distribution_df.head())
            st.write(f"#### Where is {token_name} locked? By protocol")
            ts_chart = plot_time_series(token_distribution_df, 'aggregated_date:T', 'total_value_usd:Q', 'protocol_name:N')
            st.altair_chart(ts_chart, use_container_width=True)
        
            # Dropdown for the user to select the aggregation attribute based on table A columns
            if table_a_df is not None and not table_a_df.empty:
                aggregation_attribute = st.selectbox("Select an attribute from Table A for grouping:", 
                                                     options=table_a_df.columns.tolist(), 
                                                     index=table_a_df.columns.tolist().index('chain') 
                                                     if 'category' in table_a_df.columns.tolist() else 0)                
                merged_df = pd.merge(token_distribution_df, table_a_df[['id', aggregation_attribute]], on='id')

                # Merge the two dataframes on the common id ('id')
                merged_df = pd.merge(token_distribution_df, table_a_df[['id', aggregation_attribute]], on='id')

                # Group by the selected attribute and date, and then sum up the total value
                merged_agg = merged_df.groupby([aggregation_attribute, 'aggregated_date']).sum(numeric_only=True).reset_index()

                st.write(f"#### Where is {token_name} locked? By {aggregation_attribute}")
                ts_chart_a = plot_time_series(merged_agg, 'aggregated_date:T', 'total_value_usd:Q', f'{aggregation_attribute}:N')
                st.altair_chart(ts_chart_a, use_container_width=True)

                
        else:
            st.write("No data available for the specified token.")

if __name__ == "__main__":
    main()