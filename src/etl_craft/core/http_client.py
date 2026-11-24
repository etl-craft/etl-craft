"""HTTP requests never forward credentials to a redirect target."""

from functools import partial
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    """Refuse all redirect hops so a bearer credential never changes origin."""

    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        """Leave a redirect as a refusal for the caller to report."""
        return None


class _ResponseConnection(HTTPConnection):
    read_timeout: float | None

    def getresponse(self) -> HTTPResponse:
        """Switch deadlines after sending the request, before reading headers or the body."""
        if self.sock is not None:
            self.sock.settimeout(self.read_timeout)
        return super().getresponse()


class _SecureResponseConnection(_ResponseConnection, HTTPSConnection):
    """Apply the same response deadline after HTTPS negotiation and request transmission."""


class _ResponseTimeoutHandler(HTTPHandler, HTTPSHandler):
    def __init__(self, read_timeout: float | None) -> None:
        super().__init__()
        self.read_timeout = read_timeout

    def _connection(
        self, connection: type[_ResponseConnection], host: str, *, timeout: float
    ) -> _ResponseConnection:
        result = connection(host, timeout=timeout)
        result.read_timeout = self.read_timeout
        return result

    def http_open(self, request: Request) -> HTTPResponse:
        response: HTTPResponse = self.do_open(
            partial(self._connection, _ResponseConnection), request
        )
        return response

    def https_open(self, request: Request) -> HTTPResponse:
        response: HTTPResponse = self.do_open(
            partial(self._connection, _SecureResponseConnection), request
        )
        return response


def open_request(
    request: Request, timeout: float | tuple[float, float | None] | None
) -> HTTPResponse:
    """Send without redirects, with one socket timeout or separate send and read timeouts."""
    if isinstance(timeout, tuple):
        timeout, read_timeout = timeout
        opener = build_opener(NoRedirects(), _ResponseTimeoutHandler(read_timeout))
    else:
        opener = build_opener(NoRedirects())
    response: HTTPResponse = opener.open(request, timeout=timeout)
    return response
