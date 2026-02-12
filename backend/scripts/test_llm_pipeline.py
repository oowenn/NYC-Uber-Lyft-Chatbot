"""
Ad-hoc pipeline test with agent-style validation:
question -> LLM (SQL) [with validation/retry] -> DuckDB -> LLM (chart spec) [with validation/retry] -> render chart

Features:
- SQL validation: checks syntax, schema, safety before execution
- Chart spec validation: validates structured JSON spec against data schema
- Retry logic: feeds errors back to LLM for self-correction (up to 3 attempts each)
- Structured chart generation: uses chart specs instead of Python code to avoid hallucinations

Usage:
    cd backend
    source venv/bin/activate
    PYTHONPATH=. OLLAMA_MODEL=llama3:latest python scripts/test_llm_pipeline.py

Environment variables:
    OLLAMA_MODEL: Model to use (default: llama3)
    LLM_TIMEOUT: Timeout in seconds (default: 300)
    MAX_SQL_ATTEMPTS: Max retries for SQL generation (default: 3)
    MAX_SPEC_ATTEMPTS: Max retries for chart spec generation (default: 3)

Requirements:
    - DuckDB data present in ../data
    - Ollama running locally with the specified model pulled
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import httpx
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

# Force non-GUI backend for headless/CLI use
matplotlib.use("Agg")

from db.duckdb_setup import init_duckdb, close_duckdb
from llm.llm_client import LLMClient
from scripts.validation import (
    validate_sql,
    build_sql_correction_prompt,
    ValidationError
)
from scripts.chart_renderer import render_chart_from_spec

ROOT = Path(__file__).resolve().parent.parent


def run_sql(conn: duckdb.DuckDBPyConnection, sql: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Execute SQL and return rows as list of dicts (bounded)."""
    df = conn.execute(sql).fetchdf()
    if len(df) > limit:
        df = df.head(limit)
    return json.loads(df.to_json(orient="records"))


def build_plan_sql_prompt(question: str) -> str:
    return f"""
You are a SQL planner for NYC FHVHV data.
User question: {question}
Rules:
- Use view fhv_with_company.
- Column groups:
  * Time columns: pickup_datetime (default), dropoff_datetime, request_datetime, on_scene_datetime
  * Price columns: total_price, base_passenger_fare, tolls, sales_tax, congestion_surcharge, airport_fee, tips, bcf, driver_pay
  * Location columns: PULocationID, DOLocationID, pickup_zone, pickup_borough, dropoff_zone, dropoff_borough
  * Trip/entity columns: trip_miles, trip_time, company, hvfhs_license_num, base_name, dispatching_base_num, originating_base_num
  * Flags: shared_request_flag, shared_match_flag, access_a_ride_flag, wav_request_flag, wav_match_flag
- If asked for "most expensive", "costliest", or "highest fare", rank by total_price DESC (fallback base_passenger_fare DESC if needed) and return top row(s).
- Include a time filter within 2023-01-01..2023-03-31; if none specified, default to 2023-01-01..2023-01-03.
- Use pickup_datetime for time filters unless the question explicitly asks for another column.
- For time-based aggregations (grouping by time periods), create a proper date column:
  * Use DATE_TRUNC('month', pickup_datetime) AS month for monthly grouping
  * Use DATE_TRUNC('day', pickup_datetime) AS date for daily grouping
  * Use DATE_TRUNC('hour', pickup_datetime) AS hour for hourly grouping
  * Avoid extracting year and month separately - use DATE_TRUNC to create a single date column
- When using GROUP BY, all non-aggregated columns in SELECT must appear in GROUP BY, or use aggregate functions (SUM, COUNT, AVG, etc.).
- Aggregate-first (GROUP BY); include LIMIT (e.g., 500).
- When counting trips, use COUNT(*) AS trips (or similar aggregate aliases).
- Include ORDER BY when appropriate (DESC for rankings, ASC for time series).
- Output only the SQL string, no extra text or code fences; single-line or with \\n escapes is fine.
""".strip()

