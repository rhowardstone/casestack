.PHONY: frontend dev

frontend:
	cd frontend && npm run build
	rm -rf src/casestack/static
	cp -r frontend/dist src/casestack/static

dev:
	@echo "Run in two terminals:"
	@echo "  Terminal 1: uvicorn casestack.api.app:create_app --factory --reload --port 8000"
	@echo "  Terminal 2: cd frontend && npm run dev"
