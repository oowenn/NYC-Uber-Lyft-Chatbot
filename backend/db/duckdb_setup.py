"""
DuckDB initialization and view creation
"""
import os
import duckdb
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "../data"))
TAXI_ZONE_LOOKUP = Path(os.getenv("TAXI_ZONE_LOOKUP", "../data/taxi_zone_lookup.csv"))
BASE_LOOKUP = Path(os.getenv("BASE_LOOKUP", "../data/fhv_base_lookup.csv"))
HVFHS_LOOKUP = Path(os.getenv("HVFHS_LOOKUP", "../data/hvfhs_license_num_lookup.csv"))


def init_duckdb():
    """Initialize DuckDB connection and create views"""
    conn = duckdb.connect()
    
    # Load lookup tables
    print(f"Loading taxi zone lookup from {TAXI_ZONE_LOOKUP}")
    conn.execute(f"""
        CREATE OR REPLACE TABLE taxi_zones AS 
        SELECT * FROM read_csv('{TAXI_ZONE_LOOKUP}', header=true, auto_detect=true)
    """)
    
    print(f"Loading base lookup from {BASE_LOOKUP}")
    conn.execute(f"""
        CREATE OR REPLACE TABLE base_lookup AS 
        SELECT * FROM read_csv('{BASE_LOOKUP}', header=true, auto_detect=true)
    """)

    print(f"Loading hvfhs license lookup from {HVFHS_LOOKUP}")
    conn.execute(f"""
        CREATE OR REPLACE TABLE hvfhs_lookup AS 
        SELECT * FROM read_csv('{HVFHS_LOOKUP}', header=true, auto_detect=true)
    """)
    
    # Create raw view (scan all parquet files)
    parquet_pattern = str(DATA_DIR / "fhvhv_tripdata_2023-*.parquet")
    print(f"Creating fhv_raw view from {parquet_pattern}")
    conn.execute(f"""
        CREATE OR REPLACE VIEW fhv_raw AS
        SELECT * FROM parquet_scan('{parquet_pattern}')
    """)
    
    # Create clean view (filter invalid trips)
    conn.execute("""
        CREATE OR REPLACE VIEW fhv_clean AS
        SELECT *
        FROM fhv_raw
        WHERE 
            pickup_datetime IS NOT NULL
            AND dropoff_datetime IS NOT NULL
            AND trip_time > 0
            AND trip_miles > 0
            AND PULocationID IS NOT NULL
            AND DOLocationID IS NOT NULL
    """)
    
    # Create view with zone information
    conn.execute("""
        CREATE OR REPLACE VIEW fhv_with_zones AS
        SELECT 
            f.*,
            pu.Borough AS pickup_borough,
            pu.Zone AS pickup_zone,
            doff.Borough AS dropoff_borough,
            doff.Zone AS dropoff_zone
        FROM fhv_clean f
        LEFT JOIN taxi_zones pu ON f.PULocationID = pu.LocationID
        LEFT JOIN taxi_zones doff ON f.DOLocationID = doff.LocationID
    """)
    
    # Create view with company information (use hvfhs license mapping; base lookup only for base_name)
    conn.execute("""
        CREATE OR REPLACE VIEW fhv_with_company AS
        SELECT 
            f.*,
            (
                COALESCE(f.base_passenger_fare, 0)
                + COALESCE(f.tolls, 0)
                + COALESCE(f.tips, 0)
                + COALESCE(f.sales_tax, 0)
                + COALESCE(f.congestion_surcharge, 0)
                + COALESCE(f.airport_fee, 0)
            ) AS total_price,
            COALESCE(h.company_name, 'Unknown') AS company,
            b.base_name
        FROM fhv_with_zones f
        LEFT JOIN hvfhs_lookup h ON f.hvfhs_license_num = h.hvfhs_license_num
        LEFT JOIN base_lookup b ON f.originating_base_num = b.base_number
    """)
    
    print("DuckDB initialized successfully")
    return conn


def close_duckdb(conn):
    """Close DuckDB connection"""
    if conn:
        conn.close()
        print("DuckDB connection closed")