def build_plan_chart_prompt_rows(question: str, df_sample: List[Dict[str, Any]]) -> str:
    sample_json = json.dumps(df_sample, indent=2)
    return f"""
You are a chart planner for NYC FHVHV data.
User question: {question}
Here is a small sample of the result rows (JSON): {sample_json}

Return only JSON (a single object, no extra text/fences/sample data arrays), with this schema:
{{
  "figure": {{
    "size": [x, y],
    "layout": [x, y],
    "title": "Overall title"
  }},
  "dataframe": "df",
  "axes": {{
    "ax_1": {{
      "type": "bar|line|scatter|pie|box|violin|heatmap",
      "x": "...",
      "y": "...",
      "hue": "optional grouping field (e.g., company)",
      "title": "...",
      "xlabel": "...",
      "ylabel": "...",
      "options": {{"grid": true, "legend": true}}
    }}
    // Optionally ax_2, ax_3, ...
  }}
}}
""".strip()


def build_plan_prompt(question: str) -> str:
    return f"""
You are a data analyst planning a chart and SQL for NYC FHVHV data.

User question: {question}

Return JSON with:
{{
  "sql": "...",
  "chart": {{
    "type": "bar|line|pie|scatter|boxplot|violinplot|heatmap|...",
    "x": "...",
    "y": "...",
    "columns": "optional columns field (e.g., company)",
    "title": "..."
  }}
}}

Rules:
- Use view fhv_with_company.
- Include a time filter within 2023-01-01..2023-03-31; if none specified, default to 2023-01-01..2023-01-03.
- Aggregate-first (GROUP BY); include LIMIT (e.g., 500).
- SQL must be a single JSON string (no triple quotes or fences). If you need newlines, escape them with \\n.
- Respond with JSON only. Do not include extra text or code fences.
""".strip()


def build_render_prompt(question: str, sql: str, rows: List[Dict[str, Any]], chart_plan_text: str) -> str:
    sample = json.dumps(rows[:20], indent=2)
    return f"""
You are a data analyst. You are given:
- User question: {question}
- Chart plan (plain text): {chart_plan_text}
- Result rows (JSON array, truncated): {sample}

Based ONLY on these rows and the chart plan:
Generate Python/matplotlib code that answers the question and:
  - Assumes a pandas DataFrame named df already exists with these rows.
  - Imports are already done: import pandas as pd; import matplotlib.pyplot as plt; import numpy as np. Do NOT re-import.
  - Uses only matplotlib + pandas (no seaborn/plotly).
  - Contains no ellipses or placeholders.
  - Do NOT save the figure; just build the plot. Caller will save using plt.gcf().savefig(chart_path).
  - Does NOT call plt.show().
  - IMPORTANT: Make axes readable:
    * If x-axis is time/timestamp, convert to readable format (e.g., pd.to_datetime() then format, or extract hour if hourly data)
    * If x-axis is numeric, ensure proper formatting and rotation if needed
    * Always set clear, descriptive labels using plt.xlabel() and plt.ylabel()
    * Use plt.xticks(rotation=...) if labels are long or overlapping
    * Set appropriate figure size (e.g., figsize=(12, 6) or larger for many data points)
  - The code string must be valid JSON (escape newlines with \\n), single-line, and must NOT include code fences or triple quotes.
  - The code string must not contain any prefixes like "python code here:"; return only the code.
  - The code must be valid Python code and executable.

Return JSON only, shaped as:
{{
  "code": "python code here"
}}
Do not include extra text or code fences.
""".strip()

