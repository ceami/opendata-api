# Copyright 2025 Team Aeris
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.environment := $(if $(ENV),$(ENV),local)

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