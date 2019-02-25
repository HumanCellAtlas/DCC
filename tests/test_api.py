#!/usr/bin/env python
# coding: utf-8

"""
Functional Test of the API
"""
import datetime
import os
import sys
import unittest
import uuid as u
import requests

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))  # noqa
sys.path.insert(0, pkg_root)  # noqa

from dss.config import Replica
import dss
from dss.util import UrlBuilder
from dss.util.version import datetime_to_version_format
from tests.infra import DSSAssertMixin, DSSUploadMixin, DSSStorageMixin, TestBundle, testmode, get_env
from tests.infra.server import ThreadedLocalServer
from tests import get_auth_header


class TestApi(unittest.TestCase, DSSAssertMixin, DSSUploadMixin, DSSStorageMixin):
    @classmethod
    def setUpClass(cls):
        os.environ['DSS_VERSION'] = "test_version"
        cls.app = ThreadedLocalServer()
        cls.app.start()

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()

    def setUp(self):
        self.replica = Replica.aws
        dss.Config.set_config(dss.BucketConfig.TEST)
        self.blobstore = dss.Config.get_blobstore_handle(self.replica)
        self.bucket = self.replica.bucket

    BUNDLE_FIXTURE = "fixtures/example_bundle"

    @testmode.standalone
    def test_creation_and_retrieval_of_files_and_bundle(self):

        # FIXME: This test doesn't do much because it uses the test bucket which lacks the fixtures for the test bundle.
        # FIMXE: In particular it does not test any of the /files routes. (hannes)

        """
        Test file and bundle lifecycle.
        Exercises:
          - PUT /files/<uuid>
          - PUT /bundles/<uuid>
          - GET /bundles/<uuid>
          - GET /files/<uuid>
        and checks that data corresponds where appropriate.
        """
        bundle = TestBundle(self.blobstore, self.BUNDLE_FIXTURE, self.bucket, self.replica)
        self.upload_files_and_create_bundle(bundle, self.replica)
        self.get_bundle_and_check_files(bundle, self.replica)

    @testmode.standalone
    def test_get_version(self):
        """
        Test /version endpoint and configuration
        """
        res = self.assertGetResponse("/version", requests.codes.ok, headers=get_auth_header())
        self.assertEquals(res.json['version_info']['version'], os.environ['DSS_VERSION'])

    @testmode.standalone
    def test_put_file_pattern(self):
        """
        Tests the regex pattern filtering on the PUT file/{uuid} endpoint.

        Ensures that paths with leading slashes (absolute paths) and
        relative path shortcuts (".", "~/", and "..") are disallowed.
        """

        examples_of_bad_paths = ['.', '..',
                                 '~/path',
                                 './', '../', './path', './../path', '../path', '../../path',
                                 'path/../path', 'path/..',
                                 '/path', '/path.json', '/bad..path']

        examples_of_good_paths = ['path', 'path.json', 'good..path', 'path.json/', 'good..path/',
                                  'pa/th.json', 'go/od..path', 'a/b/c/d', 'a/b.c/d', '.bashrc']

        for path, replica in [("bundles", "aws"), ("bundles", "gcp")]:
            with self.subTest(path=path, replica=replica):
                for bad_path in examples_of_bad_paths:
                    self.put_bundles_reponse(bad_path, replica, expected_code=[requests.codes.bad_request])
                for good_path in examples_of_good_paths:
                    self.put_bundles_reponse(good_path, replica, expected_code=[requests.codes.ok,
                                                                                requests.codes.created])

    @staticmethod
    def get_test_fixture_bucket(replica: str) -> str:
        return get_env("DSS_S3_BUCKET_TEST_FIXTURES") if replica == 'aws' else get_env("DSS_GS_BUCKET_TEST_FIXTURES")

    def put_bundles_reponse(self, path, replica, expected_code):
        fixtures_bucket = self.get_test_fixture_bucket(replica)  # source a file to upload
        file_version = datetime_to_version_format(datetime.datetime.utcnow())
        bundle_version = datetime_to_version_format(datetime.datetime.utcnow())
        bundle_uuid = str(u.uuid4())
        file_uuid = str(u.uuid4())
        storage_schema = 's3' if replica == 'aws' else 'gs'

        self.upload_file_wait(
            f"{storage_schema}://{fixtures_bucket}/test_good_source_data/0",
            replica,
            file_uuid,
            file_version=file_version,
            bundle_uuid=bundle_uuid
        )

        builder = UrlBuilder().set(path="/v1/bundles/" + bundle_uuid)
        builder.add_query("replica", replica)
        builder.add_query("version", bundle_version)
        url = str(builder)

        self.assertPutResponse(
            url,
            expected_code,
            json_request_body=dict(
                files=[
                    dict(
                        uuid=file_uuid,
                        version=file_version,
                        name=path,
                        indexed=False
                    )
                ],
                creator_uid=0,
            ),
            headers=get_auth_header()
        )

    @testmode.standalone
    def test_read_only(self):
        uuid = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
        body = dict(
            files=[],
            creator_uid=12345,
            es_query={},
            callback_url="https://take.me.to.funkytown",
            source_url="s3://urlurlurlbaby",
            description="supercalifragilisticexpialidocious",
            details={},
            reason="none",
            contents=[],
            name="frank",
        )
        version = datetime_to_version_format(datetime.datetime.utcnow())
        tests = [(path, replica)
                 for path in ("bundles", "files", "subscriptions", "collections")
                 for replica in ("aws", "gcp")]

        os.environ['DSS_READ_ONLY_MODE'] = "True"
        try:
            for path, replica in tests:
                with self.subTest(path=path, replica=replica):
                    put_url = str(UrlBuilder().set(path=f"/v1/{path}/{uuid}")
                                  .add_query("version", version)
                                  .add_query("replica", replica))
                    delete_url = str(UrlBuilder().set(path=f"/v1/{path}/{uuid}")
                                     .add_query("version", "asdf")
                                     .add_query("replica", replica))
                    json_request_body = body.copy()

                    if path == "subscriptions":
                        put_url = str(UrlBuilder().set(path=f"/v1/{path}")
                                      .add_query("version", "asdf")
                                      .add_query("uuid", uuid)
                                      .add_query("replica", replica))
                        delete_url = None
                        del json_request_body['source_url']
                        del json_request_body['creator_uid']
                        del json_request_body['description']
                        del json_request_body['reason']
                        del json_request_body['details']
                        del json_request_body['files']
                        del json_request_body['contents']
                        del json_request_body['name']
                    elif path == "files":
                        delete_url = None
                    elif path == "collections":
                        put_url = str(UrlBuilder().set(path=f"/v1/{path}")
                                      .add_query("version", version)
                                      .add_query("uuid", uuid)
                                      .add_query("replica", replica))
                        delete_url = str(UrlBuilder().set(path=f"/v1/{path}/{uuid}")
                                         .add_query("version", "asdf")
                                         .add_query("replica", replica))
                        del json_request_body['es_query']
                        del json_request_body['callback_url']

                    if put_url:
                        self.assertPutResponse(
                            put_url,
                            requests.codes.unavailable,
                            json_request_body=json_request_body,
                            headers=get_auth_header()
                        )

                    if delete_url:
                        self.assertDeleteResponse(
                            delete_url,
                            requests.codes.unavailable,
                            json_request_body=json_request_body,
                            headers=get_auth_header()
                        )
        finally:
            del os.environ['DSS_READ_ONLY_MODE']


if __name__ == '__main__':
    unittest.main()
