.PHONY: sync up down rebuild ps logs smoke-desktop smoke-browser run-desktop run-browser run-browser-pixel run-browser-dom view doctor clean-traces

sync:
	uv sync

up:
	docker compose up -d --build

down:
	docker compose down

rebuild:
	docker compose build --no-cache

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=50

# no model, no API cost: proves the sandbox + trace pipeline works
smoke-desktop:
	uv run cua-lab run --task tasks/desktop/d0_smoke.yaml --policy script

smoke-browser:
	uv run cua-lab run --task tasks/browser/b0_smoke.yaml --policy script

run-desktop:
	uv run cua-lab run --task tasks/desktop/d1_create_file.yaml

run-browser:
	uv run cua-lab run --task tasks/browser/b1_form.yaml

# same task, two interfaces: the ablation that matters
run-browser-pixel:
	uv run cua-lab run --task tasks/browser/b1_form.yaml --obs pixel

run-browser-dom:
	uv run cua-lab run --task tasks/browser/b1_form.yaml --obs dom

view:
	uv run cua-lab view

doctor:
	uv run cua-lab doctor

clean-traces:
	rm -rf traces/*
