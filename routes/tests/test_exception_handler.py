import logging

from rest_framework.exceptions import NotFound, Throttled

from core.errors import ApiError, NoFeasibleFuelPlan
from routes.exception_handler import api_exception_handler


def handle(exc):
    return api_exception_handler(exc, {"view": "test"})


def test_an_application_error_renders_its_code_and_status():
    response = handle(NoFeasibleFuelPlan())

    assert response.status_code == 422
    assert response.data["error"]["code"] == "NO_FEASIBLE_FUEL_PLAN"
    assert "reachable" in response.data["error"]["message"]


def test_a_custom_message_overrides_the_default():
    response = handle(NoFeasibleFuelPlan("A 900 mile stretch has no station."))

    assert response.data["error"]["message"] == "A 900 mile stretch has no station."


def test_a_drf_exception_is_mapped_to_a_code_and_its_status():
    response = handle(Throttled(wait=30))

    assert response.status_code == 429
    assert response.data["error"]["code"] == "THROTTLED"


def test_drf_not_found_keeps_its_status():
    assert handle(NotFound()).status_code == 404


def test_an_unexpected_error_is_logged_for_operators_but_never_rendered(caplog):
    """A bug must reach the logs in full and the client not at all.

    The logger is named explicitly because the `routes` logger does not
    propagate to the root logger, and whether caplog's root handler sees a
    non-propagating record differs between pytest versions.
    """
    with caplog.at_level(logging.ERROR, logger="routes.exception_handler"):
        response = handle(ZeroDivisionError("secret internal detail"))

    assert response is None, "DRF falls through to a bodyless 500, so no body is rendered"
    assert "Unhandled exception" in caplog.text
    assert caplog.records[0].exc_info is not None, "the traceback is logged too"


def test_the_base_error_has_a_safe_default():
    response = handle(ApiError())

    assert response.status_code == 500
    assert response.data["error"]["code"] == "INTERNAL_ERROR"
