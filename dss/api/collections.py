import os, sys, json, logging, datetime, io, functools
from typing import List
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import requests
from flask import jsonify, request
import jsonpointer
import iso8601

from dss import Config, Replica
from dss.error import DSSException, dss_handler
from dss.storage.blobstore import test_object_exists
from dss.storage.hcablobstore import FileMetadata, BlobStore
from dss.storage.identifiers import COLLECTION_PREFIX, TOMBSTONE_SUFFIX
from dss.util.version import datetime_to_version_format
from dss.api.bundles import _idempotent_save

from cloud_blobstore import BlobNotFoundError

MAX_METADATA_SIZE = 1024 * 1024

logger = logging.getLogger(__name__)
dss_bucket = Config.get_s3_bucket()

def get_impl(uuid: str, replica: str, version: str = None):
    uuid = uuid.lower()
    bucket = Replica[replica].bucket
    handle = Config.get_blobstore_handle(Replica[replica])

    my_collection_prefix = "{}/{}".format(COLLECTION_PREFIX, uuid)
    tombstone_key = "{}.{}".format(my_collection_prefix, TOMBSTONE_SUFFIX)
    if test_object_exists(handle, bucket, tombstone_key):
        raise DSSException(404, "not_found", "Could not find collection for UUID {}".format(uuid))

    if version is None:
        # list the collections and find the one that is the most recent.
        prefix = "collections/{}.".format(uuid)
        for matching_key in handle.list(bucket, prefix):
            matching_key = matching_key[len(prefix):]
            if version is None or matching_key > version:
                version = matching_key
    try:
        collection_blob = handle.get(bucket, "{}/{}.{}".format(COLLECTION_PREFIX, uuid, version))
    except BlobNotFoundError:
        raise DSSException(404, "not_found", "Could not find collection for UUID {}".format(uuid))
    return json.loads(collection_blob)

@dss_handler
def get(uuid: str, replica: str, version: str = None):
    authenticated_user_email = request.token_info['email']
    collection_body = get_impl(uuid=uuid, replica=replica, version=version)
    if collection_body["owner"] != authenticated_user_email:
        raise DSSException(requests.codes.forbidden, "forbidden", f"Collection access denied")
    return collection_body

@dss_handler
def put(json_request_body: dict, replica: str, uuid: str, version: str):
    authenticated_user_email = request.token_info["email"]
    collection_body = dict(json_request_body, owner=authenticated_user_email)
    uuid = uuid.lower()
    handle = Config.get_blobstore_handle(Replica[replica])
    verify_collection(collection_body["contents"], Replica[replica], handle)
    collection_uuid = uuid if uuid else str(uuid4())
    if version is not None:
        # convert it to date-time so we can format exactly as the system requires (with microsecond precision)
        timestamp = iso8601.parse_date(version)
    else:
        timestamp = datetime.datetime.utcnow()
    collection_version = datetime_to_version_format(timestamp)
    handle.upload_file_handle(Replica[replica].bucket,
                              "{}/{}.{}".format(COLLECTION_PREFIX, collection_uuid, collection_version),
                              io.BytesIO(json.dumps(collection_body).encode("utf-8")))
    return jsonify(dict(uuid=collection_uuid, version=collection_version)), requests.codes.created

class hashabledict(dict):
    def __hash__(self):
        return hash(tuple(sorted(self.items())))

@dss_handler
def patch(uuid: str, json_request_body: dict, replica: str, version: str):
    authenticated_user_email = request.token_info['email']

    uuid = uuid.lower()
    owner = get_impl(uuid=uuid, replica=replica)["owner"]
    if owner != authenticated_user_email:
        raise DSSException(requests.codes.forbidden, "forbidden", f"Collection access denied")

    handle = Config.get_blobstore_handle(Replica[replica])
    try:
        cur_collection_blob = handle.get(Replica[replica].bucket, "{}/{}.{}".format(COLLECTION_PREFIX, uuid, version))
    except BlobNotFoundError:
        raise DSSException(404, "not_found", "Could not find collection for UUID {}".format(uuid))
    collection = json.loads(cur_collection_blob)
    for field in "name", "description", "details":
        if field in json_request_body:
            collection[field] = json_request_body[field]
    remove_contents_set = set(map(hashabledict, json_request_body.get("removeContents", [])))
    collection["contents"] = [i for i in collection["contents"] if hashabledict(i) not in remove_contents_set]
    verify_collection(json_request_body.get("addContents", []), Replica[replica], handle)
    collection["contents"].extend(json_request_body.get("addContents", []))
    timestamp = datetime.datetime.utcnow()
    new_collection_version = datetime_to_version_format(timestamp)
    handle.upload_file_handle(Replica[replica].bucket,
                              "{}/{}.{}".format(COLLECTION_PREFIX, uuid, new_collection_version),
                              io.BytesIO(json.dumps(collection).encode("utf-8")))
    return jsonify(dict(uuid=uuid, version=new_collection_version)), requests.codes.ok