def build_chart_spec_prompt(question: str, sql: str, df_sample: List[Dict[str, Any]]) -> str:
    """Build prompt to generate structured chart spec from query results"""
    sample_json = json.dumps(df_sample, indent=2)
    columns = list(df_sample[0].keys()) if df_sample else []
    
    return f"""
You are a data analyst. You are given:
- User question: {question}
- SQL query that was executed: {sql}
- Result rows sample (JSON array, first 10 rows): {sample_json}
- Available columns: {', '.join(columns)}

Based on the question and the data structure, generate a chart specification in JSON format.

Chart specification schema:
{{
  "chart": {{
    "type": "line|bar|scatter|hist|box|heatmap|none",
    "title": "Descriptive title for the chart",
    "x": {{
      "col": "column_name_for_x_axis",
      "dtype": "datetime|category|number",
      "sort": true
    }},
    "y": {{
      "col": "column_name_for_y_axis",
      "dtype": "number",
      "sort": false
    }},
    "series": "column_name_for_grouping|null",
    "top_k": {{
      "col": "column_name|null",
      "k": 10,
      "by": "y",
      "order": "desc"
    }},
    "orientation": "vertical|horizontal",
    "stacked": false,
    "limits": {{
      "max_points": 2000
    }}
  }}
}}

Rules:
- Use column names exactly as they appear in the data
- For time-based data, use "datetime" dtype for x-axis
- IMPORTANT - Time axis handling:
  * If the data has separate "year" and "month" columns, you MUST combine them into a single date column for the x-axis
  * Use a column name like "date" or "period" that represents the combined year-month
  * If you see year and month columns, the x-axis should reference a combined date, not just "year"
  * Example: If data has "year"=2023, "month"=1, create x-axis as a date representing "2023-01"
  * For time series over months, the x-axis should be a proper date column, not just year numbers
- For categorical data, use "category" dtype
- Set "series" to a column name if you want to group/compare multiple series (e.g., by company)
- Use "top_k" to limit to top N items if the dataset is large
- IMPORTANT - Sorting (CRITICAL for "top N" queries):
  * For "top N" queries (e.g., "top 10 pickup zones"), you MUST use "top_k" with order "desc" to sort by the metric value
  * Example for "top 10 pickup zones by trips": use top_k={{col: "pickup_zone", k: 10, by: "trips", order: "desc"}}
  * For bar charts showing comparisons or rankings, ALWAYS sort by the y-axis value in descending order
  * For time series (line charts), sort by time (x-axis) in ascending order
  * Set x-axis "sort": true for time-based or when you want ascending order
  * Set y-axis "sort": false (sorting is handled by x-axis or top_k)
  * REMEMBER: For "top N" queries, the chart MUST be sorted descending by the metric (y-axis) to show highest values first
- Choose chart type that best answers the question:
  * "bar" for comparisons
  * "line" for trends over time
  * "scatter" for relationships
  * "hist" for distributions
  * "box" for distributions by category
  * "heatmap" for two-dimensional patterns
  * "none" if no chart is needed
- Set appropriate title that describes what the chart shows
- If x-axis has many values, consider using top_k or increasing max_points

Return ONLY valid JSON, no extra text or code fences.
""".strip()


async def call_ollama(prompt: str, model: str, timeout: float) -> str:
    """Call Ollama, Groq, or OpenAI API based on environment variables."""
    provider = os.getenv("LLM_PROVIDER", "ollama")
    
    if provider == "groq":
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY not set. Get your API key from https://console.groq.com/keys")
        
        groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 2048
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RuntimeError(f"Groq rate limit exceeded. Free tier: 30 RPM, 7K RPD. Check headers for retry-after.") from e
                raise RuntimeError(f"Groq API error {e.response.status_code}: {e.response.text}") from e
            except httpx.TimeoutException as e:
                raise TimeoutError(f"Groq request timed out after {timeout}s") from e
    
    if provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not set. Set it in your .env file.")
        
        openai_model = os.getenv("OPENAI_MODEL", "gpt-5-nano")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": openai_model,
                        "input": prompt,
                        "max_output_tokens": 2048
                    },
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
                # Preferred field in Responses API
                text = data.get("output_text")
                if isinstance(text, str) and text.strip():
                    return text.strip()

                # Fallback: extract text chunks from output array
                chunks = []
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for part in item.get("content", []):
                            part_type = part.get("type")
                            if part_type in ("output_text", "text"):
                                value = part.get("text")
                                if isinstance(value, str) and value:
                                    chunks.append(value)
                merged = "\n".join(chunks).strip()
                if merged:
                    return merged

                # Optional debug trace to inspect response shape without dumping full payload by default
                if os.getenv("LLM_DEBUG_RESPONSES", "false").lower() == "true":
                    output_types = [item.get("type") for item in data.get("output", [])]
                    print(
                        f"[OPENAI DEBUG] empty output for model={openai_model}, "
                        f"status={data.get('status')}, output_types={output_types}, "
                        f"finish_reason={data.get('finish_reason')}, usage={data.get('usage')}"
                    )

                raise RuntimeError(
                    f"OpenAI returned empty output (model={openai_model}, status={data.get('status')})"
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise RuntimeError("OpenAI rate limit exceeded. Please wait and retry.") from e
                raise RuntimeError(f"OpenAI API error {e.response.status_code}: {e.response.text}") from e
            except httpx.TimeoutException as e:
                raise TimeoutError(f"OpenAI request timed out after {timeout}s") from e
    
    # Default to Ollama
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    url = base_url + "/api/chat"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False},
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")
        except httpx.ConnectError as e:
            raise ConnectionError(f"Cannot connect to Ollama at {base_url}. Is Ollama running? Try: `ollama serve`") from e
        except httpx.TimeoutException as e:
            raise TimeoutError(f"Ollama request timed out after {timeout}s. The model might be too slow or Ollama is not responding.") from e
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama returned error {e.response.status_code}: {e.response.text}") from e


