import datetime
import json
import logging
import os
import sys
import tempfile
import time
from decimal import Decimal

import boto3
import domovoi

pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), 'domovoilib'))  # noqa
sys.path.insert(0, pkg_root)  # noqa

from dss import stepfunctions
from dss.stepfunctions import generator

from hca.dss import DSSClient
from json_generator import generate_sample

AWS_MIN_CHUNK_SIZE = 64 * 1024 * 1024
WAIT_CHECKOUT = 3
PARALLELIZATION_FACTOR = 10

app = domovoi.Domovoi()

app.log.setLevel(logging.DEBUG)

test_bucket = os.environ["DSS_S3_CHECKOUT_BUCKET"]

os.environ["HOME"] = "/tmp"

os.environ["HCA_CONFIG_FILE"] = "/tmp/config.json"
with open(os.environ["HCA_CONFIG_FILE"], "w") as fh:
    fh.write(json.dumps({"DSSClient": {"swagger_url": "https://dss.dev.data.humancellatlas.org/v1/swagger.json"}}))

client = DSSClient()

dynamodb = boto3.resource('dynamodb')


def current_time():
    return int(round(time.time() * 1000))


def upload_bundle(event, context, branch_id):
    app.log.info("Upload bundle")
    with tempfile.TemporaryDirectory() as src_dir:
        # TODO: insert json generator here
        with tempfile.NamedTemporaryFile(dir=src_dir, suffix=".json", delete=False) as jfh:
            jfh.write(bytes(generate_sample(), 'UTF-8'))
            jfh.flush()
        with tempfile.NamedTemporaryFile(dir=src_dir, suffix=".bin") as fh:
            fh.write(os.urandom(AWS_MIN_CHUNK_SIZE + 1))
            fh.flush()
            start_time = current_time()
            bundle_output = client.upload(src_dir=src_dir, replica="aws", staging_bucket=test_bucket)
            return {"bundle_id": bundle_output['bundle_uuid'], "start_time": start_time}


def download_bundle(event, context, branch_id):
    app.log.info("Download bundle")
    bundle_id = event['bundle']['bundle_id']
    with tempfile.TemporaryDirectory() as dest_dir:
        client.download(bundle_id, replica="aws", dest_name=dest_dir)
    return {}


def checkout_bundle(event, context, branch_id):
    bundle_id = event['bundle']['bundle_id']
    app.log.info(f"Checkout bundle: {bundle_id}")
    checkout_output = client.post_bundles_checkout(uuid=bundle_id, replica='aws', email='rkisin@chanzuckerberg.com')
    return {"job_id": checkout_output['checkout_job_id']}


def checkout_status(event, context, branch_id):
    job_id = event['checkout']['job_id']
    app.log.info(f"Checkout status job_id: {job_id}")
    # checkout_output = client.get_bundles_checkout(job_id)
    # return checkout_output['status']


def complete_test(event, context):
    save_results(event, 'SUCCEEDED')


def fallback(event, context, branch_id):
    return {"failed": "failed"}


def save_results(event, result: str):
    table = dynamodb.Table('scalability_test')
    start_time = None

    expiration_ttl = int(time.time()) + 14 * 24 * 60 * 60  # 14 days

    fail_count = 0
    success_count = 0
    run_id = None
    execution_id = ''
    for branch_event in event:
        if branch_event.get('failed'):
            fail_count += 1
        else:
            success_count += 1
            if run_id is None:
                run_id = branch_event["test_run_id"]
                execution_id = branch_event["execution_id"]
                start_time = branch_event['bundle']['start_time']

    table.put_item(
        Item={
            'run_id': run_id,
            'execution_id': execution_id,
            'duration': current_time() - start_time - WAIT_CHECKOUT * 1000,
            'success_count': success_count,
            'fail_count': fail_count,
            'created_on': datetime.datetime.now().isoformat(),
            'expiration_ttl': expiration_ttl
        }
    )


@app.sns_topic_subscriber("dss-scalability-test-run-" + os.environ["DSS_DEPLOYMENT_STAGE"])
def launch_test_run(event, context):
    print('Log test run')
    msg = json.loads(event["Records"][0]["Sns"]["Message"])
    table = dynamodb.Table('scalability_test_run')
    table.put_item(
        Item={
            'run_id': msg["run_id"],
            'executions': 0,
            'succeeded_count': 0,
            'failed_count': 0,
            'average_duration': 0,
            'created_on': datetime.datetime.now().isoformat()
        }
    )


@app.sns_topic_subscriber("dss-scalability-test-" + os.environ["DSS_DEPLOYMENT_STAGE"])
def launch_exec(event, context):
    msg = json.loads(event["Records"][0]["Sns"]["Message"])
    run_id = msg["run_id"]
    execution_id = msg["execution_id"]
    nextBatch = roundTime()
    test_input = {
        "execution_id": execution_id,
        "test_run_id": run_id,
        "batch": nextBatch.isoformat() + 'Z'
    }
    stepfunctions.step_functions_invoke("dss-scalability-test-{stage}", execution_id, test_input)


