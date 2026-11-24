from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    """409: the request clashes with the current state of the resource."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict with the current state of the resource."
    default_code = "conflict"


class BadRequest(APIException):
    """400 with a single {"detail": "..."} message (not a field error)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Bad request."
    default_code = "bad_request"
