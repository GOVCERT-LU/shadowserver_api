"""Shadowserver API abstraction library.

API documentation is available at: https://www.shadowserver.org/what-we-do/network-reporting/api-documentation/
"""

import hashlib
import hmac
import json
import logging
import re
import typing

import httpx

from .exceptions import InvalidRequest, InvalidResponse, NoSupportedReportFilter

regex_date = re.compile(r"""^(\d{4}-\d{2}-\d{2}|now)$""")


class ShadowServerAPI:
  def __init__(self, api_url: str, api_key: str, api_secret: str, timeout: int = 45) -> None:
    self.api_url = api_url
    self.api_key = api_key
    self.api_secret_bytes = api_secret.encode()
    self.session = httpx.Client(timeout=timeout)
    self.logger = logging.getLogger(__name__)

  def _generate_hmac(self, request_bytes: bytes) -> str:
    hmac_generator = hmac.new(self.api_secret_bytes, request_bytes, hashlib.sha256)
    return hmac_generator.hexdigest()

  def api_call(self, method: str, request_data: typing.Dict[str, typing.Any]) -> typing.Any:
    """Call the specified api method with a request dictionary."""
    url = f'{self.api_url}{method}'

    self.logger.debug('URL: %s', url)
    self.logger.debug('DATA: %s', json.dumps(request_data, indent=2))

    request_data['apikey'] = self.api_key
    request_bytes = json.dumps(request_data).encode()
    request_hmac = self._generate_hmac(request_bytes)

    response = self.session.post(url, content=request_bytes, headers={'HMAC2': request_hmac})

    if response.status_code != 200:
      try:
        response_json = response.json()
        raise InvalidRequest(response_json['error'])
      except (ValueError, KeyError, json.decoder.JSONDecodeError) as exc:
        if 'No supported report filters found' in response.text:
          raise NoSupportedReportFilter(response.text) from exc

        raise InvalidRequest(response.text) from exc

    try:
      return response.json()
    except ValueError:
      raise InvalidResponse(response.text)

  def api_test_ping(self) -> typing.Dict[str, typing.Any]:
    """Check your connection to the API server."""
    result = self.api_call('test/ping', {})

    if not isinstance(result, dict):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_key_info(self) -> typing.Dict[str, typing.Any]:
    """Returns details about your apikey."""
    result = self.api_call('key/info', {})

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    if len(result) != 1:
      raise ValueError('Invalid return value from api_call')

    return result[0]

  def api_reports_subscribed(self) -> typing.List[str]:
    """List of reports that the user is subscribed to."""
    result = self.api_call('reports/subscribed', {})

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_reports_types(self) -> typing.List[str]:
    """List of all the types of reports that are available for the subscriber."""
    result = self.api_call('reports/types', {})

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_reports_list(
    self,
    reports: typing.Optional[typing.List[str]] = None,
    start_date: typing.Optional[str] = None,
    end_date: typing.Optional[str] = None,
    report_type: typing.Optional[str] = None,
    limit: typing.Optional[int] = None,
  ) -> typing.List[typing.Dict[str, typing.Any]]:
    """List of actual reports that could be downloaded."""
    request_data: typing.Dict[str, typing.Any] = {}

    if reports:
      request_data['reports'] = reports

    if limit:
      request_data['limit'] = limit

    if start_date:
      if not regex_date.match(start_date):
        raise ValueError('Invalid start_date format.')

      if end_date:
        if not regex_date.match(end_date):
          raise ValueError('Invalid end_date format.')

        request_data['date'] = f'{start_date}:{end_date}'
      else:
        request_data['date'] = f'{start_date}'

    if report_type:
      request_data['type'] = report_type

    result = self.api_call('reports/list', request_data)

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_reports_download(
    self, report_id: str, report: typing.Optional[str] = None, limit: typing.Optional[int] = None
  ) -> typing.List[typing.Dict[str, typing.Any]]:
    """Download specific report."""
    request_data = {
      'id': report_id,
    }

    if report:
      request_data['report'] = report

    if limit:
      request_data['limit'] = str(limit)

    result = self.api_call('reports/download', request_data)

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_reports_query(
    self,
    query: typing.Dict[str, str],
    sort: str = 'ascending',
    start_date: typing.Optional[str] = None,
    end_date: typing.Optional[str] = None,
    facet: typing.Optional[str] = None,
    limit: int = 1000,
    pagination: bool = True,
  ) -> typing.Iterator[typing.Dict[str, typing.Any]]:
    """Do a reports query.

    Args:
      query: The query must contain one attribute that matches your organization’s report filters. See https://www.shadowserver.org/what-we-do/network-reporting/api-reports-query/ for details.
      sort: Sort the output. Valid values are "ascending", "descending".
      start_date: Fetch results starting from this date. Format must be (YYYY-MM-DD) or "now".
      end_date: Fetch results up to this date. Format must be (YYYY-MM-DD) or "now".
      facet: Returns the cardinality of each value of the given field sorted from highest to lowest.
      limit: Number of records to pull.
      pagination: If set to True, automatically pulls all results using pagination.
    """
    if sort not in ('ascending', 'descending'):
      raise ValueError('"sort" parameter must be one of: "ascending", "descending"')

    request_data = {
      'query': query,
      'sort': sort,
      'page': '1',
    }

    if start_date is not None:
      if not regex_date.match(start_date):
        raise ValueError('Invalid start_date format.')

      if end_date is not None:
        if not regex_date.match(end_date):
          raise ValueError('Invalid end_date format.')

        request_data['date'] = f'{start_date}:{end_date}'
      else:
        request_data['date'] = f'{start_date}'

    if facet:
      request_data['facet'] = facet

    if limit:
      request_data['limit'] = str(limit)

    result = self.api_call('reports/query', request_data)

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    yield from result

    # only do automatic pagination if page parameter was set
    if pagination:
      _page = 1

      while result:
        _page += 1
        request_data['page'] = str(_page)
        result = self.api_call('reports/query', request_data)

        if not isinstance(result, list):
          raise ValueError('Invalid return value from api_call')

        yield from result

  def api_reports_stats(
    self,
    start_date: typing.Optional[str] = None,
    end_date: typing.Optional[str] = None,
    report: typing.Optional[typing.Sequence[str]] = None,
    report_type: typing.Optional[typing.Sequence[str]] = None,
  ) -> typing.List[typing.Tuple[str, str, str]]:
    """Fetch report statistics.

    Args:
      start_date: Fetch results starting from this date. Format must be (YYYY-MM-DD) or "now".
      end_date: Fetch results up to this date. Format must be (YYYY-MM-DD) or "now".
      report: Filter by report name.
      report_type: Filter by report type.
    """
    request_data: typing.Dict[str, typing.Any] = {}

    if report:
      request_data['report'] = report

    if start_date is not None:
      if not regex_date.match(start_date):
        raise ValueError('Invalid start_date format.')

      if end_date is not None:
        if not regex_date.match(end_date):
          raise ValueError('Invalid end_date format.')

        request_data['date'] = f'{start_date}:{end_date}'
      else:
        request_data['date'] = f'{start_date}'

    if report_type:
      request_data['type'] = report_type

    result = self.api_call('reports/stats', request_data)

    if not isinstance(result, list):
      raise ValueError('Invalid return value from api_call')

    return result

  def api_reports_device_info(
    self,
    query: typing.Dict[str, str],
  ) -> typing.Dict[str, typing.Any]:
    """Do a reports device-info query, which provides device details for a given IP.

    Args:
      query: Dictionary containing search criteria. Note that the query must be limited to your organisation's report scope.
    """
    for k in query.keys():
      if k not in ('ip', 'asn', 'geo'):
        raise ValueError('query parameter may only contain the following keys: "ip", "asn", "geo".')

    request_data = {'query': query}

    result = self.api_call('reports/device-info', request_data)

    return result

  def api_reports_schema(self, report_type: str) -> typing.Dict[str, typing.Any]:
    """Return a schema for a given report type.

    Args:
      report_type: Report type to get the schema for.
    """
    request_data = {'type': report_type}

    result = self.api_call('reports/schema', request_data)

    return result
