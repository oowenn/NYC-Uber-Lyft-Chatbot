"""
Data preview endpoint - returns sample data from fhv_with_company view
"""
from fastapi import APIRouter, Request
from typing import List, Dict, Any
import json

router = APIRouter()


@router.get("/data-preview")
async def get_data_preview(request: Request):
    """Get a sample of data from fhv_with_company view"""
    duckdb_conn = request.app.state.duckdb
    
    try:
        # Get sample rows (first 5 rows with key columns including fare/price)
        query = """
        SELECT 
            pickup_datetime,
            dropoff_datetime,
            company,
            pickup_zone,
            dropoff_zone,
            trip_miles,
            trip_time,
            base_passenger_fare,
            tolls,
            sales_tax,
            congestion_surcharge,
            airport_fee,
            tips,
            driver_pay,
            total_price,
            PULocationID,
            DOLocationID
        FROM fhv_with_company
        LIMIT 5
        """
        
        result = duckdb_conn.execute(query).fetchdf()
        
        # Get column names
        columns = list(result.columns)
        
        # Convert to list of dicts
        data = result.to_dict("records")
        
        return {
            "columns": columns,
            "data": data,
            "row_count": len(data)
        }
    except Exception as e:
        return {
            "columns": [],
            "data": [],
            "row_count": 0,
            "error": str(e)
        }

