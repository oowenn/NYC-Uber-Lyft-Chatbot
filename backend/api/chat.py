"""
Chat endpoint - main query handler
"""
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import os
import json
import asyncio

from query.engine import QueryEngine
from query.metrics import MetricTemplates
from rag.rag_engine import RAGEngine
from llm.llm_client import LLMClient
from services.llm_pipeline import process_query

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    turnstile_token: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sql: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None  # Full dataset for CSV download
    data_preview: Optional[List[Dict[str, Any]]] = None  # Preview for table display
    chart: Optional[Dict[str, Any]] = None
    chart_image_url: Optional[str] = None  # URL to fetch chart image
    sources: Optional[List[str]] = None
    mode: str  # "rag", "template", "sql", "error"


def _to_chart_image_url(result: Dict[str, Any]) -> Optional[str]:
    if result.get("chart_image_path"):
        return f"/api/chart-image?path={result['chart_image_path']}"
    return None


def _response_to_dict(response: ChatResponse) -> Dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    return response.dict()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_req: ChatRequest):
    """Main chat endpoint"""
    duckdb_conn = request.app.state.duckdb
    circuit_breaker = request.app.state.circuit_breaker
    
    # Check if LLM pipeline is enabled (for local dev, can use env var)
    use_llm_pipeline = os.getenv("USE_LLM_PIPELINE", "true").lower() == "true"
    
    try:
        if use_llm_pipeline:
            # Use new LLM pipeline
            try:
                result = await process_query(chat_req.message, duckdb_conn)
            except Exception as pipeline_err:
                import traceback
                print(f"\n{'='*80}")
                print(f"ERROR in process_query: {type(pipeline_err).__name__}")
                print(f"Message: {str(pipeline_err)}")
                print(f"{'='*80}")
                traceback.print_exc()
                print(f"{'='*80}\n")
                raise
            
            # Convert chart image path to URL if present
            chart_image_url = _to_chart_image_url(result)
            
            response = ChatResponse(
                answer=result.get("answer", "Query processed"),
                sql=result.get("sql"),
                data=result.get("data"),  # Full dataset for CSV
                data_preview=result.get("data_preview"),  # Preview for table
                chart=result.get("chart"),
                chart_image_url=chart_image_url,
                mode=result.get("mode", "sql")
            )
        else:
            # Fallback to template-based approach
            query_engine = QueryEngine(duckdb_conn)
            metric_templates = MetricTemplates()
            
            template_match = metric_templates.match(chat_req.message)
            if template_match:
                template_name = template_match["template"]
                template_def = metric_templates.get_template(template_name)
                result = query_engine.execute_template(template_name, template_match.get("params", {}))
            else:
                template_name = "hourly_trips_by_company"
                template_def = metric_templates.get_template(template_name)
                result = query_engine.execute_template(template_name, {})
            
            try:
                answer = template_def["answer_template"].format(**result["summary"])
            except KeyError:
                answer = template_def.get("answer_template", "Query executed successfully")
            
            response = ChatResponse(
                answer=answer,
                sql=result["sql"],
                data=result["data"],
                chart=result["chart"],
                mode="template"
            )
        
        return response
        
    except Exception as e:
        import traceback
        error_detail = str(e)
        error_type = type(e).__name__
        
        # Log the full traceback for debugging (always print to console)
        print(f"\n{'='*80}")
        print(f"ERROR in chat endpoint: {error_type}")
        print(f"Message: {error_detail}")
        print(f"{'='*80}")
        traceback.print_exc()
        print(f"{'='*80}\n")
        
        # Provide more helpful error messages based on error type
        if "rate limit" in error_detail.lower() or "429" in error_detail or "too many requests" in error_detail.lower():
            error_detail = "ERROR: Rate Limit Reached\n\nThe LLM API rate limit has been exceeded. Please wait a moment and try again.\n\nGroq free tier limits:\n• 30 requests per minute\n• 7,000 requests per day"
        elif "ImportError" in error_type or "ModuleNotFoundError" in error_type:
            error_detail = f"Import error: {error_detail}. Check that all dependencies are installed."
        elif "connection" in error_detail.lower() or "ConnectionError" in error_type:
            error_detail = f"{error_detail}. Check your LLM provider/API connectivity and configuration."
        elif "FileNotFoundError" in error_type or "path" in error_detail.lower():
            error_detail = f"File/path error: {error_detail}. Check data files and chart output directory."
        
        # In debug mode, include more details
        if os.getenv("DEBUG") == "true":
            raise HTTPException(
                status_code=500, 
                detail=f"{error_type}: {error_detail}\n\nFull traceback available in server logs."
            )
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Internal server error: {error_detail}. Check server logs for details."
            )


