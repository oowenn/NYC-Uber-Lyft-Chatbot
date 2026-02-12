"""
LLM pipeline service for generating SQL and chart specs from user questions
"""
import os
import sys
import json
from typing import Dict, Any, List, Optional
from pathlib import Path

# Ensure backend directory is in path for imports
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pandas as pd
import duckdb
from scripts.test_llm_pipeline import (
    generate_sql_with_validation,
    build_chart_spec_prompt,
    call_ollama,
    run_sql
)
from scripts.chart_renderer import render_chart_from_spec
import matplotlib
matplotlib.use("Agg")


async def process_query(question: str, duckdb_conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
    """
    Process a user question through the LLM pipeline:
    1. Generate SQL with validation
    2. Execute SQL
    3. Generate chart spec
    4. Render chart
    
    Returns:
        {
            "answer": str,
            "sql": str,
            "data": List[Dict],
            "chart": Dict (chart spec),
            "chart_image_path": Optional[str] (path to rendered chart)
        }
    """
    # Use llama3:latest if available, fallback to llama3
    model = os.getenv("OLLAMA_MODEL", "llama3:latest")
    timeout = float(os.getenv("LLM_TIMEOUT", "300"))
    max_sql_attempts = int(os.getenv("MAX_SQL_ATTEMPTS", "3"))
    max_spec_attempts = int(os.getenv("MAX_SPEC_ATTEMPTS", "3"))
    
    # 1) Generate SQL with validation
    try:
        # Enable verbose logging to see what's happening
        # Note: generate_sql_with_validation creates its own DuckDB connection
        # This is fine for now, but could be optimized to reuse duckdb_conn
        sql = await generate_sql_with_validation(question, model, timeout, max_sql_attempts, verbose=True)
        if not sql:
            import traceback
            print(f"\n{'='*80}")
            print(f"WARNING: generate_sql_with_validation returned None")
            print(f"Question: {question}")
            print(f"Model: {model}")
            print(f"Timeout: {timeout}")
            print(f"Max attempts: {max_sql_attempts}")
            print(f"{'='*80}\n")
            return {
                "answer": "Sorry, I couldn't generate a valid SQL query for your question. Please try rephrasing it.",
                "sql": None,
                "data": None,
                "data_preview": None,
                "chart": None,
                "mode": "error"
            }
    except ConnectionError as e:
        return {
            "answer": f"❌ Cannot connect to the configured LLM provider: {str(e)}\n\nTo fix:\n1. Verify your API key and provider settings in .env\n2. Confirm network connectivity\n3. Check the health endpoint: `/api/health`",
            "sql": None,
            "data": None,
            "data_preview": None,
            "chart": None,
            "mode": "error"
        }
    except TimeoutError as e:
        return {
            "answer": f"⏱️ {str(e)}\n\nThe model may be too slow. Try:\n1. Increase `LLM_TIMEOUT`\n2. Use a faster model\n3. Retry the request",
            "sql": None,
            "data": None,
            "data_preview": None,
            "chart": None,
            "mode": "error"
        }
    except RuntimeError as e:
        error_msg = str(e)
        # Check if it's a rate limit error
        if "rate limit" in error_msg.lower() or "429" in error_msg:
            return {
                "answer": "ERROR: Rate Limit Reached\n\nThe LLM API rate limit has been exceeded. Please wait a moment and try again.\n\nGroq free tier limits:\n• 30 requests per minute\n• 7,000 requests per day",
                "sql": None,
                "data": None,
                "data_preview": None,
                "chart": None,
                "mode": "error"
            }
        # Re-raise to be handled by general exception handler
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        # Check if it's a rate limit error
        if "rate limit" in error_msg.lower() or "429" in error_msg or "too many requests" in error_msg.lower():
            return {
                "answer": "ERROR: Rate Limit Reached\n\nThe LLM API rate limit has been exceeded. Please wait a moment and try again.\n\nGroq free tier limits:\n• 30 requests per minute\n• 7,000 requests per day",
                "sql": None,
                "data": None,
                "data_preview": None,
                "chart": None,
                "mode": "error"
            }
        # Check if it's a connection error
        if "connection" in error_msg.lower() or "refused" in error_msg.lower() or "connect" in error_msg.lower():
            return {
                "answer": f"❌ Unable to connect to the configured LLM provider: {error_msg}\n\nTo fix:\n1. Verify provider credentials and base URL in `.env`\n2. Confirm internet/network access\n3. Retry the request",
                "sql": None,
                "data": None,
                "data_preview": None,
                "chart": None,
                "mode": "error"
            }
        return {
            "answer": f"Error generating SQL: {error_msg}\n\nCheck:\n1. LLM provider settings and API key in `.env`\n2. Model name and availability\n3. Health check: `/api/health`",
            "sql": None,
            "data": None,
            "data_preview": None,
            "chart": None,
            "mode": "error"
        }
    
    # 2) Execute SQL
    try:
        rows = run_sql(duckdb_conn, sql, limit=500)
        df = pd.DataFrame(rows)
        
        if len(df) == 0:
            return {
                "answer": "The query executed successfully but returned no results.",
                "sql": sql,
                "data": [],
                "data_preview": [],
                "chart": None,
                "mode": "sql"
            }
    except Exception as e:
        return {
            "answer": f"Error executing SQL query: {str(e)}",
            "sql": sql,
            "data": None,
            "data_preview": None,
            "chart": None,
            "mode": "error"
        }
    
    # 3) Generate chart spec (matching test_llm_pipeline.py logic)
    chart_spec = None
    last_error = None
    last_spec_attempt = None
    
    def try_parse(payload: str) -> Optional[Dict[str, Any]]:
        """Helper to parse JSON with fallbacks"""
        try:
            return json.loads(payload)
        except Exception:
            return None
    
    for attempt in range(1, max_spec_attempts + 1):
        df_sample = df.head(10).to_dict(orient="records")
        
        if attempt == 1:
            spec_prompt = build_chart_spec_prompt(question, sql, df_sample)
        else:
            # Retry with error feedback (matching test script)
            spec_prompt = f"""
You previously generated this chart spec for the question: "{question}"

Previous spec (Attempt {attempt}):
{json.dumps(chart_spec, indent=2) if chart_spec else "None"}

However, it failed with this error:
{last_error}

Please correct the chart spec. Remember:
- Use column names exactly as they appear in the data: {', '.join(df.columns.tolist())}
- CRITICAL for "top N" queries: You MUST use "top_k" with order "desc" to sort by the metric value
- Example for "top 10 pickup zones by trips": use top_k={{col: "pickup_zone", k: 10, by: "trips", order: "desc"}}
- For bar charts showing comparisons or rankings, ALWAYS sort by the y-axis value in descending order
- For time series, sort by time (x-axis) in ascending order
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
        except RuntimeError as e:
            error_msg = str(e)
            # Check if it's a rate limit error
            if "rate limit" in error_msg.lower() or "429" in error_msg:
                # Rate limit hit - return error immediately, don't retry
                return {
                    "answer": "ERROR: Rate Limit Reached\n\nThe LLM API rate limit has been exceeded. Please wait a moment and try again.\n\nGroq free tier limits:\n• 30 requests per minute\n• 7,000 requests per day",
                    "sql": sql,
                    "data": rows,
                    "data_preview": rows[:100],
                    "chart": None,
                    "mode": "error"
                }
            # For non-rate-limit runtime errors (e.g., empty/incomplete model output),
            # retry chart-spec generation and gracefully fall back to data-only response.
            if attempt == max_spec_attempts:
                break
            last_error = f"LLM call failed: {error_msg}"
            last_spec_attempt = {"spec": chart_spec, "error": last_error}
            continue
        except Exception as e:
            print(f"LLM call failed: {e}")
            error_msg = str(e)
            # Check if it's a rate limit error
            if "rate limit" in error_msg.lower() or "429" in error_msg or "too many requests" in error_msg.lower():
                # Rate limit hit - return error immediately
                return {
                    "answer": "ERROR: Rate Limit Reached\n\nThe LLM API rate limit has been exceeded. Please wait a moment and try again.\n\nGroq free tier limits:\n• 30 requests per minute\n• 7,000 requests per day",
                    "sql": sql,
                    "data": rows,
                    "data_preview": rows[:100],
                    "chart": None,
                    "mode": "error"
                }
            if attempt == max_spec_attempts:
                break
            last_error = f"LLM call failed: {str(e)}"
            last_spec_attempt = {"spec": chart_spec, "error": last_error}
            continue
        
        # Parse JSON (matching test script logic)
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
                break
        
        chart_spec = parsed.get("chart") or parsed  # Handle both {"chart": {...}} and just {...}
        if not chart_spec:
            print("⚠️  No chart spec found in response")
            if attempt < max_spec_attempts:
                last_error = "No chart spec found in LLM response"
                last_spec_attempt = {"spec": None, "error": last_error}
                continue
            else:
                break
        
        # Validate spec (matching test script validation)
        if not isinstance(chart_spec, dict):
            last_error = "Chart spec must be a dictionary"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                break
        
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
                break
        
        # Check if columns exist in DataFrame
        if x_col not in df.columns:
            last_error = f"Column '{x_col}' not found. Available: {list(df.columns)}"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                break
        
        if y_col not in df.columns:
            last_error = f"Column '{y_col}' not found. Available: {list(df.columns)}"
            print(f"✗ {last_error}")
            if attempt < max_spec_attempts:
                last_spec_attempt = {"spec": chart_spec, "error": last_error}
                continue
            else:
                break
        
        # Try to render chart
        try:
            # Use a more accessible path - store in backend/static/charts or /tmp
            import tempfile
            import uuid
            # Use configurable chart directory (default to /tmp for local dev)
            chart_dir = Path(os.getenv("CHART_DIR", "/tmp/nyc_taxi_charts"))
            try:
                chart_dir.mkdir(exist_ok=True, parents=True)
            except Exception as e:
                raise RuntimeError(f"Failed to create chart directory {chart_dir}: {str(e)}")
            
            chart_filename = f"chart_{uuid.uuid4().hex[:8]}.png"
            chart_path = chart_dir / chart_filename
            
            spec_to_render = {"chart": chart_spec} if "type" in chart_spec else chart_spec
            try:
                render_chart_from_spec(df, spec_to_render, chart_path)
            except Exception as e:
                raise RuntimeError(f"Failed to render chart: {str(e)}") from e
            
            # Success!
            return {
                "answer": f"I found {len(df)} rows. Here's a visualization of the data.",
                "sql": sql,
                "data": rows,  # Return all data for CSV download
                "data_preview": rows[:10],  # Preview for table display
                "chart": chart_spec,
                "chart_image_path": str(chart_path),
                "mode": "sql"
            }
        except Exception as e:
            if attempt < max_spec_attempts:
                last_error = f"Chart rendering failed: {str(e)}"
                continue
            break
    
    # If we get here, chart generation failed but we still have data
    return {
        "answer": f"I found {len(df)} rows. Unable to generate a chart, but here's the data.",
        "sql": sql,
        "data": rows,  # Return all data for CSV download
        "data_preview": rows[:10],  # Preview for table display
        "chart": None,
        "mode": "sql"
    }

