.PHONY: help backend-dev backend-dev-groq backend-dev-openai frontend-dev build-backend build-frontend setup install test clean test-llm-pipeline docker-build docker-up docker-down docker-logs docker-prod-up docker-prod-down docker-clean demo

help:
	@echo "NYC Ridehail Analytics Chatbot - Development Commands"
	@echo ""
	@echo "Demo (interview / quick run):"
	@echo "  make demo           - Check env and print Docker run steps (see DEMO_GUIDE.md)"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          - Initial setup (install dependencies)"
	@echo ""
	@echo "Development:"
	@echo "  make backend-dev    - Start backend dev server (with LLM pipeline enabled)"
	@echo "  make backend-dev-groq - Start backend dev server forcing Groq API"
	@echo "  make backend-dev-openai - Start backend dev server forcing OpenAI API"
	@echo "  make frontend-dev   - Start frontend dev server"
	@echo ""
	@echo "Build:"
	@echo "  make build-backend  - Build backend Docker image"
	@echo "  make build-frontend - Build frontend for production"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   - Build all Docker images"
	@echo "  make docker-up      - Start production services (default)"
	@echo "  make docker-down    - Stop Docker Compose services"
	@echo "  make docker-logs    - View Docker Compose logs"
	@echo "  make docker-dev-up  - Start development services"
	@echo "  make docker-dev-down - Stop development services"
	@echo "  make docker-clean   - Remove containers, volumes, and images"
	@echo ""
	@echo "Testing:"
	@echo "  make test           - Run tests"
	@echo "  make test-llm-pipeline - Test LLM pipeline (SQL + chart generation)"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean          - Clean cache and temp files"

demo:
	@echo "=== Demo setup (see DEMO_GUIDE.md for full walkthrough) ==="
	@echo ""
	@if [ ! -f .env ]; then \
		echo "  .env not found. Create it from .env.example and set GROQ_API_KEY."; \
		echo "  Example: cp .env.example .env"; \
		echo ""; \
	else \
		echo "  .env found."; \
	fi
	@echo "  Then run: docker-compose up --build"
	@echo "  Frontend: http://localhost   Backend: http://localhost:8000"
	@echo ""

setup:
	@echo "Setting up backend..."
	cd backend && python -m venv venv || true
	cd backend && source venv/bin/activate && pip install -r requirements.txt
	@echo "Setting up frontend..."
	cd frontend && npm install
	@echo "Setup complete! Copy .env.example files and configure."

backend-dev:
	cd backend && source venv/bin/activate && USE_LLM_PIPELINE=true uvicorn main:app --reload --port 8000

backend-dev-groq:
	cd backend && source venv/bin/activate && USE_LLM_PIPELINE=true LLM_PROVIDER=groq uvicorn main:app --reload --port 8000

backend-dev-openai:
	cd backend && source venv/bin/activate && USE_LLM_PIPELINE=true LLM_PROVIDER=openai uvicorn main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

build-frontend:
	cd frontend && npm run build

test:
	cd backend && source venv/bin/activate && pytest
	cd frontend && npm test

test-llm-pipeline:
	@echo "Testing LLM pipeline..."
	cd backend && source venv/bin/activate && PYTHONPATH=. python scripts/test_llm_pipeline.py

docker-build:
	@echo "Building Docker images..."
	docker-compose build

docker-up:
	@echo "Starting Docker Compose services (production)..."
	docker-compose up -d --build
	@echo "Production services started. Frontend: http://localhost, Backend: http://localhost:8000"

docker-down:
	@echo "Stopping Docker Compose services..."
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-dev-up:
	@echo "Starting development Docker Compose services..."
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Development services started. Frontend: http://localhost, Backend: http://localhost:8000"

docker-dev-down:
	@echo "Stopping development Docker Compose services..."
	docker-compose -f docker-compose.dev.yml down

docker-clean:
	@echo "Cleaning Docker resources..."
	docker-compose down -v
	docker-compose -f docker-compose.dev.yml down -v
	@echo "Removing unused images..."
	docker image prune -f

clean:
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf backend/.pytest_cache
	rm -rf frontend/node_modules/.cache
	rm -rf frontend/dist
	rm -rf /tmp/nyc_taxi_charts
	rm -rf charts/*.png
	rm -f backend/scripts/llm_chart.png
