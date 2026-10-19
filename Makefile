.PHONY: secrets config-lint build standalone-up standalone-down ha-up ha-down smoke ha-test ha-check ha-lab-build ha-integration
include versions.env
.EXPORT_ALL_VARIABLES:
secrets:
	@./scripts/generate-secrets.sh
config-lint:
	@./scripts/validate.sh
build:
	docker buildx bake --set '*.platform=linux/amd64' postgres pgbouncer
standalone-up: secrets
	docker compose -f compose/standalone.yml --env-file .env up -d --build
standalone-down:
	docker compose -f compose/standalone.yml down -v
ha-up: secrets
	docker compose -f compose/ha.yml --env-file .env up -d --build
ha-down:
	docker compose -f compose/ha.yml down -v
smoke:
	@./tests/shell/smoke.sh
ha-test:
	@./tests/shell/ha-failover.sh
ha-check:
	@./scripts/validate-production-ha.sh
ha-lab-build:
	docker build -t postgres-ha-patroni:test ha/images/patroni
	docker build -t postgres-ha-pgbouncer:test ha/images/pgbouncer
ha-integration: ha-lab-build
	UV_LINK_MODE=copy uv run --locked --directory ha pytest tests/integration -v -s