@dss_handler
def delete(uuid: str, replica: str):
    authenticated_user_email = request.token_info['email']

    uuid = uuid.lower()
    my_collection_prefix = "{}/{}".format(COLLECTION_PREFIX, uuid)
    tombstone_key = "{}.{}".format(my_collection_prefix, TOMBSTONE_SUFFIX)

    tombstone_object_data = dict(email=authenticated_user_email)

    owner = get_impl(uuid=uuid, replica=replica)["owner"]
    if owner != authenticated_user_email:
        raise DSSException(requests.codes.forbidden, "forbidden", f"Collection access denied")

    blobstore = Config.get_blobstore_handle(Replica[replica])
    bucket = Replica[replica].bucket
    created, idempotent = _idempotent_save(blobstore, bucket, tombstone_key, tombstone_object_data)
    if not idempotent:
        raise DSSException(requests.codes.conflict,
                           f"collection_tombstone_already_exists",
                           f"collection tombstone with UUID {uuid} already exists")
    status_code = requests.codes.ok
    response_body = dict()  # type: dict

    return jsonify(response_body), status_code

@functools.lru_cache(maxsize=64)
def get_json_metadata(entity_type: str, uuid: str, version: str, replica: Replica, blobstore_handle: BlobStore):
    try:
        key = "{}s/{}.{}".format(entity_type, uuid, version)
        # TODO: verify that file is a metadata file
        size = blobstore_handle.get_size(replica.bucket, key)
        if size > MAX_METADATA_SIZE:
            raise DSSException(422, "invalid_link",
                               "The file UUID {} refers to a file that is too large to process".format(uuid))
        return json.loads(blobstore_handle.get(
            replica.bucket,
            "{}s/{}.{}".format(entity_type, uuid, version)))
    except BlobNotFoundError as ex:
        raise DSSException(404, "invalid_link", "Could not find file for UUID {}".format(uuid))

def resolve_content_item(replica: Replica, blobstore_handle: BlobStore, item: dict):
    try:
        if item["type"] in {"file", "bundle", "collection"}:
            item_metadata = get_json_metadata(item["type"], item["uuid"], item["version"], replica, blobstore_handle)
        else:
            item_metadata = get_json_metadata("file", item["uuid"], item["version"], replica, blobstore_handle)
            if "fragment" not in item:
                raise Exception('The "fragment" field is required in collection elements '
                                'other than files, bundles, and collections')
            blob_path = "blobs/" + ".".join((
                item_metadata[FileMetadata.SHA256],
                item_metadata[FileMetadata.SHA1],
                item_metadata[FileMetadata.S3_ETAG],
                item_metadata[FileMetadata.CRC32C],
            ))
            # check that item is marked as metadata, is json, and is less than max size
            item_doc = json.loads(blobstore_handle.get(replica.bucket, blob_path))
            item_content = jsonpointer.resolve_pointer(item_doc, item["fragment"])
            return item_content
    except DSSException:
        raise
    except Exception as e:
        raise DSSException(
            422,
            "invalid_link",
            'Error while parsing the link "{}": {}: {}'.format(item, type(e).__name__, e)
        )

def verify_collection(contents: List[dict], replica: Replica, blobstore_handle: BlobStore):
    """
    Given user-supplied collection contents that pass schema validation, resolve all entities in the collection and
    verify they exist.
    """
    executor = ThreadPoolExecutor(max_workers=8)
    for result in executor.map(partial(resolve_content_item, replica, blobstore_handle), contents):
        pass
