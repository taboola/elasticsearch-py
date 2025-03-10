#  Licensed to Elasticsearch B.V. under one or more contributor
#  license agreements. See the NOTICE file distributed with
#  this work for additional information regarding copyright
#  ownership. Elasticsearch B.V. licenses this file to you under
#  the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
# 	http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing,
#  software distributed under the License is distributed on an
#  "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
#  KIND, either express or implied.  See the License for the
#  specific language governing permissions and limitations
#  under the License.

import io
import logging
import re

import pytest

from elasticsearch import (
    Elasticsearch,
    RequestError,
    RequestsHttpConnection,
    Urllib3HttpConnection,
)


@pytest.fixture(scope="function")
def mvt_setup(sync_client):
    sync_client.indices.create(
        index="museums",
        body={
            "mappings": {
                "properties": {
                    "location": {"type": "geo_point"},
                    "name": {"type": "keyword"},
                    "price": {"type": "long"},
                    "included": {"type": "boolean"},
                }
            }
        },
    )
    sync_client.bulk(
        index="museums",
        body=[
            {"index": {"_id": "1"}},
            {
                "location": "52.374081,4.912350",
                "name": "NEMO Science Museum",
                "price": 1750,
                "included": True,
            },
            {"index": {"_id": "2"}},
            {
                "location": "52.369219,4.901618",
                "name": "Museum Het Rembrandthuis",
                "price": 1500,
                "included": False,
            },
            {"index": {"_id": "3"}},
            {
                "location": "52.371667,4.914722",
                "name": "Nederlands Scheepvaartmuseum",
                "price": 1650,
                "included": True,
            },
            {"index": {"_id": "4"}},
            {
                "location": "52.371667,4.914722",
                "name": "Amsterdam Centre for Architecture",
                "price": 0,
                "included": True,
            },
        ],
        refresh=True,
    )


@pytest.mark.parametrize(
    "connection_class", [Urllib3HttpConnection, RequestsHttpConnection]
)
def test_mapbox_vector_tile_logging(
    elasticsearch_url, mvt_setup, connection_class, ca_certs
):
    client = Elasticsearch(
        elasticsearch_url, connection_class=connection_class, ca_certs=ca_certs
    )

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("elasticsearch")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    try:
        client.search_mvt(
            index="museums",
            zoom=13,
            x=4207,
            y=2692,
            field="location",
        )
    finally:
        logger.removeHandler(handler)

    handler.flush()
    logs = output.getvalue()
    assert re.search(
        r"^POST https?://[^/]+/museums/_mvt/location/13/4207/2692 \[status:200 request:0\.[0-9]{3}s\]\n"
        r"> None\n"
        r"< b'.+'$",
        logs,
        flags=re.DOTALL,
    )

    output = io.StringIO()
    handler = logging.StreamHandler(output)
    logger = logging.getLogger("elasticsearch")
    logger.addHandler(handler)

    # Errors should still be JSON
    try:
        with pytest.raises(RequestError) as e:
            client.search_mvt(
                index="museums",
                zoom=-100,
                x=4207,
                y=2692,
                field="location",
            )
    finally:
        logger.removeHandler(handler)

    assert str(e.value) == (
        "RequestError(400, 'illegal_argument_exception', "
        "'Invalid geotile_grid precision of -100. Must be between 0 and 29.')"
    )
    assert e.value.status_code == 400

    handler.flush()
    logs = output.getvalue()
    assert re.search(
        r"^POST https?://[^/]+/museums/_mvt/location/-100/4207/2692 \[status:400 request:0\.[0-9]{3}s\]\n",
        logs,
        flags=re.DOTALL,
    )

    # The JSON error body is still logged properly.
    assert logs.endswith(
        '> None\n< {"error":{"root_cause":[{"type":"illegal_argument_exception","reason":"Invalid '
        'geotile_grid precision of -100. Must be between 0 and 29."}],"type":"illegal_argument_exception",'
        '"reason":"Invalid geotile_grid precision of -100. Must be between 0 and 29."},"status":400}\n'
    )


