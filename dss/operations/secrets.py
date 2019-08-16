"""
Get/set secret variable values from the AWS Secrets Manager
"""
import os
import sys
import select
import typing
import argparse
import json
import logging

from dss.operations import dispatch
from dss.util.aws.clients import secretsmanager  # type: ignore
from dss.operations.util import get_store_prefix


logger = logging.getLogger(__name__)


secrets = dispatch.target("secrets", arguments={}, help=__doc__)


@secrets.action(
    "list",
    arguments={
        "--stage": dict(
            required=False, help="the stage for which secrets should be listed"
        ),
        "--json": dict(
            default=False,
            action="store_true",
            help="format the output as JSON if this flag is present",
        ),
    },
)
def list_secrets(argv: typing.List[str], args: argparse.Namespace):
    """
    Print a list of names of every secret variable in the secrets manager
    for the given store and stage.
    """
    store_prefix = get_store_prefix(args)

    paginator = secretsmanager.get_paginator("list_secrets")

    secret_names = []
    for response in paginator.paginate():
        for secret in response["SecretList"]:

            # Get resource IDs
            secret_name = secret["Name"]

            # Only save secrets for this store and stage
            if secret_name.startswith(store_prefix):
                secret_names.append(secret_name)

    secret_names.sort()

    if args.json:
        print(json.dumps(secret_names))
    else:
        for secret_name in secret_names:
            print(secret_name)


@secrets.action(
    "get",
    arguments={
        "--stage": dict(
            required=False, help="the stage for which secrets should be listed"
        ),
        "--secret-name": dict(
            required=True,
            nargs="*",
            help="name of secret or secrets to retrieve (list values can be separated by a space)",
        ),
        "--json": dict(
            default=False,
            action="store_true",
            help="format the output as JSON if this flag is present",
        ),
    },
)
def get_secret(argv: typing.List[str], args: argparse.Namespace):
    """
    Get the value of the secret variable (or list of variables) specified by
    the --secret-name flag
    """
    # Note: this function should not print anything except the final JSON,
    # in case the user pipes the JSON output of this script to something else

    store_prefix = get_store_prefix(args)

    # Make sure a secret name was specified
    if args.secret_name is None or len(args.secret_name) == 0:
        raise RuntimeError(
            "Unable to set secret: no secret name was specified! Use the --secret-name flag."
        )
    secret_names = args.secret_name

    # Tack on the store prefix if it isn't there already
    for i in range(len(secret_names)):
        secret_name = secret_names[i]
        if not secret_name.startswith(store_prefix):
            secret_names[i] = store_prefix + secret_name

    for secret_name in secret_names:
        # Attempt to obtain secret
        try:
            response = secretsmanager.get_secret_value(SecretId=secret_name)
            secret_val = response["SecretString"]
        except secretsmanager.exceptions.ResourceNotFoundException:
            # A secret variable with that name does not exist
            logger.warning(f"Resource not found: {secret_name}")
        else:
            # Get operation was successful, secret variable exists
            if args.json:
                print(json.dumps({secret_name: secret_val}))
            else:
                print(f"{secret_name}={secret_val}")


@secrets.action(
    "set",
    arguments={
        "--stage": dict(
            required=False, help="the stage for which secrets should be set"
        ),
        "--secret-name": dict(
            required=True, help="name of secret to set (limit 1 at a time)"
        ),
        "--dry-run": dict(
            default=False,
            action="store_true",
            help="do a dry run of the actual operation",
        ),
    },
)
def set_secret(argv: typing.List[str], args: argparse.Namespace):
    """Set the value of the secret variable specified by the --secret-name flag"""
    store_prefix = get_store_prefix(args)

    # Make sure a secret name was specified
    if args.secret_name is None or len(args.secret_name) == 0:
        raise RuntimeError(
            "Unable to set secret: no secret name was specified! Use the --secret-name flag."
        )
    secret_name = args.secret_name

    # Tack on the store prefix if it isn't there already
    if not secret_name.startswith(store_prefix):
        secret_name = store_prefix + secret_name

    # Use stdin (input piped to this script) as secret value.
    # stdin provides secret value, flag --secret-name provides secret name.
    if not select.select([sys.stdin], [], [], 0.0)[0]:
        err_msg = f"No data in stdin, cannot set secret {secret_name} without a value from stdin!"
        raise RuntimeError(err_msg)
    secret_val = sys.stdin.read()

    try:
        # Start by trying to get the secret variable
        secretsmanager.get_secret_value(SecretId=secret_name)

    except secretsmanager.exceptions.ResourceNotFoundException:
        # A secret variable with that name does not exist, so create it
        if args.dry_run:
            # Create it for fakes
            print(
                f"Secret variable {secret_name} not found in secrets manager, dry-run creating it"
            )
        else:
            # Create it for real
            print(
                f"Secret variable {secret_name} not found in secrets manager, creating it"
            )
            secretsmanager.create_secret(Name=secret_name, SecretString=secret_val)
    else:
        # Get operation was successful, secret variable exists
        if args.dry_run:
            # Update it for fakes
            print(
                f"Secret variable {secret_name} found in secrets manager, dry-run updating it"
            )
        else:
            # Update it for real
            print(
                f"Secret variable {secret_name} found in secrets manager, updating it"
            )
            secretsmanager.update_secret(SecretId=secret_name, SecretString=secret_val)


@secrets.action(
    "delete",
    arguments={
        "--stage": dict(
            required=False, help="the stage for which secrets should be deleted"
        ),
        "--secret-name": dict(
            required=True, help="name of secret to delete (limit 1 at a time)"
        ),
        "--force": dict(
            default=False,
            action="store_true",
            help="force the delete operation to happen non-interactively (no user prompt)",
        ),
        "--dry-run": dict(
            default=False,
            action="store_true",
            help="do a dry run of the actual operation",
        ),
    },
)
def del_secret(argv: typing.List[str], args: argparse.Namespace):
    """
    Delete the value of the secret variable specified by the
    --secret-name flag from the secrets manager
    """
    store_prefix = get_store_prefix(args)

    # Make sure a secret name was specified
    if args.secret_name is None or len(args.secret_name) == 0:
        raise RuntimeError(
            "Unable to set secret: no secret name was specified! Use the --secret-name flag."
        )
    secret_name = args.secret_name

    # Tack on the store prefix if it isn't there already
    if not secret_name.startswith(store_prefix):
        secret_name = store_prefix + secret_name

    if args.force is False:
        # Make sure the user really wants to do this
        confirm = f"""
        Are you really sure you want to delete secret {secret_name}? (Type 'y' or 'yes' to confirm):
        """
        response = input(confirm)
        if response.lower() not in ["y", "yes"]:
            raise RuntimeError("You safely aborted the delete secret operation!")

    try:
        # Start by trying to get the secret variable
        secretsmanager.get_secret_value(SecretId=secret_name)

    except secretsmanager.exceptions.ResourceNotFoundException:
        # No secret var found
        logger.warning(f"Secret variable {secret_name} not found in secrets manager!")

    except secretsmanager.exceptions.InvalidRequestException:
        # Already deleted secret var
        logger.warning(
            f"Secret variable {secret_name} already marked for deletion in secrets manager!"
        )

    else:
        # Get operation was successful, secret variable exists
        if args.dry_run:
            # Delete it for fakes
            print(
                f"Secret variable {secret_name} found in secrets manager, dry-run deleting it"
            )
        else:
            # Delete it for real
            print(
                f"Secret variable {secret_name} found in secrets manager, deleting it"
            )
            secretsmanager.delete_secret(SecretId=secret_name)