@app.dynamodb_stream_handler(table_name="scalability_test", batch_size=5)
def handle_dynamodb_stream(event, context):
    success_count = 0
    failure_count = 0
    records = 0
    duration_sum = 0
    run_id = None
    for record in event['Records']:
        if record['eventName'] == 'INSERT':
            run_id = record['dynamodb']['NewImage']['run_id']['S']
            success_count_rec = int(record['dynamodb']['NewImage']['success_count']['N'])
            fail_count_rec = int(record['dynamodb']['NewImage']['fail_count']['N'])

            duration = record['dynamodb']['NewImage']['duration']['N']
            duration_sum += Decimal(duration)
            records += 1
            success_count += success_count_rec
            failure_count += fail_count_rec
    print(f"success_count_rec: {success_count}")
    if records > 0:
        table = dynamodb.Table('scalability_test_run')
        run_entry_pk = {'run_id': run_id}
        run_entry = table.get_item(Key=run_entry_pk)
        if run_entry.get('Item'):
            old_avg_duration = run_entry['Item']['average_duration']
            old_count = run_entry['Item']['succeeded_count'] + run_entry['Item']['failed_count']

            table.update_item(
                Key=run_entry_pk,
                UpdateExpression='SET '
                                 'succeeded_count = succeeded_count + :success_count, '
                                 'failed_count = failed_count + :failure_count, '
                                 'executions = executions + :records, '
                                 'average_duration = :new_average',
                ExpressionAttributeValues={
                    ':success_count': success_count,
                    ':failure_count': failure_count,
                    ':records': records,
                    ':new_average': old_avg_duration + (duration_sum / records - old_avg_duration) /
                                                       (old_count + records)
                }
            )
        else:
            print('No run entries found')
    else:
        print('No INSERT records to process')

    return 'Successfully processed {} records.'.format(len(event['Records']))


def roundTime(to=datetime.timedelta(minutes=5)):
    roundTo = to.total_seconds()
    now = datetime.datetime.now()
    seconds = (now - now.min).seconds
    rounding = (seconds + roundTo / 2) // roundTo * roundTo
    return now + datetime.timedelta(0, rounding - seconds, -now.microsecond)


exec_branch_def = {
    "StartAt": "UploadBundle{t}",
    "States": {

        "UploadBundle{t}": {
            "Type": "Task",
            "Resource": upload_bundle,
            "InputPath": "$",
            "ResultPath": "$.bundle",
            "OutputPath": "$",
            "Next": "DownloadBundle{t}",
            "Catch": [{
                "ErrorEquals": ["States.TaskFailed"],
                "Next": "fallback{t}"
            }]
        },
        "DownloadBundle{t}": {
            "Type": "Task",
            "Resource": download_bundle,
            "InputPath": "$",
            "OutputPath": "$",
            "ResultPath": "$.download",
            "Next": "CheckoutBundle{t}",
            "Catch": [{
                "ErrorEquals": ["States.TaskFailed"],
                "Next": "fallback{t}"
            }]
        },
        "CheckoutBundle{t}": {
            "Type": "Task",
            "Resource": checkout_bundle,
            "InputPath": "$",
            "ResultPath": "$.checkout",
            "OutputPath": "$",
            "Next": "Wait_Checkout{t}",
            "Catch": [{
                "ErrorEquals": ["States.TaskFailed"],
                "Next": "fallback{t}"
            }]
        },
        "Wait_Checkout{t}": {
            "Type": "Wait",
            "Seconds": WAIT_CHECKOUT,
            "Next": "CheckoutDownloadStatus{t}"
        },
        "CheckoutDownloadStatus{t}": {
            "Type": "Task",
            "Resource": checkout_status,
            "InputPath": "$",
            "ResultPath": "$.checkout.status",
            "OutputPath": "$",
            "End": True,
            "Catch": [{
                "ErrorEquals": ["States.TaskFailed"],
                "Next": "fallback{t}"
            }]
        },
        "fallback{t}": {
            "Type": "Task",
            "Resource": fallback,
            "InputPath": "$",
            "ResultPath": "$.status",
            "OutputPath": "$",
            "End": True,
        }
    }
}

state_machine_def = {
    "Comment": "DSS scalability test state machine.",
    "StartAt": "WaitUntil",
    "TimeoutSeconds": 3600,
    "States": {
        "WaitUntil": {
            "Type": "Wait",
            "TimestampPath": "$.batch",
            "Next": "Executors"
        },

        "Executors": {
            "Type": "Parallel",
            "Branches": generator.ThreadPoolAnnotation(exec_branch_def, PARALLELIZATION_FACTOR, "{t}"),
            "Next": "CompleteTest",
        },

        "CompleteTest": {
            "Type": "Task",
            "Resource": complete_test,
            "End": True,
        }
    }
}

annotation_processor = generator.StateMachineAnnotationProcessor()
sfn = annotation_processor.process_annotations(state_machine_def)
app.register_state_machine(sfn)