@router.post("/chat/stream")
async def chat_stream(request: Request, chat_req: ChatRequest):
    """
    Streaming chat endpoint (SSE) for stage-accurate frontend transitions.

    Emits events:
    - stage: {"stage": "..."}
    - result: ChatResponse payload
    - error: {"detail": "..."}
    - done: {}
    """
    duckdb_conn = request.app.state.duckdb
    use_llm_pipeline = os.getenv("USE_LLM_PIPELINE", "true").lower() == "true"

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()

        async def progress_callback(stage: str):
            await queue.put(("stage", {"stage": stage}))

        async def run_pipeline():
            try:
                if use_llm_pipeline:
                    result = await process_query(
                        chat_req.message,
                        duckdb_conn,
                        progress_callback=progress_callback
                    )
                    response_payload = _response_to_dict(ChatResponse(
                        answer=result.get("answer", "Query processed"),
                        sql=result.get("sql"),
                        data=result.get("data"),
                        data_preview=result.get("data_preview"),
                        chart=result.get("chart"),
                        chart_image_url=_to_chart_image_url(result),
                        mode=result.get("mode", "sql")
                    ))
                else:
                    # Template fallback path still emits "running-query"
                    await progress_callback("running-query")
                    query_engine = QueryEngine(duckdb_conn)
                    metric_templates = MetricTemplates()
                    template_match = metric_templates.match(chat_req.message)
                    if template_match:
                        template_name = template_match["template"]
                        template_def = metric_templates.get_template(template_name)
                        result = query_engine.execute_template(template_name, template_match.get("params", {}))
                    else:
                        template_name = "hourly_trips_by_company"
                        template_def = metric_templates.get_template(template_name)
                        result = query_engine.execute_template(template_name, {})

                    try:
                        answer = template_def["answer_template"].format(**result["summary"])
                    except KeyError:
                        answer = template_def.get("answer_template", "Query executed successfully")

                    response_payload = _response_to_dict(ChatResponse(
                        answer=answer,
                        sql=result.get("sql"),
                        data=result.get("data"),
                        chart=result.get("chart"),
                        mode="template"
                    ))

                await queue.put(("result", response_payload))
            except Exception as e:
                await queue.put(("error", {"detail": str(e)}))
            finally:
                await queue.put(("done", {}))

        worker = asyncio.create_task(run_pipeline())

        try:
            while True:
                event_name, payload = await queue.get()
                yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
                if event_name == "done":
                    break
        finally:
            if not worker.done():
                worker.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chart-image")
async def get_chart_image(path: str):
    """Serve chart image files"""
    from pathlib import Path
    
    if not path:
        raise HTTPException(status_code=400, detail="Path parameter required")
    
    # Get chart directory from environment (default to /tmp for backward compatibility)
    chart_dir = Path(os.getenv("CHART_DIR", "/tmp/nyc_taxi_charts"))
    chart_dir = chart_dir.resolve()  # Resolve to absolute path
    
    # Security: ensure path is within allowed directory
    chart_path = Path(path).resolve()
    if not str(chart_path).startswith(str(chart_dir)):
        raise HTTPException(status_code=403, detail="Invalid path")
    
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="Chart image not found")
    
    return FileResponse(str(chart_path), media_type="image/png")

