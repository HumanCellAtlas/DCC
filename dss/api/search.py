import json
import typing

import requests
from copy import deepcopy
from elasticsearch.exceptions import ElasticsearchException, TransportError
from flask import request, jsonify, make_response

from dss import ESDocType
from .. import Config, Replica, ESIndexType, dss_handler, get_logger, DSSException
from ..util import UrlBuilder
from ..util.es import ElasticsearchClient


class PerPageBounds:
    per_page_max = 500
    per_page_min = 10

    @classmethod
    def check(cls, n):
        """Limits per_page from exceed its min and max value"""
        return max(min(cls.per_page_max, n), cls.per_page_min)


@dss_handler
def post(json_request_body: dict,
         replica: str,
         per_page: int,
         output_format: str,
         _scroll_id: typing.Optional[str] = None) -> dict:
    es_query = json_request_body['es_query']
    per_page = PerPageBounds.check(per_page)

    if replica is None:
        replica = "aws"

    get_logger().debug("Received posted query. Replica: %s Query: %s Per_page: %i Timeout: %s Scroll_id: %s",
                       replica, json.dumps(es_query, indent=4), per_page, _scroll_id)
    # TODO: (tsmith12) determine if a search operation timeout limit is needed
    # TODO: (tsmith12) allow users to retrieve previous search results
    # TODO: (tsmith12) if page returns 0 hits, then all results have been found. delete search id
    try:
        page = _es_search_page(es_query, replica, per_page, _scroll_id, output_format)
        request_dict = _format_request_body(page, es_query, replica, output_format)
        request_body = jsonify(request_dict)

        if len(request_dict['results']) < per_page:
            response = make_response(request_body, requests.codes.ok)
        else:
            response = make_response(request_body, requests.codes.partial)
            next_url = _build_scroll_url(page['_scroll_id'], per_page, replica, output_format)
            response.headers['Link'] = _build_link_header({next_url: {"rel": "next"}})
        return response
    except TransportError as ex:
        if ex.status_code == requests.codes.bad_request:
            get_logger().debug("%s", f"Invalid Query Recieved. Exception: {ex}")
            raise DSSException(requests.codes.bad_request,
                               "elasticsearch_bad_request",
                               f"Invalid Elasticsearch query was received: {str(ex)}")
        elif ex.status_code == requests.codes.not_found:
            get_logger().debug("%s", f"Search Context Error. Exception: {ex}")
            raise DSSException(requests.codes.not_found,
                               "elasticsearch_context_not_found",
                               "Elasticsearch context has returned all results or timeout has expired.")
        elif ex.status_code == 'N/A':
            get_logger().error("%s", f"Elasticsearch Invalid Endpoint. Exception: {ex}")
            raise DSSException(requests.codes.service_unavailable,
                               "service_unavailable",
                               "Elasticsearch reached an invalid endpoint. Try again later.")
        else:
            get_logger().error("%s", f"Elasticsearch Internal Server Error. Exception: {ex}")
            raise DSSException(requests.codes.internal_server_error,
                               "internal_server_error",
                               "Elasticsearch Internal Server Error")

    except ElasticsearchException as ex:
        get_logger().error("%s", f"Elasticsearch Internal Server Error. Exception: {ex}")
        raise DSSException(requests.codes.internal_server_error,
                           "internal_server_error",
                           "Elasticsearch Internal Server Error")


def _es_search_page(es_query: dict,
                    replica: str,
                    per_page: int,
                    _scroll_id: typing.Optional[str],
                    output_format: str) -> dict:
    es_query = deepcopy(es_query)
    es_client = ElasticsearchClient.get(get_logger())

    # Do not return the raw indexed data unless it is requested
    if output_format != 'raw':
        es_query['_source'] = False

    # The time for a scroll search context to stay open per page. A page of results must be retreived before this
    # timeout expires. Subsequent calls to search will refresh the scroll timeout. For more details on time format see:
    # https://www.elastic.co/guide/en/elasticsearch/reference/current/common-options.html#time-units
    scroll = '2m'  # set a timeout of 2min to keep the search context alive. This is reset

    # From: https://www.elastic.co/guide/en/elasticsearch/reference/current/search-request-scroll.html
    # Scroll requests have optimizations that make them faster when the sort order is _doc. If you want to iterate over
    # all documents regardless of the order, this is the most efficient option:
    # {
    #   "sort": [
    #     "_doc"
    #   ]
    # }
    sort = {"sort": ["_doc"]}
    if _scroll_id is None:
        page = es_client.search(index=Config.get_es_alias_name(ESIndexType.docs, Replica[replica]),
                                doc_type=ESDocType.doc.name,
                                scroll=scroll,
                                size=per_page,
                                body=es_query,
                                sort=sort
                                )
        get_logger().debug("Created ES scroll instance")
    else:
        page = es_client.scroll(scroll_id=_scroll_id, scroll=scroll)
        get_logger().debug(f"Retrieved ES results from scroll instance Scroll_id: {_scroll_id}")
    return page


def _format_request_body(page: dict, es_query: dict, replica: str, output_format: str) -> dict:
    result_list = []  # type: typing.List[dict]
    for hit in page['hits']['hits']:
        result = {
            'bundle_fqid': hit['_id'],
            'bundle_url': _build_bundle_url(hit, replica),
            'search_score': hit['_score']
        }
        if output_format == 'raw':
            result['metadata'] = hit['_source']
        result_list.append(result)

    return {
        'es_query': es_query,
        'results': result_list,
        'total_hits': page['hits']['total']
    }


def _build_bundle_url(hit: dict, replica: str) -> str:
    uuid, version = hit['_id'].split('.', 1)
    return request.host_url + str(UrlBuilder()
                                  .set(path='v1/bundles/' + uuid)
                                  .add_query("version", version)
                                  .add_query("replica", replica)
                                  )


def _build_scroll_url(_scroll_id: str, per_page: int, replica: str, output_format: str) -> str:
    return request.host_url + str(UrlBuilder()
                                  .set(path="v1/search")
                                  .add_query('per_page', str(per_page))
                                  .add_query("replica", replica)
                                  .add_query("_scroll_id", _scroll_id)
                                  .add_query("output_format", output_format)
                                  )


def _build_link_header(links):
    """
    Builds a Link header according to RFC 5988.
    The format is a dict where the keys are the URI with the value being
    a dict of link parameters:
        {
            '/page=3': {
                'rel': 'next',
            },
            '/page=1': {
                'rel': 'prev',
            },
            ...
        }
    See https://tools.ietf.org/html/rfc5988#section-6.2.2 for registered
    link relation types.
    """
    _links = []
    for uri, params in links.items():
        link = [f"<{uri}>"]
        for key, value in params.items():
            link.append(f'{key}="{str(value)}"')
        _links.append('; '.join(link))
    return ', '.join(_links)
