.PHONY: dev api worker test build demo reset

dev:            ## API + worker + Vite dev server (needs Postgres on :5432)
	cd backend && ledgerline migrate
	(cd backend && ledgerline api --reload) & (cd backend && ledgerline worker) & (cd frontend && npm run dev) & wait

api:
	cd backend && ledgerline migrate && ledgerline api

worker:
	cd backend && ledgerline worker

test:
	cd backend && python -m pytest -q

build:
	cd frontend && npm ci && npm run build

demo:           ## reproducible demo with no PayPal or LLM keys
	cd backend && ledgerline migrate && ledgerline reset --yes && LLM_MODEL=$${LLM_MODEL:-stub} PAYPAL_DRY_RUN=true ledgerline sim replay

reset:
	cd backend && ledgerline reset --yes
