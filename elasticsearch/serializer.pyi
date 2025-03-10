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

from typing import Any, Dict, Optional

class Serializer:
    mimetype: str
    def loads(self, s: str) -> Any: ...
    def dumps(self, data: Any) -> str: ...

class TextSerializer(Serializer):
    mimetype: str
    def loads(self, s: str) -> Any: ...
    def dumps(self, data: Any) -> str: ...

class JSONSerializer(Serializer):
    mimetype: str
    def default(self, data: Any) -> Any: ...
    def loads(self, s: str) -> Any: ...
    def dumps(self, data: Any) -> str: ...

class MapboxVectorTileSerializer(Serializer):
    mimetype: str
    def loads(self, s: bytes) -> bytes: ...  # type: ignore
    def dumps(self, data: bytes) -> bytes: ...  # type: ignore

DEFAULT_SERIALIZERS: Dict[str, Serializer]

class Deserializer:
    def __init__(
        self,
        serializers: Dict[str, Serializer],
        default_mimetype: str = ...,
    ) -> None: ...
    def loads(self, s: str, mimetype: Optional[str] = ...) -> Any: ...
