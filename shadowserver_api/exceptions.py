class ShadowServerApiException(Exception):
  """General exception."""


class InvalidRequest(ShadowServerApiException):
  """Raised for invalid requests."""


class InvalidResponse(ShadowServerApiException):
  """Raised on unexpected server response."""


class NoSupportedReportFilter(InvalidRequest):
  """Raised if no or an invalid, report filter was provided."""
