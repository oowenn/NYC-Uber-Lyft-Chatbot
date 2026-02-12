"""
LLM client abstraction supporting Ollama and hosted APIs
"""
import os
from typing import Dict, Any, Optional
import json
import httpx


class LLMClient:
    def __init__(self):
        # Default to Groq (API) - faster and no local setup needed
        # Set LLM_PROVIDER=ollama to use local Ollama instead
        self.provider = os.getenv("LLM_PROVIDER", "groq")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        # Default to llama3; can override with env
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
        # Allow tuning timeout for slower local models. If not set, be generous.
        self.timeout = float(os.getenv("LLM_TIMEOUT", "300"))
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.groq_key = os.getenv("GROQ_API_KEY")
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    
    async def generate_sql(self, query: str, max_attempts: int = 2) -> Optional[Dict[str, Any]]:
        """Generate SQL from natural language query"""
        prompt = self._build_sql_prompt(query)
        
        for attempt in range(max_attempts):
            try:
                if self.provider == "ollama":
                    response = await self._call_ollama(prompt)
                elif self.provider == "openai":
                    response = await self._call_openai(prompt)
                elif self.provider == "anthropic":
                    response = await self._call_anthropic(prompt)
                elif self.provider == "groq":
                    response = await self._call_groq(prompt)
                else:
                    raise ValueError(f"Unknown provider: {self.provider}")
                
                # Parse response
                result = self._parse_response(response)
                if result:
                    return result
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                continue
        
        return None
    
    def _build_sql_prompt(self, query: str) -> str:
        """Build prompt for SQL generation"""
        return f"""You are a SQL expert for NYC TLC FHVHV (For-Hire Vehicle High Volume) data.

DATA COVERAGE:
- Trips available from 2023-01-01 through 2023-03-31 (inclusive). No data beyond March 2023.

Available views:
- fhv_with_company: Main view with trip data joined with company info
  Columns: pickup_datetime, dropoff_datetime, PULocationID, DOLocationID, 
           trip_miles, trip_time, base_passenger_fare, company, pickup_zone, 
           pickup_borough, dropoff_zone, dropoff_borough

Rules:
1. Only use SELECT statements; no DDL/DML.
2. Use only the fhv_with_company view and its columns.
3. Make sure to follow the user's instructions about the time range if its within the dataset's time range, otherwise use the entire dataset.
4. Prefer aggregation (COUNT, SUM, AVG) and GROUP BY to keep results small.
5. Always include LIMIT (e.g., LIMIT 500) if not guaranteed to be tiny.
6. Return ONLY the SQL code. Do not return JSON, prose, or markdown. Do not wrap in triple backticks.

User query: {query}

Return only the SQL:"""
    
    async def _call_ollama(self, prompt: str) -> str:
        """Call Ollama API. Prefer /api/chat; fall back to /api/generate if chat is unavailable."""
        async with httpx.AsyncClient() as client:
            payload_chat = {
                "model": self.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
            url_chat = f"{self.ollama_url}/api/chat"

            resp = await client.post(url_chat, json=payload_chat, timeout=self.timeout)
            if resp.status_code == 404:
                payload_gen = {
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                }
                url_gen = f"{self.ollama_url}/api/generate"
                resp = await client.post(url_gen, json=payload_gen, timeout=self.timeout)

            # Capture more detail on failure
            try:
                resp.raise_for_status()
            except Exception as e:
                body = None
                try:
                    body = resp.text
                except Exception:
                    body = "<unreadable body>"
                raise RuntimeError(f"Ollama call failed: {e}, status={resp.status_code}, body={body}") from e

            data = resp.json()
            if "message" in data and isinstance(data["message"], dict):
                return data["message"].get("content", "")
            return data.get("response", "")
    
    async def _call_openai(self, prompt: str) -> str:
        """Call OpenAI API"""
        if not self.openai_key:
            raise ValueError("OPENAI_API_KEY not set")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.openai_key}"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-5-nano"),
                    "input": prompt,
                    "max_output_tokens": 2048
                },
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            text = data.get("output_text")
            if isinstance(text, str) and text.strip():
                return text

            chunks = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        part_type = part.get("type")
                        if part_type in ("output_text", "text"):
                            value = part.get("text")
                            if isinstance(value, str) and value:
                                chunks.append(value)
            return "\n".join(chunks).strip()
    
    async def _call_anthropic(self, prompt: str) -> str:
        """Call Anthropic API"""
        if not self.anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.anthropic_key,
                    "anthropic-version": "2023-06-01"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=60.0
            )
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
    
    async def _call_groq(self, prompt: str) -> str:
        """Call Groq API (OpenAI-compatible)"""
        if not self.groq_key:
            raise ValueError("GROQ_API_KEY not set")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.groq_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.groq_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 2048
                },
                timeout=30.0  # Groq is fast, shorter timeout
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    def _parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response to extract SQL and chart config"""
        try:
            # Try to extract JSON from response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()
            
            result = json.loads(json_str)
            
            # Validate required fields
            if "sql" not in result:
                return None
            
            return {
                "sql": result["sql"],
                "chart": {
                    "type": result.get("chart_type", "bar"),
                    "x": result.get("x"),
                    "y": result.get("y"),
                    "series": result.get("series"),
                    "title": result.get("title", "Query Results")
                },
                "explanation": result.get("explanation", "Query executed successfully"),
                "raw_response": response,
            }
        except Exception as e:
            # Fallback: treat the whole response as raw SQL text
            sql_text = response.strip()
            # Remove fences if present
            if sql_text.startswith("```"):
                parts = sql_text.split("```")
                if len(parts) >= 2:
                    sql_text = parts[1].strip()
            if not sql_text.lower().startswith("select") and "with" not in sql_text.lower():
                print(f"Error parsing LLM response: {e}")
                return None
            return {
                "sql": sql_text,
                "chart": None,
                "explanation": "Raw SQL returned",
                "raw_response": response,
            }

