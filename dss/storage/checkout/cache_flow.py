import os
import json
import typing
from dss.config import Replica
from dss.storage.hcablobstore import FileMetadata

"""
These functions assist with the caching process, the lifecycle policies are set to delete files within
the checkout buckets;
For AWS object tagging is used to mark files for deletion: TagSet=[{uncached:True}]
For GCP object classes are used to indicate what is to be cached:
See MetaData Caching RFC for more information (Google Docs)
"""


def _cache_net():
    with open("checkout_cache_criteria.json", "r") as file:
        temp = json.load(file)
    return temp


def get_uncached_status(file_metadata: dict):
    # That are over the size limit have an uncached status
    for file_type in _cache_net():
        if file_type['type'] == file_metadata[FileMetadata.CONTENT_TYPE]:
            if file_type['max_size'] >= file_metadata[FileMetadata.SIZE]:
                return "False"
    return "True"
