"""
Isolated test for SQL generation with validation and retry logic.
Shows exactly what prompts and error context are being sent to the LLM.

Usage:
    cd backend
    source venv/bin/activate
    PYTHONPATH=. OLLAMA_MODEL=llama3 python scripts/test_sql_generation.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from db.duckdb_setup import init_duckdb, close_duckdb
from scripts.validation import validate_sql, build_sql_correction_prompt
from scripts.test_llm_pipeline import build_plan_sql_prompt, call_ollama, run_sql


async def test_sql_generation():
    """Test SQL generation with detailed prompt/error logging"""
    question = "Show hourly trips by company for the first 3 days of January 2023."
    model = os.getenv("OLLAMA_MODEL", "llama3")
    timeout = float(os.getenv("LLM_TIMEOUT", "300"))
    max_attempts = int(os.getenv("MAX_SQL_ATTEMPTS", "3"))
    
    conn = init_duckdb()
    sql = None
    errors = []
    last_attempt = None  # Only track the last attempt, not all
    
    try:
        for attempt in range(1, max_attempts + 1):
            print("\n" + "="*80)
            print(f"=== SQL Generation Attempt {attempt}/{max_attempts} ===")
            print("="*80)
            
            # Generate SQL
            if attempt == 1:
                prompt = build_plan_sql_prompt(question)
                print("\n[PROMPT SENT TO LLM - ATTEMPT 1]")
                print("-" * 80)
                print(prompt)
                print("-" * 80)
            else:
                # Use correction prompt with only the last attempt's errors
                prompt = build_sql_correction_prompt(question, sql, errors, attempt, last_attempt)
                print("\n[PROMPT SENT TO LLM - RETRY ATTEMPT]")
                print("-" * 80)
                print(prompt)
                print("-" * 80)
            
            try:
                sql_raw = await call_ollama(prompt, model=model, timeout=timeout)
            except Exception as e:
                print(f"\n❌ LLM call failed: {e}")
                last_attempt = {"sql": sql, "errors": [f"LLM call failed: {str(e)}"]}
                if attempt == max_attempts:
                    return sql
                continue
            
            # Clean SQL
            sql = sql_raw.strip()
            sql = sql.replace("```sql", "").replace("```", "")
            sql = sql.replace("Here is the answer:", "").replace("Here is the response:", "").strip()
            
            print(f"\n[SQL GENERATED]")
            print("-" * 80)
            print(sql)
            print("-" * 80)
            
            # Validate SQL
            print(f"\n[VALIDATING SQL...]")
            is_valid, errors = validate_sql(sql, conn)
            execution_error = None
            
            if is_valid:
                # Try to execute to catch runtime errors
                try:
                    test_rows = run_sql(conn, sql, limit=5)
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
                    print(f"\n[RETRYING WITH ERROR FEEDBACK]")
                    print(f"Last attempt context will be included in next prompt:")
                    print(f"  - SQL: {sql[:100]}..." if len(sql) > 100 else f"  - SQL: {sql}")
                    print(f"  - Errors: {len(errors)} error(s)")
                else:
                    print(f"\n[MAX ATTEMPTS REACHED]")
                    print(f"Using last generated SQL (may fail).")
                    return sql
        
        return sql
    finally:
        close_duckdb(conn)


if __name__ == "__main__":
    result = asyncio.run(test_sql_generation())
    if result:
        print(f"\n✅ Final SQL:\n{result}")
    else:
        print("\n❌ Failed to generate valid SQL")

