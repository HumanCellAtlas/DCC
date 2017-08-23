#!/usr/bin/env python
# coding: utf-8

import json
import logging
import os
import sys
import unittest

import requests

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))  # noqa
sys.path.insert(0, pkg_root)  # noqa

import dss
from dss.events.handlers.index import create_elasticsearch_index
from dss.util.es import ElasticsearchServer
from tests.infra import DSSAsserts


class TestSearch(unittest.TestCase, DSSAsserts):
    @classmethod
    def setUpClass(cls):
        cls.es_server = ElasticsearchServer()
        os.environ['DSS_ES_PORT'] = str(cls.es_server.port)

    @classmethod
    def tearDownClass(cls):
        cls.es_server.shutdown()

    def setUp(self):
        dss.Config.set_config(dss.DeploymentStage.TEST)
        self.app = dss.create_app().app.test_client()
        create_elasticsearch_index(logging.getLogger(__name__))

    def test_search_post(self):
        query = \
            {
                "query": {
                    "bool": {
                        "must": [{
                            "match": {
                                "files.sample_json.donor.species": "Homo sapiens"
                            }
                        }, {
                            "match": {
                                "files.assay_json.single_cell.method": "Fluidigm C1"
                            }
                        }, {
                            "match": {
                                "files.sample_json.ncbi_biosample": "SAMN04303778"
                            }
                        }]
                    }
                }
            }
        self.assertPostResponse(
            '/v1/search',
            json_request_body=(query),
            expected_code=requests.codes.ok)
