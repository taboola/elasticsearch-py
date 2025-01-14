# -*- coding: utf-8 -*-
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

from __future__ import unicode_literals

import json
import re
import time

import pytest
from mock import patch

from elasticsearch.connection import Connection
from elasticsearch.connection_pool import DummyConnectionPool
from elasticsearch.exceptions import (
    ConnectionError,
    NotFoundError,
    TransportError,
    UnsupportedProductError,
)
from elasticsearch.transport import Transport, get_host_info


class DummyConnection(Connection):
    def __init__(self, **kwargs):
        self.exception = kwargs.pop("exception", None)
        self.status, self.data = kwargs.pop("status", 200), kwargs.pop("data", "{}")
        self.headers = kwargs.pop("headers", {"X-elastic-product": "Elasticsearch"})
        self.calls = []
        super(DummyConnection, self).__init__(**kwargs)

    def perform_request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.exception:
            raise self.exception
        return self.status, self.headers, self.data


CLUSTER_NODES = """{
  "_nodes" : {
    "total" : 1,
    "successful" : 1,
    "failed" : 0
  },
  "cluster_name" : "elasticsearch",
  "nodes" : {
    "SRZpKFZdQguhhvifmN6UVA" : {
      "name" : "SRZpKFZ",
      "transport_address" : "127.0.0.1:9300",
      "host" : "127.0.0.1",
      "ip" : "127.0.0.1",
      "version" : "5.0.0",
      "build_hash" : "253032b",
      "roles" : [ "master", "data", "ingest" ],
      "http" : {
        "bound_address" : [ "[fe80::1]:9200", "[::1]:9200", "127.0.0.1:9200" ],
        "publish_address" : "1.1.1.1:123",
        "max_content_length_in_bytes" : 104857600
      }
    }
  }
}"""

CLUSTER_NODES_7x_PUBLISH_HOST = """{
  "_nodes" : {
    "total" : 1,
    "successful" : 1,
    "failed" : 0
  },
  "cluster_name" : "elasticsearch",
  "nodes" : {
    "SRZpKFZdQguhhvifmN6UVA" : {
      "name" : "SRZpKFZ",
      "transport_address" : "127.0.0.1:9300",
      "host" : "127.0.0.1",
      "ip" : "127.0.0.1",
      "version" : "5.0.0",
      "build_hash" : "253032b",
      "roles" : [ "master", "data", "ingest" ],
      "http" : {
        "bound_address" : [ "[fe80::1]:9200", "[::1]:9200", "127.0.0.1:9200" ],
        "publish_address" : "somehost.tld/1.1.1.1:123",
        "max_content_length_in_bytes" : 104857600
      }
    }
  }
}"""


class TestHostsInfoCallback:
    def test_master_only_nodes_are_ignored(self):
        nodes = [
            {"roles": ["master"]},
            {"roles": ["master", "data", "ingest"]},
            {"roles": ["data", "ingest"]},
            {"roles": []},
            {},
        ]
        chosen = [
            i
            for i, node_info in enumerate(nodes)
            if get_host_info(node_info, i) is not None
        ]
        assert [1, 2, 3, 4] == chosen