async def generate_sql_with_validation(question: str, model: str, timeout: float, max_attempts: int = 3, verbose: bool = True) -> Optional[str]:
    """Generate SQL with validation and retry logic"""
    try:
        conn = init_duckdb()
    except Exception as e:
        if verbose:
            print(f"\n❌ Failed to initialize DuckDB: {e}")
            import traceback
            traceback.print_exc()
        raise RuntimeError(f"Failed to initialize DuckDB: {e}") from e
    
    sql = None
    errors = []
    last_attempt = None  # Only track the last attempt, not all previous attempts
    
    try:
        for attempt in range(1, max_attempts + 1):
            if verbose:
                print("\n" + "="*80)
                print(f"=== SQL Generation Attempt {attempt}/{max_attempts} ===")
                print("="*80)
            
            # Generate SQL
            if attempt == 1:
                prompt = build_plan_sql_prompt(question)
                if verbose:
                    print("\n[PROMPT SENT TO LLM - ATTEMPT 1]")
                    print("-" * 80)
                    print(prompt)
                    print("-" * 80)
            else:
                # Use correction prompt with only the last attempt's errors
                prompt = build_sql_correction_prompt(question, sql, errors, attempt, last_attempt)
                if verbose:
                    print("\n[PROMPT SENT TO LLM - RETRY ATTEMPT]")
                    print("-" * 80)
                    print(prompt)
                    print("-" * 80)
            
            try:
                sql_raw = await call_ollama(prompt, model=model, timeout=timeout)
            except Exception as e:
                error_msg = str(e)
                if verbose:
                    print(f"❌ LLM call failed: {error_msg}")
                    if "connection" in error_msg.lower() or "refused" in error_msg.lower():
                        print("   → Make sure Ollama is running: `ollama serve`")
                        print(f"   → Check model is pulled: `ollama list` (should see {model})")
                last_attempt = {"sql": sql, "errors": [f"LLM call failed: {error_msg}"]}
                if attempt == max_attempts:
                    # If it's a connection error, raise it so caller can handle it
                    if "connection" in error_msg.lower() or "refused" in error_msg.lower():
                        raise ConnectionError(f"Cannot connect to Ollama: {error_msg}")
                    return sql  # Return last attempt if any
                continue
            
            # Clean SQL
            sql = sql_raw.strip()
            sql = sql.replace("```sql", "").replace("```", "")
            sql = sql.replace("Here is the answer:", "").replace("Here is the response:", "").strip()

            if not sql:
                errors = ["LLM returned empty response text"]
                last_attempt = {"sql": "", "errors": errors}
                if verbose:
                    print("❌ LLM returned empty response text")
                if attempt == max_attempts:
                    return None
                continue
            
            if verbose:
                print(f"\n[SQL GENERATED]")
                print("-" * 80)
                print(sql)
                print("-" * 80)
            
            # Validate SQL
            if verbose:
                print(f"\n[VALIDATING SQL...]")
            is_valid, errors = validate_sql(sql, conn)
            execution_error = None
            
            if is_valid:
                # Try to execute to catch runtime errors
                try:
                    test_rows = run_sql(conn, sql, limit=5)
                    if verbose:
                        print(f"✅ SQL validation passed! (returned {len(test_rows)} test rows)")
                        print(f"\n[SAMPLE ROWS]")
                        print("-" * 80)
                        for i, row in enumerate(test_rows[:3], 1):
                            print(f"Row {i}: {row}")
                        print("-" * 80)
                    return sql
                except Exception as e:
                    error_msg = str(e)
                    execution_error = error_msg
                    errors = [f"SQL execution error: {error_msg}"]
                    print(f"❌ SQL execution failed: {error_msg}")
            
            if errors:
                if verbose:
                    print(f"\n[VALIDATION ERRORS FOUND]")
                    print("-" * 80)
                    for i, err in enumerate(errors, 1):
                        print(f"{i}. {err}")
                    print("-" * 80)
                
                # Store only the last attempt (not all previous attempts)
                last_attempt = {
                    "sql": sql,
                    "errors": errors,
                    "execution_error": execution_error
                }
                
                if attempt < max_attempts:
                    if verbose:
                        print(f"\n[RETRYING WITH ERROR FEEDBACK]")
                        print(f"Last attempt context will be included in next prompt:")
                        print(f"  - SQL: {sql[:100]}..." if len(sql) > 100 else f"  - SQL: {sql}")
                        print(f"  - Errors: {len(errors)} error(s)")
                else:
                    if verbose:
                        print(f"\n[MAX ATTEMPTS REACHED]")
                    print(f"Using last generated SQL (may fail).")
                    return sql
        
        return sql
    finally:
        close_duckdb(conn)


