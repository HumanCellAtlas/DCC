#!/usr/bin/env python

"""
DSS description FIXME: elaborate
"""

import os, sys, json, time, logging
from datetime import datetime, timedelta

import boto3
import google.cloud.storage
from azure.storage.blob import BlockBlobService, BlobPermissions
from flask import Flask, request, redirect, jsonify
import connexion
from connexion.resolver import RestyResolver
from flask_failsafe import failsafe

logging.basicConfig(level=logging.DEBUG)

app = None
logger = None

@failsafe
def create_app():
    global app, logger
    app = connexion.App(__name__)
    logger = app.app.logger
    resolver = RestyResolver("dss.api", collection_endpoint_name="list")
    app.add_api('../dss-api.yml', resolver=resolver, validate_responses=True)
    return app
