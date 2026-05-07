"""ULTRACAM-specific server utilities."""

import xml.etree.ElementTree as ET

import requests
from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread


def isResponseOK(xml_string):
    """
    Tests whether an XML response from an ULTRACAM server is OK.

    Checks for:
    - a ``<source>`` element with a non-empty text value
    - a ``<status>`` element with ``software="OK"`` attribute
    - if source is ``"Camera server"``, ``<status>`` must also have ``camera="OK"``

    Parameters
    ----------
    xml_string : str
        The raw XML response text from the server.

    Returns
    -------
    ok : bool
        True if the response indicates success.
    message : str
        Empty string on success, or a description of the failure.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as e:
        return False, "Failed to parse XML response: {}".format(e)

    source_el = root.find(".//source")
    if source_el is None:
        return False, "Could not find 'source' element in XML response"
    source = (source_el.text or "").strip()
    if not source:
        return False, "'source' element was empty in XML response"

    status_el = root.find(".//status")
    if status_el is None:
        return False, "Could not find 'status' element in XML response"

    software = status_el.get("software")
    if software is None:
        return False, (
            "Could not find 'software' attribute of 'status' element "
            "from source = {}".format(source)
        )
    if software != "OK":
        return False, (
            "'software' attribute = {} (not OK) from source = {}".format(
                software, source
            )
        )

    if source == "Camera server":
        camera = status_el.get("camera")
        if camera is None:
            return False, (
                "Could not find 'camera' attribute of 'status' element "
                "from source = {}".format(source)
            )
        if camera != "OK":
            return False, (
                "'camera' attribute = {} (not OK) from source = {}".format(
                    camera, source
                )
            )
    elif source != "Filesave data handler":
        return False, (
            "source = '{}' not recognised "
            "(expected 'Camera server' or 'Filesave data handler')".format(source)
        )

    return True, ""


@inlineCallbacks
def execCommand(g, command):
    """
    Executes a command on the ULTRACAM camera server.

    Sends a GET request to ``HTTP_CAMERA_SERVER/HTTP_PATH_EXEC?command`` and
    verifies the XML response.

    Parameters
    ----------
    g : hcam_widgets.globals.Container
        Container with globals. Required ``cpars`` keys:
        ``ucam_server_on``, ``http_camera_server``, ``http_path_exec``.
    command : str
        The command string, e.g. ``"GO"``, ``"ST"``, ``"RCO"``, ``"RST"``,
        ``"SRS"``, ``"EX,0"``.

    Returns
    -------
    bool
        True if the server accepted the command, False otherwise.
    """
    if not g.cpars.get("ucam_server_on", False):
        g.clog.warn("execCommand: ULTRACAM servers are not active")
        return False

    camera_server = g.cpars["http_camera_server"].rstrip("/") + "/"
    path_exec = g.cpars.get("http_path_exec", "exec")
    url = camera_server + path_exec + "?" + command

    g.clog.info("Sent command '{}'".format(command))
    try:
        response = yield deferToThread(requests.get, url, timeout=10)
        xml_string = response.text.strip()
    except Exception as err:
        g.clog.warn(
            "Failed to execute command '{}': connection error - {}".format(command, err)
        )
        return False

    ok, msg = isResponseOK(xml_string)
    if not ok:
        g.rlog.warn("Response to command '{}': {}".format(command, msg))
        g.clog.warn("Failed to execute command '{}'".format(command))
        return False

    g.rlog.info("Response to command '{}' was OK".format(command))
    g.clog.info("Executed command '{}'".format(command))
    return True


@inlineCallbacks
def execRemoteApp(g, application):
    """
    Executes a remote application on both the ULTRACAM camera and data servers.

    Sends GET requests to ``HTTP_CAMERA_SERVER/HTTP_PATH_CONFIG?application``
    and ``HTTP_DATA_SERVER/HTTP_PATH_CONFIG?application``, checking both
    XML responses.

    Parameters
    ----------
    g : hcam_widgets.globals.Container
        Container with globals. Required ``cpars`` keys:
        ``ucam_server_on``, ``http_camera_server``, ``http_data_server``,
        ``http_path_config``.
    application : str
        The application filename, e.g. ``"ap1_250_poweron.xml"``.

    Returns
    -------
    bool
        True if both servers accepted the application, False otherwise.
    """
    if not g.cpars.get("ucam_server_on", False):
        g.clog.warn("execRemoteApp: ULTRACAM servers are not active")
        return False

    camera_server = g.cpars["http_camera_server"].rstrip("/") + "/"
    data_server = g.cpars["http_data_server"].rstrip("/") + "/"
    path_config = g.cpars.get("http_path_config", "config")
    camera_url = camera_server + path_config + "?" + application
    data_url = data_server + path_config + "?" + application

    # Camera server
    try:
        response = yield deferToThread(requests.get, camera_url, timeout=10)
        xml_string = response.text.strip()
    except Exception as err:
        g.clog.warn(
            "Failed to execute '{}' on camera server: connection error - {}".format(
                application, err
            )
        )
        return False

    ok, msg = isResponseOK(xml_string)
    if not ok:
        g.rlog.warn("Response to '{}' from camera server: {}".format(application, msg))
        g.clog.warn("Failed to execute '{}' on camera server".format(application))
        return False

    g.rlog.info("Response to '{}' from camera server was OK".format(application))

    # Data server
    try:
        response = yield deferToThread(requests.get, data_url, timeout=10)
        xml_string = response.text.strip()
    except Exception as err:
        g.clog.warn(
            "Failed to execute '{}' on data server: connection error - {}".format(
                application, err
            )
        )
        return False

    ok, msg = isResponseOK(xml_string)
    if not ok:
        g.rlog.warn("Response to '{}' from data server: {}".format(application, msg))
        g.clog.warn("Failed to execute '{}' on data server".format(application))
        return False

    g.rlog.info("Response to '{}' from data server was OK".format(application))
    g.clog.info("Executed '{}' on both servers".format(application))
    return True


@inlineCallbacks
def postApp(g, xml_string):
    """
    Posts an XML application document to both the ULTRACAM camera and data servers.

    Sends POST requests to ``HTTP_CAMERA_SERVER/HTTP_PATH_CONFIG`` and
    ``HTTP_DATA_SERVER/HTTP_PATH_CONFIG`` with the XML body, then checks both
    XML responses.

    Parameters
    ----------
    g : hcam_widgets.globals.Container
        Container with globals. Required ``cpars`` keys:
        ``ucam_server_on``, ``http_camera_server``, ``http_data_server``,
        ``http_path_config``.
    xml_string : str
        The full XML document to POST, as a string.

    Returns
    -------
    bool
        True if both servers accepted the application, False otherwise.
    """
    if not g.cpars.get("ucam_server_on", False):
        g.clog.warn("postApp: ULTRACAM servers are not active")
        return False

    camera_server = g.cpars["http_camera_server"].rstrip("/") + "/"
    data_server = g.cpars["http_data_server"].rstrip("/") + "/"
    path_config = g.cpars.get("http_path_config", "config")
    camera_url = camera_server + path_config
    data_url = data_server + path_config

    headers = {"Content-Type": "text/xml"}
    data = xml_string.encode("utf-8") if isinstance(xml_string, str) else xml_string

    # Camera server
    try:
        response = yield deferToThread(
            requests.post, camera_url, data=data, headers=headers, timeout=10
        )
        xml_resp = response.text.strip()
    except Exception as err:
        g.clog.warn("postApp: camera server connection error - {}".format(err))
        return False

    ok, msg = isResponseOK(xml_resp)
    if not ok:
        g.rlog.warn("postApp camera response: {}".format(msg))
        g.clog.warn("postApp: camera server rejected application")
        return False

    g.rlog.info("postApp: camera server response OK")

    # Data server
    try:
        response = yield deferToThread(
            requests.post, data_url, data=data, headers=headers, timeout=10
        )
        xml_resp = response.text.strip()
    except Exception as err:
        g.clog.warn("postApp: data server connection error - {}".format(err))
        return False

    ok, msg = isResponseOK(xml_resp)
    if not ok:
        g.rlog.warn("postApp data response: {}".format(msg))
        g.clog.warn("postApp: data server rejected application")
        return False

    g.rlog.info("postApp: data server response OK")
    g.clog.info("Application posted to both servers")
    return True
