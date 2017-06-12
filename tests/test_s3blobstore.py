#!/usr/bin/env python
# coding: utf-8

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
import unittest

from test_blobstore import BlobStoreTests

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, pkg_root)

from dss.blobstore.s3 import S3BlobStore # noqa


class TestS3BlobStore(unittest.TestCase, BlobStoreTests):
    def setUp(self):
        if "DSS_S3_TEST_BUCKET" not in os.environ:
            raise Exception("Please set the DSS_S3_TEST_BUCKET environment variable")
        self.test_bucket = os.environ["DSS_S3_TEST_BUCKET"]
        self.handle = S3BlobStore()

    def tearDown(self):
        pass

if __name__ == '__main__':
    unittest.main()
