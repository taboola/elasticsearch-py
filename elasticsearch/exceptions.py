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

__all__ = [
    "ImproperlyConfigured",
    "ElasticsearchException",
    "SerializationError",
    "TransportError",
    "NotFoundError",
    "ConflictError",
    "RequestError",
    "ConnectionError",
    "SSLError",
    "ConnectionTimeout",
    "AuthenticationException",
    "AuthorizationException",
]


class ImproperlyConfigured(Exception):
    """
    Exception raised when the config passed to the client is inconsistent or invalid.
    """


class ElasticsearchException(Exception):
    """
    Base class for all exceptions raised by this package's operations (doesn't
    apply to :class:`~elasticsearch.ImproperlyConfigured`).
    """


class SerializationError(ElasticsearchException):
    """
    Data passed in failed to serialize properly in the ``Serializer`` being
    used.
    """


class UnsupportedProductError(ElasticsearchException):
    """Error which is raised when the client detects
    it's not connected to a supported product.
    """


class TransportError(ElasticsearchException):
    """
    Exception raised when ES returns a non-OK (>=400) HTTP status code. Or when
    an actual connection error happens; in that case the ``status_code`` will
    be set to ``'N/A'``.
    """

    @property
    def status_code(self):
        """
        The HTTP status code of the response that precipitated the error or
        ``'N/A'`` if not applicable.
        """
        return self.args[0]

    @property
    def error(self):
        """A string error message."""
        return self.args[1]

    @property
    def info(self):
        """
        Dict of returned error info from ES, where available, underlying
        exception when not.
        """
        return self.args[2]

    def __str__(self):
        cause = ""
        try:
            if self.info and "error" in self.info:
                if isinstance(self.info["error"], dict):
                    root_cause = self.info["error"]["root_cause"][0]
                    cause = ", ".join(
                        filter(
                            None,
                            [
                                repr(root_cause["reason"]),
                                root_cause.get("resource.id"),
                                root_cause.get("resource.type"),
                            ],
                        )
                    )

                else:
                    cause = repr(self.info["error"])
        except LookupError:
            pass
        msg = ", ".join(filter(None, [str(self.status_code), repr(self.error), cause]))
        return f"{self.__class__.__name__}({msg})"


class ConnectionError(TransportError):
    """
    Error raised when there was an exception while talking to ES. Original
    exception from the underlying :class:`~elasticsearch.Connection`
    implementation is available as ``.info``.
    """

    def __str__(self):
        return "ConnectionError({}) caused by: {}({})".format(
            self.error,
            self.info.__class__.__name__,
            self.info,
        )


class SSLError(ConnectionError):
    """Error raised when encountering SSL errors."""


class ConnectionTimeout(ConnectionError):
    """A network timeout. Doesn't cause a node retry by default."""

    def __str__(self):
        return "ConnectionTimeout caused by - {}({})".format(
            self.info.__class__.__name__,
            self.info,
        )


class NotFoundError(TransportError):
    """Exception representing a 404 status code."""


class ConflictError(TransportError):
    """Exception representing a 409 status code."""


class RequestError(TransportError):
    """Exception representing a 400 status code."""


class AuthenticationException(TransportError):
    """Exception representing a 401 status code."""


class AuthorizationException(TransportError):
    """Exception representing a 403 status code."""


class ElasticsearchWarning(Warning):
    """Warning that is raised when a deprecated option
    or incorrect usage is flagged via the 'Warning' HTTP header.
    """


# Alias of 'ElasticsearchWarning' for backwards compatibility.
# Additional functionality was added to the 'Warning' HTTP header
# not related to deprecations.
ElasticsearchDeprecationWarning = ElasticsearchWarning


# more generic mappings from status_code to python exceptions
HTTP_EXCEPTIONS = {
    400: RequestError,
    401: AuthenticationException,
    403: AuthorizationException,
    404: NotFoundError,
    409: ConflictError,
}
