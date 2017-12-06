SHELL=/bin/bash

ifndef DSS_HOME
$(error Please run "source environment" in the data-store repo root directory before running make commands)
endif

ifeq ($(shell which jq),)
$(error Please install jq using "apt-get install jq" or "brew install jq")
endif

ifeq ($(shell which sponge),)
$(error Please install sponge using "apt-get install moreutils" or "brew install moreutils")
endif

ifeq ($(shell which envsubst),)
$(error Please install envsubst using "apt-get install gettext" or "brew install gettext; brew link gettext")
endif

ifeq ($(findstring Python 3.6, $(shell python --version)),)
$(error Please run make commands from a Python 3.6 virtualenv)
endif

ifneq ($(shell python -c 'import dyndbmutex' && echo yes), yes)
$(error The dyndbmutex package is missing. Installing build requirements from requirements-dev.txt should fix that)
endif