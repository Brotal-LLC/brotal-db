.PHONY: secrets config-lint build standalone-up standalone-down ha-up ha-down smoke ha-test
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
