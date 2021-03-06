import json
import random
import string

from dss.util.json_gen.hca_generator import HCAJsonGenerator


def id_generator(size=30, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


schema_urls = [
    "https://schema.humancellatlas.org/bundle/5.1.0/project",
    "https://schema.humancellatlas.org/bundle/5.1.0/submission",
    "https://schema.humancellatlas.org/bundle/5.1.0/ingest_audit",
]

json_faker = None

def generate_sample() -> str:
    global json_faker
    if json_faker is None:
        json_faker = HCAJsonGenerator(schema_urls)
    return json_faker.generate()
