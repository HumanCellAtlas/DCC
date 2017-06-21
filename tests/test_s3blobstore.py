#!/usr/bin/env python
# coding: utf-8

from __future__ import absolute_import, division, print_function, unicode_literals

import io
import os
import requests
import sys
import unittest
import uuid

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, pkg_root)

from dss.blobstore import BlobNotFoundError # noqa
from dss.blobstore.s3 import S3BlobStore # noqa
from tests import TESTOUTPUT_PREFIX, utils # noqa
from tests.test_blobstore import BlobStoreTests # noqa


class TestS3BlobStore(unittest.TestCase, BlobStoreTests):
    def setUp(self):
        self.test_bucket = utils.get_env("DSS_S3_TEST_BUCKET")
        self.test_src_data_bucket = utils.get_env("DSS_S3_TEST_SRC_DATA_BUCKET")

        self.handle = S3BlobStore()

    def tearDown(self):
        pass

    # TODO: this should be moved to BlobStoreTests once we build the GCS
    # equivalents out
    def testList(self):
        items = [item for item in
                 self.handle.list(
                     self.test_src_data_bucket,
                     "test_good_source_data/0",
                 )]
        self.assertTrue(len(items) > 0)
        for item in items:
            if item == "test_good_source_data/0":
                break
        else:
            self.fail("did not find the requisite key")

        # fetch a bunch of items all at once.
        items = [item for item in
                 self.handle.list(
                     self.test_src_data_bucket,
                     "testList/prefix",
                 )]
        self.assertEqual(len(items), 100)

        # this should fetch both testList/delimiter and testList/delimiter/test
        items = [item for item in
                 self.handle.list(
                     self.test_src_data_bucket,
                     "testList/delimiter",
                 )]
        self.assertEqual(len(items), 2)

        # this should fetch only testList/delimiter
        items = [item for item in
                 self.handle.list(
                     self.test_src_data_bucket,
                     "testList/delimiter",
                     delimiter="/"
                 )]
        self.assertEqual(len(items), 1)

    # TODO: this should be moved to BlobStoreTests once we build the GCS
    # equivalents out
    def testUploadFileHandle(self):
        fobj = io.BytesIO(b"abcabcabc")
        function_name = "%s.%s" % (
            TestS3BlobStore.__name__,
            self.testUploadFileHandle.__name__
        )
        dst_blob_name = os.path.join(
            TESTOUTPUT_PREFIX, function_name, str(uuid.uuid4()))

        self.handle.upload_file_handle(
            self.test_bucket,
            dst_blob_name,
            fobj
        )

        # should be able to get metadata for the file.
        self.handle.get_metadata(
            self.test_bucket, dst_blob_name)

    # TODO: this should be moved to BlobStoreTests once we build the GCS
    # equivalents out
    def testGet(self):
        data = self.handle.get(
            self.test_src_data_bucket,
            "test_good_source_data/0",
        )
        self.assertEqual(len(data), 11358)

        with self.assertRaises(BlobNotFoundError):
            self.handle.get(
                self.test_src_data_bucket,
                "test_good_source_data_DOES_NOT_EXIST",
            )

    # TODO: this should be moved to BlobStoreTests once we build the GCS
    # equivalents out
    def testGetPresignedUrl(self):
        presigned_url = self.handle.generate_presigned_GET_url(
            self.test_src_data_bucket,
            "test_good_source_data/0",
        )

        resp = requests.get(presigned_url)
        self.assertEqual(resp.status_code, requests.codes.ok)

if __name__ == '__main__':
    unittest.main()
