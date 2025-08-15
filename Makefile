environment := $(if $(ENV),$(ENV),local)

COMPOSE_FILE := docker-compose.yml
COMPOSE_OVERRIDE := docker-compose.override.yml
COMPOSE_OVERRIDE_DEV := docker-compose.override.dev.yml


ENV_FILE := .env.$(environment)

ifeq ($(environment),prod)
    COMPOSE_FILES := -f $(COMPOSE_FILE) -f $(COMPOSE_OVERRIDE)
	DOCKER := /bin/docker
else ifeq ($(environment),dev)
    COMPOSE_FILES := -f $(COMPOSE_FILE) -f $(COMPOSE_OVERRIDE) -f $(COMPOSE_OVERRIDE_DEV)
	DOCKER := /bin/docker
else
    COMPOSE_FILES := -f $(COMPOSE_FILE)
	DOCKER := $(shell which docker)
endif

DC := $(DOCKER) compose -p opendata-api --env-file $(ENV_FILE) $(COMPOSE_FILES)

restart:
	echo $(DC)
	@$(DC) down
	@$(DC) up -d --build
down:
	@$(DC) down
up:
	@$(DC) up -d --build