@pytest.mark.parametrize(
    "connection_class", [Urllib3HttpConnection, RequestsHttpConnection]
)
def test_mapbox_vector_tile_response(
    elasticsearch_url, mvt_setup, connection_class, ca_certs
):
    try:
        import mapbox_vector_tile
    except ImportError:
        return pytest.skip(reason="Requires the 'mapbox-vector-tile' package")

    client = Elasticsearch(
        elasticsearch_url, connection_class=connection_class, ca_certs=ca_certs
    )

    resp = client.search_mvt(
        index="museums",
        zoom=13,
        x=4207,
        y=2692,
        field="location",
        body={
            "grid_precision": 2,
            "fields": ["name", "price"],
            "query": {"term": {"included": True}},
            "aggs": {
                "min_price": {"min": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "avg_price": {"avg": {"field": "price"}},
            },
        },
    )
    assert isinstance(resp, bytes)

    # Decode the binary as MVT
    tile = mapbox_vector_tile.decode(resp)

    # Pop the 'took' value as it's variable on execution time.
    assert isinstance(tile["meta"]["features"][0]["properties"].pop("took"), int)

    assert tile == {
        "hits": {
            "extent": 4096,
            "version": 2,
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [3208, 3864]},
                    "properties": {
                        "_id": "1",
                        "name": "NEMO Science Museum",
                        "price": 1750,
                    },
                    "id": 0,
                    "type": 1,
                },
                {
                    "geometry": {"type": "Point", "coordinates": [3429, 3496]},
                    "properties": {
                        "_id": "3",
                        "name": "Nederlands Scheepvaartmuseum",
                        "price": 1650,
                    },
                    "id": 0,
                    "type": 1,
                },
                {
                    "geometry": {"type": "Point", "coordinates": [3429, 3496]},
                    "properties": {
                        "_id": "4",
                        "name": "Amsterdam Centre for Architecture",
                        "price": 0,
                    },
                    "id": 0,
                    "type": 1,
                },
            ],
        },
        "aggs": {
            "extent": 4096,
            "version": 2,
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [3072, 3072],
                                [4096, 3072],
                                [4096, 4096],
                                [3072, 4096],
                                [3072, 3072],
                            ]
                        ],
                    },
                    "properties": {
                        "_count": 3,
                        "max_price.value": 1750.0,
                        "min_price.value": 0.0,
                        "avg_price.value": 1133.3333333333333,
                    },
                    "id": 0,
                    "type": 3,
                }
            ],
        },
        "meta": {
            "extent": 4096,
            "version": 2,
            "features": [
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[0, 0], [4096, 0], [4096, 4096], [0, 4096], [0, 0]]
                        ],
                    },
                    "properties": {
                        "_shards.failed": 0,
                        "_shards.skipped": 0,
                        "_shards.successful": 1,
                        "_shards.total": 1,
                        "aggregations._count.avg": 3.0,
                        "aggregations._count.count": 1,
                        "aggregations._count.max": 3.0,
                        "aggregations._count.min": 3.0,
                        "aggregations._count.sum": 3.0,
                        "aggregations.avg_price.avg": 1133.3333333333333,
                        "aggregations.avg_price.count": 1,
                        "aggregations.avg_price.max": 1133.3333333333333,
                        "aggregations.avg_price.min": 1133.3333333333333,
                        "aggregations.avg_price.sum": 1133.3333333333333,
                        "aggregations.max_price.avg": 1750.0,
                        "aggregations.max_price.count": 1,
                        "aggregations.max_price.max": 1750.0,
                        "aggregations.max_price.min": 1750.0,
                        "aggregations.max_price.sum": 1750.0,
                        "aggregations.min_price.avg": 0.0,
                        "aggregations.min_price.count": 1,
                        "aggregations.min_price.max": 0.0,
                        "aggregations.min_price.min": 0.0,
                        "aggregations.min_price.sum": 0.0,
                        "hits.total.relation": "eq",
                        "hits.total.value": 3,
                        "timed_out": False,
                    },
                    "id": 0,
                    "type": 3,
                }
            ],
        },
    }
