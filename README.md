# NYC Uber/Lyft Data Chatbot

LLM-powered chatbot for querying NYC TLC FHVHV (For-Hire Vehicle High Volume) data using natural language. Generates SQL queries, executes them with DuckDB, and creates visualizations.

## Features

- 🤖 Natural language to SQL generation using LLMs (Groq API - default, or Ollama local)
- 📊 Structured chart specification generation (JSON specs instead of Python code)
- 🎯 Agent-style validation with automatic error correction and retry logic
- ⚡ Fast queries using DuckDB on Parquet files
- 📈 Reliable chart rendering from structured specifications
- 🌐 Web interface for interactive querying

## Quick Start (Docker - Recommended)

### Prerequisites

- **Docker** and **Docker Compose** installed
- **Groq API key** (get from https://console.groq.com/)
- Data files in `data/` directory

### Setup

1. **Get your Groq API key:**
   - Sign up at https://console.groq.com/
   - Navigate to API Keys
   - Create a new API key

2. **Create `.env` file in project root:**
   ```bash
   cat > .env << EOF
   LLM_PROVIDER=groq
   GROQ_API_KEY=your_groq_api_key_here
   TURNSTILE_SECRET_KEY=1x00000000000000000000AA
   EOF
   ```

3. **Prepare data files:**
   
   **Download trip data from NYC TLC:**
   - Download `fhvhv_tripdata_2023-*.parquet` files from the [NYC TLC Trip Record Data page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)
   - Look for "High Volume For-Hire Vehicle Trip Records" under the 2023 section
   - Place the downloaded Parquet files in the `data/` directory
   
   **Lookup files (already included in `data/`):**
   - `taxi_zone_lookup.csv` - From NYC TLC website
   - `fhv_base_lookup.csv` - Project-created
   - `hvfhs_license_num_lookup.csv` - Project-created

### Running with Docker

**Start production services (default):**
```bash
docker-compose up --build
```

**Or using Makefile:**
```bash
make docker-up
```

**For development (with bind mounts and permissive settings):**
```bash
docker-compose -f docker-compose.dev.yml up
# Or: make docker-dev-up
```

The application will be available at:
- **Frontend:** http://localhost (port 80)
- **Backend API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs

### Usage

1. Open http://localhost in your browser
2. Ask questions about the NYC Uber/Lyft data, for example:
   - "What are the top 10 pickup zones?"
   - "Show hourly trips by company for the first 3 days of January 2023"
   - "What is the percentage of base passenger fares held by each company?"
3. View the generated SQL, data table, and visualization

**Note:** The system uses **Groq API** by default (no local LLM installation needed). See [LLM_SETUP.md](LLM_SETUP.md) for configuration details.

## Local Development (Alternative)

### Prerequisites

- Python 3.10+
- Node.js 18+
- **Groq API key** (recommended) OR Ollama installed and running

### Setup

1. **Install dependencies:**
   ```bash
   make setup
   ```

2. **Configure LLM:**
   
   **Groq API (Recommended):**
   ```bash
   cat > backend/.env << EOF
   LLM_PROVIDER=groq
   GROQ_API_KEY=your_groq_api_key_here
   TURNSTILE_SECRET_KEY=1x00000000000000000000AA
   EOF
   ```
   
   **Ollama (Local):**
   ```bash
   # Install Ollama: https://ollama.ai/
   ollama serve  # In a separate terminal
   ollama pull llama3:latest
   cat > backend/.env << EOF
   LLM_PROVIDER=ollama
   OLLAMA_MODEL=llama3:latest
   TURNSTILE_SECRET_KEY=1x00000000000000000000AA
   EOF
   ```

### Running Locally

**Start backend (Terminal 1):**
```bash
make backend-dev
```

**Start frontend (Terminal 2):**
```bash
make frontend-dev
```

The application will be available at:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000

## Testing the LLM Pipeline

The main test script (`backend/scripts/test_llm_pipeline.py`) implements the full pipeline:

**Pipeline Flow:**
1. User question → LLM generates SQL (with validation/retry)
2. SQL → DuckDB executes query
3. Query results → LLM generates chart spec (with validation/retry)
4. Chart spec → Renderer generates visualization

### Prerequisites

- Python 3.10+
- **Groq API key** (recommended) OR Ollama installed and running
- Data files in `data/` directory

### Setup

1. **Install dependencies:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure LLM:**

   **Groq API (Recommended - Default):**
   ```bash
   export GROQ_API_KEY=your_groq_api_key_here
   export LLM_PROVIDER=groq
   ```
   
   **Ollama (Local):**
   ```bash
   ollama serve  # In a separate terminal
   ollama pull llama3:latest
   export LLM_PROVIDER=ollama
   export OLLAMA_MODEL=llama3:latest
   ```

### Running Tests

**Test the full LLM pipeline:**
```bash
cd backend
source venv/bin/activate
PYTHONPATH=. python scripts/test_llm_pipeline.py
```

**With Groq (default):**
```bash
PYTHONPATH=. GROQ_API_KEY=your_key python scripts/test_llm_pipeline.py
```

**With Ollama:**
```bash
PYTHONPATH=. LLM_PROVIDER=ollama OLLAMA_MODEL=llama3:latest python scripts/test_llm_pipeline.py
```

**Using Makefile:**
```bash
make test-llm-pipeline
```

### Environment Variables

**For Groq API (Default - Recommended):**
- `LLM_PROVIDER`: Set to `groq` (default)
- `GROQ_API_KEY`: Your Groq API key (get from https://console.groq.com/keys) - **Required**
- `GROQ_MODEL`: Model to use (default: `llama-3.1-8b-instant`)

**For Ollama (local):**
- `LLM_PROVIDER`: Set to `ollama`
- `OLLAMA_MODEL`: Model to use (default: `llama3:latest`)
- `OLLAMA_BASE_URL`: Ollama server URL (default: `http://127.0.0.1:11434`)

**General:**
- `LLM_TIMEOUT`: Timeout in seconds (default: `300` for Ollama, `30` for Groq)
- `MAX_SQL_ATTEMPTS`: Max retries for SQL generation (default: `3`)
- `MAX_SPEC_ATTEMPTS`: Max retries for chart spec generation (default: `3`)

**Note:** Groq free tier provides 30 requests/minute and 7,000 requests/day, which is sufficient for prototyping and demos. For production, consider upgrading to Developer plan or using Ollama on a VPS.

## Docker Commands

**Start services:**
```bash
docker-compose up
# Or: make docker-up
```

**Stop services:**
```bash
docker-compose down
# Or: make docker-down
```

**View logs:**
```bash
docker-compose logs -f
# Or: make docker-logs
```

**Rebuild after code changes:**
```bash
docker-compose up --build
```

**Production is now the default:**
```bash
docker-compose up -d --build
```

**For development (bind mounts, permissive settings):**
```bash
docker-compose -f docker-compose.dev.yml up
```

See [DOCKER.md](DOCKER.md) for detailed Docker documentation and [DEPLOYMENT.md](DEPLOYMENT.md) for production deployment guide.

### Output

The test script will:
1. Generate and validate SQL
2. Execute the query and show sample results
3. Generate a structured chart specification
4. Render the chart using matplotlib
5. Save the chart to `backend/scripts/llm_chart.png`

### Validation Features

- **SQL Validation**: Checks syntax, schema (column existence), safety (dangerous keywords), and execution
- **Chart Spec Validation**: Validates JSON structure, column existence, and data types
- **Retry Logic**: Automatically retries with error feedback (up to 3 attempts each)
- **Error Feedback**: Feeds validation errors back to LLM for self-correction

## Project Structure

```
.
├── backend/
│   ├── scripts/
│   │   ├── test_llm_pipeline.py    # Main pipeline test
│   │   ├── test_sql_generation.py  # SQL generation test
│   │   ├── validation.py           # Validation tools
│   │   └── chart_renderer.py       # Chart renderer from specs
│   ├── services/
│   │   └── llm_pipeline.py         # LLM pipeline service
│   ├── db/
│   │   └── duckdb_setup.py         # DuckDB initialization
│   └── requirements.txt
├── frontend/
│   └── src/                        # React frontend
├── data/                           # Parquet files (gitignored)
├── docker-compose.yml              # Docker Compose config
├── .env                            # Environment variables (for Docker)
└── Makefile                        # Development commands
```
## License

MIT
