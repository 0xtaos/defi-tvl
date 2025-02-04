from google.cloud import bigquery
from google.cloud.bigquery.table import Table
from google.cloud.bigquery.client import Client
from google.cloud.bigquery.dataset import DatasetReference
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials
from typing import Optional
import pandas as pd
import streamlit as st
from .config import TABLES

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import QUERY_DATA_SET, QUERY_PROJECT


class BigQueryClient:
    def __init__(self, project: str = QUERY_PROJECT, dataset: str = QUERY_DATA_SET) -> None:
        self.credentials: Credentials = service_account.Credentials.from_service_account_info(
            st.secrets["gcp_service_account"]
        )
        self.client: Client = bigquery.Client(credentials=self.credentials, project=project)
        self.dataset_ref: DatasetReference = self.client.dataset(dataset)

    def get_table(self, table_name: str) -> Table:
        table_ref = self.dataset_ref.table(table_name)
        return self.client.get_table(table_ref)  # Returns a Table object

    def get_table_schema(self, table_name: str) -> list:
        """Fetch the table schema"""
        table = self.get_table(table_name)
        return table.schema  # Returns a list of SchemaField objects

    def get_dataframe(self, table_name: str, limit: Optional[int] = None) -> pd.DataFrame:
        if limit is not None:
            query_string = (
                f"SELECT * FROM `{self.dataset_ref.dataset_id}.{table_name}` LIMIT {limit}"
            )
        else:
            query_string = (
                f"SELECT * FROM `{self.dataset_ref.dataset_id}.{table_name}`"
            )
        return self.client.query(query_string).to_dataframe()
    
    def get_table_rows(self, table_name, unique_ids):
        table_name = TABLES[table_name]
        """Retrieve entire rows from a specified table based on unique IDs."""
        query = f"""
        SELECT *
        FROM `{self.dataset_ref.dataset_id}.{table_name}`
        WHERE id IN ({', '.join(map(str, unique_ids))})
        """
        return self.client.query(query).to_dataframe()
        
    def get_token_distribution(self, token_name: str, granularity: str) -> pd.DataFrame:
        """Retrieve the distribution of a specific token across protocols over time at specified granularity."""
        print("Preparing SQL query...")

        # Helper function to get the SQL expression for date truncation
        def get_date_trunc_expr(granularity):
            if granularity == 'weekly':
                return "DATE_TRUNC(DATE(TIMESTAMP_SECONDS(CAST(ROUND(C.date) AS INT64))), WEEK(MONDAY))"
            elif granularity == 'monthly':
                return "DATE_TRUNC(DATE(TIMESTAMP_SECONDS(CAST(ROUND(C.date) AS INT64))), MONTH)"
            else:  # Default to daily granularity
                return "DATE(DATE(TIMESTAMP_SECONDS(CAST(ROUND(C.date) AS INT64))))"

        # Get the date truncation expression based on the granularity
        date_trunc_expr = get_date_trunc_expr(granularity)

        # Construct the SQL query with aggregation
        query_string = f"""
        SELECT 
            {date_trunc_expr} as aggregated_date,
            C.id as id,
            A.name as protocol_name,
            A.category as category,
            A.type as type,
            C.chain_name,
            SUM(C.quantity) as total_quantity,
            SUM(C.value_usd) as total_value_usd
        FROM 
            `{self.dataset_ref.dataset_id}.{TABLES['C']}` C
        INNER JOIN 
            `{self.dataset_ref.dataset_id}.{TABLES['A']}` A ON C.id = A.id
        WHERE 
            C.token_name = '{token_name}' AND
            C.quantity > 0 AND
            C.value_usd > 0
        GROUP BY 
            aggregated_date,
            id,
            protocol_name,
            category,
            type,
            chain_name
        ORDER BY 
            aggregated_date,
            id
        """
        print(f"Executing data query: {query_string}")

        # Execute query and retrieve data
        df = self.client.query(query_string).to_dataframe()
        latest_date = df['aggregated_date'].max()
        print(f"Latest date in the fetched data: {latest_date}")

        return df
    
if __name__ == '__main__':
    bq_client = BigQueryClient()
    df = bq_client.get_dataframe('C_protocol_token_tvl', limit=10)
    print(df.head())
