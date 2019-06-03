from concurrent.futures import ThreadPoolExecutor
import logging
import json
import os
import sys

import domovoi

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), 'domovoilib'))  # noqa
sys.path.insert(0, pkg_root)  # noqa

import dss
from dss import Config
from dss import Replica
from dss.index import DEFAULT_BACKENDS
from dss.index.backend import CompositeIndexBackend
from dss.index.indexer import Indexer
from dss.logging import configure_lambda_logging
from dss.util import tracing
from dss.util.time import RemainingLambdaContextTime, AdjustedRemainingTime


app = domovoi.Domovoi(configure_logs=False)


configure_lambda_logging()
logger = logging.getLogger(__name__)
dss.Config.set_config(dss.BucketConfig.NORMAL)


@app.s3_event_handler(bucket=Config.get_s3_bucket(), events=["s3:ObjectCreated:*"], use_sqs=True)
def dispatch_s3_indexer_event(event, context) -> None:
    if event.get("Event") == "s3:TestEvent":
        logger.info("DSS index daemon received S3 test event")
    else:
        for event_record in event["Records"]:
            _handle_event(Replica.aws, event_record, context)


@app.sqs_queue_subscriber("dss-index-" + os.environ["DSS_DEPLOYMENT_STAGE"])
def dispatch_gs_indexer_event(event, context):
    """
    This handler receives GS events via the Google Cloud Function deployed from daemons/dss-gs-event-relay.
    """
    for event_record in event["Records"]:
        message = json.loads(json.loads(event_record["body"])["Message"])
        if message['resourceState'] == "not_exists":
            logger.info("Ignoring object deletion event")
        else:
            _handle_event(Replica.gcp, message, context)


def _handle_event(replica, event, context):
    executor = ThreadPoolExecutor(len(DEFAULT_BACKENDS))
    # We can't use executor as context manager because we don't want the shutdown to block
    try:
        remaining_time = AdjustedRemainingTime(actual=RemainingLambdaContextTime(context),
                                               offset=-10)  # leave 10s for shutdown
        backend = CompositeIndexBackend(executor, remaining_time, DEFAULT_BACKENDS)
        indexer_cls = Indexer.for_replica(replica)
        indexer = indexer_cls(backend, remaining_time)
        indexer.process_new_indexable_object(event)
    finally:
        executor.shutdown(False)