class TestTransport:
    def test_single_connection_uses_dummy_connection_pool(self):
        t = Transport([{}])
        assert isinstance(t.connection_pool, DummyConnectionPool)
        t = Transport([{"host": "localhost"}])
        assert isinstance(t.connection_pool, DummyConnectionPool)

    def test_request_timeout_extracted_from_params_and_passed(self):
        t = Transport([{}], meta_header=False, connection_class=DummyConnection)

        t.perform_request("GET", "/", params={"request_timeout": 42})
        assert 1 == len(t.get_connection().calls)
        assert ("GET", "/", {}, None) == t.get_connection().calls[0][0]
        assert {
            "timeout": 42,
            "ignore": (),
            "headers": None,
        } == t.get_connection().calls[0][1]

    def test_opaque_id(self):
        t = Transport(
            [{}], opaque_id="app-1", meta_header=False, connection_class=DummyConnection
        )

        t.perform_request("GET", "/")
        assert 1 == len(t.get_connection().calls)
        assert ("GET", "/", None, None) == t.get_connection().calls[0][0]
        assert {
            "timeout": None,
            "ignore": (),
            "headers": None,
        } == t.get_connection().calls[0][1]

        # Now try with an 'x-opaque-id' set on perform_request().
        t.perform_request("GET", "/", headers={"x-opaque-id": "request-1"})
        assert 2 == len(t.get_connection().calls)
        assert ("GET", "/", None, None) == t.get_connection().calls[1][0]
        assert {
            "timeout": None,
            "ignore": (),
            "headers": {"x-opaque-id": "request-1"},
        } == t.get_connection().calls[1][1]

    def test_request_with_custom_user_agent_header(self):
        t = Transport([{}], meta_header=False, connection_class=DummyConnection)

        t.perform_request("GET", "/", headers={"user-agent": "my-custom-value/1.2.3"})
        assert 1 == len(t.get_connection().calls)
        assert {
            "timeout": None,
            "ignore": (),
            "headers": {"user-agent": "my-custom-value/1.2.3"},
        } == t.get_connection().calls[0][1]

    def test_send_get_body_as_source(self):
        t = Transport([{}], send_get_body_as="source", connection_class=DummyConnection)

        t.perform_request("GET", "/", body={})
        assert 1 == len(t.get_connection().calls)
        assert ("GET", "/", {"source": "{}"}, None) == t.get_connection().calls[0][0]

    def test_send_get_body_as_post(self):
        t = Transport([{}], send_get_body_as="POST", connection_class=DummyConnection)

        t.perform_request("GET", "/", body={})
        assert 1 == len(t.get_connection().calls)
        assert ("POST", "/", None, b"{}") == t.get_connection().calls[0][0]

    def test_client_meta_header(self):
        t = Transport([{}], connection_class=DummyConnection)

        t.perform_request("GET", "/", body={})
        assert 1 == len(t.get_connection().calls)
        headers = t.get_connection().calls[0][1]["headers"]
        assert re.search(
            r"^es=[0-9.]+p?,py=[0-9.]+p?,t=[0-9.]+p?$", headers["x-elastic-client-meta"]
        )

        class DummyConnectionWithMeta(DummyConnection):
            HTTP_CLIENT_META = ("dm", "1.2.3")

        t = Transport([{}], connection_class=DummyConnectionWithMeta)

        t.perform_request("GET", "/", body={}, headers={"Custom": "header"})
        assert 1 == len(t.get_connection().calls)
        headers = t.get_connection().calls[0][1]["headers"]
        assert re.search(
            r"^es=[0-9.]+p?,py=[0-9.]+p?,t=[0-9.]+p?,dm=1.2.3$",
            headers["x-elastic-client-meta"],
        )
        assert headers["Custom"] == "header"

    def test_client_meta_header_not_sent(self):
        t = Transport([{}], meta_header=False, connection_class=DummyConnection)

        t.perform_request("GET", "/", body={})
        assert 1 == len(t.get_connection().calls)
        headers = t.get_connection().calls[0][1]["headers"]
        assert headers is None

    def test_meta_header_type_error(self):
        with pytest.raises(TypeError) as e:
            Transport([{}], meta_header=1)
        assert str(e.value) == "meta_header must be of type bool"

    def test_body_gets_encoded_into_bytes(self):
        t = Transport([{}], connection_class=DummyConnection)

        t.perform_request("GET", "/", body="你好")
        assert 1 == len(t.get_connection().calls)
        assert (
            "GET",
            "/",
            None,
            b"\xe4\xbd\xa0\xe5\xa5\xbd",
        ) == t.get_connection().calls[0][0]

    def test_body_bytes_get_passed_untouched(self):
        t = Transport([{}], connection_class=DummyConnection)

        body = b"\xe4\xbd\xa0\xe5\xa5\xbd"
        t.perform_request("GET", "/", body=body)
        assert 1 == len(t.get_connection().calls)
        assert ("GET", "/", None, body) == t.get_connection().calls[0][0]

    def test_body_surrogates_replaced_encoded_into_bytes(self):
        t = Transport([{}], connection_class=DummyConnection)

        t.perform_request("GET", "/", body="你好\uda6a")
        assert 1 == len(t.get_connection().calls)
        assert (
            "GET",
            "/",
            None,
            b"\xe4\xbd\xa0\xe5\xa5\xbd\xed\xa9\xaa",
        ) == t.get_connection().calls[0][0]

    def test_kwargs_passed_on_to_connections(self):
        t = Transport([{"host": "google.com"}], port=123)
        assert 1 == len(t.connection_pool.connections)
        assert "http://google.com:123" == t.connection_pool.connections[0].host

    def test_kwargs_passed_on_to_connection_pool(self):
        dt = object()
        t = Transport([{}, {}], dead_timeout=dt)
        assert dt is t.connection_pool.dead_timeout

    def test_custom_connection_class(self):
        class MyConnection(object):
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        t = Transport([{}], connection_class=MyConnection)
        assert 1 == len(t.connection_pool.connections)
        assert isinstance(t.connection_pool.connections[0], MyConnection)

    def test_add_connection(self):
        t = Transport([{}], randomize_hosts=False)
        t.add_connection({"host": "google.com", "port": 1234})

        assert 2 == len(t.connection_pool.connections)
        assert "http://google.com:1234" == t.connection_pool.connections[1].host

    def test_request_will_fail_after_X_retries(self):
        t = Transport(
            [{"exception": ConnectionError("abandon ship")}],
            connection_class=DummyConnection,
        )

        with pytest.raises(ConnectionError):
            t.perform_request("GET", "/")
        assert 4 == len(t.get_connection().calls)

    def test_failed_connection_will_be_marked_as_dead(self):
        t = Transport(
            [{"exception": ConnectionError("abandon ship")}] * 2,
            connection_class=DummyConnection,
        )

        with pytest.raises(ConnectionError):
            t.perform_request("GET", "/")
        assert 0 == len(t.connection_pool.connections)

    def test_resurrected_connection_will_be_marked_as_live_on_success(self):
        for method in ("GET", "HEAD"):
            t = Transport([{}, {}], connection_class=DummyConnection)
            con1 = t.connection_pool.get_connection()
            con2 = t.connection_pool.get_connection()
            t.connection_pool.mark_dead(con1)
            t.connection_pool.mark_dead(con2)

            t.perform_request(method, "/")
            assert 1 == len(t.connection_pool.connections)
            assert 1 == len(t.connection_pool.dead_count)

    def test_sniff_will_use_seed_connections(self):
        t = Transport([{"data": CLUSTER_NODES}], connection_class=DummyConnection)
        t.set_connections([{"data": "invalid"}])

        t.sniff_hosts()
        assert 1 == len(t.connection_pool.connections)
        assert "http://1.1.1.1:123" == t.get_connection().host

    def test_sniff_on_start_fetches_and_uses_nodes_list(self):
        t = Transport(
            [{"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniff_on_start=True,
        )
        assert 1 == len(t.connection_pool.connections)
        assert "http://1.1.1.1:123" == t.get_connection().host

    def test_sniff_on_start_ignores_sniff_timeout(self):
        t = Transport(
            [{"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniff_on_start=True,
            sniff_timeout=12,
        )
        assert (("GET", "/_nodes/_all/http"), {"timeout": None}) == t.seed_connections[
            0
        ].calls[0]

    def test_sniff_uses_sniff_timeout(self):
        t = Transport(
            [{"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniff_timeout=42,
        )
        t.sniff_hosts()
        assert (("GET", "/_nodes/_all/http"), {"timeout": 42}) == t.seed_connections[
            0
        ].calls[0]

    def test_sniff_reuses_connection_instances_if_possible(self):
        t = Transport(
            [{"data": CLUSTER_NODES}, {"host": "1.1.1.1", "port": 123}],
            connection_class=DummyConnection,
            randomize_hosts=False,
        )
        connection = t.connection_pool.connections[1]

        t.sniff_hosts()
        assert 1 == len(t.connection_pool.connections)
        assert connection is t.get_connection()

    def test_sniff_on_fail_triggers_sniffing_on_fail(self):
        t = Transport(
            [{"exception": ConnectionError("abandon ship")}, {"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniff_on_connection_fail=True,
            max_retries=0,
            randomize_hosts=False,
        )

        with pytest.raises(ConnectionError):
            t.perform_request("GET", "/")
        assert 1 == len(t.connection_pool.connections)
        assert "http://1.1.1.1:123" == t.get_connection().host

    @patch("elasticsearch.transport.Transport.sniff_hosts")
    def test_sniff_on_fail_failing_does_not_prevent_retires(self, sniff_hosts):
        sniff_hosts.side_effect = [TransportError("sniff failed")]
        t = Transport(
            [{"exception": ConnectionError("abandon ship")}, {"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniff_on_connection_fail=True,
            max_retries=3,
            randomize_hosts=False,
        )

        conn_err, conn_data = t.connection_pool.connections
        response = t.perform_request("GET", "/")
        assert json.loads(CLUSTER_NODES) == response
        assert 1 == sniff_hosts.call_count
        assert 1 == len(conn_err.calls)
        assert 1 == len(conn_data.calls)

    def test_sniff_after_n_seconds(self):
        t = Transport(
            [{"data": CLUSTER_NODES}],
            connection_class=DummyConnection,
            sniffer_timeout=5,
        )

        for _ in range(4):
            t.perform_request("GET", "/")
        assert 1 == len(t.connection_pool.connections)
        assert isinstance(t.get_connection(), DummyConnection)
        t.last_sniff = time.time() - 5.1

        t.perform_request("GET", "/")
        assert 1 == len(t.connection_pool.connections)
        assert "http://1.1.1.1:123" == t.get_connection().host
        assert time.time() - 1 < t.last_sniff < time.time() + 0.01

    def test_sniff_7x_publish_host(self):
        # Test the response shaped when a 7.x node has publish_host set
        # and the returend data is shaped in the fqdn/ip:port format.
        t = Transport(
            [{"data": CLUSTER_NODES_7x_PUBLISH_HOST}],
            connection_class=DummyConnection,
            sniff_timeout=42,
        )
        t.sniff_hosts()
        # Ensure we parsed out the fqdn and port from the fqdn/ip:port string.
        assert t.connection_pool.connection_opts[0][1] == {
            "host": "somehost.tld",
            "port": 123,
        }

    @patch("elasticsearch.transport.Transport.sniff_hosts")
    def test_sniffing_disabled_on_cloud_instances(self, sniff_hosts):
        t = Transport(
            [{}],
            sniff_on_start=True,
            sniff_on_connection_fail=True,
            cloud_id="cluster:dXMtZWFzdC0xLmF3cy5mb3VuZC5pbyQ0ZmE4ODIxZTc1NjM0MDMyYmVkMWNmMjIxMTBlMmY5NyQ0ZmE4ODIxZTc1NjM0MDMyYmVkMWNmMjIxMTBlMmY5Ng==",
        )

        assert not t.sniff_on_connection_fail
        assert sniff_hosts.call_args is None  # Assert not called.


@pytest.mark.parametrize("headers", [{}, {"X-elastic-product": "BAD HEADER"}])
def test_unsupported_product_error(headers):
    t = Transport(
        [{"headers": headers}], meta_header=False, connection_class=DummyConnection
    )

    with pytest.raises(UnsupportedProductError) as e:
        t.perform_request("GET", "/")
    assert str(e.value) == (
        "The client noticed that the server is not Elasticsearch "
        "and we do not support this unknown product"
    )

    calls = t.get_connection().calls
    assert len(calls) == 1
    assert calls[0][0] == ("GET", "/", None, None)
    assert calls[0][1] == {"timeout": None, "ignore": (), "headers": None}


@pytest.mark.parametrize(
    "error", [TransportError(500, "", {}), NotFoundError(404, "", {})]
)
def test_transport_error_raised_before_product_error(error):
    t = Transport(
        [{"headers": {"X-elastic-product": "BAD HEADER"}, "exception": error}],
        meta_header=False,
        connection_class=DummyConnection,
    )

    with pytest.raises(TransportError) as e:
        t.perform_request("GET", "/")
    assert e.value.status_code == error.status_code

    calls = t.get_connection().calls
    assert len(calls) == 1
    assert calls[0][0] == ("GET", "/", None, None)
    assert calls[0][1] == {"timeout": None, "ignore": (), "headers": None}
