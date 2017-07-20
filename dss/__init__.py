#!/usr/bin/env python

"""
DSS description FIXME: elaborate
"""

import logging

import flask
import connexion
from connexion.resolver import RestyResolver
from flask_failsafe import failsafe

from .config import BucketStage, Config

# Constants common to the indexer and query route.
DSS_ELASTICSEARCH_INDEX_NAME = "hca"
DSS_ELASTICSEARCH_DOC_TYPE = "hca"
DSS_ELASTICSEARCH_QUERIES_INDEX_NAME = "queries"
DSS_ELASTICSEARCH_QUERIES_DOC_TYPE = "queries_type"

def get_logger():
    try:
        return flask.current_app.logger
    except RuntimeError:
        return logging.getLogger(__name__)

@failsafe
def create_app():
    app = connexion.App(__name__)
    resolver = RestyResolver("dss.api", collection_endpoint_name="list")
    app.add_api('../dss-api.yml', resolver=resolver, validate_responses=True)
    return app