async def main():
    question = "Show hourly trips by company for the first 3 days of January 2023."
    model = os.getenv("OLLAMA_MODEL", "llama3")
    timeout = float(os.getenv("LLM_TIMEOUT", "300"))
    max_sql_attempts = int(os.getenv("MAX_SQL_ATTEMPTS", "3"))
    max_spec_attempts = int(os.getenv("MAX_SPEC_ATTEMPTS", "3"))

    def try_parse(payload: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(payload)
        except Exception:
            return None

    # 0) Generate SQL with validation and retry
    sql = await generate_sql_with_validation(question, model, timeout, max_sql_attempts)
    if not sql:
        print("Failed to generate valid SQL after all attempts")
        return

    # 1) Execute SQL
    conn = init_duckdb()
    try:
        rows = run_sql(conn, sql, limit=200)
        df = pd.DataFrame(rows)
        print(f"\nSQL returned {len(df)} rows (truncated in rows list).")
        print("df.head():")
        print(df.head())
    except Exception as e:
        print(f"SQL execution failed: {e}")
        return
    finally:
        close_duckdb(conn)

    # 2) Generate chart spec from query results
    max_spec_attempts = int(os.getenv("MAX_SPEC_ATTEMPTS", "3"))
    chart_spec = None
    last_spec_attempt = None
    
    for attempt in range(1, max_spec_attempts + 1):
        print(f"\n=== Chart Spec Generation Attempt {attempt}/{max_spec_attempts} ===")
        
        # Generate chart spec
        df_sample = df.head(10).to_dict(orient="records")
        if attempt == 1:
            spec_prompt = build_chart_spec_prompt(question, sql, df_sample)
        else:
            # Retry with error feedback
            spec_prompt = f"""
You previously generated this chart spec for the question: "{question}"

Previous spec (Attempt {attempt}):
{json.dumps(chart_spec, indent=2) if chart_spec else "None"}

However, it failed with this error:
{last_error}

Please correct the chart spec. Remember:
- Use column names exactly as they appear in the data: {', '.join(df.columns.tolist())}
- Return valid JSON matching the schema
- Chart spec schema:
{{
  "chart": {{
    "type": "line|bar|scatter|hist|box|heatmap|none",
    "title": "string",
    "x": {{"col": "string", "dtype": "datetime|category|number", "sort": true}},
    "y": {{"col": "string", "dtype": "number", "sort": false}},
    "series": "string|null",
    "top_k": {{"col": "string|null", "k": 10, "by": "y", "order": "desc"}},
    "orientation": "vertical|horizontal",
    "stacked": false,
    "limits": {{"max_points": 2000}}
  }}
}}

Return ONLY valid JSON, no extra text or code fences.
""".strip()
        
        try:
            spec_raw = await call_ollama(spec_prompt, model=model, timeout=timeout)
        except Exception as e:
            print(f"LLM call failed: {e}")
            if attempt == max_spec_attempts:
                return
            continue
        
        print(f"LLM raw response:\n{spec_raw}")
        
        # Parse JSON response
        parsed = try_parse(spec_raw)
        if parsed is None:
            # Strip any leading text before the first '{' and after the last '}'
            if "{" in spec_raw and "}" in spec_raw:
                trimmed = spec_raw[spec_raw.find("{"): spec_raw.rfind("}") + 1]
            else:
                trimmed = spec_raw
            cleaned = trimmed.replace("```json", "").replace("```", "").replace("Here is the JSON response:", "").replace("Here is the response:", "")
            parsed = try_parse(cleaned)
        
        if parsed is None:
            print("⚠️  Failed to parse JSON response")
            if attempt < max_spec_attempts:
                last_error = "Failed to parse JSON response from LLM"
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                return
        
        chart_spec = parsed.get("chart") or parsed  # Handle both {"chart": {...}} and just {...}
        if not chart_spec:
            print("⚠️  No chart spec found in response")
            if attempt < max_spec_attempts:
                last_error = "No chart spec found in LLM response"
                last_spec_attempt = {"spec": None, "error": last_error}
                continue
            else:
                return
        
        # Validate chart spec
        print(f"\n[CHART SPEC RECEIVED]")
        print("-" * 80)
        print(json.dumps({"chart": chart_spec} if not isinstance(chart_spec, dict) or "type" not in chart_spec else chart_spec, indent=2))
        print("-" * 80)
        
        # Check required fields
        if not isinstance(chart_spec, dict):
            last_error = "Chart spec must be a dictionary"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                return
        
        x_config = chart_spec.get("x", {})
        y_config = chart_spec.get("y", {})
        x_col = x_config.get("col") if isinstance(x_config, dict) else None
        y_col = y_config.get("col") if isinstance(y_config, dict) else None
        
        if not x_col or not y_col:
            last_error = f"Missing required columns: x={x_col}, y={y_col}"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                return
        
        # Check if columns exist in DataFrame
        if x_col not in df.columns:
            last_error = f"Column '{x_col}' not found. Available: {list(df.columns)}"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                return
        
        if y_col not in df.columns:
            last_error = f"Column '{y_col}' not found. Available: {list(df.columns)}"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                return
        
        # Try to render the chart
        print(f"\n[RENDERING CHART FROM SPEC...]")
        chart_path = ROOT / "scripts" / "llm_chart.png"
        plt.switch_backend("Agg")
        plt.close("all")
        
        try:
            # Normalize spec format (ensure it's {"chart": {...}})
            spec_to_render = {"chart": chart_spec} if "type" in chart_spec else chart_spec
            render_chart_from_spec(df, spec_to_render, chart_path)
            print(f"✅ Chart rendered successfully!")
            print(f"Saved chart to {chart_path}")
            return  # Success!
        except Exception as e:
            last_error = str(e)
            print(f"✗ Chart rendering failed: {last_error}")
            
            last_spec_attempt = {
                "spec": chart_spec,
                "error": last_error
            }
            
            if attempt < max_spec_attempts:
                print(f"Retrying with error feedback...")
            else:
                print(f"Max attempts reached. Chart generation failed.")
                return


if __name__ == "__main__":
    asyncio.run(main())
